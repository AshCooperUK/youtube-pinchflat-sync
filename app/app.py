import json
import os
import queue
import re
import secrets
import sqlite3
import threading
import time
from datetime import date, datetime, timezone
from pathlib import Path
from urllib.parse import urlparse

import requests
import yt_dlp
from apscheduler.schedulers.background import BackgroundScheduler
from bs4 import BeautifulSoup
from dateutil.relativedelta import relativedelta
from flask import Flask, flash, jsonify, redirect, render_template, request, session, url_for
from google.auth.transport.requests import Request as GoogleRequest
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import Flow
from werkzeug.middleware.proxy_fix import ProxyFix

VERSION = "1.5.2"

DATA_DIR = Path(os.getenv("DATA_DIR", "/data"))
DATA_DIR.mkdir(parents=True, exist_ok=True)
DB_PATH = DATA_DIR / "sync.db"
TOKEN_PATH = DATA_DIR / "google-token.json"
SECRET_PATH = DATA_DIR / "flask-secret.txt"

YOUTUBE_SCOPE = os.getenv(
    "YOUTUBE_SCOPE",
    "https://www.googleapis.com/auth/youtube",
)
YOUTUBE_WRITE_SCOPES = {
    "https://www.googleapis.com/auth/youtube",
    "https://www.googleapis.com/auth/youtube.force-ssl",
    "https://www.googleapis.com/auth/youtubepartner",
}
YOUTUBE_API_BASE = "https://www.googleapis.com/youtube/v3"

DOWNLOAD_ROOT = Path(os.getenv("DOWNLOAD_ROOT", "/downloads"))
DOWNLOAD_ROOT.mkdir(parents=True, exist_ok=True)

PINCHFLAT_URL = os.getenv("PINCHFLAT_URL", "http://pinchflat:8945").rstrip("/")
PINCHFLAT_PUBLIC_URL = os.getenv(
    "PINCHFLAT_PUBLIC_URL",
    "http://localhost:8945",
).rstrip("/")
PINCHFLAT_USER = os.getenv("PINCHFLAT_BASIC_AUTH_USERNAME", "")
PINCHFLAT_PASS = os.getenv("PINCHFLAT_BASIC_AUTH_PASSWORD", "")

SYNC_INTERVAL_MINUTES = int(os.getenv("SYNC_INTERVAL_MINUTES", "60"))
MAX_NEW_SOURCES_PER_RUN = int(os.getenv("MAX_NEW_SOURCES_PER_RUN", "0"))
ADD_DELAY_SECONDS = float(os.getenv("ADD_DELAY_SECONDS", "2"))
DRY_RUN = os.getenv("DRY_RUN", "false").lower() in ("1", "true", "yes", "on")

DEFAULT_HISTORY_MODE = os.getenv("INITIAL_IMPORT_CUTOFF", "today").strip().lower()
DEFAULT_HISTORY_YEARS = os.getenv("INITIAL_IMPORT_YEARS", "1").strip()
DEFAULT_CUSTOM_DATE = os.getenv("INITIAL_IMPORT_CUSTOM_DATE", "").strip()

HISTORY_MODES = {
    "default",
    "today",
    "this_week",
    "this_month",
    "six_months",
    "last_year",
    "years_2",
    "years_3",
    "years_4",
    "years_5",
    "years_6",
    "years_7",
    "years_8",
    "years_9",
    "years_10",
    "custom_date",
    "subscription_date",
}


def persistent_flask_secret():
    env_secret = os.getenv("FLASK_SECRET_KEY", "").strip()
    if env_secret:
        return env_secret

    if SECRET_PATH.exists():
        return SECRET_PATH.read_text(encoding="utf-8").strip()

    value = secrets.token_hex(32)
    SECRET_PATH.write_text(value, encoding="utf-8")
    try:
        SECRET_PATH.chmod(0o600)
    except OSError:
        pass
    return value


app = Flask(__name__)
app.secret_key = persistent_flask_secret()
app.config.update(
    SESSION_COOKIE_HTTPONLY=True,
    SESSION_COOKIE_SAMESITE="Lax",
)
app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1, x_proto=1, x_host=1)

sync_lock = threading.Lock()
download_queue = queue.Queue()
download_worker_started = False
storage_cache = {"updated_at": 0.0, "total": 0, "by_name": {}}
storage_cache_lock = threading.Lock()


def db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def ensure_column(conn, table, column, definition):
    columns = {
        row["name"]
        for row in conn.execute(f"PRAGMA table_info({table})").fetchall()
    }
    if column not in columns:
        conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} {definition}")
        return True
    return False


def init_db():
    with db() as conn:
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS subscriptions (
                channel_id TEXT PRIMARY KEY,
                title TEXT NOT NULL,
                channel_url TEXT NOT NULL,
                subscribed_at TEXT,
                first_seen_at TEXT NOT NULL,
                active INTEGER NOT NULL DEFAULT 1,
                pinchflat_added INTEGER NOT NULL DEFAULT 0,
                last_error TEXT
            );

            CREATE TABLE IF NOT EXISTS runs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                started_at TEXT NOT NULL,
                finished_at TEXT,
                status TEXT NOT NULL,
                total_subscriptions INTEGER DEFAULT 0,
                new_sources INTEGER DEFAULT 0,
                errors INTEGER DEFAULT 0,
                message TEXT
            );

            CREATE TABLE IF NOT EXISTS settings (
                key TEXT PRIMARY KEY,
                value TEXT NOT NULL
            );
            """
        )

        # Existing databases are upgraded in place.
        ensure_column(conn, "subscriptions", "history_mode", "TEXT")
        ensure_column(conn, "subscriptions", "history_custom_date", "TEXT")
        ensure_column(conn, "subscriptions", "pinchflat_source_id", "TEXT")
        download_enabled_added = ensure_column(
            conn,
            "subscriptions",
            "download_enabled",
            "INTEGER NOT NULL DEFAULT 0",
        )

        # Preserve the behaviour of sources created before v1.3. New YouTube
        # subscriptions still default to disabled.
        if download_enabled_added:
            conn.execute(
                """
                UPDATE subscriptions
                SET download_enabled = CASE
                    WHEN pinchflat_added = 1 THEN 1
                    ELSE 0
                END
                """
            )

        ensure_column(conn, "subscriptions", "needs_review", "INTEGER NOT NULL DEFAULT 0")
        ensure_column(conn, "subscriptions", "media_profile_id", "TEXT")
        ensure_column(conn, "subscriptions", "removed_at", "TEXT")
        ensure_column(conn, "subscriptions", "retry_count", "INTEGER NOT NULL DEFAULT 0")
        ensure_column(conn, "subscriptions", "youtube_subscription_id", "TEXT")
        ensure_column(conn, "subscriptions", "thumbnail_url", "TEXT")

        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS activity (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                created_at TEXT NOT NULL,
                event_type TEXT NOT NULL,
                title TEXT NOT NULL,
                message TEXT NOT NULL,
                severity TEXT NOT NULL DEFAULT 'info',
                channel_id TEXT
            );

            CREATE TABLE IF NOT EXISTS api_usage (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                occurred_at TEXT NOT NULL,
                usage_date TEXT NOT NULL,
                method TEXT NOT NULL,
                units INTEGER NOT NULL,
                success INTEGER NOT NULL DEFAULT 1
            );

            CREATE TABLE IF NOT EXISTS downloads (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                job_id TEXT UNIQUE NOT NULL,
                source_type TEXT NOT NULL,
                youtube_url TEXT NOT NULL,
                video_id TEXT,
                title TEXT,
                channel_title TEXT,
                playlist_item_id TEXT,
                status TEXT NOT NULL DEFAULT 'queued',
                progress REAL NOT NULL DEFAULT 0,
                speed TEXT,
                eta TEXT,
                downloaded_bytes INTEGER NOT NULL DEFAULT 0,
                total_bytes INTEGER NOT NULL DEFAULT 0,
                output_path TEXT,
                error TEXT,
                remove_playlist_item INTEGER NOT NULL DEFAULT 0,
                created_at TEXT NOT NULL,
                started_at TEXT,
                finished_at TEXT
            );
            """
        )

        defaults = {
            "history_mode": DEFAULT_HISTORY_MODE,
            "history_years": DEFAULT_HISTORY_YEARS,
            "history_custom_date": DEFAULT_CUSTOM_DATE,
            "app_url": os.getenv("APP_URL", "").strip(),
            "google_client_id": os.getenv("GOOGLE_CLIENT_ID", "").strip(),
            "google_client_secret": os.getenv("GOOGLE_CLIENT_SECRET", "").strip(),
            "pinchflat_media_profile_id": os.getenv(
                "PINCHFLAT_MEDIA_PROFILE_ID", "1"
            ).strip(),
            "new_subscription_policy": "auto_enable",
            "unsubscribe_policy": "keep",
            "show_removed": "0",
            "sync_interval_minutes": str(SYNC_INTERVAL_MINUTES),
            "auto_retry": "1",
            "auto_create_media_profile": "1",
            "emby_download_enabled": "1",
            "emby_download_playlist_name": "Emby Download",
            "emby_download_poll_minutes": "5",
            "emby_download_remove_after_success": "1",
            "youtube_daily_quota": "10000",
            "single_download_folder": "Single Downloads",
            "emby_download_folder": "Emby Download",
        }
        for key, value in defaults.items():
            if value:
                conn.execute(
                    "INSERT OR IGNORE INTO settings (key, value) VALUES (?, ?)",
                    (key, value),
                )


def now_iso():
    return datetime.now(timezone.utc).isoformat()


def get_setting(key, default=""):
    with db() as conn:
        row = conn.execute(
            "SELECT value FROM settings WHERE key = ?",
            (key,),
        ).fetchone()
    return row["value"] if row else default


def set_setting(key, value):
    with db() as conn:
        conn.execute(
            """
            INSERT INTO settings (key, value)
            VALUES (?, ?)
            ON CONFLICT(key) DO UPDATE SET value = excluded.value
            """,
            (key, str(value)),
        )


def setting_bool(key, default=False):
    value = get_setting(key, "1" if default else "0").strip().lower()
    return value in ("1", "true", "yes", "on")


def setting_int(key, default, minimum=None, maximum=None):
    try:
        value = int(get_setting(key, str(default)))
    except (TypeError, ValueError):
        value = default

    if minimum is not None:
        value = max(minimum, value)
    if maximum is not None:
        value = min(maximum, value)
    return value


def log_activity(event_type, title, message, severity="info", channel_id=None):
    with db() as conn:
        conn.execute(
            """
            INSERT INTO activity (
                created_at, event_type, title, message, severity, channel_id
            )
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (now_iso(), event_type, title, message, severity, channel_id),
        )


def record_api_usage(method, units, success=True):
    with db() as conn:
        conn.execute(
            """
            INSERT INTO api_usage (occurred_at, usage_date, method, units, success)
            VALUES (?, ?, ?, ?, ?)
            """,
            (now_iso(), date.today().isoformat(), method, int(units), 1 if success else 0),
        )


def api_usage_stats():
    today = date.today().isoformat()
    quota = setting_int("youtube_daily_quota", 10000, 100, 100000000)
    with db() as conn:
        row = conn.execute(
            """
            SELECT COALESCE(SUM(units), 0) AS units,
                   COUNT(*) AS calls,
                   COALESCE(SUM(CASE WHEN success = 0 THEN 1 ELSE 0 END), 0) AS failures
            FROM api_usage
            WHERE usage_date = ?
            """,
            (today,),
        ).fetchone()
        methods = conn.execute(
            """
            SELECT method, SUM(units) AS units, COUNT(*) AS calls
            FROM api_usage
            WHERE usage_date = ?
            GROUP BY method
            ORDER BY units DESC, method ASC
            LIMIT 20
            """,
            (today,),
        ).fetchall()

    used = int(row["units"] or 0)
    return {
        "date": today,
        "quota": quota,
        "used": used,
        "remaining": max(0, quota - used),
        "calls": int(row["calls"] or 0),
        "failures": int(row["failures"] or 0),
        "percent": min(100.0, (used / quota * 100.0) if quota else 0.0),
        "methods": [dict(item) for item in methods],
    }


def youtube_api_request(creds, http_method, path, quota_method, quota_cost=1, **kwargs):
    url = path if path.startswith("http") else f"{YOUTUBE_API_BASE}/{path.lstrip('/')}"
    headers = dict(kwargs.pop("headers", {}) or {})
    headers["Authorization"] = f"Bearer {creds.token}"
    response = requests.request(
        http_method,
        url,
        headers=headers,
        timeout=kwargs.pop("timeout", 30),
        **kwargs,
    )
    record_api_usage(quota_method, quota_cost, response.ok)
    response.raise_for_status()
    return response


def google_write_scope_ready(creds=None):
    try:
        creds = creds or load_credentials()
    except Exception:
        return False
    if not creds:
        return False
    granted = set(creds.scopes or [])
    return bool(granted.intersection(YOUTUBE_WRITE_SCOPES))


def format_bytes(value):
    try:
        value = float(value or 0)
    except (TypeError, ValueError):
        value = 0.0

    units = ["B", "KB", "MB", "GB", "TB", "PB"]
    index = 0
    while value >= 1024 and index < len(units) - 1:
        value /= 1024.0
        index += 1

    if index == 0:
        return f"{int(value)} {units[index]}"
    return f"{value:.1f} {units[index]}"


def normalise_storage_name(value):
    value = (value or "").strip().casefold()
    value = re.sub(r'[<>:"/\\\\|?*]', "", value)
    value = re.sub(r"\\s+", " ", value)
    return value.strip(" .")


def storage_snapshot(force=False):
    now = time.time()
    with storage_cache_lock:
        if not force and now - storage_cache["updated_at"] < 300:
            return {
                "total": storage_cache["total"],
                "by_name": dict(storage_cache["by_name"]),
            }

    total = 0
    by_name = {}
    if DOWNLOAD_ROOT.exists():
        for root, _dirs, files in os.walk(DOWNLOAD_ROOT):
            root_path = Path(root)
            try:
                relative = root_path.relative_to(DOWNLOAD_ROOT)
                parts = list(relative.parts)
            except ValueError:
                parts = []

            folder_keys = {
                normalise_storage_name(part)
                for part in parts[-4:]
                if normalise_storage_name(part)
            }

            for filename in files:
                path = root_path / filename
                try:
                    size = path.stat().st_size
                except OSError:
                    continue
                total += size
                for key in folder_keys:
                    by_name[key] = by_name.get(key, 0) + size

    with storage_cache_lock:
        storage_cache["updated_at"] = now
        storage_cache["total"] = total
        storage_cache["by_name"] = dict(by_name)

    return {"total": total, "by_name": by_name}


def channel_disk_usage(title, snapshot=None):
    snapshot = snapshot or storage_snapshot()
    return int(snapshot["by_name"].get(normalise_storage_name(title), 0))


def valid_youtube_url(value):
    try:
        parsed = urlparse(value)
    except Exception:
        return False
    host = (parsed.hostname or "").casefold()
    return parsed.scheme in {"http", "https"} and (
        host == "youtu.be"
        or host.endswith(".youtube.com")
        or host == "youtube.com"
        or host.endswith(".youtube-nocookie.com")
    )


def download_job_row(job_id):
    with db() as conn:
        row = conn.execute(
            "SELECT * FROM downloads WHERE job_id = ?",
            (job_id,),
        ).fetchone()
    return dict(row) if row else None


def enqueue_download(
    youtube_url,
    source_type="single",
    video_id=None,
    title=None,
    channel_title=None,
    playlist_item_id=None,
    remove_playlist_item=False,
):
    if not valid_youtube_url(youtube_url):
        raise RuntimeError("Enter a valid YouTube video URL.")

    if playlist_item_id:
        with db() as conn:
            existing = conn.execute(
                """
                SELECT job_id, status
                FROM downloads
                WHERE playlist_item_id = ?
                ORDER BY id DESC
                LIMIT 1
                """,
                (playlist_item_id,),
            ).fetchone()
        if existing and existing["status"] in {"queued", "downloading", "completed"}:
            return existing["job_id"], False

    job_id = secrets.token_hex(12)
    with db() as conn:
        conn.execute(
            """
            INSERT INTO downloads (
                job_id, source_type, youtube_url, video_id, title, channel_title,
                playlist_item_id, status, progress, remove_playlist_item, created_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, 'queued', 0, ?, ?)
            """,
            (
                job_id,
                source_type,
                youtube_url,
                video_id,
                title,
                channel_title,
                playlist_item_id,
                1 if remove_playlist_item else 0,
                now_iso(),
            ),
        )

    download_queue.put(job_id)
    log_activity(
        "download",
        "Download queued",
        f"{title or youtube_url} queued from {source_type}.",
        "info",
    )
    return job_id, True


def update_download_job(job_id, **values):
    if not values:
        return
    allowed = {
        "video_id", "title", "channel_title", "status", "progress", "speed",
        "eta", "downloaded_bytes", "total_bytes", "output_path", "error",
        "started_at", "finished_at",
    }
    values = {key: value for key, value in values.items() if key in allowed}
    if not values:
        return
    assignments = ", ".join(f"{key} = ?" for key in values)
    params = list(values.values()) + [job_id]
    with db() as conn:
        conn.execute(
            f"UPDATE downloads SET {assignments} WHERE job_id = ?",
            params,
        )


def remove_playlist_item_from_youtube(playlist_item_id):
    if not playlist_item_id:
        return False
    creds = load_credentials()
    if not creds or not google_write_scope_ready(creds):
        raise RuntimeError("Google needs reconnecting with YouTube write access.")
    youtube_api_request(
        creds,
        "DELETE",
        "playlistItems",
        "playlistItems.delete",
        50,
        params={"id": playlist_item_id},
    )
    return True


def _download_progress_hook(job_id):
    def hook(data):
        status = data.get("status")
        if status == "downloading":
            downloaded = int(data.get("downloaded_bytes") or 0)
            total = int(data.get("total_bytes") or data.get("total_bytes_estimate") or 0)
            progress = (downloaded / total * 100.0) if total else 0.0
            speed = data.get("_speed_str") or (
                f"{format_bytes(data.get('speed'))}/s" if data.get("speed") else ""
            )
            eta = data.get("_eta_str") or (
                str(data.get("eta")) + "s" if data.get("eta") is not None else ""
            )
            update_download_job(
                job_id,
                status="downloading",
                progress=round(progress, 2),
                speed=str(speed).strip(),
                eta=str(eta).strip(),
                downloaded_bytes=downloaded,
                total_bytes=total,
            )
        elif status == "finished":
            update_download_job(
                job_id,
                status="processing",
                progress=100.0,
                output_path=data.get("filename") or "",
            )
    return hook


def run_download_job(job_id):
    job = download_job_row(job_id)
    if not job:
        return

    folder_setting = (
        get_setting("emby_download_folder", "Emby Download")
        if job["source_type"] == "emby_download"
        else get_setting("single_download_folder", "Single Downloads")
    )
    folder_setting = folder_setting.strip().strip("/\\\\") or "Single Downloads"
    output_dir = DOWNLOAD_ROOT / folder_setting
    output_dir.mkdir(parents=True, exist_ok=True)

    update_download_job(
        job_id,
        status="downloading",
        started_at=now_iso(),
        error=None,
        progress=0,
    )

    output_template = str(
        output_dir
        / "%(uploader,channel|Unknown Channel).80B"
        / "%(title).180B [%(id)s].%(ext)s"
    )

    ydl_opts = {
        "format": "bestvideo*+bestaudio/best",
        "merge_output_format": "mp4",
        "outtmpl": output_template,
        "noplaylist": True,
        "continuedl": True,
        "overwrites": False,
        "writethumbnail": True,
        "writeinfojson": True,
        "embedmetadata": True,
        "embedthumbnail": True,
        "progress_hooks": [_download_progress_hook(job_id)],
        "quiet": True,
        "no_warnings": True,
    }

    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(job["youtube_url"], download=True)

        output_path = ""
        requested = info.get("requested_downloads") or []
        if requested:
            output_path = requested[0].get("filepath") or requested[0].get("filename") or ""
        if not output_path:
            try:
                output_path = ydl.prepare_filename(info)
            except Exception:
                output_path = job.get("output_path") or ""

        update_download_job(
            job_id,
            video_id=info.get("id") or job.get("video_id"),
            title=info.get("title") or job.get("title"),
            channel_title=(
                info.get("uploader")
                or info.get("channel")
                or job.get("channel_title")
            ),
            status="completed",
            progress=100.0,
            output_path=output_path,
            finished_at=now_iso(),
            error=None,
        )

        if job.get("remove_playlist_item") and job.get("playlist_item_id"):
            try:
                remove_playlist_item_from_youtube(job["playlist_item_id"])
                log_activity(
                    "emby_download",
                    "Emby Download item completed",
                    f"{info.get('title') or job['youtube_url']} downloaded and removed from the playlist.",
                    "success",
                )
            except Exception as exc:
                log_activity(
                    "emby_download",
                    "Playlist cleanup failed",
                    f"Download completed, but the playlist item could not be removed: {exc}",
                    "warning",
                )
        else:
            log_activity(
                "download",
                "Download completed",
                f"{info.get('title') or job['youtube_url']} completed.",
                "success",
            )

        storage_snapshot(force=True)

    except Exception as exc:
        update_download_job(
            job_id,
            status="failed",
            error=str(exc)[:1500],
            finished_at=now_iso(),
        )
        log_activity(
            "download",
            "Download failed",
            f"{job.get('title') or job['youtube_url']}: {exc}",
            "error",
        )


def download_worker():
    while True:
        job_id = download_queue.get()
        try:
            run_download_job(job_id)
        finally:
            download_queue.task_done()


def start_download_worker():
    global download_worker_started
    if download_worker_started:
        return
    download_worker_started = True

    with db() as conn:
        conn.execute(
            """
            UPDATE downloads
            SET status = 'queued', started_at = NULL
            WHERE status IN ('downloading', 'processing')
            """
        )
        queued = conn.execute(
            "SELECT job_id FROM downloads WHERE status = 'queued' ORDER BY id ASC"
        ).fetchall()

    thread = threading.Thread(
        target=download_worker,
        name="youtube-download-worker",
        daemon=True,
    )
    thread.start()

    for row in queued:
        download_queue.put(row["job_id"])


def youtube_playlists(creds):
    items = []
    page_token = None
    while True:
        params = {
            "part": "snippet,status",
            "mine": "true",
            "maxResults": 50,
        }
        if page_token:
            params["pageToken"] = page_token
        response = youtube_api_request(
            creds,
            "GET",
            "playlists",
            "playlists.list",
            1,
            params=params,
        )
        payload = response.json()
        items.extend(payload.get("items", []))
        page_token = payload.get("nextPageToken")
        if not page_token:
            break
    return items


def ensure_emby_download_playlist(creds=None):
    if not setting_bool("emby_download_enabled", True):
        return None

    creds = creds or load_credentials()
    if not creds:
        raise RuntimeError("Google account is not connected.")
    if not google_write_scope_ready(creds):
        raise RuntimeError("Reconnect Google to enable Emby Download playlist access.")

    playlist_name = get_setting("emby_download_playlist_name", "Emby Download").strip() or "Emby Download"
    playlists = youtube_playlists(creds)
    for item in playlists:
        if (item.get("snippet", {}).get("title") or "").strip().casefold() == playlist_name.casefold():
            playlist_id = item.get("id")
            set_setting("emby_download_playlist_id", playlist_id or "")
            return playlist_id

    response = youtube_api_request(
        creds,
        "POST",
        "playlists?part=snippet,status",
        "playlists.insert",
        50,
        json={
            "snippet": {
                "title": playlist_name,
                "description": "Videos placed here are downloaded automatically by YouTube Pinchflat Sync for Emby.",
            },
            "status": {"privacyStatus": "private"},
        },
    )
    playlist_id = response.json().get("id")
    if not playlist_id:
        raise RuntimeError("YouTube created the playlist but returned no playlist ID.")
    set_setting("emby_download_playlist_id", playlist_id)
    log_activity(
        "emby_download",
        "Emby Download playlist created",
        f'Created private YouTube playlist "{playlist_name}".',
        "success",
    )
    return playlist_id


def emby_download_playlist_items(creds, playlist_id):
    items = []
    page_token = None
    while True:
        params = {
            "part": "snippet,contentDetails",
            "playlistId": playlist_id,
            "maxResults": 50,
        }
        if page_token:
            params["pageToken"] = page_token
        response = youtube_api_request(
            creds,
            "GET",
            "playlistItems",
            "playlistItems.list",
            1,
            params=params,
        )
        payload = response.json()
        items.extend(payload.get("items", []))
        page_token = payload.get("nextPageToken")
        if not page_token:
            break
    return items


def sync_emby_download_playlist():
    result = {"playlist_id": None, "found": 0, "queued": 0, "skipped": 0, "error": None}
    if not setting_bool("emby_download_enabled", True):
        return result

    try:
        creds = load_credentials()
        if not creds:
            return result
        if not google_write_scope_ready(creds):
            result["error"] = "Reconnect Google to grant YouTube write access."
            return result

        playlist_id = ensure_emby_download_playlist(creds)
        result["playlist_id"] = playlist_id
        if not playlist_id:
            return result

        items = emby_download_playlist_items(creds, playlist_id)
        result["found"] = len(items)
        remove_after = setting_bool("emby_download_remove_after_success", True)

        for item in items:
            snippet = item.get("snippet", {})
            details = item.get("contentDetails", {})
            video_id = details.get("videoId") or snippet.get("resourceId", {}).get("videoId")
            playlist_item_id = item.get("id")
            title = snippet.get("title") or video_id
            channel_title = snippet.get("videoOwnerChannelTitle") or snippet.get("channelTitle") or ""

            if not video_id or not playlist_item_id:
                result["skipped"] += 1
                continue

            job_id, created = enqueue_download(
                f"https://www.youtube.com/watch?v={video_id}",
                source_type="emby_download",
                video_id=video_id,
                title=title,
                channel_title=channel_title,
                playlist_item_id=playlist_item_id,
                remove_playlist_item=remove_after,
            )
            if created:
                result["queued"] += 1
            else:
                result["skipped"] += 1

        if result["queued"]:
            log_activity(
                "emby_download",
                "Emby Download queue updated",
                f"Queued {result['queued']} new video(s) from the Emby Download playlist.",
                "success",
            )
    except Exception as exc:
        result["error"] = str(exc)
        log_activity(
            "emby_download",
            "Emby Download sync failed",
            str(exc),
            "error",
        )

    return result


def youtube_unsubscribe(channel_id, youtube_subscription_id=None):
    creds = load_credentials()
    if not creds:
        raise RuntimeError("Google account is not connected.")
    if not google_write_scope_ready(creds):
        raise RuntimeError("Reconnect Google to grant permission to unsubscribe from channels.")

    subscription_id = youtube_subscription_id
    if not subscription_id:
        for item in youtube_subscriptions(creds):
            if item.get("channel_id") == channel_id:
                subscription_id = item.get("youtube_subscription_id")
                break

    if not subscription_id:
        raise RuntimeError("The YouTube subscription ID could not be found.")

    youtube_api_request(
        creds,
        "DELETE",
        "subscriptions",
        "subscriptions.delete",
        50,
        params={"id": subscription_id},
    )
    return subscription_id


def current_sync_interval():
    return setting_int("sync_interval_minutes", SYNC_INTERVAL_MINUTES, 5, 1440)


def current_emby_poll_interval():
    """Return the configured Emby Download playlist polling interval."""
    return setting_int("emby_download_poll_minutes", 5, 1, 1440)


def new_subscription_policy():
    value = get_setting("new_subscription_policy", "auto_enable").strip()
    if value not in {"auto_enable", "disabled", "review"}:
        return "auto_enable"
    return value


def unsubscribe_policy():
    value = get_setting("unsubscribe_policy", "keep").strip()
    if value not in {"keep", "disable", "remove"}:
        return "keep"
    return value


def effective_app_url():
    value = get_setting("app_url", os.getenv("APP_URL", "")).strip()
    return value.rstrip("/")


def effective_google_client_id():
    return get_setting(
        "google_client_id",
        os.getenv("GOOGLE_CLIENT_ID", ""),
    ).strip()


def effective_google_client_secret():
    return get_setting(
        "google_client_secret",
        os.getenv("GOOGLE_CLIENT_SECRET", ""),
    ).strip()


def effective_media_profile_id():
    return get_setting(
        "pinchflat_media_profile_id",
        os.getenv("PINCHFLAT_MEDIA_PROFILE_ID", "1"),
    ).strip() or "1"


def subscription_media_profile_id(sub):
    override = str(row_value(sub, "media_profile_id", "") or "").strip()
    return override or effective_media_profile_id()


def google_redirect_uri():
    explicit = os.getenv("GOOGLE_REDIRECT_URI", "").strip()
    if explicit:
        return explicit

    app_url = effective_app_url()
    if not app_url:
        return ""

    return f"{app_url}/oauth/google/callback"


def google_configured():
    return bool(
        effective_google_client_id()
        and effective_google_client_secret()
        and google_redirect_uri()
    )


def client_config():
    if not google_configured():
        raise RuntimeError(
            "Google OAuth is not configured. Open Configuration first."
        )

    return {
        "web": {
            "client_id": effective_google_client_id(),
            "client_secret": effective_google_client_secret(),
            "auth_uri": "https://accounts.google.com/o/oauth2/auth",
            "token_uri": "https://oauth2.googleapis.com/token",
        }
    }


def make_flow(state=None):
    flow = Flow.from_client_config(
        client_config(),
        scopes=[YOUTUBE_SCOPE],
        state=state,
    )
    flow.redirect_uri = google_redirect_uri()
    return flow


def load_credentials():
    if not TOKEN_PATH.exists():
        return None

    data = json.loads(TOKEN_PATH.read_text(encoding="utf-8"))
    creds = Credentials.from_authorized_user_info(data)

    if creds.expired and creds.refresh_token:
        creds.refresh(GoogleRequest())
        save_credentials(creds)

    return creds


def save_credentials(creds):
    TOKEN_PATH.write_text(creds.to_json(), encoding="utf-8")
    try:
        TOKEN_PATH.chmod(0o600)
    except OSError:
        pass


def default_history_settings():
    mode = get_setting("history_mode", DEFAULT_HISTORY_MODE)
    try:
        years = int(
            get_setting("history_years", DEFAULT_HISTORY_YEARS) or "1"
        )
    except ValueError:
        years = 1

    years = min(max(years, 1), 20)
    custom_date = get_setting(
        "history_custom_date",
        DEFAULT_CUSTOM_DATE,
    )

    return {
        "mode": mode,
        "years": years,
        "custom_date": custom_date,
    }


def row_value(row, key, default=None):
    if row is None:
        return default

    try:
        value = row[key]
    except (KeyError, IndexError, TypeError):
        value = row.get(key, default) if isinstance(row, dict) else default

    return default if value is None else value


def resolve_history_cutoff(
    subscribed_at=None,
    mode=None,
    custom_date=None,
):
    defaults = default_history_settings()

    effective_mode = (mode or "default").strip()
    if effective_mode == "default":
        effective_mode = defaults["mode"]

    if effective_mode == "years_back":
        # Compatibility with v1.1 global setting.
        try:
            years = defaults["years"]
        except (TypeError, ValueError):
            years = 1
        effective_mode = f"years_{years}"

    today = date.today()

    if effective_mode == "today":
        cutoff = today
    elif effective_mode == "this_week":
        cutoff = today - relativedelta(days=today.weekday())
    elif effective_mode == "this_month":
        cutoff = today.replace(day=1)
    elif effective_mode == "six_months":
        cutoff = today - relativedelta(months=6)
    elif effective_mode == "last_year":
        cutoff = today - relativedelta(years=1)
    elif effective_mode.startswith("years_"):
        try:
            years = int(effective_mode.split("_", 1)[1])
        except (ValueError, IndexError):
            years = 1
        years = min(max(years, 1), 20)
        cutoff = today - relativedelta(years=years)
    elif effective_mode == "custom_date":
        candidate = custom_date or defaults["custom_date"]
        try:
            cutoff = date.fromisoformat(candidate)
        except (TypeError, ValueError):
            cutoff = today
    elif effective_mode == "subscription_date" and subscribed_at:
        try:
            cutoff = date.fromisoformat(subscribed_at[:10])
        except (TypeError, ValueError):
            cutoff = today
    else:
        cutoff = today

    return cutoff.isoformat()


def history_label(mode, custom_date="", subscribed_at=None):
    defaults = default_history_settings()
    effective_mode = (mode or "default").strip()

    if effective_mode == "default":
        effective_mode = defaults["mode"]

    labels = {
        "today": "Today",
        "this_week": "This week",
        "this_month": "This month",
        "six_months": "Last 6 months",
        "last_year": "Last year",
        "custom_date": "Custom date",
        "subscription_date": "Original subscription date",
    }

    if effective_mode == "years_back":
        years = defaults["years"]
        return f"Last {years} year{'s' if years != 1 else ''}"

    if effective_mode.startswith("years_"):
        try:
            years = int(effective_mode.split("_", 1)[1])
        except (ValueError, IndexError):
            years = 1
        return f"Last {years} year{'s' if years != 1 else ''}"

    if effective_mode == "custom_date" and custom_date:
        return f"From {custom_date}"

    if effective_mode == "subscription_date" and subscribed_at:
        return f"From subscription date"

    return labels.get(effective_mode, "Today")


def subscription_cutoff(sub):
    mode = row_value(sub, "history_mode", "default") or "default"
    custom_date = row_value(sub, "history_custom_date", "") or ""
    subscribed_at = row_value(sub, "subscribed_at", None)

    return resolve_history_cutoff(
        subscribed_at=subscribed_at,
        mode=mode,
        custom_date=custom_date,
    )


def youtube_subscriptions(creds):
    headers = {"Authorization": f"Bearer {creds.token}"}
    params = {
        "part": "snippet",
        "mine": "true",
        "maxResults": 50,
    }

    items = []
    page_token = None

    while True:
        if page_token:
            params["pageToken"] = page_token
        else:
            params.pop("pageToken", None)

        response = youtube_api_request(
            creds,
            "GET",
            "subscriptions",
            "subscriptions.list",
            1,
            params=params,
        )
        payload = response.json()

        for item in payload.get("items", []):
            snippet = item["snippet"]
            channel_id = snippet["resourceId"]["channelId"]

            thumbnails = snippet.get("thumbnails") or {}
            thumbnail = (
                thumbnails.get("high")
                or thumbnails.get("medium")
                or thumbnails.get("default")
                or {}
            )

            items.append(
                {
                    "channel_id": channel_id,
                    "title": snippet.get("title", channel_id),
                    "channel_url": (
                        f"https://www.youtube.com/channel/{channel_id}"
                    ),
                    "subscribed_at": snippet.get("publishedAt"),
                    "youtube_subscription_id": item.get("id"),
                    "thumbnail_url": thumbnail.get("url", ""),
                }
            )

        page_token = payload.get("nextPageToken")
        if not page_token:
            break

    return items


def refresh_subscriptions():
    creds = load_credentials()
    if not creds:
        raise RuntimeError("Google account is not connected.")

    subs = youtube_subscriptions(creds)
    first_seen = now_iso()
    current_ids = {sub["channel_id"] for sub in subs}
    policy = new_subscription_policy()

    new_count = 0
    removed_rows = []

    with db() as conn:
        existing_active = conn.execute(
            """
            SELECT *
            FROM subscriptions
            WHERE active = 1
            """
        ).fetchall()

        removed_rows = [
            dict(row)
            for row in existing_active
            if row["channel_id"] not in current_ids
        ]

        conn.execute("UPDATE subscriptions SET active = 0")

        for sub in subs:
            existing = conn.execute(
                """
                SELECT channel_id
                FROM subscriptions
                WHERE channel_id = ?
                """,
                (sub["channel_id"],),
            ).fetchone()

            if existing is None:
                new_count += 1
                enabled = 1 if policy == "auto_enable" else 0
                needs_review = 1 if policy == "review" else 0

                conn.execute(
                    """
                    INSERT INTO subscriptions (
                        channel_id,
                        title,
                        channel_url,
                        subscribed_at,
                        first_seen_at,
                        active,
                        history_mode,
                        download_enabled,
                        needs_review,
                        removed_at,
                        youtube_subscription_id,
                        thumbnail_url
                    )
                    VALUES (?, ?, ?, ?, ?, 1, 'default', ?, ?, NULL, ?, ?)
                    """,
                    (
                        sub["channel_id"],
                        sub["title"],
                        sub["channel_url"],
                        sub["subscribed_at"],
                        first_seen,
                        enabled,
                        needs_review,
                        sub.get("youtube_subscription_id"),
                        sub.get("thumbnail_url", ""),
                    ),
                )
            else:
                conn.execute(
                    """
                    UPDATE subscriptions
                    SET title = ?,
                        channel_url = ?,
                        subscribed_at = ?,
                        youtube_subscription_id = ?,
                        thumbnail_url = ?,
                        active = 1,
                        removed_at = NULL
                    WHERE channel_id = ?
                    """,
                    (
                        sub["title"],
                        sub["channel_url"],
                        sub["subscribed_at"],
                        sub.get("youtube_subscription_id"),
                        sub.get("thumbnail_url", ""),
                        sub["channel_id"],
                    ),
                )

        for row in removed_rows:
            conn.execute(
                """
                UPDATE subscriptions
                SET active = 0,
                    removed_at = COALESCE(removed_at, ?)
                WHERE channel_id = ?
                """,
                (now_iso(), row["channel_id"]),
            )

    policy_errors = 0

    for row in removed_rows:
        try:
            if unsubscribe_policy() == "disable":
                with db() as conn:
                    conn.execute(
                        """
                        UPDATE subscriptions
                        SET download_enabled = 0
                        WHERE channel_id = ?
                        """,
                        (row["channel_id"],),
                    )

                if row.get("pinchflat_added") and row.get("pinchflat_source_id"):
                    update_pinchflat_source_settings(
                        row["pinchflat_source_id"],
                        cutoff=subscription_cutoff(row),
                        download_enabled=False,
                        media_profile_id=subscription_media_profile_id(row),
                    )

            elif unsubscribe_policy() == "remove":
                if row.get("pinchflat_added") and row.get("pinchflat_source_id"):
                    delete_pinchflat_source(
                        row["pinchflat_source_id"],
                        delete_files=False,
                    )

                with db() as conn:
                    conn.execute(
                        """
                        UPDATE subscriptions
                        SET pinchflat_added = 0,
                            pinchflat_source_id = NULL,
                            last_error = NULL
                        WHERE channel_id = ?
                        """,
                        (row["channel_id"],),
                    )

        except Exception as exc:
            policy_errors += 1
            with db() as conn:
                conn.execute(
                    """
                    UPDATE subscriptions
                    SET last_error = ?,
                        retry_count = retry_count + 1
                    WHERE channel_id = ?
                    """,
                    (str(exc)[:1000], row["channel_id"]),
                )

    if new_count:
        log_activity(
            "youtube_refresh",
            "New YouTube subscriptions",
            f"Found {new_count} new subscription(s). Policy: {policy}.",
            "success",
        )

    if removed_rows:
        log_activity(
            "youtube_refresh",
            "Removed YouTube subscriptions",
            (
                f"Found {len(removed_rows)} removed subscription(s). "
                f"Policy: {unsubscribe_policy()}. Errors: {policy_errors}."
            ),
            "warning" if policy_errors else "info",
        )

    return {
        "total": len(subs),
        "new": new_count,
        "removed": len(removed_rows),
        "policy_errors": policy_errors,
    }


def pinchflat_session():
    session_obj = requests.Session()

    if PINCHFLAT_USER and PINCHFLAT_PASS:
        session_obj.auth = (PINCHFLAT_USER, PINCHFLAT_PASS)

    session_obj.headers.update(
        {"User-Agent": f"youtube-pinchflat-sync/{VERSION}"}
    )

    return session_obj


def pinchflat_health():
    try:
        response = requests.get(
            f"{PINCHFLAT_URL}/healthcheck",
            timeout=10,
        )
        return response.ok
    except requests.RequestException:
        return False


def scrape_form_payload(form):
    """Build a normal HTML form payload using the values Pinchflat supplies."""
    payload = {}

    for field in form.find_all(["input", "select", "textarea"]):
        name = field.get("name")
        if not name:
            continue

        if field.name == "input":
            field_type = (field.get("type") or "text").lower()
            if field_type in ("submit", "button", "file", "image"):
                continue
            if field_type in ("checkbox", "radio") and not field.has_attr("checked"):
                continue
            payload[name] = field.get("value", "")

        elif field.name == "select":
            selected = field.find("option", selected=True)
            if selected is None:
                selected = field.find("option")
            payload[name] = selected.get("value", "") if selected else ""

        else:
            payload[name] = field.text or ""

    return payload


def load_new_source_form(session_obj):
    form_page = session_obj.get(
        f"{PINCHFLAT_URL}/sources/new",
        timeout=30,
    )
    form_page.raise_for_status()

    soup = BeautifulSoup(form_page.text, "html.parser")
    form = soup.find("form", action=lambda value: value and "/sources" in value)
    if form is None:
        form = soup.find("form")

    if form is None:
        raise RuntimeError(
            "Pinchflat is online but its New Source form is unavailable."
        )

    profile_select = form.find("select", {"name": "source[media_profile_id]"})
    profiles = []
    if profile_select:
        for option in profile_select.find_all("option"):
            value = (option.get("value") or "").strip()
            label = " ".join(option.stripped_strings).strip()
            if value:
                profiles.append({"id": value, "name": label})

    return form, profiles


def create_default_media_profile(session_obj=None):
    """Create a simple Pinchflat media profile using Pinchflat's own form."""
    session_obj = session_obj or pinchflat_session()

    page = session_obj.get(
        f"{PINCHFLAT_URL}/media_profiles/new",
        timeout=30,
    )
    page.raise_for_status()

    soup = BeautifulSoup(page.text, "html.parser")
    form = soup.find(
        "form",
        action=lambda value: value and "/media_profiles" in value,
    )
    if form is None:
        form = soup.find("form")

    if form is None:
        raise RuntimeError(
            "Pinchflat's New Media Profile form is unavailable."
        )

    payload = scrape_form_payload(form)
    payload["media_profile[name]"] = "YouTube Sync"
    payload["media_profile[output_path_template]"] = (
        "/{{ source_custom_name }}/{{ upload_yyyy_mm_dd }} {{ title }}/"
        "{{ title }} [{{ id }}].{{ ext }}"
    )

    action = form.get("action") or "/media_profiles"
    if action.startswith("http://") or action.startswith("https://"):
        target = action
    else:
        target = (
            f"{PINCHFLAT_URL}"
            f"{action if action.startswith('/') else '/' + action}"
        )

    response = session_obj.post(
        target,
        data=payload,
        timeout=60,
        allow_redirects=False,
    )

    if response.status_code not in (301, 302, 303):
        text = " ".join(
            BeautifulSoup(response.text, "html.parser").stripped_strings
        )
        raise RuntimeError(
            "Pinchflat could not create the automatic Media Profile. "
            f"Response: {text[:350] or 'No error text returned.'}"
        )

    # Reload the source form and identify the newly created profile by name.
    source_form, profiles = load_new_source_form(session_obj)
    created = next(
        (
            profile
            for profile in profiles
            if profile["name"].strip().lower() == "youtube sync"
        ),
        None,
    )

    if created is None and len(profiles) == 1:
        created = profiles[0]

    if created is None:
        raise RuntimeError(
            "The Media Profile was created, but its ID could not be identified."
        )

    set_setting("pinchflat_media_profile_id", created["id"])
    return created, source_form, profiles


def get_new_source_form(session_obj=None, auto_create_profile=True):
    """Load Pinchflat's source form and ensure a usable media profile exists."""
    session_obj = session_obj or pinchflat_session()

    try:
        form, profiles = load_new_source_form(session_obj)
    except RuntimeError:
        if not auto_create_profile:
            raise
        _created, form, profiles = create_default_media_profile(session_obj)

    if not profiles and auto_create_profile:
        _created, form, profiles = create_default_media_profile(session_obj)

    if not profiles:
        raise RuntimeError(
            "Pinchflat has no Media Profile and automatic creation failed."
        )

    configured_profile = effective_media_profile_id()
    profile_ids = [profile["id"] for profile in profiles]

    if configured_profile not in profile_ids:
        # If there is only one profile, use it automatically. This keeps fresh
        # installs portable even if Pinchflat did not allocate ID 1.
        if len(profiles) == 1:
            configured_profile = profiles[0]["id"]
            set_setting("pinchflat_media_profile_id", configured_profile)
        else:
            raise RuntimeError(
                f"Pinchflat Media Profile ID {configured_profile} does not exist. "
                f"Available profile ID(s): {', '.join(profile_ids)}."
            )

    return session_obj, form, profile_ids


def pinchflat_profile_status():
    """Return whether Pinchflat has a usable profile, creating one if needed."""
    if not pinchflat_health():
        return {
            "ready": False,
            "message": "Pinchflat is offline or unreachable.",
            "profile_ids": [],
        }

    try:
        _session, _form, profile_ids = get_new_source_form(
            auto_create_profile=setting_bool("auto_create_media_profile", True)
        )
        return {
            "ready": True,
            "message": f"Media Profile {effective_media_profile_id()} ready.",
            "profile_ids": profile_ids,
        }
    except Exception as exc:
        return {
            "ready": False,
            "message": str(exc),
            "profile_ids": [],
        }


def complete_pinchflat_onboarding():
    """Use Pinchflat's supported onboarding flag to open the normal dashboard."""
    try:
        session_obj = pinchflat_session()
        response = session_obj.get(
            f"{PINCHFLAT_URL}/",
            params={"onboarding": "0"},
            timeout=30,
            allow_redirects=True,
        )
        response.raise_for_status()
        return True
    except requests.RequestException:
        return False


def subscription_download_enabled(sub):
    value = row_value(sub, "download_enabled", 0)
    try:
        return bool(int(value))
    except (TypeError, ValueError):
        return bool(value)


def add_pinchflat_source(sub):
    session_obj, form, _profile_ids = get_new_source_form(
        auto_create_profile=setting_bool("auto_create_media_profile", True)
    )
    payload = scrape_form_payload(form)

    cutoff = subscription_cutoff(sub)
    payload.update(
        {
            "source[original_url]": row_value(sub, "channel_url", ""),
            "source[custom_name]": row_value(sub, "title", ""),
            "source[media_profile_id]": subscription_media_profile_id(sub),
            "source[download_media]": (
                "true" if subscription_download_enabled(sub) else "false"
            ),
            "source[fast_index]": "false",
            "source[index_frequency_minutes]": "1440",
            "source[download_cutoff_date]": cutoff,
        }
    )

    if DRY_RUN:
        return "dry-run", None

    action = form.get("action") or "/sources"
    if action.startswith("http://") or action.startswith("https://"):
        target = action
    else:
        target = f"{PINCHFLAT_URL}{action if action.startswith('/') else '/' + action}"

    response = session_obj.post(
        target,
        data=payload,
        timeout=180,
        allow_redirects=False,
    )

    if response.status_code in (301, 302, 303):
        location = response.headers.get("Location", "")
        match = __import__("re").search(r"/sources/([^/?#]+)", location)
        source_id = match.group(1) if match else None
        return "created", source_id

    text = " ".join(BeautifulSoup(response.text, "html.parser").stripped_strings)

    if response.status_code == 200:
        if "already been taken" in text.lower():
            return "exists", None

        raise RuntimeError(
            "Pinchflat rejected the source. "
            f"Response: {text[:350] or 'No error text returned.'}"
        )

    if response.status_code >= 500:
        raise RuntimeError(
            f"Pinchflat returned HTTP {response.status_code} while creating the source. "
            "Check the selected Media Profile and Pinchflat logs. "
            f"Response: {text[:250] or 'No error text returned.'}"
        )

    response.raise_for_status()
    return "created", None

def update_pinchflat_source_settings(
    source_id,
    cutoff=None,
    download_enabled=None,
    media_profile_id=None,
):
    """Update an existing Pinchflat source through its HTML edit form."""
    session_obj = pinchflat_session()
    edit_url = f"{PINCHFLAT_URL}/sources/{source_id}/edit"
    response = session_obj.get(edit_url, timeout=30)
    response.raise_for_status()

    soup = BeautifulSoup(response.text, "html.parser")

    # Pinchflat pages can contain several forms, including the global search
    # form. Select the actual Source edit form rather than the first form on
    # the page. Posting the search form caused updates to be sent to /search.
    forms = soup.find_all("form")
    form = None

    for candidate in forms:
        action = candidate.get("action") or ""
        has_source_fields = (
            candidate.find(attrs={"name": "source[download_cutoff_date]"})
            or candidate.find(attrs={"name": "source[download_media]"})
            or candidate.find(attrs={"name": "source[original_url]"})
        )
        action_matches_source = (
            f"/sources/{source_id}" in action
            and "/search" not in action
        )

        if has_source_fields or action_matches_source:
            form = candidate
            break

    if form is None:
        raise RuntimeError(
            "Pinchflat Source edit form was not found. "
            "The page contained no form with Source settings."
        )

    payload = scrape_form_payload(form)

    if cutoff is not None:
        payload["source[download_cutoff_date]"] = cutoff

    if download_enabled is not None:
        payload["source[download_media]"] = (
            "true" if download_enabled else "false"
        )

    if media_profile_id is not None:
        payload["source[media_profile_id]"] = str(media_profile_id)

    action = form.get("action") or f"/sources/{source_id}"
    if action.startswith("http://") or action.startswith("https://"):
        target = action
    else:
        target = (
            f"{PINCHFLAT_URL}"
            f"{action if action.startswith('/') else '/' + action}"
        )

    update_response = session_obj.post(
        target,
        data=payload,
        timeout=180,
        allow_redirects=False,
    )

    if update_response.status_code in (301, 302, 303):
        return True

    text = " ".join(
        BeautifulSoup(update_response.text, "html.parser").stripped_strings
    )

    if update_response.status_code == 200:
        raise RuntimeError(
            "Pinchflat did not accept the source update. "
            f"Response: {text[:300]}"
        )

    if update_response.status_code >= 500:
        raise RuntimeError(
            f"Pinchflat returned HTTP {update_response.status_code} while "
            f"updating source {source_id}. Target: {target}. "
            f"Response: {text[:300] or 'No error text returned.'}"
        )

    update_response.raise_for_status()
    return True



def delete_pinchflat_source(source_id, delete_files=False):
    """Delete a Pinchflat source through its normal HTML form."""
    session_obj = pinchflat_session()
    source_url = f"{PINCHFLAT_URL}/sources/{source_id}"
    response = session_obj.get(source_url, timeout=30)
    response.raise_for_status()

    soup = BeautifulSoup(response.text, "html.parser")
    delete_form = None

    for form in soup.find_all("form"):
        method_field = form.find("input", {"name": "_method"})
        method_value = (
            (method_field.get("value") or "").strip().lower()
            if method_field
            else ""
        )
        action = form.get("action") or ""
        if method_value == "delete" and f"/sources/{source_id}" in action:
            delete_form = form
            break

    if delete_form is None:
        raise RuntimeError(
            "Pinchflat delete form was not found for this source."
        )

    payload = scrape_form_payload(delete_form)
    payload["_method"] = "delete"
    payload["delete_files"] = "true" if delete_files else "false"

    action = delete_form.get("action") or f"/sources/{source_id}"
    target = (
        action
        if action.startswith(("http://", "https://"))
        else f"{PINCHFLAT_URL}{action if action.startswith('/') else '/' + action}"
    )

    delete_response = session_obj.post(
        target,
        data=payload,
        timeout=180,
        allow_redirects=False,
    )

    if delete_response.status_code in (301, 302, 303):
        return True

    text = " ".join(
        BeautifulSoup(delete_response.text, "html.parser").stripped_strings
    )
    raise RuntimeError(
        f"Pinchflat could not remove source {source_id}. "
        f"HTTP {delete_response.status_code}. "
        f"Response: {text[:300] or 'No error text returned.'}"
    )


def pinchflat_profiles():
    if not pinchflat_health():
        return []

    try:
        session_obj = pinchflat_session()
        _form, profiles = load_new_source_form(session_obj)

        if not profiles and setting_bool("auto_create_media_profile", True):
            _created, _form, profiles = create_default_media_profile(session_obj)

        return profiles
    except Exception:
        return []


def retry_failed_source_updates():
    if not setting_bool("auto_retry", True):
        return {"attempted": 0, "fixed": 0, "errors": 0}

    with db() as conn:
        rows = conn.execute(
            """
            SELECT *
            FROM subscriptions
            WHERE active = 1
              AND pinchflat_added = 1
              AND pinchflat_source_id IS NOT NULL
              AND TRIM(COALESCE(last_error, '')) <> ''
            ORDER BY retry_count ASC, title COLLATE NOCASE ASC
            """
        ).fetchall()

    attempted = 0
    fixed = 0
    errors = 0

    for row in rows:
        attempted += 1
        try:
            update_pinchflat_source_settings(
                row["pinchflat_source_id"],
                cutoff=subscription_cutoff(row),
                download_enabled=subscription_download_enabled(row),
                media_profile_id=subscription_media_profile_id(row),
            )
            with db() as conn:
                conn.execute(
                    """
                    UPDATE subscriptions
                    SET last_error = NULL,
                        retry_count = 0
                    WHERE channel_id = ?
                    """,
                    (row["channel_id"],),
                )
            fixed += 1
        except Exception as exc:
            errors += 1
            with db() as conn:
                conn.execute(
                    """
                    UPDATE subscriptions
                    SET last_error = ?,
                        retry_count = retry_count + 1
                    WHERE channel_id = ?
                    """,
                    (str(exc)[:1000], row["channel_id"]),
                )

    if attempted:
        log_activity(
            "retry",
            "Automatic retry",
            f"Retried {attempted} source update(s). Fixed {fixed}. Errors {errors}.",
            "success" if errors == 0 else "warning",
        )

    return {"attempted": attempted, "fixed": fixed, "errors": errors}




def add_pending_sources():
    with db() as conn:
        pending = conn.execute(
            """
            SELECT *
            FROM subscriptions
            WHERE active = 1
              AND pinchflat_added = 0
              AND COALESCE(needs_review, 0) = 0
            ORDER BY first_seen_at ASC, title COLLATE NOCASE ASC
            """
        ).fetchall()

    pending = [dict(row) for row in pending]

    if MAX_NEW_SOURCES_PER_RUN > 0:
        pending = pending[:MAX_NEW_SOURCES_PER_RUN]

    added = 0
    errors = 0

    for sub in pending:
        try:
            _result, source_id = add_pinchflat_source(sub)

            with db() as conn:
                conn.execute(
                    """
                    UPDATE subscriptions
                    SET pinchflat_added = 1,
                        pinchflat_source_id = COALESCE(?, pinchflat_source_id),
                        last_error = NULL,
                        retry_count = 0
                    WHERE channel_id = ?
                    """,
                    (source_id, sub["channel_id"]),
                )

            added += 1

        except Exception as exc:
            errors += 1

            with db() as conn:
                conn.execute(
                    """
                    UPDATE subscriptions
                    SET last_error = ?,
                        retry_count = retry_count + 1
                    WHERE channel_id = ?
                    """,
                    (
                        str(exc)[:1000],
                        sub["channel_id"],
                    ),
                )

        if ADD_DELAY_SECONDS > 0:
            time.sleep(ADD_DELAY_SECONDS)

    if added > 0:
        complete_pinchflat_onboarding()

    if pending:
        log_activity(
            "pinchflat_add",
            "Pinchflat source import",
            f"Processed {len(pending)} pending source(s). Added {added}. Errors {errors}.",
            "success" if errors == 0 else "warning",
        )

    return {
        "pending": len(pending),
        "added": added,
        "errors": errors,
    }


def sync_once():
    if not sync_lock.acquire(blocking=False):
        return {
            "status": "busy",
            "message": "A sync is already running.",
        }

    run_id = None

    try:
        with db() as conn:
            cur = conn.execute(
                """
                INSERT INTO runs (started_at, status, message)
                VALUES (?, ?, ?)
                """,
                (
                    now_iso(),
                    "running",
                    "Sync started",
                ),
            )
            run_id = cur.lastrowid

        refresh = refresh_subscriptions()
        result = add_pending_sources()
        retry = retry_failed_source_updates()
        emby = sync_emby_download_playlist()

        total_errors = (
            refresh["policy_errors"]
            + result["errors"]
            + retry["errors"]
            + (1 if emby.get("error") else 0)
        )

        status = (
            "ok"
            if total_errors == 0
            else "completed_with_errors"
        )

        message = (
            f"Found {refresh['total']} subscriptions. "
            f"New {refresh['new']}. Removed {refresh['removed']}. "
            f"Added {result['added']} Pinchflat sources. "
            f"Retry fixes {retry['fixed']}. "
            f"Emby Download queued {emby.get('queued', 0)}. "
            f"Errors {total_errors}."
        )

        with db() as conn:
            conn.execute(
                """
                UPDATE runs
                SET finished_at = ?,
                    status = ?,
                    total_subscriptions = ?,
                    new_sources = ?,
                    errors = ?,
                    message = ?
                WHERE id = ?
                """,
                (
                    now_iso(),
                    status,
                    refresh["total"],
                    result["added"],
                    total_errors,
                    message,
                    run_id,
                ),
            )

        log_activity(
            "sync",
            "Synchronisation completed",
            message,
            "success" if total_errors == 0 else "warning",
        )

        return {
            "status": status,
            "total": refresh["total"],
            "added": result["added"],
            "errors": total_errors,
            "message": message,
        }

    except Exception as exc:
        if run_id:
            with db() as conn:
                conn.execute(
                    """
                    UPDATE runs
                    SET finished_at = ?,
                        status = 'failed',
                        errors = 1,
                        message = ?
                    WHERE id = ?
                    """,
                    (
                        now_iso(),
                        str(exc)[:1000],
                        run_id,
                    ),
                )

        return {
            "status": "failed",
            "message": str(exc),
        }

    finally:
        sync_lock.release()


def subscription_view(row):
    item = dict(row)
    mode = item.get("history_mode") or "default"
    custom_date = item.get("history_custom_date") or ""

    item["cutoff"] = resolve_history_cutoff(
        subscribed_at=item.get("subscribed_at"),
        mode=mode,
        custom_date=custom_date,
    )
    item["history_label"] = history_label(
        mode,
        custom_date,
        item.get("subscribed_at"),
    )
    item["download_enabled"] = subscription_download_enabled(item)
    item["media_profile_id"] = (
        item.get("media_profile_id")
        or effective_media_profile_id()
    )
    item["needs_review"] = bool(item.get("needs_review") or 0)

    if not item.get("active"):
        item["ui_status"] = "removed"
    elif item.get("needs_review"):
        item["ui_status"] = "review"
    elif item.get("last_error"):
        item["ui_status"] = "error"
    elif not item.get("pinchflat_added"):
        item["ui_status"] = "pending"
    elif item["download_enabled"]:
        item["ui_status"] = "enabled"
    else:
        item["ui_status"] = "disabled"

    return item


@app.route("/")
def index():
    google_connected = False
    google_write_ready = False

    if google_configured():
        try:
            creds = load_credentials()
            google_connected = bool(creds and creds.valid)
            google_write_ready = bool(google_connected and google_write_scope_ready(creds))
        except Exception as exc:
            flash(
                f"Google token error: {exc}",
                "error",
            )

    with db() as conn:
        rows = conn.execute(
            """
            SELECT *
            FROM subscriptions
            ORDER BY active DESC, title COLLATE NOCASE ASC
            """
        ).fetchall()

        last_run = conn.execute(
            "SELECT * FROM runs ORDER BY id DESC LIMIT 1"
        ).fetchone()

        recent_runs = conn.execute(
            "SELECT * FROM runs ORDER BY id DESC LIMIT 20"
        ).fetchall()

        activity_rows = conn.execute(
            "SELECT * FROM activity ORDER BY id DESC LIMIT 60"
        ).fetchall()

        recent_downloads = conn.execute(
            "SELECT * FROM downloads ORDER BY id DESC LIMIT 30"
        ).fetchall()

        download_counts_row = conn.execute(
            """
            SELECT
                SUM(CASE WHEN status = 'queued' THEN 1 ELSE 0 END) AS queued,
                SUM(CASE WHEN status IN ('downloading','processing') THEN 1 ELSE 0 END) AS running,
                SUM(CASE WHEN status = 'failed' THEN 1 ELSE 0 END) AS failed
            FROM downloads
            """
        ).fetchone()

    subs = [subscription_view(row) for row in rows]
    defaults = default_history_settings()
    profile_status = pinchflat_profile_status()
    profiles = pinchflat_profiles()
    storage = storage_snapshot()
    for sub in subs:
        sub["disk_bytes"] = channel_disk_usage(sub.get("title"), storage)
        sub["disk_usage"] = format_bytes(sub["disk_bytes"])

    download_counts = {
        "queued": int(download_counts_row["queued"] or 0),
        "running": int(download_counts_row["running"] or 0),
        "failed": int(download_counts_row["failed"] or 0),
    }
    api_stats = api_usage_stats()
    emby_playlist_id = get_setting("emby_download_playlist_id", "")

    counts = {
        "active": sum(1 for sub in subs if sub["active"]),
        "enabled": sum(1 for sub in subs if sub["active"] and sub["download_enabled"]),
        "disabled": sum(1 for sub in subs if sub["active"] and not sub["download_enabled"]),
        "pending": sum(1 for sub in subs if sub["active"] and not sub["pinchflat_added"]),
        "errors": sum(1 for sub in subs if sub.get("last_error")),
        "removed": sum(1 for sub in subs if not sub["active"]),
        "review": sum(1 for sub in subs if sub.get("needs_review")),
    }

    next_sync = None
    try:
        job = scheduler.get_job("subscription-sync")
        if job and job.next_run_time:
            next_sync = job.next_run_time.isoformat()
    except Exception:
        pass

    return render_template(
        "index.html",
        version=VERSION,
        google_configured=google_configured(),
        google_connected=google_connected,
        google_write_ready=google_write_ready,
        callback_uri=google_redirect_uri(),
        app_url=effective_app_url(),
        media_profile_id=effective_media_profile_id(),
        profiles=profiles,
        pinchflat_online=pinchflat_health(),
        pinchflat_profile_ready=profile_status["ready"],
        pinchflat_profile_message=profile_status["message"],
        pinchflat_public_url=PINCHFLAT_PUBLIC_URL,
        pinchflat_open_url=(
            f"{PINCHFLAT_PUBLIC_URL}/?onboarding=0"
            if profile_status["ready"]
            else PINCHFLAT_PUBLIC_URL
        ),
        subs=subs,
        counts=counts,
        last_run=last_run,
        recent_runs=recent_runs,
        activity_rows=activity_rows,
        dry_run=DRY_RUN,
        interval=current_sync_interval(),
        next_sync=next_sync,
        default_history_mode=defaults["mode"],
        default_history_years=defaults["years"],
        default_history_custom_date=defaults["custom_date"],
        default_history_cutoff=resolve_history_cutoff(),
        new_subscription_policy=new_subscription_policy(),
        unsubscribe_policy=unsubscribe_policy(),
        show_removed=setting_bool("show_removed", False),
        auto_retry=setting_bool("auto_retry", True),
        auto_create_media_profile=setting_bool("auto_create_media_profile", True),
        api_stats=api_stats,
        storage_total_bytes=storage["total"],
        storage_total=format_bytes(storage["total"]),
        download_counts=download_counts,
        recent_downloads=recent_downloads,
        emby_download_enabled=setting_bool("emby_download_enabled", True),
        emby_download_playlist_name=get_setting("emby_download_playlist_name", "Emby Download"),
        emby_download_poll_minutes=current_emby_poll_interval(),
        emby_download_playlist_id=emby_playlist_id,
        emby_download_remove_after_success=setting_bool("emby_download_remove_after_success", True),
        youtube_daily_quota=setting_int("youtube_daily_quota", 10000, 100, 100000000),
    )


@app.post("/settings/configuration")
def save_configuration():
    app_url = (
        request.form.get("app_url", "")
        .strip()
        .rstrip("/")
    )
    client_id = request.form.get(
        "google_client_id",
        "",
    ).strip()
    client_secret = request.form.get(
        "google_client_secret",
        "",
    ).strip()
    media_profile_id = request.form.get(
        "pinchflat_media_profile_id",
        "1",
    ).strip()

    if app_url:
        set_setting("app_url", app_url)

    if client_id:
        set_setting("google_client_id", client_id)

    if client_secret:
        set_setting(
            "google_client_secret",
            client_secret,
        )

    if media_profile_id:
        set_setting(
            "pinchflat_media_profile_id",
            media_profile_id,
        )

    flash(
        "Configuration saved.",
        "success",
    )
    return redirect(url_for("index"))


@app.post("/settings/history")
def save_default_history():
    mode = request.form.get(
        "history_mode",
        "today",
    ).strip()

    allowed = {
        "today",
        "this_week",
        "this_month",
        "six_months",
        "last_year",
        "years_back",
        "custom_date",
        "subscription_date",
    }

    if mode not in allowed:
        flash(
            "Unknown download history option.",
            "error",
        )
        return redirect(url_for("index"))

    try:
        years = int(
            request.form.get("history_years", "1")
        )
    except ValueError:
        years = 1

    years = min(max(years, 1), 20)
    custom_date = request.form.get(
        "history_custom_date",
        "",
    ).strip()

    if mode == "custom_date":
        try:
            parsed = date.fromisoformat(custom_date)
            if parsed > date.today():
                raise ValueError
        except ValueError:
            flash(
                "Choose a valid custom date which is not in the future.",
                "error",
            )
            return redirect(url_for("index"))

    set_setting("history_mode", mode)
    set_setting("history_years", str(years))
    set_setting("history_custom_date", custom_date)

    flash(
        "Default download range saved. "
        "Per-source choices override this default.",
        "success",
    )
    return redirect(url_for("index"))


@app.post("/subscriptions/<channel_id>/history")
def save_subscription_history(channel_id):
    mode = request.form.get(
        "history_mode",
        "default",
    ).strip()

    custom_date = request.form.get(
        "history_custom_date",
        "",
    ).strip()

    if mode not in HISTORY_MODES:
        flash(
            "Unknown source download range.",
            "error",
        )
        return redirect(
            url_for("index") + "#subscriptions"
        )

    if mode == "custom_date":
        try:
            parsed = date.fromisoformat(custom_date)
            if parsed > date.today():
                raise ValueError
        except ValueError:
            flash(
                "Choose a valid custom date which is not in the future.",
                "error",
            )
            return redirect(
                url_for("index") + "#subscriptions"
            )

    with db() as conn:
        row = conn.execute(
            """
            SELECT *
            FROM subscriptions
            WHERE channel_id = ?
            """,
            (channel_id,),
        ).fetchone()

        if not row:
            flash(
                "The YouTube subscription was not found.",
                "error",
            )
            return redirect(
                url_for("index") + "#subscriptions"
            )

        conn.execute(
            """
            UPDATE subscriptions
            SET history_mode = ?,
                history_custom_date = ?,
                last_error = NULL
            WHERE channel_id = ?
            """,
            (
                mode,
                custom_date,
                channel_id,
            ),
        )

    if row["pinchflat_added"] and row["pinchflat_source_id"]:
        try:
            cutoff = resolve_history_cutoff(
                subscribed_at=row["subscribed_at"],
                mode=mode,
                custom_date=custom_date,
            )
            update_pinchflat_source_settings(
                row["pinchflat_source_id"],
                cutoff=cutoff,
                download_enabled=bool(row["download_enabled"]),
                media_profile_id=subscription_media_profile_id(row),
            )
            flash(
                f"Source download range saved and Pinchflat updated to cutoff {cutoff}.",
                "success",
            )
        except Exception as exc:
            flash(
                "The local range was saved, but Pinchflat could not be updated: "
                f"{exc}",
                "error",
            )
    elif row["pinchflat_added"]:
        flash(
            "Download range saved locally. This older source does not have a "
            "stored Pinchflat source ID, so update its cutoff in Pinchflat.",
            "success",
        )
    else:
        flash(
            "Source download range saved.",
            "success",
        )

    return redirect(
        url_for("index") + "#subscriptions"
    )



@app.post("/subscriptions/<channel_id>/download")
def save_subscription_download(channel_id):
    enabled = request.form.get("download_enabled", "0") == "1"

    with db() as conn:
        row = conn.execute(
            """
            SELECT *
            FROM subscriptions
            WHERE channel_id = ?
            """,
            (channel_id,),
        ).fetchone()

        if not row:
            flash("The YouTube subscription was not found.", "error")
            return redirect(url_for("index") + "#subscriptions")

        conn.execute(
            """
            UPDATE subscriptions
            SET download_enabled = ?,
                last_error = NULL
            WHERE channel_id = ?
            """,
            (1 if enabled else 0, channel_id),
        )

    if row["pinchflat_added"] and row["pinchflat_source_id"]:
        try:
            update_pinchflat_source_settings(
                row["pinchflat_source_id"],
                cutoff=subscription_cutoff(row),
                download_enabled=enabled,
                media_profile_id=subscription_media_profile_id(row),
            )
            flash(
                f"{row['title']} is now "
                f"{'enabled' if enabled else 'disabled'} in Pinchflat.",
                "success",
            )
        except Exception as exc:
            flash(
                "The local setting was saved, but Pinchflat could not be updated: "
                f"{exc}",
                "error",
            )
    else:
        flash(
            f"{row['title']} will be "
            f"{'enabled' if enabled else 'disabled'} when added to Pinchflat.",
            "success",
        )

    return redirect(url_for("index") + "#subscriptions")


@app.post("/subscriptions/bulk-download")
def bulk_subscription_download():
    channel_ids = request.form.getlist("channel_ids")
    action = request.form.get("bulk_action", "").strip()

    if action not in {"enable", "disable"}:
        flash("Choose Enable selected or Disable selected.", "error")
        return redirect(url_for("index") + "#subscriptions")

    if not channel_ids:
        flash("Select at least one source.", "error")
        return redirect(url_for("index") + "#subscriptions")

    enabled = action == "enable"
    updated = 0
    pinchflat_errors = 0

    with db() as conn:
        placeholders = ",".join("?" for _ in channel_ids)
        rows = conn.execute(
            f"""
            SELECT *
            FROM subscriptions
            WHERE channel_id IN ({placeholders})
            """,
            channel_ids,
        ).fetchall()

        conn.executemany(
            """
            UPDATE subscriptions
            SET download_enabled = ?,
                last_error = NULL
            WHERE channel_id = ?
            """,
            [
                (1 if enabled else 0, row["channel_id"])
                for row in rows
            ],
        )

    for row in rows:
        updated += 1
        if row["pinchflat_added"] and row["pinchflat_source_id"]:
            try:
                update_pinchflat_source_settings(
                    row["pinchflat_source_id"],
                    cutoff=subscription_cutoff(row),
                    download_enabled=enabled,
                    media_profile_id=subscription_media_profile_id(row),
                )
            except Exception as exc:
                pinchflat_errors += 1
                with db() as conn:
                    conn.execute(
                        """
                        UPDATE subscriptions
                        SET last_error = ?
                        WHERE channel_id = ?
                        """,
                        (str(exc)[:1000], row["channel_id"]),
                    )

    flash(
        f"{'Enabled' if enabled else 'Disabled'} {updated} selected source(s). "
        f"Pinchflat errors: {pinchflat_errors}.",
        "success" if pinchflat_errors == 0 else "error",
    )
    return redirect(url_for("index") + "#subscriptions")


def reschedule_sync_job():
    try:
        scheduler.reschedule_job(
            "subscription-sync",
            trigger="interval",
            minutes=current_sync_interval(),
        )
    except Exception:
        pass

    try:
        scheduler.reschedule_job(
            "emby-download-sync",
            trigger="interval",
            minutes=current_emby_poll_interval(),
        )
    except Exception:
        pass


@app.post("/settings/general")
def save_general_settings():
    new_policy = request.form.get("new_subscription_policy", "auto_enable").strip()
    removed_policy = request.form.get("unsubscribe_policy", "keep").strip()

    if new_policy not in {"auto_enable", "disabled", "review"}:
        new_policy = "auto_enable"
    if removed_policy not in {"keep", "disable", "remove"}:
        removed_policy = "keep"

    set_setting("new_subscription_policy", new_policy)
    set_setting("unsubscribe_policy", removed_policy)
    set_setting(
        "show_removed",
        "1" if request.form.get("show_removed") == "1" else "0",
    )

    log_activity(
        "settings",
        "General settings updated",
        f"New subscriptions: {new_policy}. Removed subscriptions: {removed_policy}.",
    )
    flash("General settings saved.", "success")
    return redirect(url_for("index") + "#subscriptions")


@app.post("/settings/automation")
def save_automation_settings():
    try:
        interval = int(request.form.get("sync_interval_minutes", "60"))
    except ValueError:
        interval = 60

    interval = min(max(interval, 5), 1440)
    set_setting("sync_interval_minutes", str(interval))
    set_setting(
        "auto_retry",
        "1" if request.form.get("auto_retry") == "1" else "0",
    )
    reschedule_sync_job()

    log_activity(
        "settings",
        "Automation settings updated",
        f"Sync interval set to {interval} minutes.",
    )
    flash("Automation settings saved.", "success")
    return redirect(url_for("index"))


@app.post("/settings/pinchflat")
def save_pinchflat_settings():
    profile_id = request.form.get("pinchflat_media_profile_id", "").strip()
    if profile_id:
        set_setting("pinchflat_media_profile_id", profile_id)

    set_setting(
        "auto_create_media_profile",
        "1" if request.form.get("auto_create_media_profile") == "1" else "0",
    )

    log_activity(
        "settings",
        "Pinchflat settings updated",
        f"Default Media Profile: {profile_id or effective_media_profile_id()}.",
    )
    flash("Pinchflat settings saved.", "success")
    return redirect(url_for("index"))


@app.post("/subscriptions/<channel_id>/profile")
def save_subscription_profile(channel_id):
    profile_id = request.form.get("media_profile_id", "").strip()

    with db() as conn:
        row = conn.execute(
            "SELECT * FROM subscriptions WHERE channel_id = ?",
            (channel_id,),
        ).fetchone()
        if not row:
            flash("The YouTube subscription was not found.", "error")
            return redirect(url_for("index") + "#subscriptions")

        conn.execute(
            """
            UPDATE subscriptions
            SET media_profile_id = ?,
                last_error = NULL
            WHERE channel_id = ?
            """,
            (profile_id or None, channel_id),
        )

    if row["pinchflat_added"] and row["pinchflat_source_id"]:
        try:
            update_pinchflat_source_settings(
                row["pinchflat_source_id"],
                cutoff=subscription_cutoff(row),
                download_enabled=subscription_download_enabled(row),
                media_profile_id=profile_id or effective_media_profile_id(),
            )
            flash("Media Profile updated in Pinchflat.", "success")
        except Exception as exc:
            with db() as conn:
                conn.execute(
                    "UPDATE subscriptions SET last_error = ? WHERE channel_id = ?",
                    (str(exc)[:1000], channel_id),
                )
            flash(f"Profile saved locally, but Pinchflat update failed: {exc}", "error")
    else:
        flash("Media Profile selection saved.", "success")

    return redirect(url_for("index") + "#subscriptions")


@app.post("/subscriptions/<channel_id>/retry")
def retry_subscription(channel_id):
    with db() as conn:
        row = conn.execute(
            "SELECT * FROM subscriptions WHERE channel_id = ?",
            (channel_id,),
        ).fetchone()

    if not row:
        flash("The YouTube subscription was not found.", "error")
        return redirect(url_for("index") + "#subscriptions")

    try:
        if row["pinchflat_added"] and row["pinchflat_source_id"]:
            update_pinchflat_source_settings(
                row["pinchflat_source_id"],
                cutoff=subscription_cutoff(row),
                download_enabled=subscription_download_enabled(row),
                media_profile_id=subscription_media_profile_id(row),
            )
        elif not row["needs_review"]:
            _result, source_id = add_pinchflat_source(row)
            with db() as conn:
                conn.execute(
                    """
                    UPDATE subscriptions
                    SET pinchflat_added = 1,
                        pinchflat_source_id = COALESCE(?, pinchflat_source_id)
                    WHERE channel_id = ?
                    """,
                    (source_id, channel_id),
                )

        with db() as conn:
            conn.execute(
                """
                UPDATE subscriptions
                SET last_error = NULL, retry_count = 0
                WHERE channel_id = ?
                """,
                (channel_id,),
            )
        flash("Source retry completed.", "success")
    except Exception as exc:
        with db() as conn:
            conn.execute(
                """
                UPDATE subscriptions
                SET last_error = ?, retry_count = retry_count + 1
                WHERE channel_id = ?
                """,
                (str(exc)[:1000], channel_id),
            )
        flash(f"Retry failed: {exc}", "error")

    return redirect(url_for("index") + "#subscriptions")


@app.post("/subscriptions/bulk")
def bulk_subscription_action():
    channel_ids = request.form.getlist("channel_ids")
    action = request.form.get("bulk_action", "").strip()

    if not channel_ids:
        flash("Select at least one source.", "error")
        return redirect(url_for("index") + "#subscriptions")

    placeholders = ",".join("?" for _ in channel_ids)
    with db() as conn:
        rows = [
            dict(row)
            for row in conn.execute(
                f"SELECT * FROM subscriptions WHERE channel_id IN ({placeholders})",
                channel_ids,
            ).fetchall()
        ]

    errors = 0
    changed = 0

    for row in rows:
        try:
            if action in {"enable", "disable"}:
                enabled = action == "enable"
                with db() as conn:
                    conn.execute(
                        """
                        UPDATE subscriptions
                        SET download_enabled = ?,
                            needs_review = 0,
                            last_error = NULL
                        WHERE channel_id = ?
                        """,
                        (1 if enabled else 0, row["channel_id"]),
                    )
                if row["pinchflat_added"] and row["pinchflat_source_id"]:
                    update_pinchflat_source_settings(
                        row["pinchflat_source_id"],
                        cutoff=subscription_cutoff(row),
                        download_enabled=enabled,
                        media_profile_id=subscription_media_profile_id(row),
                    )

            elif action == "approve":
                with db() as conn:
                    conn.execute(
                        """
                        UPDATE subscriptions
                        SET needs_review = 0,
                            last_error = NULL
                        WHERE channel_id = ?
                        """,
                        (row["channel_id"],),
                    )

            elif action == "range":
                mode = request.form.get("bulk_history_mode", "default").strip()
                custom = request.form.get("bulk_custom_date", "").strip()
                if mode not in HISTORY_MODES:
                    raise RuntimeError("Invalid bulk download range.")
                with db() as conn:
                    conn.execute(
                        """
                        UPDATE subscriptions
                        SET history_mode = ?,
                            history_custom_date = ?,
                            last_error = NULL
                        WHERE channel_id = ?
                        """,
                        (mode, custom, row["channel_id"]),
                    )
                if row["pinchflat_added"] and row["pinchflat_source_id"]:
                    update_pinchflat_source_settings(
                        row["pinchflat_source_id"],
                        cutoff=resolve_history_cutoff(
                            subscribed_at=row.get("subscribed_at"),
                            mode=mode,
                            custom_date=custom,
                        ),
                        download_enabled=subscription_download_enabled(row),
                        media_profile_id=subscription_media_profile_id(row),
                    )

            elif action == "profile":
                profile_id = request.form.get("bulk_profile_id", "").strip()
                if not profile_id:
                    raise RuntimeError("Choose a Media Profile.")
                with db() as conn:
                    conn.execute(
                        """
                        UPDATE subscriptions
                        SET media_profile_id = ?,
                            last_error = NULL
                        WHERE channel_id = ?
                        """,
                        (profile_id, row["channel_id"]),
                    )
                if row["pinchflat_added"] and row["pinchflat_source_id"]:
                    update_pinchflat_source_settings(
                        row["pinchflat_source_id"],
                        cutoff=subscription_cutoff(row),
                        download_enabled=subscription_download_enabled(row),
                        media_profile_id=profile_id,
                    )

            elif action == "retry":
                if row["pinchflat_added"] and row["pinchflat_source_id"]:
                    update_pinchflat_source_settings(
                        row["pinchflat_source_id"],
                        cutoff=subscription_cutoff(row),
                        download_enabled=subscription_download_enabled(row),
                        media_profile_id=subscription_media_profile_id(row),
                    )
                elif not row["needs_review"]:
                    _result, source_id = add_pinchflat_source(row)
                    with db() as conn:
                        conn.execute(
                            """
                            UPDATE subscriptions
                            SET pinchflat_added = 1,
                                pinchflat_source_id = COALESCE(?, pinchflat_source_id)
                            WHERE channel_id = ?
                            """,
                            (source_id, row["channel_id"]),
                        )
                with db() as conn:
                    conn.execute(
                        "UPDATE subscriptions SET last_error = NULL, retry_count = 0 WHERE channel_id = ?",
                        (row["channel_id"],),
                    )

            else:
                raise RuntimeError("Unknown bulk action.")

            changed += 1

        except Exception as exc:
            errors += 1
            with db() as conn:
                conn.execute(
                    """
                    UPDATE subscriptions
                    SET last_error = ?,
                        retry_count = retry_count + 1
                    WHERE channel_id = ?
                    """,
                    (str(exc)[:1000], row["channel_id"]),
                )

    log_activity(
        "bulk",
        "Bulk source action",
        f"Action {action}. Changed {changed}. Errors {errors}.",
        "success" if errors == 0 else "warning",
    )
    flash(
        f"Bulk action complete. Updated {changed} source(s). Errors {errors}.",
        "success" if errors == 0 else "error",
    )
    return redirect(url_for("index") + "#subscriptions")


@app.post("/subscriptions/<channel_id>/unsubscribe")
def unsubscribe_from_youtube(channel_id):
    with db() as conn:
        row = conn.execute(
            "SELECT * FROM subscriptions WHERE channel_id = ?",
            (channel_id,),
        ).fetchone()

    if row is None:
        flash("Subscription was not found.", "error")
        return redirect(url_for("index") + "#subscriptions")

    try:
        youtube_unsubscribe(
            channel_id,
            row_value(row, "youtube_subscription_id", None),
        )

        with db() as conn:
            conn.execute(
                """
                UPDATE subscriptions
                SET active = 0,
                    removed_at = ?,
                    last_error = NULL
                WHERE channel_id = ?
                """,
                (now_iso(), channel_id),
            )

        row_dict = dict(row)
        policy = unsubscribe_policy()
        if policy == "disable" and row_dict.get("pinchflat_added") and row_dict.get("pinchflat_source_id"):
            update_pinchflat_source_settings(
                row_dict["pinchflat_source_id"],
                cutoff=subscription_cutoff(row_dict),
                download_enabled=False,
                media_profile_id=subscription_media_profile_id(row_dict),
            )
        elif policy == "remove" and row_dict.get("pinchflat_added") and row_dict.get("pinchflat_source_id"):
            delete_pinchflat_source(row_dict["pinchflat_source_id"], delete_files=False)
            with db() as conn:
                conn.execute(
                    """
                    UPDATE subscriptions
                    SET pinchflat_added = 0, pinchflat_source_id = NULL
                    WHERE channel_id = ?
                    """,
                    (channel_id,),
                )

        log_activity(
            "youtube",
            "YouTube subscription removed",
            f"Unsubscribed from {row_dict.get('title') or channel_id}.",
            "success",
            channel_id,
        )
        flash(f"Unsubscribed from {row_dict.get('title') or channel_id} on YouTube.", "success")
    except Exception as exc:
        with db() as conn:
            conn.execute(
                "UPDATE subscriptions SET last_error = ? WHERE channel_id = ?",
                (str(exc)[:1000], channel_id),
            )
        flash(str(exc), "error")

    return redirect(url_for("index") + "#subscriptions")


@app.post("/single-download/start")
def single_download_start():
    payload = request.get_json(silent=True) or request.form
    youtube_url = str(payload.get("youtube_url", "")).strip()
    try:
        job_id, _created = enqueue_download(youtube_url, source_type="single")
        return jsonify({"ok": True, "job_id": job_id})
    except Exception as exc:
        return jsonify({"ok": False, "error": str(exc)}), 400


@app.get("/api/downloads/<job_id>")
def download_status(job_id):
    row = download_job_row(job_id)
    if not row:
        return jsonify({"ok": False, "error": "Download job not found."}), 404
    row["downloaded_text"] = format_bytes(row.get("downloaded_bytes"))
    row["total_text"] = format_bytes(row.get("total_bytes"))
    return jsonify({"ok": True, "job": row})


@app.get("/api/downloads/recent")
def recent_download_status():
    with db() as conn:
        rows = conn.execute(
            "SELECT * FROM downloads ORDER BY id DESC LIMIT 20"
        ).fetchall()
    return jsonify(
        {
            "ok": True,
            "jobs": [
                {
                    **dict(row),
                    "downloaded_text": format_bytes(row["downloaded_bytes"]),
                    "total_text": format_bytes(row["total_bytes"]),
                }
                for row in rows
            ],
        }
    )


@app.post("/settings/youtube")
def save_youtube_settings():
    set_setting(
        "emby_download_enabled",
        "1" if request.form.get("emby_download_enabled") == "1" else "0",
    )
    set_setting("emby_download_playlist_name", "Emby Download")
    try:
        poll_minutes = int(request.form.get("emby_download_poll_minutes", "5"))
    except ValueError:
        poll_minutes = 5
    poll_minutes = min(max(poll_minutes, 1), 1440)
    set_setting("emby_download_poll_minutes", str(poll_minutes))
    set_setting(
        "emby_download_remove_after_success",
        "1" if request.form.get("emby_download_remove_after_success") == "1" else "0",
    )
    try:
        quota = int(request.form.get("youtube_daily_quota", "10000"))
    except ValueError:
        quota = 10000
    quota = min(max(quota, 100), 100000000)
    set_setting("youtube_daily_quota", str(quota))

    if setting_bool("emby_download_enabled", True) and google_write_scope_ready():
        try:
            ensure_emby_download_playlist()
        except Exception as exc:
            flash(f"Settings saved, but Emby Download setup needs attention: {exc}", "error")
            return redirect(url_for("index"))

    reschedule_sync_job()

    log_activity(
        "settings",
        "YouTube settings updated",
        "Emby Download and API settings were updated.",
        "info",
    )
    flash("YouTube settings saved.", "success")
    return redirect(url_for("index"))


@app.post("/emby-download/ensure")
def ensure_emby_download_now():
    try:
        playlist_id = ensure_emby_download_playlist()
        flash(f'Private playlist "Emby Download" is ready ({playlist_id}).', "success")
    except Exception as exc:
        flash(str(exc), "error")
    return redirect(url_for("index"))



@app.route("/oauth/google/login")
def google_login():
    if not google_configured():
        flash(
            "Save the Google OAuth configuration first.",
            "error",
        )
        return redirect(url_for("index"))

    flow = make_flow()
    auth_url, state = flow.authorization_url(
        access_type="offline",
        prompt="consent",
    )

    session["oauth_state"] = state
    return redirect(auth_url)


@app.route("/oauth/google/callback")
def google_callback():
    state = session.pop("oauth_state", None)
    flow = make_flow(state=state)
    flow.fetch_token(
        authorization_response=request.url
    )
    save_credentials(flow.credentials)
    log_activity("google", "Google connected", "Google OAuth connection completed.", "success")

    playlist_note = ""
    if google_write_scope_ready(flow.credentials) and setting_bool("emby_download_enabled", True):
        try:
            ensure_emby_download_playlist(flow.credentials)
            playlist_note = ' Private playlist "Emby Download" is ready.'
        except Exception as exc:
            playlist_note = f" Emby Download setup needs attention: {exc}"

    flash(
        "Google account connected." + playlist_note,
        "success",
    )
    return redirect(url_for("index"))


@app.post("/oauth/google/disconnect")
def google_disconnect():
    if TOKEN_PATH.exists():
        TOKEN_PATH.unlink()
    log_activity("google", "Google disconnected", "Google OAuth token removed.", "info")

    flash(
        "Google account disconnected.",
        "success",
    )
    return redirect(url_for("index"))


@app.post("/refresh-subscriptions")
def refresh_only():
    try:
        result = refresh_subscriptions()
        flash(
            (
                f"Refreshed {result['total']} YouTube subscriptions. "
                f"New {result['new']}. Removed {result['removed']}. "
                f"Policy errors {result['policy_errors']}."
            ),
            "success" if result["policy_errors"] == 0 else "error",
        )
    except Exception as exc:
        flash(
            str(exc),
            "error",
        )

    return redirect(
        url_for("index") + "#subscriptions"
    )


@app.post("/add-pending")
def add_pending():
    if not pinchflat_health():
        flash(
            "Pinchflat is offline or unreachable.",
            "error",
        )
        return redirect(
            url_for("index") + "#subscriptions"
        )

    result = add_pending_sources()

    flash(
        (
            f"Added {result['added']} pending source(s) to Pinchflat. "
            f"Errors: {result['errors']}."
        ),
        "success" if result["errors"] == 0 else "error",
    )

    return redirect(
        url_for("index") + "#subscriptions"
    )


@app.post("/sync")
def sync_now():
    result = sync_once()

    category = (
        "success"
        if result["status"] in (
            "ok",
            "completed_with_errors",
        )
        else "error"
    )

    flash(
        result["message"],
        category,
    )
    return redirect(url_for("index"))


@app.route("/health")
def health():
    return jsonify(
        {
            "status": "ok",
            "version": VERSION,
            "google_configured": google_configured(),
            "pinchflat": pinchflat_health(),
            "google_write_ready": google_write_scope_ready(),
            "default_cutoff": resolve_history_cutoff(),
            "download_storage_bytes": storage_snapshot()["total"],
        }
    )


init_db()
start_download_worker()

scheduler = BackgroundScheduler(
    timezone=os.getenv("TZ", "Europe/London")
)
scheduler.add_job(
    sync_once,
    "interval",
    minutes=current_sync_interval(),
    id="subscription-sync",
    max_instances=1,
)
scheduler.add_job(
    sync_emby_download_playlist,
    "interval",
    minutes=current_emby_poll_interval(),
    id="emby-download-sync",
    max_instances=1,
)
scheduler.start()
