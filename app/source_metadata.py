"""Provider metadata shared by downloads, local playback and Emby sidecars."""
import json
import re

from publication_metadata import publication_value


FIELDS = (
    'id', 'extractor_key', 'extractor', 'title', 'description', 'series', 'episode',
    'season', 'season_number', 'episode_number', 'uploader', 'channel', 'channel_id',
    'thumbnail', 'webpage_url', 'original_url', 'duration', 'release_timestamp',
    'timestamp', 'upload_date', 'release_date', 'published_at', 'youtube_published_at',
    'view_count', 'like_count', 'comment_count', 'categories', 'tags', 'language',
    'age_limit', 'provider',
)


def provider_name(info):
    key = str(info.get('extractor_key') or info.get('extractor') or '').lower()
    if key.startswith('bbc'):
        return 'BBC iPlayer' if '/iplayer/' in str(info.get('webpage_url') or info.get('original_url') or '') else 'BBC'
    if key == 'youtube':
        return 'YouTube'
    return str(info.get('provider') or info.get('extractor_key') or info.get('extractor') or 'Online video')


def is_external_info(info):
    key = str(info.get('extractor_key') or info.get('extractor') or '').lower()
    return bool(key and key != 'youtube')


def number(value):
    try:
        value = int(value)
        return value if 0 <= value <= 9999 else None
    except (TypeError, ValueError):
        return None


def normalise_source_info(info):
    """Use explicit extractor fields, with a narrow BBC title fallback."""
    data = dict(info or {})
    data['provider'] = provider_name(data)
    # Some BBCCoUk extractor paths return only a combined programme title.
    if str(data.get('extractor_key') or data.get('extractor') or '').lower().startswith('bbc'):
        match = re.fullmatch(r'(.+?)[,:]\s*(?:Series|Season)\s+(\d+)[,:]\s*(.+)', str(data.get('title') or ''), re.I)
        if match:
            data['series'] = data.get('series') or match[1].strip()
            if number(data.get('season_number')) is None:
                data['season_number'] = int(match[2])
            episode = re.fullmatch(r'Episode\s+(\d+)(?:\s*[:.\-]\s*(.+))?', match[3], re.I)
            if episode:
                if number(data.get('episode_number')) is None:
                    data['episode_number'] = int(episode[1])
                data['episode'] = data.get('episode') or episode[2] or f'Episode {episode[1]}'
        # BBC also supplies series separately and an episode-only title.
        if data.get('series'):
            match = re.fullmatch(r'(?:Series|Season)\s+(\d+)[,:]\s*Episode\s+(\d+)', str(data.get('title') or ''), re.I)
            if match:
                data.setdefault('season_number', int(match[1]))
                data.setdefault('episode_number', int(match[2]))
                data.setdefault('episode', f'Episode {match[2]}')
    for key in ('season_number', 'episode_number'):
        data[key] = number(data.get(key))
    if is_external_info(data) and not (data.get('uploader') or data.get('channel')):
        data['uploader'] = data['provider']
    return data


def is_series_episode(info):
    return bool(info.get('series') and number(info.get('season_number')) is not None
                and number(info.get('episode_number')) is not None)


def metadata_json(info):
    # Do not persist signed stream URLs, request headers, cookies or formats.
    info = normalise_source_info(info)
    data = {key: info[key] for key in FIELDS if info.get(key) is not None}
    for key, value in list(data.items()):
        if isinstance(value, str):
            data[key] = value[:40000 if key == 'description' else 4000]
        elif isinstance(value, list):
            data[key] = [str(part)[:300] for part in value[:100]]
    return json.dumps(data, ensure_ascii=False)


def media_details(info):
    info = normalise_source_info(info)
    try:
        seconds = max(0, int(float(info.get('duration') or 0)))
    except (TypeError, ValueError, OverflowError):
        seconds = 0
    clock = f'{seconds // 60}:{seconds % 60:02d}' if seconds else ''
    if seconds >= 3600:
        clock = f'{seconds // 3600}:{seconds // 60 % 60:02d}:{seconds % 60:02d}'
    return {
        'title': info.get('title') or 'Downloaded video',
        'description': info.get('description') or '',
        'provider': info['provider'],
        'series': info.get('series') or '',
        'season_number': info.get('season_number'),
        'episode_number': info.get('episode_number'),
        'episode': info.get('episode') or '',
        'channel_title': info.get('series') or info.get('channel') or info.get('uploader') or info['provider'],
        'thumbnail_url': info.get('thumbnail') or '',
        'published_at': publication_value(info),
        'duration_seconds': seconds,
        'duration': clock,
        'category': ', '.join(info.get('categories') or []),
        'default_language': info.get('language') or '',
        'tags': info.get('tags') or [],
        'metadata_complete': True,
        'metadata_rich': True,
    }
