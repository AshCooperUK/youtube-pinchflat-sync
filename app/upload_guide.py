"""Persistent, read-only YouTube catalogue, independent of downloader cutoffs.

The scheduled worker is the only catalogue API caller. Web reads never enqueue
media. Checkpoints, backoff and leases survive container restarts.
"""
from datetime import date, datetime, time, timedelta, timezone
from pathlib import Path
import calendar
import hashlib
import json
import re
import threading
import unicodedata
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from publication_metadata import exact_timestamp
from guide_forecasts import forecast_events

UTC = timezone.utc
VIDEO_PARTS = 'snippet,contentDetails,status,liveStreamingDetails,statistics'


def now():
    return datetime.now(UTC)


def stamp(value=None):
    return (value or now()).astimezone(UTC).isoformat()


def plain(value):
    return ' '.join(str(value or '').split())


def sort_text(value):
    return ''.join(c for c in unicodedata.normalize('NFKD', str(value or '').lower())
                   if not unicodedata.category(c).startswith('M'))


def channel_sort_key(channel, mode='title'):
    """Match subscription-sort.js, including direction and stable name/ID ties."""
    field, _, direction = str(mode or 'title').partition(':')
    defaults = {'title':'asc', 'enabled':'desc', 'range':'asc', 'media_profile':'asc',
                'cutoff':'asc', 'storage':'desc', 'error':'asc', 'actions':'desc', 'status':'asc', 'newest':'desc'}
    if field not in defaults:
        field = 'title'
    if direction not in ('asc', 'desc'):
        direction = defaults[field]
    title = sort_text(channel.get('title'))
    key = (title,)
    if field == 'media_profile':
        profile = channel.get('profile_id') or ''
        key = (int(profile[:-1]) if re.fullmatch(r'\d+p', profile) else 9007199254740991,
               sort_text(channel.get('profile_name')))
    elif field == 'enabled':
        key = (int(bool(channel.get('download_enabled'))),)
    elif field == 'range':
        ranges = {'default':0,'today':1,'this_week':2,'this_month':3,'six_months':4,'last_year':5,'subscription_date':15,'custom_date':16}
        value = channel.get('range_mode') or 'default'
        key = (ranges.get(value, 4+int(value[6:]) if re.fullmatch(r'years_\d+', value) else 17),)
    elif field == 'cutoff':
        key = (channel.get('cutoff') or '',)
    elif field == 'error':
        key = (not bool(channel.get('last_error')), sort_text(channel.get('last_error')))
    elif field == 'actions':
        key = (int(bool(channel.get('dirty'))),)
    elif field == 'status':
        key = (channel.get('status') or '',)
    elif field == 'newest':
        key = (channel.get('first_seen_at') or '',)
    elif field == 'storage':
        key = (int(channel.get('storage_bytes') or 0),)
    if direction == 'desc':
        # The terminator also reverses strings where one is a prefix of another.
        key = tuple(tuple(-ord(c) for c in v)+(1,) if isinstance(v, str) else -v for v in key)
    return (not channel.get('favourite'), *key, title, channel['channel_id'])


def thumbnail(snippet):
    images = snippet.get('thumbnails') or {}
    for size in ('maxres', 'standard', 'high', 'medium', 'default'):
        url = str((images.get(size) or {}).get('url') or '')
        if url.startswith('https://'):
            return url
    return ''


def duration_seconds(value):
    match = re.fullmatch(r'P(?:(\d+)D)?(?:T(?:(\d+)H)?(?:(\d+)M)?(?:(\d+(?:\.\d+)?)S)?)?', str(value or ''))
    return int(sum(float(v or 0) * factor for v, factor in zip(match.groups(), (86400, 3600, 60, 1)))) if match else None


def init_guide_db(db):
    with db() as conn:
        conn.executescript('''
        CREATE TABLE IF NOT EXISTS guide_channel_preferences (channel_id TEXT PRIMARY KEY, visible INTEGER NOT NULL DEFAULT 1);
        CREATE TABLE IF NOT EXISTS guide_channels (
          channel_id TEXT PRIMARY KEY, title TEXT, description TEXT, thumbnail_url TEXT,
          uploads_playlist_id TEXT, channel_created_at TEXT, metadata_checked_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS guide_videos (
          video_id TEXT PRIMARY KEY, channel_id TEXT NOT NULL, title TEXT, description TEXT,
          thumbnail_url TEXT, published_at TEXT, publication_date TEXT, time_precision TEXT,
          scheduled_start_at TEXT, actual_start_at TEXT, actual_end_at TEXT,
          duration_seconds INTEGER, availability TEXT, embeddable INTEGER,
          broadcast_state TEXT, classification TEXT NOT NULL DEFAULT 'unknown',
          first_seen_at TEXT NOT NULL, metadata_checked_at TEXT NOT NULL
        );
        CREATE INDEX IF NOT EXISTS guide_video_publication ON guide_videos(channel_id, published_at);
        CREATE INDEX IF NOT EXISTS guide_video_scheduled ON guide_videos(channel_id, scheduled_start_at);
        CREATE INDEX IF NOT EXISTS guide_video_refresh ON guide_videos(metadata_checked_at);
        CREATE TABLE IF NOT EXISTS guide_sync (
          channel_id TEXT PRIMARY KEY, backfill_cursor TEXT, recent_cursor TEXT,
          initialised INTEGER NOT NULL DEFAULT 0, history_complete INTEGER NOT NULL DEFAULT 0,
          oldest_covered_at TEXT, last_success_at TEXT, recent_checked_at TEXT,
          refresh_requested INTEGER NOT NULL DEFAULT 1, error TEXT
        );
        CREATE TABLE IF NOT EXISTS guide_runtime (
          id INTEGER PRIMARY KEY CHECK(id=1), lease_until TEXT NOT NULL DEFAULT '',
          retry_at TEXT NOT NULL DEFAULT '', last_error TEXT NOT NULL DEFAULT '',
          last_success_at TEXT, calls_day TEXT, calls INTEGER NOT NULL DEFAULT 0
        );
        INSERT OR IGNORE INTO guide_runtime(id) VALUES(1);
        CREATE TABLE IF NOT EXISTS guide_predictions (
          prediction_id TEXT PRIMARY KEY, channel_id TEXT NOT NULL, provider TEXT NOT NULL,
          window_start TEXT NOT NULL, window_end TEXT NOT NULL, explanation TEXT,
          created_at TEXT NOT NULL, expires_at TEXT NOT NULL
        );
        ''')
        if 'channel_refresh_requested' not in {r[1] for r in conn.execute('PRAGMA table_info(guide_sync)')}:
            conn.execute('ALTER TABLE guide_sync ADD COLUMN channel_refresh_requested INTEGER NOT NULL DEFAULT 0')
        if 'retry_at' not in {r[1] for r in conn.execute('PRAGMA table_info(guide_sync)')}:
            conn.execute("ALTER TABLE guide_sync ADD COLUMN retry_at TEXT NOT NULL DEFAULT ''")
            # Older releases incorrectly paused the entire guide for one playlist.
            for code in ('playlistNotFound', 'playlistItemsNotAccessible', 'invalidPageToken'):
                conn.execute("UPDATE guide_runtime SET last_error='',retry_at='' WHERE last_error LIKE ?", ('%(' + code + ')%',))
        for table, name, declaration in (
            ('guide_videos', 'view_count', 'INTEGER'), ('guide_videos', 'like_count', 'INTEGER'),
            ('guide_videos', 'comment_count', 'INTEGER'), ('guide_predictions', 'details', 'TEXT'),
            ('guide_runtime', 'scheduled_at', "TEXT NOT NULL DEFAULT ''"),
            ('guide_runtime', 'forecast_revision', "TEXT NOT NULL DEFAULT ''"),
        ):
            if name not in {r[1] for r in conn.execute(f'PRAGMA table_info({table})')}:
                conn.execute(f'ALTER TABLE {table} ADD COLUMN {name} {declaration}')



class ForecastProvider:
    def __init__(self, app, timezone_name):
        self.app, self.timezone_name = app, timezone_name

    def status(self):
        enabled = self.app.setting_bool('guide_predictions_enabled', True)
        return {'enabled': enabled, 'reason': ('Estimates use saved upload patterns. Channels without enough reliable history have no forecast.'
                if enabled else 'Upload estimates are switched off in Settings > Guide.')}

    def rebuild(self):
        with self.app.db() as conn:
            conn.execute('DELETE FROM guide_predictions')
            if not self.status()['enabled']:
                return
            channels = conn.execute("SELECT s.channel_id,g.oldest_covered_at,g.initialised FROM subscriptions s JOIN guide_sync g USING(channel_id) WHERE s.active=1 AND s.channel_id NOT IN (SELECT channel_id FROM guide_channel_preferences WHERE visible=0)").fetchall()
            for channel in channels:
                if not channel['initialised']:
                    continue
                records = [dict(r) for r in conn.execute("SELECT * FROM guide_videos WHERE channel_id=? AND availability IN ('public','unlisted') AND metadata_checked_at>?", (channel['channel_id'], stamp(now()-timedelta(days=30))))]
                for item in forecast_events(channel['channel_id'], records, now(), self.timezone_name()):
                    conn.execute('INSERT INTO guide_predictions(prediction_id,channel_id,provider,window_start,window_end,explanation,created_at,expires_at,details) VALUES(?,?,?,?,?,?,?,?,?)',
                        (item['id'], channel['channel_id'], 'calendar-v1', stamp(datetime.fromisoformat(item['window_start'])), stamp(datetime.fromisoformat(item['window_end'])), item['explanation'], stamp(), stamp(datetime.fromisoformat(item['window_end'])), json.dumps(item)))

    def events(self, conn, channel_id, window, include_shorts, include_live):
        if not self.status()['enabled']:
            return []
        items = [json.loads(r['details']) for r in conn.execute('SELECT details FROM guide_predictions WHERE channel_id=? AND window_start<? AND window_end>? AND expires_at>?', (channel_id, window['end'], window['start'], stamp())) if r['details']]
        known = [dict(r) for r in conn.execute('SELECT published_at,scheduled_start_at,broadcast_state,classification FROM guide_videos WHERE channel_id=? AND metadata_checked_at>?', (channel_id, stamp(now()-timedelta(days=30))))]
        result = []
        for item in items:
            if (not include_shorts and item['classification']=='short') or (not include_live and item['classification']=='livestream'):
                continue
            moment = datetime.fromisoformat(item['event_at'])
            if not (datetime.fromisoformat(window['start']) <= moment < datetime.fromisoformat(window['end'])):
                continue
            duplicate = False
            for video in known:
                value = video['scheduled_start_at'] if video['broadcast_state']=='upcoming' else video['published_at']
                if value and video['classification']==item['classification'] and abs((datetime.fromisoformat(value)-moment).total_seconds()) <= 3*3600:
                    duplicate = True
                    break
            if not duplicate:
                result.append(item)
        return result


class GuidePaused(Exception):
    pass


class UploadGuide:
    def __init__(self, app):
        self.app = app
        self.lock = threading.Lock()
        self.forecasts = ForecastProvider(app, self.timezone_name)
        self.budget_left = 0

    def timezone_name(self):
        name = self.app.get_setting('guide_timezone', 'Europe/London')
        try:
            ZoneInfo(name)
            return name
        except (ValueError, ZoneInfoNotFoundError):
            return 'Europe/London'

    def enabled_ids(self):
        with self.app.db() as conn:
            return [row[0] for row in conn.execute('SELECT channel_id FROM subscriptions WHERE active=1 AND channel_id NOT IN (SELECT channel_id FROM guide_channel_preferences WHERE visible=0) ORDER BY channel_id')]

    def request_refresh(self):
        ids = self.enabled_ids()
        with self.app.db() as conn:
            conn.executemany('INSERT OR IGNORE INTO guide_sync(channel_id) VALUES(?)', [(cid,) for cid in ids])
            conn.executemany('UPDATE guide_sync SET refresh_requested=1,channel_refresh_requested=1 WHERE channel_id=?', [(cid,) for cid in ids])
        return len(ids)

    def expire(self):
        cutoff = stamp(now() - timedelta(days=30))
        with self.app.db() as conn:
            expired = [r[0] for r in conn.execute('SELECT DISTINCT channel_id FROM guide_videos WHERE metadata_checked_at<=?', (cutoff,))]
            expired += [r[0] for r in conn.execute('SELECT channel_id FROM guide_channels WHERE metadata_checked_at<=?', (cutoff,))]
            conn.execute('DELETE FROM guide_videos WHERE metadata_checked_at<=?', (cutoff,))
            conn.execute('DELETE FROM guide_channels WHERE metadata_checked_at<=?', (cutoff,))
            conn.executemany('UPDATE guide_sync SET initialised=0,history_complete=0,backfill_cursor=NULL,recent_cursor=NULL,refresh_requested=1,oldest_covered_at=NULL WHERE channel_id=?', [(cid,) for cid in set(expired)])
            conn.execute('DELETE FROM guide_predictions WHERE expires_at<=?', (stamp(),))

    def _request(self, creds, path, params):
        if self.budget_left < 1:
            raise GuidePaused('Batch complete')
        daily_limit = self.app.setting_int('guide_daily_budget', 1000, 50, 10000)
        with self.app.db() as conn:
            runtime = dict(conn.execute('SELECT * FROM guide_runtime WHERE id=1').fetchone())
            day = now().astimezone(ZoneInfo('America/Los_Angeles')).date().isoformat()
            calls = runtime['calls'] if runtime['calls_day'] == day else 0
            if calls >= daily_limit:
                raise GuidePaused('Daily guide allowance reached')
            conn.execute('UPDATE guide_runtime SET calls_day=?,calls=?,lease_until=? WHERE id=1', (day, calls+1, stamp(now()+timedelta(minutes=10))))
        self.budget_left -= 1
        return self.app.youtube_api_request(creds, 'GET', path, path+'.list', 1, params=params).json()

    def _save_channels(self, records):
        with self.app.db() as conn:
            for record in records:
                snippet = record.get('snippet') or {}
                local = snippet.get('localized') or snippet
                playlist = (record.get('contentDetails') or {}).get('relatedPlaylists', {}).get('uploads', '')
                conn.execute('''INSERT INTO guide_channels VALUES(?,?,?,?,?,?,?)
                  ON CONFLICT(channel_id) DO UPDATE SET title=excluded.title,description=excluded.description,
                  thumbnail_url=excluded.thumbnail_url,uploads_playlist_id=excluded.uploads_playlist_id,
                  channel_created_at=excluded.channel_created_at,metadata_checked_at=excluded.metadata_checked_at''',
                  (record['id'], plain(local.get('title') or snippet.get('title')), plain(local.get('description') or snippet.get('description')),
                   thumbnail(snippet), playlist, exact_timestamp(snippet.get('publishedAt')), stamp()))
                conn.execute('UPDATE guide_sync SET channel_refresh_requested=0 WHERE channel_id=?', (record['id'],))

    def save_videos(self, records, fallbacks=None):
        fallbacks = fallbacks or {}
        saved = []
        with self.app.db() as conn:
            for record in records:
                vid = str(record.get('id') or '')
                if not re.fullmatch(r'[A-Za-z0-9_-]{11}', vid):
                    continue
                snippet, details, status, live = [record.get(key) or {} for key in ('snippet', 'contentDetails', 'status', 'liveStreamingDetails')]
                channel = snippet.get('channelId')
                if not channel:
                    continue
                published = exact_timestamp(snippet.get('publishedAt')) or exact_timestamp(fallbacks.get(vid))
                # Date-only legacy/fallback metadata has no invented midnight.
                day = ''
                if not published:
                    for value in (snippet.get('publishedAt'), fallbacks.get(vid)):
                        try:
                            day = date.fromisoformat(str(value)).isoformat()
                            break
                        except ValueError:
                            pass
                scheduled = exact_timestamp(live.get('scheduledStartTime'))
                actual = exact_timestamp(live.get('actualStartTime'))
                ended = exact_timestamp(live.get('actualEndTime'))
                state = ('completed_live' if ended else 'live' if actual or snippet.get('liveBroadcastContent') == 'live'
                         else 'upcoming' if snippet.get('liveBroadcastContent') == 'upcoming' else 'published')
                classification = 'livestream' if actual or ended or state == 'live' else 'unknown'
                # Data API duration is not evidence of a Short. Use downloader evidence only.
                short = conn.execute("SELECT 1 FROM downloads WHERE video_id=? AND (failure_code='shorts_excluded' OR youtube_url LIKE '%youtube.com/shorts/%') LIMIT 1", (vid,)).fetchone()
                if short:
                    classification = 'short'
                availability = status.get('privacyStatus') or 'public'
                title, description, thumb = plain(snippet.get('title')), plain(snippet.get('description')), thumbnail(snippet)
                if availability not in ('public', 'unlisted'):
                    title, description, thumb = 'Unavailable video', '', ''
                conn.execute('''INSERT INTO guide_videos (video_id,channel_id,title,description,thumbnail_url,published_at,publication_date,
                  time_precision,scheduled_start_at,actual_start_at,actual_end_at,duration_seconds,availability,embeddable,
                  broadcast_state,classification,first_seen_at,metadata_checked_at) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
                  ON CONFLICT(video_id) DO UPDATE SET channel_id=excluded.channel_id,title=excluded.title,
                  description=excluded.description,thumbnail_url=excluded.thumbnail_url,published_at=excluded.published_at,
                  publication_date=excluded.publication_date,time_precision=excluded.time_precision,
                  scheduled_start_at=excluded.scheduled_start_at,actual_start_at=excluded.actual_start_at,
                  actual_end_at=excluded.actual_end_at,duration_seconds=excluded.duration_seconds,
                  availability=excluded.availability,embeddable=excluded.embeddable,broadcast_state=excluded.broadcast_state,
                  classification=CASE WHEN excluded.classification='unknown' THEN guide_videos.classification ELSE excluded.classification END,
                  metadata_checked_at=excluded.metadata_checked_at''',
                  (vid, channel, title, description, thumb, published, day or None, 'exact' if published else 'date' if day else 'unknown',
                   scheduled, actual, ended, duration_seconds(details.get('duration')), availability, int(status.get('embeddable', True)),
                   state, classification, stamp(), stamp()))
                stats = record.get('statistics') or {}
                numbers = [int(str(stats[k])) if str(stats.get(k, '')).isdigit() else None for k in ('viewCount', 'likeCount', 'commentCount')]
                conn.execute('UPDATE guide_videos SET view_count=?,like_count=?,comment_count=? WHERE video_id=?', (*numbers, vid))
                saved.append(vid)
        return saved

    def _videos(self, creds, ids, fallbacks=None):
        if not ids:
            return
        response = self._request(creds, 'videos', {'part': VIDEO_PARTS, 'id': ','.join(ids), 'hl': 'en'})
        found = self.save_videos(response.get('items') or [], fallbacks)
        with self.app.db() as conn:
            # Deleted/private items do not keep old API titles/thumbnails indefinitely.
            for vid in set(ids) - set(found):
                conn.execute('DELETE FROM guide_videos WHERE video_id=?', (vid,))
        self.app.repair_publication_dates(video_ids=found, quiet=True)

    def _page(self, creds, channel, mode):
        with self.app.db() as conn:
            state = dict(conn.execute('SELECT * FROM guide_sync WHERE channel_id=?', (channel['channel_id'],)).fetchone())
        cursor = state['recent_cursor'] if mode == 'recent' else state['backfill_cursor']
        params = {'part': 'snippet,contentDetails', 'playlistId': channel['uploads_playlist_id'], 'maxResults': 50}
        if cursor:
            params['pageToken'] = cursor
        response = self._request(creds, 'playlistItems', params)
        entries = response.get('items') or []
        ids, fallbacks = [], {}
        for item in entries:
            content = item.get('contentDetails') or {}
            vid = content.get('videoId') or (item.get('snippet') or {}).get('resourceId', {}).get('videoId')
            if vid and re.fullmatch(r'[A-Za-z0-9_-]{11}', vid) and vid not in ids:
                ids.append(vid)
                fallbacks[vid] = content.get('videoPublishedAt')
        with self.app.db() as conn:
            known = {r[0] for r in conn.execute('SELECT video_id FROM guide_videos WHERE channel_id=?', (channel['channel_id'],))}
        self._videos(creds, ids, fallbacks)
        next_page = response.get('nextPageToken') or None
        cid = channel['channel_id']
        with self.app.db() as conn:
            oldest = conn.execute('SELECT MIN(published_at) FROM guide_videos WHERE channel_id=?', (cid,)).fetchone()[0]
            if mode == 'backfill' or not state['initialised']:
                conn.execute('''UPDATE guide_sync SET backfill_cursor=?,history_complete=?,initialised=1,
                   oldest_covered_at=?,last_success_at=?,error=NULL WHERE channel_id=?''',
                   (next_page, int(not next_page), oldest, stamp(), cid))
            if mode == 'recent':
                continuation = next_page if state['initialised'] and not set(ids).intersection(known) else None
                conn.execute('''UPDATE guide_sync SET recent_cursor=?,recent_checked_at=?,refresh_requested=?,
                  last_success_at=?,error=NULL WHERE channel_id=?''', (continuation, stamp(), int(bool(continuation)), stamp(), cid))
            conn.execute("UPDATE guide_sync SET retry_at='' WHERE channel_id=?", (cid,))
            conn.execute("UPDATE guide_runtime SET last_success_at=?,last_error='',retry_at='' WHERE id=1", (stamp(),))

    def _failure(self, exc, channel_id=None):
        response = getattr(exc, 'response', None)
        status = getattr(response, 'status_code', None)
        reason = ''
        try:
            reason = response.json()['error']['errors'][0]['reason']
        except (AttributeError, TypeError, ValueError, KeyError, IndexError):
            pass
        # Never include request headers, tokens or full exception URLs in activity.
        code = reason if re.fullmatch(r'[A-Za-z0-9_]{1,80}', str(reason)) else (f'HTTP {status}' if status else type(exc).__name__)
        if channel_id and reason in ('playlistNotFound', 'playlistItemsNotAccessible', 'invalidPageToken'):
            delay = timedelta(minutes=10) if reason == 'invalidPageToken' else timedelta(hours=24)
            error = f'Uploads unavailable ({code}). Cached uploads remain available.'
            with self.app.db() as conn:
                old = conn.execute('SELECT error FROM guide_sync WHERE channel_id=?', (channel_id,)).fetchone()
                title = conn.execute('SELECT title FROM subscriptions WHERE channel_id=?', (channel_id,)).fetchone()
                conn.execute("""UPDATE guide_sync SET error=?,retry_at=?,refresh_requested=1,
                    channel_refresh_requested=1,initialised=0,history_complete=0,
                    backfill_cursor=NULL,recent_cursor=NULL WHERE channel_id=?""", (error, stamp(now()+delay), channel_id))
            if not old or old[0] != error:
                self.app.log_activity('guide', 'Channel guide refresh paused',
                    f'{title[0] if title else channel_id}: {error} Other channels continue refreshing.', 'warning', channel_id)
            return True
        error = f'YouTube guide refresh paused ({code}). Cached uploads remain available.' 
        delay = timedelta(minutes=10)
        if reason in ('quotaExceeded', 'dailyLimitExceeded'):
            pacific = now().astimezone(ZoneInfo('America/Los_Angeles'))
            tomorrow = datetime.combine(pacific.date()+timedelta(days=1), time(0, 5), pacific.tzinfo)
            delay = tomorrow.astimezone(UTC) - now()
        elif status in (401, 403) or 'RefreshError' in type(exc).__name__:
            delay = timedelta(hours=6)
        with self.app.db() as conn:
            old = conn.execute('SELECT last_error FROM guide_runtime WHERE id=1').fetchone()[0]
            conn.execute('UPDATE guide_runtime SET last_error=?,retry_at=? WHERE id=1', (error, stamp(now()+delay)))
            if channel_id:
                conn.execute('UPDATE guide_sync SET error=? WHERE channel_id=?', (error, channel_id))
                if reason == 'invalidPageToken':
                    conn.execute('UPDATE guide_sync SET initialised=0,history_complete=0,backfill_cursor=NULL,recent_cursor=NULL WHERE channel_id=?', (channel_id,))
        if old != error:
            self.app.log_activity('guide', 'Upload guide refresh paused', error, 'warning', channel_id)

    def _channel_page(self, creds, channel, mode):
        try:
            self._page(creds, channel, mode)
        except GuidePaused:
            raise
        except Exception as exc:
            if not self._failure(exc, channel['channel_id']):
                raise GuidePaused('Guide refresh paused') from exc

    def scheduled_boundary(self):
        zone = ZoneInfo(self.timezone_name())
        clock = self.app.get_setting('guide_refresh_time', '04:00')
        try:
            hour, minute = map(int, clock.split(':'))
            scheduled = datetime.combine(now().astimezone(zone).date(), time(hour, minute), zone)
        except (ValueError, TypeError):
            scheduled = datetime.combine(now().astimezone(zone).date(), time(4), zone)
        return stamp(scheduled if scheduled <= now() else scheduled-timedelta(days=1))

    def next_refresh(self):
        last = datetime.fromisoformat(self.scheduled_boundary()).astimezone(ZoneInfo(self.timezone_name()))
        return stamp(last+timedelta(days=1))

    def tick(self):
        if not self.lock.acquire(blocking=False):
            return False
        leased = False
        channel_id = None
        try:
            with self.app.db() as conn:
                leased = bool(conn.execute('UPDATE guide_runtime SET lease_until=? WHERE id=1 AND lease_until<?', (stamp(now()+timedelta(minutes=10)), stamp())).rowcount)
            if not leased:
                return False
            self.expire()
            with self.app.db() as conn:
                runtime = dict(conn.execute('SELECT * FROM guide_runtime WHERE id=1').fetchone())
            if runtime['retry_at'] > stamp():
                return False
            ids = self.enabled_ids()
            if not ids:
                return False
            # A restart resumes incomplete indexing. The stored checkpoint stops
            # completed catalogues being re-fetched every time a container starts.
            boundary = self.scheduled_boundary()
            if runtime['scheduled_at'] < boundary:
                with self.app.db() as conn:
                    conn.execute('UPDATE guide_sync SET refresh_requested=1 WHERE channel_id IN (SELECT channel_id FROM subscriptions WHERE active=1 AND channel_id NOT IN (SELECT channel_id FROM guide_channel_preferences WHERE visible=0))')
                    conn.execute('UPDATE guide_runtime SET scheduled_at=? WHERE id=1', (boundary,))

            creds = self.app.load_credentials()
            if not creds:
                with self.app.db() as conn:
                    conn.execute("UPDATE guide_runtime SET last_error='Connect Google in Settings > YouTube to index uploads.' WHERE id=1")
                return False
            self.budget_left = 10
            with self.app.db() as conn:
                conn.executemany('INSERT OR IGNORE INTO guide_sync(channel_id) VALUES(?)', [(cid,) for cid in ids])
                existing = {row['channel_id']: dict(row) for row in conn.execute('SELECT * FROM guide_channels')}
                requested = {r[0] for r in conn.execute('SELECT channel_id FROM guide_sync WHERE channel_refresh_requested=1')}
                blocked = {r[0] for r in conn.execute('SELECT channel_id FROM guide_sync WHERE retry_at>?', (stamp(),))}
            stale = [cid for cid in ids if cid not in blocked and (cid in requested or cid not in existing or existing[cid]['metadata_checked_at'] < stamp(now()-timedelta(days=7)))][:50]
            if stale:
                response = self._request(creds, 'channels', {'part': 'snippet,contentDetails', 'id': ','.join(stale), 'hl': 'en'})
                self._save_channels(response.get('items') or [])
                missing = set(stale) - {c['id'] for c in response.get('items', [])}
                with self.app.db() as conn:
                    for cid in missing:
                        conn.execute("INSERT OR REPLACE INTO guide_channels VALUES(?,'','','','',NULL,?)", (cid, stamp()))
                        conn.execute("UPDATE guide_sync SET error='Channel metadata is unavailable on YouTube.',channel_refresh_requested=0 WHERE channel_id=?", (cid,))
            # Renew historical data before expiry, plus actual scheduled/live states.
            with self.app.db() as conn:
                stale_videos = [r[0] for r in conn.execute('''SELECT v.video_id FROM guide_videos v
                   JOIN subscriptions s ON s.channel_id=v.channel_id WHERE s.active=1 AND s.channel_id NOT IN (SELECT channel_id FROM guide_channel_preferences WHERE visible=0)
                   AND (v.metadata_checked_at<? OR (v.broadcast_state IN ('upcoming','live') AND v.metadata_checked_at<?))
                   ORDER BY v.metadata_checked_at LIMIT 50''', (stamp(now()-timedelta(days=25)), self.scheduled_boundary()))]
            self._videos(creds, stale_videos)
            with self.app.db() as conn:
                channels = [dict(r) for r in conn.execute('''SELECT c.*,s.* FROM guide_channels c JOIN guide_sync s USING(channel_id)
                   JOIN subscriptions sub USING(channel_id) WHERE sub.active=1 AND sub.channel_id NOT IN (SELECT channel_id FROM guide_channel_preferences WHERE visible=0) AND c.uploads_playlist_id!=''
                   ORDER BY COALESCE(s.recent_checked_at,''), c.channel_id''')]
            # Recent history gets a separate pass. Older pages resume fairly afterwards.
            for channel in channels:
                if self.budget_left < 2:
                    break
                if channel['retry_at'] > stamp():
                    continue
                if channel['refresh_requested'] or not channel['initialised'] or (channel['recent_checked_at'] or '') < self.scheduled_boundary():
                    channel_id = channel['channel_id']
                    self._channel_page(creds, channel, 'recent')
            with self.app.db() as conn:
                backfill = [dict(r) for r in conn.execute('''SELECT c.*,s.* FROM guide_channels c JOIN guide_sync s USING(channel_id)
                   JOIN subscriptions sub USING(channel_id) WHERE sub.active=1 AND sub.channel_id NOT IN (SELECT channel_id FROM guide_channel_preferences WHERE visible=0)
                   AND s.initialised=1 AND s.history_complete=0 AND s.backfill_cursor IS NOT NULL
                   ORDER BY COALESCE(s.last_success_at,''), c.channel_id''')]
            history = self.app.get_setting('guide_history', 'all')
            for channel in backfill:
                if self.budget_left < 2:
                    break
                if channel['retry_at'] > stamp():
                    continue
                if history == 'year' and (channel['oldest_covered_at'] or stamp()) < stamp(now()-timedelta(days=366)):
                    continue
                channel_id = channel['channel_id']
                self._channel_page(creds, channel, 'backfill')
            with self.app.db() as conn:
                updated = dict(conn.execute('SELECT * FROM guide_runtime WHERE id=1').fetchone())
            revision = str(updated['last_success_at']) + ':' + boundary + ':' + str(self.forecasts.status()['enabled']) + ':' + self.timezone_name()
            if updated['forecast_revision'] != revision:
                self.forecasts.rebuild()
                with self.app.db() as conn:
                    conn.execute('UPDATE guide_runtime SET forecast_revision=? WHERE id=1', (revision,))
            return True
        except GuidePaused as exc:
            if str(exc) == 'Daily guide allowance reached':
                with self.app.db() as conn:
                    conn.execute("UPDATE guide_runtime SET last_error='Daily guide API allowance reached. Indexing resumes tomorrow.' WHERE id=1")
            return False
        except Exception as exc:
            self._failure(exc, channel_id)
            return False
        finally:
            if leased:
                with self.app.db() as conn:
                    conn.execute("UPDATE guide_runtime SET lease_until='' WHERE id=1")
            self.lock.release()

    def window(self, args):
        zone = ZoneInfo(self.timezone_name())
        today = now().astimezone(zone).date()
        anchor = date.fromisoformat(args.get('date') or today.isoformat())
        mode = args.get('zoom', 'week')
        if mode not in ('day', 'week', 'month'):
            raise ValueError('Unknown guide view')
        start = anchor - timedelta(days=2) if mode == 'week' else anchor.replace(day=1) if mode == 'month' else anchor
        end = start + timedelta(days=7 if mode == 'week' else calendar.monthrange(start.year, start.month)[1] if mode == 'month' else 1)
        return {'date': anchor.isoformat(), 'zoom': mode, 'start_date': start.isoformat(), 'end_date': end.isoformat(),
                'start': stamp(datetime.combine(start, time(), zone)), 'end': stamp(datetime.combine(end, time(), zone)),
                'today': today.isoformat(), 'timezone': str(zone)}

    def initial_payload(self, args):
        try:
            return self.read(args)
        except (ValueError, OverflowError):
            return None

    def read(self, args):
        window = self.window(args)
        minimum = stamp(now()-timedelta(days=30))
        mode = args.get('sort', 'title')
        offset = max(0, int(args.get('offset', 0)))
        limit = min(100, max(1, int(args['limit']))) if args.get('limit') else None
        terms = plain(args.get('search', '')).casefold().split()
        kind = args.get('filter', 'all')
        favourite_ids = self.app.favourite_channel_ids()
        with self.app.db() as conn:
            rows = conn.execute('''SELECT s.*,c.description AS guide_description,c.thumbnail_url AS guide_thumbnail,
                c.metadata_checked_at AS channel_checked_at,g.initialised,g.history_complete,g.oldest_covered_at,
                g.last_success_at,g.retry_at AS guide_retry_at,g.error AS guide_error,g.refresh_requested,g.recent_cursor
                FROM subscriptions s LEFT JOIN guide_channels c USING(channel_id) LEFT JOIN guide_sync g USING(channel_id)
                WHERE s.active=1 AND s.channel_id NOT IN (SELECT channel_id FROM guide_channel_preferences WHERE visible=0)''').fetchall()
            runtime = dict(conn.execute('SELECT * FROM guide_runtime WHERE id=1').fetchone())
            title_matches = {}
            if terms:
                # The catalogue search is independent of the visible date window.
                for r in conn.execute('SELECT channel_id,title FROM guide_videos WHERE metadata_checked_at>?', (minimum,)):
                    title_matches.setdefault(r['channel_id'], []).append(r['title'] or '')
        channels = []
        enabled_channels = {}
        storage = self.app.storage_snapshot_cached()
        for row in rows:
            sub = self.app.subscription_view(row)
            fresh = (row['channel_checked_at'] or '') > minimum
            channel = {'channel_id': row['channel_id'], 'title': row['title'],
                'description': (row['guide_description'] if fresh else '') or 'No channel description',
                'thumbnail_url': (row['guide_thumbnail'] if fresh else '') or row['thumbnail_url'] or '',
                'favourite': row['channel_id'] in favourite_ids, 'profile_id': self.app.subscription_media_profile_id(dict(row)),
                'status': sub.get('ui_status') or 'enabled', 'first_seen_at': row['first_seen_at'] or '',
                'download_enabled': bool(sub['download_enabled']), 'range_mode': row['history_mode'] or 'default',
                'cutoff': sub['cutoff'], 'last_error': row['last_error'] or '', 'dirty': False,
                'storage_bytes': self.app.channel_disk_usage(row['title'], storage, row['download_folder'] or self.app.safe_media_component(row['title'], 80)),
                'coverage': {'initialised': bool(row['initialised']), 'complete': bool(row['history_complete']),
                  'oldest_at': row['oldest_covered_at'], 'last_success_at': row['last_success_at'],
                  'pending': bool(row['refresh_requested'] or row['recent_cursor']), 'error': row['guide_error'], 'retry_at': row['guide_retry_at'],
                  'history_limited': self.app.get_setting('guide_history', 'all') == 'year' and bool(row['oldest_covered_at']) and row['oldest_covered_at'] < stamp(now()-timedelta(days=366))}, 'events': []}
            channel['profile_name'] = self.app.V3_MEDIA_PROFILE_MAP.get(channel['profile_id'], {}).get('name', channel['profile_id'])
            enabled_channels[channel['channel_id']] = channel
            haystack = ' '.join([channel['title'], channel['description'], *title_matches.get(channel['channel_id'], [])]).casefold()
            if all(term in haystack for term in terms):
                channels.append(channel)
        channels.sort(key=lambda row: channel_sort_key(row, mode))
        revision = hashlib.sha256(json.dumps([(c['channel_id'], c['favourite'], c['profile_id'], c['status'], c['storage_bytes']) for c in channels]).encode()).hexdigest()[:20]
        total = len(channels)
        selected_channel = args.get('channel')
        channels = [c for c in channels if c['channel_id'] == selected_channel] if selected_channel else channels[offset:offset+limit if limit else None]
        completed = {r['video_id']: r for r in self.app.completed_video_inventory().get('rows', []) if r.get('video_id')}
        include_shorts = self.app.setting_bool('downloader_include_shorts', False)
        include_live = self.app.setting_bool('downloader_include_livestreams', True)
        event_offset = max(0, int(args.get('event_offset', 0))) if selected_channel else 0
        selection = None
        with self.app.db() as conn:
            for channel in channels:
                sql = '''SELECT * FROM guide_videos WHERE channel_id=? AND metadata_checked_at>?
                  AND availability IN ('public','unlisted')
                  AND ((CASE WHEN broadcast_state='upcoming' THEN scheduled_start_at ELSE published_at END >= ?
                    AND CASE WHEN broadcast_state='upcoming' THEN scheduled_start_at ELSE published_at END < ?)
                    OR (published_at IS NULL AND broadcast_state!='upcoming' AND publication_date>=? AND publication_date<?))'''
                values = [channel['channel_id'], minimum, window['start'], window['end'], window['start_date'], window['end_date']]
                if not include_shorts:
                    sql += " AND classification!='short'"
                if not include_live:
                    sql += " AND classification!='livestream'"
                if kind == 'published':
                    sql += " AND broadcast_state!='upcoming'"
                elif kind == 'expected':
                    sql += ' AND 0'
                sql += " ORDER BY COALESCE(CASE WHEN broadcast_state='upcoming' THEN scheduled_start_at ELSE published_at END,publication_date),video_id"
                records = [dict(r) for r in conn.execute(sql, values)]
                channel['events_next_offset'] = None
                for item in records:
                    channel['events'].append(self.event_item(item, channel, completed))
                if kind != 'published':
                    channel['events'].extend(self.forecasts.events(conn, channel['channel_id'], window, include_shorts, include_live))
                channel['events'].sort(key=lambda e:e.get('event_at') or e.get('publication_date') or '')
                channel['forecast_status'] = ('Estimates available' if any(e['state']=='expected' for e in channel['events']) else 'No reliable pattern or not enough history')
            selected = conn.execute('SELECT * FROM guide_videos WHERE video_id=? AND metadata_checked_at>?',
                                    (args.get('selected', ''), minimum)).fetchone()
            if selected and selected['channel_id'] in enabled_channels and selected['availability'] in ('public', 'unlisted'):
                channel = enabled_channels[selected['channel_id']]
                allowed = (include_shorts or selected['classification'] != 'short') and (include_live or selected['classification'] != 'livestream')
                if allowed:
                    selection = {'channel': {k: v for k, v in channel.items() if k != 'events'},
                                 'item': self.event_item(dict(selected), channel, completed)}
        return {'ok': True, 'window': window, 'channels': channels, 'total_channels': total, 'enabled_channels': len(rows),
                'selection': selection, 'next_offset': offset+limit if limit and offset+limit<total else None, 'revision': revision,
                'show_thumbnails': self.app.setting_bool('guide_show_thumbnails', False), 'forecasts': self.forecasts.status(), 'coverage': {'history': self.app.get_setting('guide_history', 'all'),
                'channel_errors': [{'channel_id': r['channel_id'], 'title': r['title'], 'error': r['guide_error'], 'retry_at': r['guide_retry_at']} for r in rows if r['guide_error']],
                'error': runtime['last_error'], 'retry_at': runtime['retry_at'], 'last_success_at': runtime['last_success_at'],
                'running': runtime['lease_until']>stamp(), 'daily_calls': runtime['calls'], 'next_refresh_at': self.next_refresh()}, 'server_time': stamp()}

    def event_item(self, item, channel, completed):
        event = {**item, 'id': item['video_id'], 'channel_title': channel['title'],
                 'video_url': 'https://www.youtube.com/watch?v='+item['video_id'],
                 'event_at': item['scheduled_start_at'] if item['broadcast_state']=='upcoming' else item['published_at'],
                 'state': 'scheduled' if item['broadcast_state']=='upcoming' else 'published',
                 'downloaded': False, 'is_short': item['classification']=='short', 'metadata_rich': True, 'channel_thumbnail_url': channel['thumbnail_url']}
        local = completed.get(item['video_id'])
        if local and self.app.is_finished_media_file(Path(str(local.get('output_path') or '')), video_only=True):
            event['downloaded'] = True
        return event
