"""Read-only TV catalogue. Existing authentication and streaming stay authoritative."""
import hashlib
import math
import re
from pathlib import Path

from flask import abort, jsonify, request, send_file, url_for


def install_tv_routes(app, host):
    def private(payload):
        response = jsonify(payload)
        response.headers['Cache-Control'] = 'private, no-store'
        return response

    def page(items, serialise=None):
        try:
            offset = max(0, int(request.args.get('offset', 0)))
            limit = max(1, min(100, int(request.args.get('limit', 60))))
        except (ValueError, TypeError):
            abort(400, description='Invalid page parameters.')
        end = offset + limit
        selected = items[offset:end]
        if serialise:
            selected = [value for row in selected if (value := serialise(row)) is not None]
        return private(dict(ok=True, items=selected, total=len(items),
                            next_offset=end if end < len(items) else None))

    def valid_path(row):
        if not row or row.get('status') != 'completed' or row.get('profile_id') == 'audio':
            return None
        path = Path(str(row.get('output_path') or ''))
        if path.suffix.lower() == '.avi':
            return None  # No AVI extractor in the native TV player.
        if not host['is_finished_media_file'](path, video_only=True):
            return None
        return path.resolve()

    def job(job_id):
        row = host['download_job_row'](job_id)
        path = valid_path(row)
        if path is None:
            abort(404)
        return row, path

    def local_sidecar(path, suffix):
        candidate = path.with_suffix(suffix)
        try:
            resolved = candidate.resolve()
            if resolved.parent == path.parent and resolved.is_file() and resolved.stat().st_size > 0:
                return resolved
        except OSError:
            pass
        return None

    def artwork(path):
        return next((p for ext in ('.jpg', '.webp', '.png', '.jpeg')
                     if (p := local_sidecar(path, ext))), None)

    def subtitles(path):
        result = []
        # A directory scan with literal stem matching avoids glob metacharacters in titles.
        for candidate in sorted(path.parent.iterdir()):
            if candidate.suffix.lower() not in {'.vtt', '.srt', '.ass', '.ssa'}:
                continue
            if not (candidate.stem == path.stem or candidate.stem.startswith(path.stem + '.')):
                continue
            try:
                resolved = candidate.resolve()
                if resolved.parent != path.parent or not resolved.is_file() or not resolved.stat().st_size:
                    continue
                if resolved.stat().st_size > 20 * 1024 * 1024:
                    continue
            except OSError:
                continue
            result.append(resolved)
        return result[:32]

    def summary(row, fav_channels, fav_videos):
        path = valid_path(row)
        if path is None:
            return None
        details = host['stored_download_details'](row)
        channel_id = str(row.get('channel_id') or '')
        channel_key = channel_id or 'one-time'
        seconds = details.get('duration_seconds') or 0
        try:
            seconds = max(0, int(seconds)) if math.isfinite(float(seconds)) else 0
        except (TypeError, ValueError, OverflowError):
            seconds = 0
        job_id = row['job_id']
        # Stable across device restarts, without exposing a NAS path.
        identity = str(row.get('video_id') or job_id)
        return dict(id=job_id, video_id=str(row.get('video_id') or ''),
                    progress_key=hashlib.sha256(identity.encode()).hexdigest(),
                    title=details.get('title') or row.get('title') or 'Downloaded video',
                    description=details.get('description') or '',
                    channel_id=channel_key, channel_title=row.get('channel_title') or 'One-time downloads',
                    channel_favourite=channel_id in fav_channels,
                    favourite=identity in fav_videos or channel_id in fav_channels,
                    published_at=details.get('published_at') or row.get('published_at') or '',
                    downloaded_at=row.get('finished_at') or '', duration_seconds=seconds,
                    provider=details.get('provider') or 'Video',
                    thumbnail_url=url_for('tv_artwork', job_id=job_id) if artwork(path) else
                                  str(row.get('thumbnail_url') or ''),
                    stream_url=url_for('completed_download_media', job_id=job_id),
                    detail_url=url_for('tv_video', job_id=job_id))

    def inventory():
        # Keep the full-library pass small. Parse descriptions and check artwork only on the page being returned.
        return [row for row in host['completed_video_inventory']()['rows'] if valid_path(row) is not None]

    @app.get('/api/tv/session')
    def tv_session():
        user = host['current_user_record']()
        return private(dict(ok=True, api_version=1, server_version=host['VERSION'],
                            user_id=str(user['id']), username=user['username'],
                            csrf_token=host['csrf_token'](), progress_storage='device'))

    @app.get('/api/tv/library')
    def tv_library():
        items = inventory()
        fav_channels = host['favourite_channel_ids']()
        fav_videos = host['favourite_video_ids']()
        channel = request.args.get('channel')
        ids = request.args.getlist('id')
        if len(ids) > 100:
            abort(400, description='At most 100 video identifiers per request.')
        if channel:
            items = [item for item in items if (item.get('channel_id') or 'one-time') == channel]
        if ids:
            wanted = set(ids)
            items = [item for item in items if item['job_id'] in wanted]
            order = {identifier: index for index, identifier in enumerate(ids)}
            items.sort(key=lambda item: order[item['job_id']])
        if request.args.get('favourites') == '1':
            items = [item for item in items if item.get('channel_id') in fav_channels or item.get('video_id') in fav_videos]
        return page(items, lambda row: summary(row, fav_channels, fav_videos))

    @app.get('/api/tv/channels')
    def tv_channels():
        grouped = {}
        favourites = host['favourite_channel_ids']()
        for item in inventory():
            key = item.get('channel_id') or 'one-time'
            if key not in grouped:
                local = artwork(Path(item['output_path']).resolve())
                grouped[key] = dict(id=key, title=item.get('channel_title') or 'One-time downloads', count=0,
                                    favourite=key in favourites,
                                    thumbnail_url=url_for('tv_artwork', job_id=item['job_id']) if local else item.get('thumbnail_url') or '')
            grouped[key]['count'] += 1
        items = sorted(grouped.values(), key=lambda item: (not item['favourite'], item['title'].casefold(), item['id']))
        return page(items)

    @app.get('/api/tv/videos/<job_id>')
    def tv_video(job_id):
        row, path = job(job_id)
        item = summary(row, host['favourite_channel_ids'](), host['favourite_video_ids']())
        item['subtitles'] = []
        mime = {'.vtt': 'text/vtt', '.srt': 'application/x-subrip',
                '.ass': 'text/x-ssa', '.ssa': 'text/x-ssa'}
        for index, sub in enumerate(subtitles(path)):
            label = sub.stem[len(path.stem):].strip('.') or 'Subtitles'
            language = label.split('.')[0]
            item['subtitles'].append(dict(url=url_for('tv_subtitle', job_id=job_id, index=index),
                                         label=label, language=language if re.fullmatch(r'[a-z]{2,3}(?:-[A-Za-z]{2,4})?', language) else '',
                                         mime_type=mime[sub.suffix.lower()]))
        return private(dict(ok=True, item=item))

    @app.get('/api/tv/artwork/<job_id>')
    def tv_artwork(job_id):
        _, path = job(job_id)
        image = artwork(path)
        if image is None:
            abort(404)
        response = send_file(image, conditional=True)
        response.headers['Cache-Control'] = 'private, no-store'
        return response

    @app.get('/api/tv/subtitles/<job_id>/<int:index>')
    def tv_subtitle(job_id, index):
        _, path = job(job_id)
        tracks = subtitles(path)
        if index >= len(tracks):
            abort(404)
        response = send_file(tracks[index], conditional=True)
        response.headers['Cache-Control'] = 'private, no-store'
        return response
