import base64
import hashlib
import hmac
import http.client
import io
import json
import os
import queue
import random
import re
import secrets
import shutil
import socket
import subprocess
import sqlite3
import struct
import threading
import xml.etree.ElementTree as ET
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import parse_qs, quote, urlencode, urlparse

import qrcode
import requests
import yt_dlp
from PIL import Image, ImageOps
from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError, VerifyMismatchError
from apscheduler.schedulers.background import BackgroundScheduler
from bs4 import BeautifulSoup
from dateutil.relativedelta import relativedelta
from flask import Flask, abort, flash, jsonify, redirect, render_template, request, session, url_for
from google.auth.transport.requests import Request as GoogleRequest
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import Flow
from werkzeug.middleware.proxy_fix import ProxyFix

from downloader_auth import (
    authenticated_ydl_options,
    classify_yt_dlp_error,
    cookie_file_status,
    parse_custom_yt_dlp_options,
    save_cookie_upload,
    should_retry_with_cookies,
    test_cookie_authentication,
)

VERSION = "3.0.0"

ENV_APP_URL = os.getenv("APP_URL", "").strip().rstrip("/")
CANONICAL_REDIRECT = os.getenv(
    "CANONICAL_REDIRECT",
    "false",
).strip().lower() in ("1", "true", "yes", "on")

DATA_DIR = Path(os.getenv("DATA_DIR", "/data"))
DATA_DIR.mkdir(parents=True, exist_ok=True)
DB_PATH = DATA_DIR / "sync.db"
TOKEN_PATH = DATA_DIR / "google-token.json"
SECRET_PATH = DATA_DIR / "flask-secret.txt"
AUTH_DIR = DATA_DIR / "auth"
AUTH_DIR.mkdir(parents=True, exist_ok=True)
YOUTUBE_COOKIE_PATH = AUTH_DIR / "youtube-cookies.txt"

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
PINCHFLAT_DB_PATH_OVERRIDE = os.getenv(
    "PINCHFLAT_DB_PATH",
    "",
).strip()

PINCHFLAT_DB_CANDIDATES = (
    Path("/pinchflat-config/db/pinchflat.db"),
    Path("/pinchflat-config/pinchflat.db"),
)


def resolve_pinchflat_db_path():
    """
    Find the mounted Pinchflat SQLite database.

    New Pinchflat installs normally use:
        /config/db/pinchflat.db

    The Pinchflat config directory is mounted into this app at:
        /pinchflat-config

    Older layouts used the database directly inside the config directory.
    """
    if PINCHFLAT_DB_PATH_OVERRIDE:
        override = Path(PINCHFLAT_DB_PATH_OVERRIDE)
        if override.exists():
            return override

    for candidate in PINCHFLAT_DB_CANDIDATES:
        if candidate.exists():
            return candidate

    # Use the current layout as the diagnostic/default path if neither exists.
    return PINCHFLAT_DB_CANDIDATES[0]


PINCHFLAT_DB_PATH = resolve_pinchflat_db_path()
DOCKER_SOCKET_PATH = Path(
    os.getenv("DOCKER_SOCKET_PATH", "/var/run/docker.sock")
)
PINCHFLAT_CONTAINER_NAME = os.getenv(
    "PINCHFLAT_CONTAINER_NAME",
    "pinchflat",
).strip() or "pinchflat"
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

PASSWORD_MIN_LENGTH = 12
PASSWORD_HASHER = PasswordHasher(
    time_cost=3,
    memory_cost=65536,
    parallelism=2,
    hash_len=32,
    salt_len=16,
)
USERNAME_RE = re.compile(r"^[A-Za-z0-9_.-]{3,64}$")
RECOVERY_CODE_COUNT = 10

LEGACY_EMBY_OUTPUT_PATH_TEMPLATE = (
    "{{ source_custom_name }}/"
    "{{ season_by_year__episode_by_date_and_index }} - {{ title }}.{{ ext }}"
)

EMBY_OUTPUT_PATH_TEMPLATE = (
    "/shows/{{ source_custom_name }}/"
    "{{ season_by_year__episode_by_date_and_index }} - {{ title }}.{{ ext }}"
)

SPONSORBLOCK_COMMON_CATEGORIES = [
    ("sponsor", "Sponsor"),
    ("outro", "Outro/Credits"),
    ("preview", "Preview/Recap"),
    ("intro", "Intro/Intermission"),
]

STANDARD_MEDIA_PROFILES = [
    {"name": "YouTube 1080p", "resolution": "1080p"},
    {"name": "YouTube 720p", "resolution": "720p"},
    {"name": "YouTube Audio Only", "resolution": "audio"},
    {"name": "YouTube 4K", "resolution": "2160p"},
]

DISCOVERY_TERMS = [
    "technology", "engineering", "history", "science", "photography",
    "documentary", "computers", "networking", "cars", "motorcycles",
    "aviation", "trains", "architecture", "restoration", "workshop",
    "electronics", "retro computing", "space", "nature", "wildlife",
    "travel", "cooking", "music", "art", "design", "manufacturing",
    "infrastructure", "cybersecurity", "linux", "homelab", "radio",
    "mechanical", "urban exploration", "maker", "woodworking", "tools",
    "farming", "boats", "weather", "geography", "archaeology",
]

TOP100_WIKIPEDIA_URL = (
    "https://en.wikipedia.org/wiki/"
    "List_of_most-subscribed_YouTube_channels"
)
TOP100_CACHE_SECONDS = 21600
TOP100_CACHE = {
    "expires_at": 0.0,
    "results": [],
    "retrieved_at": "",
}

LATEST_SUBSCRIPTIONS_CACHE_SECONDS = 300
LATEST_SUBSCRIPTIONS_CACHE = {
    "expires_at": 0.0,
    "results": [],
    "shorts": [],
    "retrieved_at": "",
}

YOUTUBE_CHANNEL_FEED_CACHE_SECONDS = 600
YOUTUBE_CHANNEL_FEED_CACHE = {}
YOUTUBE_CHANNEL_FEED_LOCK = threading.Lock()

YOUTUBE_ACCOUNT_STATS_CACHE_SECONDS = 600
YOUTUBE_ACCOUNT_STATS_CACHE = {
    "expires_at": 0.0,
    "data": None,
}
YOUTUBE_ACCOUNT_STATS_LOCK = threading.Lock()

YOUTUBE_VIDEO_METADATA_CACHE_SECONDS = 900
YOUTUBE_VIDEO_METADATA_CACHE = {}
YOUTUBE_VIDEO_METADATA_LOCK = threading.Lock()

YOUTUBE_LIKED_VIDEOS_CACHE_SECONDS = 600
YOUTUBE_LIKED_VIDEOS_CACHE = {
    "expires_at": 0.0,
    "results": [],
    "retrieved_at": "",
}
YOUTUBE_LIKED_VIDEOS_LOCK = threading.Lock()

YOUTUBE_DISLIKED_VIDEOS_CACHE_SECONDS = 600
YOUTUBE_DISLIKED_VIDEOS_CACHE = {
    "expires_at": 0.0,
    "results": [],
    "retrieved_at": "",
}
YOUTUBE_DISLIKED_VIDEOS_LOCK = threading.Lock()

YOUTUBE_CHANNEL_DETAILS_CACHE_SECONDS = 21600
YOUTUBE_CHANNEL_DETAILS_CACHE = {}
YOUTUBE_CHANNEL_DETAILS_LOCK = threading.Lock()

YOUTUBE_VIDEO_CATEGORIES = {
    "1": "Film & Animation",
    "2": "Autos & Vehicles",
    "10": "Music",
    "15": "Pets & Animals",
    "17": "Sports",
    "19": "Travel & Events",
    "20": "Gaming",
    "22": "People & Blogs",
    "23": "Comedy",
    "24": "Entertainment",
    "25": "News & Politics",
    "26": "Howto & Style",
    "27": "Education",
    "28": "Science & Technology",
    "29": "Nonprofits & Activism",
    "30": "Movies",
    "43": "Shows",
    "44": "Trailers",
}

YOUTUBE_CHANNEL_FEED_WORKERS = 24

TOTP_ISSUER = "YouTube Subscription Downloader"



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
    SESSION_COOKIE_SECURE=ENV_APP_URL.lower().startswith("https://"),
    PERMANENT_SESSION_LIFETIME=timedelta(days=365),
)
app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1, x_proto=1, x_host=1)

sync_lock = threading.Lock()
pinchflat_source_action_lock = threading.Lock()
download_queue = queue.Queue()
download_worker_started = False
download_worker_count = 0
scan_queue = queue.Queue()
scan_worker_started = False
pinchflat_task_blocker_started = False
pinchflat_task_block_lock = threading.Lock()
pinchflat_task_block_last = {"at": "", "cancelled": 0, "deleted": 0, "error": ""}
storage_cache = {"updated_at": 0.0, "total": 0, "by_name": {}}
storage_cache_lock = threading.Lock()
retention_cleanup_lock = threading.Lock()

# Rolling file-size samples used to estimate live Pinchflat download speed when
# yt-dlp does not emit a progress line.  Pinchflat commonly runs yt-dlp with
# --no-progress, so this gives the dashboard a useful best-effort speed without
# changing Pinchflat's own downloader arguments.
pinchflat_speed_samples = {}
pinchflat_speed_samples_lock = threading.Lock()


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
        source_authorised_added = ensure_column(
            conn,
            "subscriptions",
            "source_authorised",
            "INTEGER NOT NULL DEFAULT 0",
        )

        # v1.9.1 safety migration. Only an existing Pinchflat link is trusted
        # as authorised. Old Enabled/Pending state must not recreate sources.
        if source_authorised_added:
            conn.execute(
                """
                UPDATE subscriptions
                SET source_authorised = CASE
                    WHEN pinchflat_added = 1 THEN 1
                    ELSE 0
                END
                """
            )
            conn.execute(
                """
                UPDATE subscriptions
                SET download_enabled = 0
                WHERE source_authorised = 0
                  AND pinchflat_added = 0
                """
            )

        # v2.6 retires the old approval workflow. The Enabled toggle is now
        # the only authority for whether an active YouTube subscription
        # should exist as a Pinchflat source. Keep needs_review only for
        # backwards-compatible database upgrades.
        conn.execute(
            """
            UPDATE subscriptions
            SET needs_review = 0,
                source_authorised = CASE
                    WHEN active = 1 AND download_enabled = 1 THEN 1
                    ELSE 0
                END
            """
        )

        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS manually_deleted_channels (
                channel_id TEXT PRIMARY KEY,
                title TEXT,
                deleted_at TEXT NOT NULL,
                absence_confirmed INTEGER NOT NULL DEFAULT 0
            );

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
                phase TEXT,
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

            CREATE TABLE IF NOT EXISTS users (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                username TEXT UNIQUE NOT NULL,
                display_name TEXT,
                password_hash TEXT NOT NULL,
                role TEXT NOT NULL DEFAULT 'viewer',
                active INTEGER NOT NULL DEFAULT 1,
                totp_secret TEXT,
                totp_enabled INTEGER NOT NULL DEFAULT 0,
                recovery_code_hashes TEXT NOT NULL DEFAULT '[]',
                failed_attempts INTEGER NOT NULL DEFAULT 0,
                locked_until REAL,
                session_version INTEGER NOT NULL DEFAULT 1,
                created_at TEXT NOT NULL,
                last_login_at TEXT
            );

            CREATE TABLE IF NOT EXISTS auth_events (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                created_at TEXT NOT NULL,
                user_id INTEGER,
                username TEXT,
                event_type TEXT NOT NULL,
                success INTEGER NOT NULL DEFAULT 1,
                ip_address TEXT,
                user_agent TEXT,
                message TEXT
            );

            CREATE TABLE IF NOT EXISTS cleanup_jobs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                channel_id TEXT NOT NULL,
                channel_title TEXT NOT NULL,
                output_template TEXT,
                due_at REAL NOT NULL,
                checks_remaining INTEGER NOT NULL DEFAULT 6,
                interval_seconds INTEGER NOT NULL DEFAULT 300,
                status TEXT NOT NULL DEFAULT 'pending',
                last_error TEXT,
                created_at TEXT NOT NULL,
                finished_at TEXT
            );

            CREATE TABLE IF NOT EXISTS favourite_channels (
                user_id INTEGER NOT NULL,
                channel_id TEXT NOT NULL,
                channel_title TEXT NOT NULL,
                channel_url TEXT NOT NULL,
                thumbnail_url TEXT,
                created_at TEXT NOT NULL,
                PRIMARY KEY (user_id, channel_id)
            );

            CREATE TABLE IF NOT EXISTS pinchflat_force_index_state (
                channel_id TEXT PRIMARY KEY,
                source_id TEXT,
                last_forced_at REAL NOT NULL DEFAULT 0,
                last_status TEXT,
                last_error TEXT,
                updated_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS discovery_likes (
                user_id INTEGER NOT NULL,
                video_id TEXT NOT NULL,
                title TEXT NOT NULL,
                channel_id TEXT,
                channel_title TEXT,
                created_at TEXT NOT NULL,
                PRIMARY KEY (user_id, video_id)
            );

            CREATE TABLE IF NOT EXISTS saved_videos (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                video_id TEXT NOT NULL,
                title TEXT NOT NULL,
                channel_id TEXT,
                channel_title TEXT,
                video_url TEXT NOT NULL,
                thumbnail_url TEXT,
                favourite INTEGER NOT NULL DEFAULT 1,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                UNIQUE (user_id, video_id)
            );

            CREATE TABLE IF NOT EXISTS video_lists (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                name TEXT NOT NULL,
                created_at TEXT NOT NULL,
                UNIQUE (user_id, name)
            );

            CREATE TABLE IF NOT EXISTS video_list_members (
                list_id INTEGER NOT NULL,
                saved_video_id INTEGER NOT NULL,
                added_at TEXT NOT NULL,
                PRIMARY KEY (list_id, saved_video_id)
            );

            CREATE TABLE IF NOT EXISTS video_retention_overrides (
                channel_id TEXT PRIMARY KEY,
                retention_days INTEGER,
                minimum_videos INTEGER,
                updated_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS retention_protected_videos (
                video_id TEXT PRIMARY KEY,
                channel_id TEXT,
                title TEXT,
                created_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS retention_runs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                started_at TEXT NOT NULL,
                finished_at TEXT,
                status TEXT NOT NULL DEFAULT 'running',
                candidate_count INTEGER NOT NULL DEFAULT 0,
                deleted_count INTEGER NOT NULL DEFAULT 0,
                reclaimed_bytes INTEGER NOT NULL DEFAULT 0,
                errors INTEGER NOT NULL DEFAULT 0,
                message TEXT
            );

            CREATE TABLE IF NOT EXISTS retention_deletions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                deleted_at TEXT NOT NULL,
                video_id TEXT,
                media_item_id INTEGER,
                channel_id TEXT,
                channel_title TEXT,
                title TEXT,
                size_bytes INTEGER NOT NULL DEFAULT 0,
                reason TEXT
            );

            CREATE TABLE IF NOT EXISTS channel_stats_history (
                channel_id TEXT NOT NULL,
                snapshot_date TEXT NOT NULL,
                recorded_at TEXT NOT NULL,
                subscriber_count INTEGER NOT NULL DEFAULT 0,
                view_count INTEGER NOT NULL DEFAULT 0,
                video_count INTEGER NOT NULL DEFAULT 0,
                PRIMARY KEY (channel_id, snapshot_date)
            );

            CREATE INDEX IF NOT EXISTS idx_channel_stats_history_channel_date
            ON channel_stats_history(channel_id, snapshot_date DESC);
            """
        )

        ensure_column(conn, "cleanup_jobs", "source_id", "TEXT")
        ensure_column(
            conn,
            "cleanup_jobs",
            "delete_files",
            "INTEGER NOT NULL DEFAULT 0",
        )
        ensure_column(
            conn,
            "cleanup_jobs",
            "source_deleted",
            "INTEGER NOT NULL DEFAULT 0",
        )
        ensure_column(
            conn,
            "downloads",
            "phase",
            "TEXT",
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
            "pin_favourites_to_top": "1",
            "sync_interval_minutes": str(SYNC_INTERVAL_MINUTES),
            "youtube_sync_interval_minutes": str(SYNC_INTERVAL_MINUTES),
            "pinchflat_sync_interval_minutes": str(SYNC_INTERVAL_MINUTES),
            "pinchflat_force_index_favourite_minutes": "0",
            "pinchflat_force_index_nonfavourite_minutes": "0",
            "pinchflat_task_block_enabled": "0",
            "downloader_default_profile": "1080p",
            "downloader_worker_concurrency": "1",
            "downloader_scan_workers": "4",
            "downloader_deep_scan_limit": "500",
            "downloader_po_token": "",
            "downloader_custom_yt_dlp_options": "{}",
            "downloader_auth_retry": "1",
            "retention_enabled": "0",
            "retention_favourite_days": "365",
            "retention_favourite_min_videos": "20",
            "retention_nonfavourite_days": "90",
            "retention_nonfavourite_min_videos": "5",
            "retention_grace_days": "7",
            "retention_cleanup_interval_hours": "24",
            "retention_protect_favourite_videos": "1",
            "retention_last_run_at": "",
            "auto_retry": "1",
            "auto_create_media_profile": "1",
            "emby_download_enabled": "1",
            "emby_download_playlist_name": "Emby Download",
            "emby_download_poll_minutes": "5",
            "emby_download_remove_after_success": "1",
            "youtube_daily_quota": "10000",
            "youtube_search_daily_limit": "100",
            "single_download_folder": "Single Downloads",
            "single_download_format": "best",
            "single_download_compatibility_profile": "emby_tv",
            "single_download_audio_format": "m4a",
            "single_download_write_nfo": "1",
            "single_download_output_template": "%(uploader,channel|Unknown Channel).80B/%(title).180B [%(id)s].%(ext)s",
            "emby_download_folder": "Emby Download",
            "emby_server_url": os.getenv("EMBY_SERVER_URL", "").strip().rstrip("/"),
            "emby_api_key": os.getenv("EMBY_API_KEY", "").strip(),
            "emby_auto_refresh_after_download": "1",
            "emby_library_path": "/media/Storage/Media/YouTube",
            "emby_last_refresh_media_id": "",
            "auth_remember_login_days": "30",
            "auth_session_timeout_minutes": "720",
            "auth_lockout_attempts": "5",
            "auth_lockout_minutes": "15",

            # Page View defaults
            "page_load_summary": "1",
            "page_load_pinchflat_downloads": "1",
            "page_load_latest_videos": "1",
            "page_load_subscriptions": "1",

            "page_min_pinchflat_downloads": "1",
            "page_min_latest_videos": "1",
            "page_min_subscriptions": "1",

            "page_show_summary_google": "1",
            "page_show_summary_pinchflat": "1",
            "page_show_summary_pinchflat_tasks": "1",
            "page_show_summary_subscriptions": "1",
            "page_show_summary_downloads": "1",
            "page_show_summary_errors": "1",
            "page_show_summary_latest_download": "1",

            "page_button_sync": "1",
            "page_button_refresh_youtube": "1",
            "page_button_single_download": "1",
            "page_button_discover": "1",
            "page_button_favourites": "1",
            "page_button_logout": "1",

            # Channel image controls are global. These switches apply anywhere
            # the interface renders the shared channel avatar control widget.
            "page_channel_controls": "1",
            "page_channel_control_favourite": "1",
            "page_channel_control_downloads": "1",
            "page_channel_control_scan": "1",
            "page_channel_control_delete": "1",
            "page_channel_control_retention": "1",

            "page_section_order": "summary,pinchflat,latest,subscriptions",
            "page_summary_order": "google,pinchflat,pinchflat_tasks,latest_download,subscriptions,downloads,errors",
        }
        for key, value in defaults.items():
            if value:
                conn.execute(
                    "INSERT OR IGNORE INTO settings (key, value) VALUES (?, ?)",
                    (key, value),
                )

        legacy_sync = conn.execute(
            "SELECT value FROM settings WHERE key = 'sync_interval_minutes'"
        ).fetchone()
        legacy_sync_value = (
            legacy_sync["value"] if legacy_sync else str(SYNC_INTERVAL_MINUTES)
        )
        for schedule_key in (
            "youtube_sync_interval_minutes",
            "pinchflat_sync_interval_minutes",
        ):
            conn.execute(
                "INSERT OR IGNORE INTO settings (key, value) VALUES (?, ?)",
                (schedule_key, legacy_sync_value),
            )

        baseline = conn.execute(
            "SELECT value FROM settings WHERE key = 'youtube_baseline_complete'"
        ).fetchone()
        if baseline is None:
            existing_count = conn.execute(
                "SELECT COUNT(*) AS c FROM subscriptions"
            ).fetchone()["c"]
            conn.execute(
                """
                INSERT INTO settings (key, value)
                VALUES ('youtube_baseline_complete', ?)
                """,
                ("1" if existing_count else "0",),
            )


def init_v3_db():
    """Upgrade the existing V2 database in place for the native V3 downloader."""
    with db() as conn:
        ensure_column(conn, "downloads", "channel_id", "TEXT")
        ensure_column(conn, "downloads", "published_at", "TEXT")
        ensure_column(conn, "downloads", "profile_id", "TEXT")
        ensure_column(conn, "downloads", "failure_code", "TEXT")
        ensure_column(conn, "downloads", "auth_mode", "TEXT")
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS subscription_scan_jobs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                channel_id TEXT NOT NULL,
                deep INTEGER NOT NULL DEFAULT 0,
                redownload INTEGER NOT NULL DEFAULT 0,
                status TEXT NOT NULL DEFAULT 'queued',
                created_at TEXT NOT NULL,
                started_at TEXT,
                finished_at TEXT,
                found INTEGER NOT NULL DEFAULT 0,
                queued INTEGER NOT NULL DEFAULT 0,
                error TEXT
            );
            CREATE INDEX IF NOT EXISTS idx_subscription_scan_jobs_status
            ON subscription_scan_jobs(status, id);
            """
        )

        # V3 keeps the old Pinchflat-named columns only as schema-compatibility
        # fields. They now mean "registered with the native downloader" and no
        # external Pinchflat database/container is required.
        conn.execute(
            """
            UPDATE subscriptions
            SET pinchflat_added = CASE
                    WHEN active = 1 AND COALESCE(download_enabled, 0) = 1 THEN 1
                    ELSE 0
                END,
                pinchflat_source_id = CASE
                    WHEN active = 1 AND COALESCE(download_enabled, 0) = 1 THEN channel_id
                    ELSE NULL
                END,
                source_authorised = CASE
                    WHEN active = 1 AND COALESCE(download_enabled, 0) = 1 THEN 1
                    ELSE 0
                END
            """
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


def emby_server_url():
    return get_setting(
        "emby_server_url",
        os.getenv("EMBY_SERVER_URL", ""),
    ).strip().rstrip("/")


def emby_api_key():
    return get_setting(
        "emby_api_key",
        os.getenv("EMBY_API_KEY", ""),
    ).strip()


def emby_configured():
    return bool(emby_server_url() and emby_api_key())


def emby_api_url(path):
    base = emby_server_url()
    if not base:
        raise RuntimeError("Emby Server URL is not configured.")

    path = str(path or "").lstrip("/")
    if base.lower().endswith("/emby"):
        return f"{base}/{path}"
    return f"{base}/emby/{path}"


def emby_api_request(method, path, **kwargs):
    if not emby_configured():
        raise RuntimeError("Configure the Emby Server URL and API key in Settings → Emby.")

    headers = dict(kwargs.pop("headers", {}) or {})
    headers["X-Emby-Token"] = emby_api_key()
    headers.setdefault("Accept", "application/json")

    response = requests.request(
        method,
        emby_api_url(path),
        headers=headers,
        timeout=kwargs.pop("timeout", 30),
        **kwargs,
    )
    response.raise_for_status()
    return response


def _normalise_media_path(value):
    text = str(value or "").strip().replace("\\", "/")
    text = re.sub(r"/+", "/", text).rstrip("/")
    return text.casefold()


def _path_basename(value):
    text = str(value or "").strip().replace("\\", "/").rstrip("/")
    return text.rsplit("/", 1)[-1] if text else ""


def _docker_containers_with_mounts():
    if not DOCKER_SOCKET_PATH.exists():
        return []

    try:
        status, _headers, body = docker_request(
            "GET",
            "/containers/json?all=1",
            timeout=20,
        )
        if status >= 400:
            return []
        payload = json.loads(body.decode("utf-8", "replace"))
        return payload if isinstance(payload, list) else []
    except Exception:
        return []


def _download_host_mount_source():
    """Resolve /downloads back to the host bind path from Docker."""
    wanted = _normalise_media_path(DOWNLOAD_ROOT)
    candidates = []

    for container in _docker_containers_with_mounts():
        names = [str(name or "").lstrip("/") for name in container.get("Names") or []]
        image = str(container.get("Image") or "")
        identity = " ".join(names + [image]).casefold()
        score = 0
        if "youtube-pinchflat-sync" in identity:
            score += 30
        if "pinchflat" in identity:
            score += 10

        for mount in container.get("Mounts") or []:
            destination = _normalise_media_path(mount.get("Destination"))
            source = str(mount.get("Source") or "").strip()
            if destination == wanted and source:
                candidates.append((score, source))

    if not candidates:
        return ""

    candidates.sort(key=lambda item: item[0], reverse=True)
    return candidates[0][1]


def _emby_container_destinations_for_host_source(host_source):
    wanted_source = _normalise_media_path(host_source)
    if not wanted_source:
        return []

    destinations = []
    for container in _docker_containers_with_mounts():
        names = [str(name or "").lstrip("/") for name in container.get("Names") or []]
        image = str(container.get("Image") or "")
        identity = " ".join(names + [image]).casefold()
        if "emby" not in identity:
            continue

        for mount in container.get("Mounts") or []:
            if _normalise_media_path(mount.get("Source")) != wanted_source:
                continue
            destination = str(mount.get("Destination") or "").strip()
            if destination:
                destinations.append(destination)

    return list(dict.fromkeys(destinations))


def _emby_container_mount_mappings():
    """Return host->container bind mappings for local Emby containers."""
    mappings = []
    for container in _docker_containers_with_mounts():
        names = [str(name or "").lstrip("/") for name in container.get("Names") or []]
        image = str(container.get("Image") or "")
        identity = " ".join(names + [image]).casefold()
        if "emby" not in identity:
            continue

        for mount in container.get("Mounts") or []:
            source = str(mount.get("Source") or "").strip()
            destination = str(mount.get("Destination") or "").strip()
            if source and destination:
                mappings.append({"source": source, "destination": destination})

    unique = []
    seen = set()
    for item in mappings:
        key = (_normalise_media_path(item["source"]), _normalise_media_path(item["destination"]))
        if key in seen:
            continue
        seen.add(key)
        unique.append(item)
    return unique


def _path_join_text(root, relative):
    root = str(root or "").strip().rstrip("/\\")
    relative = str(relative or "").strip().replace("\\", "/").strip("/")
    if not relative:
        return root
    separator = "\\" if "\\" in root and "/" not in root else "/"
    return root + separator + relative.replace("/", separator)


def emby_detect_download_library(relative_folder=""):
    """
    Resolve the most specific Emby library for a path below the app's
    /downloads bind.  This is used by direct downloads so a separate Emby
    library such as ``YouTube Single Downloads`` is refreshed instead of the
    main Pinchflat YouTube library.
    """
    if not emby_configured():
        raise RuntimeError("Configure the Emby Server URL and API key in Settings → Emby.")

    relative_folder = str(relative_folder or "").strip().replace("\\", "/").strip("/")
    host_root = _download_host_mount_source()
    host_target = _path_join_text(host_root, relative_folder) if host_root else ""
    virtual_folders = emby_virtual_folders()
    mount_mappings = _emby_container_mount_mappings()

    target_candidates = []
    if host_target:
        target_candidates.append((host_target, "matching Docker host path", 170))

    host_root_norm = _normalise_media_path(host_root)
    host_target_norm = _normalise_media_path(host_target)
    for mapping in mount_mappings:
        source = mapping["source"]
        destination = mapping["destination"]
        source_norm = _normalise_media_path(source)
        if host_target_norm and source_norm == host_target_norm:
            target_candidates.append((destination, "matching Emby Docker bind", 168))
        elif host_root_norm and source_norm == host_root_norm:
            target_candidates.append((_path_join_text(destination, relative_folder), "mapped through Emby Docker bind", 166))
        elif host_target_norm and source_norm and host_target_norm.startswith(source_norm + "/"):
            relative_from_mount = host_target_norm[len(source_norm) + 1:]
            target_candidates.append((_path_join_text(destination, relative_from_mount), "mapped through parent Emby Docker bind", 164))

    # Some Emby installations see the same host paths as the app.  Keep the
    # app-visible path as a low-priority exact candidate as well.
    target_candidates.append((str(DOWNLOAD_ROOT / relative_folder), "matching app download path", 120))

    best = None
    best_score = -1
    target_basename = _path_basename(relative_folder)

    for folder in virtual_folders:
        name = str(folder.get("Name") or folder.get("name") or "").strip()
        locations = folder.get("Locations") or folder.get("locations") or []
        if isinstance(locations, str):
            locations = [locations]

        for location in locations or [""]:
            location = str(location or "").strip()
            normal_location = _normalise_media_path(location)
            score = 0
            reason = ""

            for candidate, candidate_reason, candidate_score in target_candidates:
                if normal_location and normal_location == _normalise_media_path(candidate):
                    if candidate_score > score:
                        score = candidate_score
                        reason = candidate_reason

            if relative_folder and target_basename:
                if _path_basename(location).casefold() == target_basename.casefold() and score < 92:
                    score = 92
                    reason = "matching download folder name"
                if name.casefold() == target_basename.casefold() and score < 90:
                    score = 90
                    reason = "matching Emby library name"
                if target_basename.casefold() in name.casefold() and score < 78:
                    score = 78
                    reason = "similar Emby library name"

            if score <= best_score:
                continue

            item_id = str(
                folder.get("ItemId")
                or folder.get("itemId")
                or folder.get("Id")
                or folder.get("id")
                or ""
            ).strip()
            if not item_id and location:
                item_id = _emby_item_id_for_path(location)

            best = {
                "name": name or (target_basename or "YouTube"),
                "item_id": item_id,
                "location": location,
                "host_source": host_root,
                "app_path": str(DOWNLOAD_ROOT / relative_folder),
                "match_reason": reason,
                "relative_folder": relative_folder,
                "score": score,
                "scope": "library",
            }
            best_score = score

    # If the direct-download subfolder is not its own Emby library, refresh
    # that folder item inside the main YouTube library where possible.
    if relative_folder and (not best or best_score < 100):
        root_library = emby_detect_youtube_library()
        target_path = _join_emby_path(root_library.get("location"), relative_folder)
        target_item_id = _emby_item_id_for_path(target_path)
        if target_item_id:
            return {
                **root_library,
                "name": f"{root_library.get('name') or 'YouTube'} / {target_basename}",
                "item_id": target_item_id,
                "location": target_path,
                "relative_folder": relative_folder,
                "match_reason": "download subfolder inside detected YouTube library",
                "scope": "folder",
            }

        # The folder may not have been indexed yet.  Scan only the parent
        # YouTube library so Emby creates it, rather than touching every Emby
        # library on the server.
        return {
            **root_library,
            "relative_folder": relative_folder,
            "target_location": target_path,
            "match_reason": "parent YouTube library fallback for a new download folder",
            "scope": "parent_library",
        }

    if not best or best_score < 70:
        raise RuntimeError(
            f"The Emby library for /downloads/{relative_folder or ''} could not be detected. "
            "No whole-server Emby scan was started."
        )

    if not best.get("item_id"):
        raise RuntimeError(
            f"Matched the Emby library {best.get('name') or target_basename or 'YouTube'}, but its item ID could not be resolved."
        )

    return best


def emby_refresh_download_library(relative_folder, label="Direct Downloads"):
    """Refresh one direct-download library/folder and then its metadata."""
    target = emby_detect_download_library(relative_folder)
    item_id = str(target.get("item_id") or "").strip()
    if not item_id:
        raise RuntimeError(f"Emby item ID for {label} could not be resolved.")

    _emby_refresh_item(item_id, recursive=True)
    _emby_schedule_metadata_refresh(
        item_id,
        recursive=True,
        label=target.get("name") or label,
    )
    log_activity(
        "emby",
        f"{label} Emby refresh",
        f"Started an Emby scan for {target.get('name') or label}; a Replace all metadata pass will follow.",
        "success",
    )
    return {"scope": target.get("scope") or "library", "library": target}


def emby_virtual_folders():
    response = emby_api_request("GET", "Library/VirtualFolders", timeout=20)
    payload = response.json() if response.content else []
    if isinstance(payload, dict):
        payload = payload.get("Items") or payload.get("items") or []
    return payload if isinstance(payload, list) else []


def _emby_item_id_for_path(path):
    path = str(path or "").strip()
    if not path:
        return ""

    try:
        response = emby_api_request(
            "GET",
            "Items",
            params={
                "Path": path,
                "Fields": "Path",
                "Limit": 20,
            },
            timeout=20,
        )
        payload = response.json() if response.content else {}
        items = payload.get("Items") or payload.get("items") or []
        wanted = _normalise_media_path(path)
        for item in items:
            if _normalise_media_path(item.get("Path") or item.get("path")) == wanted:
                return str(item.get("Id") or item.get("id") or "").strip()
    except Exception:
        pass
    return ""


def emby_detect_youtube_library():
    """
    Locate the Emby library backed by the same host directory as /downloads.

    The app learns the host bind source from Docker, maps the same source into
    a local Emby container when possible, then matches the result against
    Emby's VirtualFolders API. A legacy saved path and the folder name are
    retained as safe fallbacks for remote Emby servers.
    """
    if not emby_configured():
        raise RuntimeError("Configure the Emby Server URL and API key in Settings → Emby.")

    host_source = _download_host_mount_source()
    emby_mounts = _emby_container_destinations_for_host_source(host_source)
    legacy_path = get_setting("emby_library_path", "").strip()
    source_basename = _path_basename(host_source or DOWNLOAD_ROOT)
    virtual_folders = emby_virtual_folders()

    best = None
    best_score = -1

    for folder in virtual_folders:
        name = str(folder.get("Name") or folder.get("name") or "").strip()
        locations = folder.get("Locations") or folder.get("locations") or []
        if isinstance(locations, str):
            locations = [locations]

        for location in locations or [""]:
            location = str(location or "").strip()
            normal_location = _normalise_media_path(location)
            score = 0
            match_reason = ""

            relative_root = ""
            host_normal = _normalise_media_path(host_source)
            if host_source and normal_location == host_normal:
                score = 120
                match_reason = "same Docker host bind"
            elif host_source and host_normal and normal_location.startswith(host_normal + "/"):
                score = 112
                match_reason = "subfolder of the same Docker host bind"
                relative_root = normal_location[len(host_normal) + 1:]

            for destination in emby_mounts:
                destination_normal = _normalise_media_path(destination)
                if normal_location == destination_normal and score < 115:
                    score = 115
                    match_reason = "same Docker bind inside Emby"
                    relative_root = ""
                elif (
                    destination_normal
                    and normal_location.startswith(destination_normal + "/")
                    and score < 110
                ):
                    score = 110
                    match_reason = "subfolder of the same Docker bind inside Emby"
                    relative_root = normal_location[len(destination_normal) + 1:]

            if legacy_path and normal_location == _normalise_media_path(legacy_path) and score < 100:
                score = 100
                match_reason = "saved path fallback"

            location_basename = _path_basename(location)
            if (
                source_basename
                and location_basename.casefold() == source_basename.casefold()
                and score < 70
            ):
                score = 70
                match_reason = "matching media folder name"

            if "youtube" in name.casefold() and score < 60:
                score = 60
                match_reason = "YouTube library name"

            if "youtube" in location.casefold() and score < 50:
                score = 50
                match_reason = "YouTube library path"

            if score <= best_score:
                continue

            item_id = str(
                folder.get("ItemId")
                or folder.get("itemId")
                or folder.get("Id")
                or folder.get("id")
                or ""
            ).strip()
            best = {
                "name": name or "YouTube",
                "item_id": item_id,
                "location": location,
                "host_source": host_source,
                "app_path": str(DOWNLOAD_ROOT),
                "emby_mounts": emby_mounts,
                "match_reason": match_reason,
                "download_relative_root": relative_root,
                "score": score,
            }
            best_score = score

    if not best or best_score < 40:
        raise RuntimeError(
            "The Emby YouTube library could not be matched to the app's /downloads bind mount. "
            "No whole-server Emby scan was started."
        )

    if not best.get("item_id") and best.get("location"):
        best["item_id"] = _emby_item_id_for_path(best["location"])

    if not best.get("item_id"):
        raise RuntimeError(
            f"Matched the Emby library {best.get('name') or 'YouTube'}, but its item ID could not be resolved."
        )

    return best


def _join_emby_path(root, relative):
    root = str(root or "").strip().rstrip("/\\")
    relative = str(relative or "").strip().replace("\\", "/").strip("/")
    if not relative:
        return root
    separator = "\\" if "\\" in root and "/" not in root else "/"
    return root + separator + relative.replace("/", separator)


def _local_channel_relative_path(channel_id="", channel_title=""):
    title = str(channel_title or "").strip()
    output_template = None

    if channel_id:
        try:
            with db() as conn:
                row = conn.execute(
                    "SELECT media_profile_id, title FROM subscriptions WHERE channel_id = ?",
                    (channel_id,),
                ).fetchone()
            if row:
                title = str(row["title"] or title).strip()
                profile_id = str(row["media_profile_id"] or effective_media_profile_id())
                output_template = media_profile_settings(profile_id).get("output_path_template")
        except Exception:
            pass

    parent = subscription_folder_parent(output_template)
    if not parent or not parent.exists() or not title:
        return ""

    wanted = normalise_storage_name(title)
    for candidate in parent.iterdir():
        if candidate.is_dir() and normalise_storage_name(candidate.name) == wanted:
            try:
                return candidate.resolve().relative_to(DOWNLOAD_ROOT.resolve()).as_posix()
            except Exception:
                return ""
    return ""


def _emby_find_channel_item(library, channel_id="", channel_title=""):
    title = str(channel_title or channel_id or "").strip()
    if not title:
        return None

    library_id = str(library.get("item_id") or "").strip()
    library_location = str(library.get("location") or "").strip()
    relative_path = _local_channel_relative_path(channel_id, title)

    if relative_path and library_location:
        library_relative_root = str(library.get("download_relative_root") or "").strip().replace("\\", "/").strip("/")
        relative_for_library = relative_path
        if library_relative_root:
            prefix = library_relative_root.casefold() + "/"
            if relative_for_library.casefold().startswith(prefix):
                relative_for_library = relative_for_library[len(library_relative_root) + 1:]
            elif relative_for_library.casefold() == library_relative_root.casefold():
                relative_for_library = ""
        expected_path = _join_emby_path(library_location, relative_for_library)
        try:
            response = emby_api_request(
                "GET",
                "Items",
                params={
                    "Path": expected_path,
                    "Fields": "Path",
                    "Limit": 20,
                },
                timeout=20,
            )
            payload = response.json() if response.content else {}
            items = payload.get("Items") or payload.get("items") or []
            wanted_path = _normalise_media_path(expected_path)
            for item in items:
                if _normalise_media_path(item.get("Path") or item.get("path")) == wanted_path:
                    return item
        except Exception:
            pass

    if not library_id:
        return None

    try:
        response = emby_api_request(
            "GET",
            "Items",
            params={
                "ParentId": library_id,
                "Recursive": "true",
                "SearchTerm": title,
                "Fields": "Path",
                "Limit": 100,
            },
            timeout=25,
        )
        payload = response.json() if response.content else {}
        items = payload.get("Items") or payload.get("items") or []
        wanted_name = normalise_storage_name(title)

        exact = []
        partial = []
        for item in items:
            name = str(item.get("Name") or item.get("name") or "").strip()
            path = str(item.get("Path") or item.get("path") or "").strip()
            path_name = _path_basename(path)
            if normalise_storage_name(name) == wanted_name or normalise_storage_name(path_name) == wanted_name:
                exact.append(item)
            elif wanted_name and wanted_name in normalise_storage_name(name):
                partial.append(item)

        if exact:
            return exact[0]
        if partial:
            return partial[0]
    except Exception:
        pass

    return None


def _emby_refresh_item(item_id, recursive=True):
    """Run the normal Emby item/library refresh used to discover new files."""
    item_id = str(item_id or "").strip()
    if not item_id:
        raise RuntimeError("Emby item ID is missing.")

    return emby_api_request(
        "POST",
        f"Items/{quote(item_id, safe='')}/Refresh",
        params={"Recursive": "true" if recursive else "false"},
        json={"ReplaceThumbnailImages": False},
        timeout=45,
    )


def _emby_refresh_metadata_item(item_id, recursive=True):
    """Run Emby's 'Replace all metadata' refresh without replacing images."""
    item_id = str(item_id or "").strip()
    if not item_id:
        raise RuntimeError("Emby item ID is missing.")

    return emby_api_request(
        "POST",
        f"Items/{quote(item_id, safe='')}/Refresh",
        params={
            "Recursive": "true" if recursive else "false",
            "MetadataRefreshMode": "FullRefresh",
            "ImageRefreshMode": "Default",
            "ReplaceAllMetadata": "true",
            "ReplaceAllImages": "false",
        },
        json={"ReplaceThumbnailImages": False},
        timeout=45,
    )


def _emby_schedule_metadata_refresh(
    item_id,
    label="",
    *,
    recursive=True,
    channel_id="",
    delay_seconds=15,
):
    """
    Queue a second Emby metadata pass after the filesystem scan has had time
    to discover new files. The delay keeps the FullRefresh request from racing
    the initial scan, which otherwise can run before newly downloaded NFO and
    media files have appeared in Emby's item tree.
    """
    item_id = str(item_id or "").strip()
    if not item_id:
        return False

    label = str(label or "Emby item").strip() or "Emby item"
    try:
        delay_seconds = max(1, int(delay_seconds))
    except (TypeError, ValueError):
        delay_seconds = 15

    def worker():
        time.sleep(delay_seconds)
        try:
            _emby_refresh_metadata_item(item_id, recursive=recursive)
            log_activity(
                "emby",
                "Emby metadata refresh",
                f"Started Replace all metadata for {label} after the library scan.",
                "success",
                channel_id or None,
            )
        except Exception as exc:
            log_activity(
                "emby",
                "Emby metadata refresh failed",
                f"{label}: {exc}",
                "error",
                channel_id or None,
            )

    threading.Thread(
        target=worker,
        name="emby-metadata-refresh",
        daemon=True,
    ).start()
    return True


def emby_refresh_channel(channel_id="", channel_title="", library=None):
    label = str(channel_title or channel_id or "").strip()
    if not label:
        return False

    try:
        library = library or emby_detect_youtube_library()
        item = _emby_find_channel_item(library, channel_id, channel_title)
        if not item:
            return False

        item_id = str(item.get("Id") or item.get("id") or "").strip()
        if not item_id:
            return False

        _emby_refresh_item(item_id, recursive=True)
        _emby_schedule_metadata_refresh(
            item_id,
            label=f"{label} in {library['name']}",
            recursive=True,
            channel_id=channel_id,
        )
        log_activity(
            "emby",
            "Emby channel refresh",
            f"Started a recursive Emby scan for {label} inside {library['name']}; a Replace all metadata pass will follow.",
            "success",
            channel_id or None,
        )
        return True
    except Exception as exc:
        log_activity(
            "emby",
            "Emby channel refresh fallback",
            f"Could not refresh {label} directly: {exc}",
            "info",
            channel_id or None,
        )
        return False


def emby_refresh_library(channel_id="", channel_title="", library=None):
    label = str(channel_title or channel_id or "").strip()

    if label and emby_refresh_channel(channel_id, channel_title, library=library):
        return {
            "scope": "channel",
            "channel": label,
        }

    library = library or emby_detect_youtube_library()
    _emby_refresh_item(library["item_id"], recursive=True)
    _emby_schedule_metadata_refresh(
        library["item_id"],
        label=f"{library['name']} library",
        recursive=True,
        channel_id=channel_id,
    )

    detail = f" Requested for {label}." if label else ""
    log_activity(
        "emby",
        "Emby YouTube library refresh",
        f"Emby library {library['name']} scan started; a Replace all metadata pass will follow.{detail}",
        "success",
        channel_id or None,
    )
    return {
        "scope": "library",
        "library": library,
        "channel": label,
    }

def emby_test_connection():
    response = emby_api_request("GET", "System/Info", timeout=15)
    data = response.json() if response.content else {}
    result = {
        "server_name": data.get("ServerName") or data.get("serverName") or "Emby",
        "version": data.get("Version") or data.get("version") or "",
        "id": data.get("Id") or data.get("id") or "",
    }
    try:
        result["youtube_library"] = emby_detect_youtube_library()
    except Exception as exc:
        result["youtube_library_error"] = str(exc)
    return result


def emby_auto_refresh_new_downloads():
    if not setting_bool("emby_auto_refresh_after_download", True):
        return {"status": "disabled"}
    if not emby_configured():
        return {"status": "not_configured"}

    try:
        overview = pinchflat_download_overview(queue_limit=0)
        latest = overview.get("last_downloaded") or {}
        media_id = str(latest.get("media_item_id") or "").strip()
        if not media_id:
            return {"status": "no_download"}

        previous = get_setting("emby_last_refresh_media_id", "").strip()
        if media_id == previous:
            return {"status": "unchanged"}

        emby_refresh_library(
            channel_id=str(latest.get("channel_id") or ""),
            channel_title=str(latest.get("channel") or ""),
        )
        set_setting("emby_last_refresh_media_id", media_id)
        return {
            "status": "refreshed",
            "media_item_id": media_id,
        }
    except Exception as exc:
        log_activity(
            "emby",
            "Automatic Emby refresh failed",
            str(exc),
            "error",
        )
        return {
            "status": "error",
            "error": str(exc),
        }


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


def setting_order(key, allowed, default_order):
    allowed = list(allowed)
    default_order = list(default_order)

    raw = get_setting(
        key,
        ",".join(default_order),
    )

    requested = [
        item.strip()
        for item in str(raw or "").split(",")
        if item.strip() in allowed
    ]

    result = []

    for item in requested + default_order + allowed:
        if item in allowed and item not in result:
            result.append(item)

    return result


def csrf_token():
    token = session.get("_csrf_token")
    if not token:
        token = secrets.token_urlsafe(32)
        session["_csrf_token"] = token
    return token


app.jinja_env.globals["csrf_token"] = csrf_token


def users_exist():
    with db() as conn:
        row = conn.execute("SELECT COUNT(*) AS count FROM users").fetchone()
    return bool(row and int(row["count"] or 0) > 0)


def normalise_username(value):
    return (value or "").strip().lower()


def valid_username(value):
    return bool(USERNAME_RE.fullmatch((value or "").strip()))


def valid_password(value):
    value = value or ""
    return PASSWORD_MIN_LENGTH <= len(value) <= 200


def hash_password(value):
    return PASSWORD_HASHER.hash(value)


def verify_password(password_hash, value):
    try:
        return bool(PASSWORD_HASHER.verify(password_hash, value or ""))
    except (VerifyMismatchError, VerificationError, InvalidHashError):
        return False


def maybe_rehash_password(user_id, password_hash, value):
    try:
        if PASSWORD_HASHER.check_needs_rehash(password_hash):
            with db() as conn:
                conn.execute(
                    "UPDATE users SET password_hash = ? WHERE id = ?",
                    (hash_password(value), user_id),
                )
    except Exception:
        pass


def client_ip():
    return (
        request.headers.get("CF-Connecting-IP")
        or request.headers.get("X-Forwarded-For", "").split(",")[0].strip()
        or request.remote_addr
        or ""
    )


def record_auth_event(event_type, success=True, user=None, username=None, message=""):
    user_id = None
    if user is not None:
        try:
            user_id = user["id"]
            username = username or user["username"]
        except Exception:
            pass
    with db() as conn:
        conn.execute(
            """
            INSERT INTO auth_events (
                created_at, user_id, username, event_type, success,
                ip_address, user_agent, message
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                now_iso(),
                user_id,
                username,
                event_type,
                1 if success else 0,
                client_ip(),
                (request.headers.get("User-Agent") or "")[:500],
                (message or "")[:1000],
            ),
        )


def login_ip_blocked():
    ip = client_ip()
    if not ip:
        return False
    cutoff = (datetime.now(timezone.utc) - timedelta(minutes=10)).isoformat()
    with db() as conn:
        row = conn.execute(
            """
            SELECT COUNT(*) AS count
            FROM auth_events
            WHERE event_type = 'login_failed'
              AND success = 0
              AND ip_address = ?
              AND created_at >= ?
            """,
            (ip, cutoff),
        ).fetchone()
    return int(row["count"] or 0) >= 20


def get_user_by_id(user_id):
    if not user_id:
        return None
    with db() as conn:
        return conn.execute("SELECT * FROM users WHERE id = ?", (user_id,)).fetchone()


def get_user_by_username(username):
    username = normalise_username(username)
    if not username:
        return None
    with db() as conn:
        return conn.execute("SELECT * FROM users WHERE username = ?", (username,)).fetchone()


def current_user_record():
    return get_user_by_id(session.get("auth_user_id"))


def current_user_is_admin():
    user = current_user_record()
    return bool(user and user["role"] == "admin" and user["active"])


def session_timeout_minutes():
    return setting_int("auth_session_timeout_minutes", 720, 5, 10080)


def remember_login_days():
    return setting_int("auth_remember_login_days", 30, 1, 365)


def lockout_attempt_limit():
    return setting_int("auth_lockout_attempts", 5, 3, 50)


def lockout_minutes():
    return setting_int("auth_lockout_minutes", 15, 1, 1440)


def generate_totp_secret():
    return base64.b32encode(secrets.token_bytes(20)).decode("ascii").rstrip("=")


def _totp_key(secret):
    secret = (secret or "").strip().replace(" ", "").upper()
    padding = "=" * ((8 - len(secret) % 8) % 8)
    return base64.b32decode(secret + padding, casefold=True)


def totp_code(secret, at_time=None):
    timestamp = int(at_time if at_time is not None else time.time())
    counter = timestamp // 30
    digest = hmac.new(_totp_key(secret), struct.pack(">Q", counter), hashlib.sha1).digest()
    offset = digest[-1] & 0x0F
    number = struct.unpack(">I", digest[offset:offset + 4])[0] & 0x7FFFFFFF
    return f"{number % 1000000:06d}"


def verify_totp(secret, code, window=1):
    code = re.sub(r"\D", "", code or "")
    if len(code) != 6:
        return False
    now = int(time.time())
    for offset in range(-window, window + 1):
        expected = totp_code(secret, now + offset * 30)
        if hmac.compare_digest(expected, code):
            return True
    return False


def totp_provisioning_uri(username, secret):
    label = quote(f"{TOTP_ISSUER}:{username}")
    issuer = quote(TOTP_ISSUER)
    return f"otpauth://totp/{label}?secret={secret}&issuer={issuer}&digits=6&period=30"


def totp_qr_data_uri(username, secret):
    image = qrcode.make(totp_provisioning_uri(username, secret))
    buffer = io.BytesIO()
    image.save(buffer, format="PNG")
    encoded = base64.b64encode(buffer.getvalue()).decode("ascii")
    return f"data:image/png;base64,{encoded}"


def recovery_code_hash(value):
    normalised = re.sub(r"[^A-Za-z0-9]", "", value or "").upper()
    return hashlib.sha256(normalised.encode("utf-8")).hexdigest()


def generate_recovery_codes():
    alphabet = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"
    codes = []
    for _ in range(RECOVERY_CODE_COUNT):
        raw = "".join(secrets.choice(alphabet) for _ in range(12))
        codes.append(f"{raw[:4]}-{raw[4:8]}-{raw[8:]}")
    return codes


def consume_recovery_code(user, code):
    try:
        hashes = json.loads(user["recovery_code_hashes"] or "[]")
    except Exception:
        hashes = []
    candidate = recovery_code_hash(code)
    if candidate not in hashes:
        return False
    hashes.remove(candidate)
    with db() as conn:
        conn.execute(
            "UPDATE users SET recovery_code_hashes = ? WHERE id = ?",
            (json.dumps(hashes), user["id"]),
        )
    return True


def verify_user_second_factor(user, value):
    if user["totp_enabled"] and user["totp_secret"] and verify_totp(user["totp_secret"], value):
        return True, "totp"
    if consume_recovery_code(user, value):
        return True, "recovery"
    return False, None


def complete_login(user, method="password"):
    session.clear()
    session["auth_user_id"] = int(user["id"])
    session["auth_session_version"] = int(user["session_version"] or 1)
    now = time.time()
    session.permanent = True
    session["auth_authenticated_at"] = now
    session["auth_last_seen"] = now
    session["auth_remember_until"] = now + (remember_login_days() * 86400)
    with db() as conn:
        conn.execute(
            """
            UPDATE users
            SET failed_attempts = 0, locked_until = NULL, last_login_at = ?
            WHERE id = ?
            """,
            (now_iso(), user["id"]),
        )
    record_auth_event("login_success", True, user=user, message=f"Signed in using {method}.")


def auth_context():
    user = current_user_record()
    if not user:
        return {"current_user": None, "is_admin": False}
    return {
        "current_user": dict(user),
        "is_admin": bool(user["role"] == "admin"),
    }


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
    search_limit = setting_int(
        "youtube_search_daily_limit",
        100,
        1,
        100000,
    )
    search_calls = 0
    for method_row in methods:
        if method_row["method"] == "search.list":
            search_calls = int(method_row["calls"] or 0)
            break

    return {
        "date": today,
        "quota": quota,
        "used": used,
        "remaining": max(0, quota - used),
        "calls": int(row["calls"] or 0),
        "failures": int(row["failures"] or 0),
        "percent": min(100.0, (used / quota * 100.0) if quota else 0.0),
        "methods": [dict(item) for item in methods],
        "search_limit": search_limit,
        "search_calls": search_calls,
        "search_remaining": max(0, search_limit - search_calls),
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


def english_language_code(value):
    value = str(value or "").strip().lower()
    if not value:
        return None
    return value == "en" or value.startswith("en-")


def has_obvious_non_latin_title(value):
    """
    Reject titles dominated by scripts which are clearly not English.

    This is only a fallback when YouTube does not publish a default language
    for a video. Latin-script languages are left to YouTube's
    relevanceLanguage=en and GB-region ranking.
    """
    text = str(value or "")
    letters = [char for char in text if char.isalpha()]
    if not letters:
        return False

    non_latin = 0
    for char in letters:
        codepoint = ord(char)
        if (
            0x0400 <= codepoint <= 0x052F   # Cyrillic
            or 0x0590 <= codepoint <= 0x05FF  # Hebrew
            or 0x0600 <= codepoint <= 0x06FF  # Arabic
            or 0x0900 <= codepoint <= 0x0D7F  # Indic scripts
            or 0x0E00 <= codepoint <= 0x0E7F  # Thai
            or 0x3040 <= codepoint <= 0x30FF  # Japanese
            or 0x3400 <= codepoint <= 0x9FFF  # CJK
            or 0xAC00 <= codepoint <= 0xD7AF  # Korean
        ):
            non_latin += 1

    return (non_latin / max(1, len(letters))) >= 0.20


def youtube_channel_details_from_url(creds, channel_url):
    """
    Resolve a YouTube channel URL to a channel resource.

    Wikipedia links use a mixture of /channel/, /@handle and /user/ URLs.
    channels.list supports each of those identities through id, forHandle or
    forUsername.
    """
    parsed = urlparse(channel_url or "")
    path = parsed.path.strip("/")
    params = {
        "part": "snippet",
        "maxResults": 1,
    }

    if path.startswith("channel/"):
        channel_id = path.split("/", 1)[1].split("/", 1)[0]
        if not channel_id:
            return {}
        params["id"] = channel_id

    elif path.startswith("@"):
        handle = path.split("/", 1)[0]
        params["forHandle"] = handle

    elif path.startswith("user/"):
        username = path.split("/", 1)[1].split("/", 1)[0]
        if not username:
            return {}
        params["forUsername"] = username

    else:
        return {}

    response = youtube_api_request(
        creds,
        "GET",
        "channels",
        "channels.list",
        1,
        params=params,
    )

    items = response.json().get("items", [])
    if not items:
        return {}

    item = items[0]
    snippet = item.get("snippet") or {}
    thumbnails = snippet.get("thumbnails") or {}
    image = (
        thumbnails.get("high")
        or thumbnails.get("medium")
        or thumbnails.get("default")
        or {}
    )

    return {
        "channel_id": item.get("id") or "",
        "channel_title_api": snippet.get("title") or "",
        "channel_avatar_url": image.get("url") or "",
    }


def enrich_top100_channel_images(creds, rows):
    """
    Add live YouTube channel avatars to the English Top 100 subset.

    Results are already cached by youtube_top100_channels(), so these
    channels.list calls only occur on a Top 100 cache refresh.
    """
    enriched = []

    for row in rows:
        item = dict(row)
        try:
            details = youtube_channel_details_from_url(
                creds,
                item.get("channel_url", ""),
            )
            item.update(details)
        except Exception:
            item.setdefault("channel_avatar_url", "")
            item.setdefault("channel_id", "")
        enriched.append(item)

    return enriched


def youtube_top100_channels(force=False):
    now_ts = time.time()

    if (
        not force
        and TOP100_CACHE["results"]
        and TOP100_CACHE["expires_at"] > now_ts
    ):
        return {
            "kind": "top100",
            "results": TOP100_CACHE["results"],
            "retrieved_at": TOP100_CACHE["retrieved_at"],
            "source": "Wikipedia + YouTube",
        }

    response = requests.get(
        TOP100_WIKIPEDIA_URL,
        timeout=25,
        headers={
            "User-Agent": (
                "YouTube-Pinchflat-Sync/"
                f"{VERSION} (+https://github.com/AshCooperUK/"
                "youtube-pinchflat-sync)"
            )
        },
    )
    response.raise_for_status()

    soup = BeautifulSoup(response.text, "html.parser")
    heading = soup.find(id="100_most-subscribed_channels")
    table = heading.find_next("table") if heading else None

    if table is None:
        for candidate in soup.find_all("table"):
            headers = " ".join(
                cell.get_text(" ", strip=True)
                for cell in candidate.find_all("th")
            ).lower()
            if "subscribers" in headers and "primary" in headers and "language" in headers:
                table = candidate
                break

    if table is None:
        raise RuntimeError(
            "The Top 100 YouTube channel table could not be found."
        )

    rows = []

    for row in table.find_all("tr"):
        cells = row.find_all(["th", "td"])
        if len(cells) < 7:
            continue

        name = cells[0].get_text(" ", strip=True)
        if not name or name.lower() == "name":
            continue

        youtube_link = None
        for link in cells[1].find_all("a", href=True):
            href = link.get("href", "").strip()
            if "youtube.com/" in href:
                youtube_link = href
                break

        if not youtube_link:
            continue

        if youtube_link.startswith("//"):
            youtube_link = "https:" + youtube_link
        elif youtube_link.startswith("/"):
            youtube_link = "https://www.youtube.com" + youtube_link

        subscribers = cells[2].get_text(" ", strip=True)
        primary_language = cells[3].get_text(" ", strip=True)
        category = cells[4].get_text(" ", strip=True)
        country = cells[6].get_text(" ", strip=True)

        # The global Top 100 table explicitly lists each channel's primary
        # language. Keep English and multilingual entries containing English.
        if "english" not in primary_language.lower():
            continue

        rows.append(
            {
                "global_rank": len(rows) + 1,
                "channel_title": name,
                "channel_url": youtube_link,
                "subscribers": subscribers,
                "primary_language": primary_language,
                "category": category,
                "country": country,
            }
        )

    if not rows:
        raise RuntimeError(
            "The Top 100 table returned no English-language channels."
        )

    creds = load_credentials()
    if creds:
        rows = enrich_top100_channel_images(creds, rows)

    # Rank the English-language subset in the order it appears in the global
    # subscriber ranking.
    for index, row in enumerate(rows, start=1):
        row["rank"] = index

    retrieved_at = now_iso()
    TOP100_CACHE["expires_at"] = now_ts + TOP100_CACHE_SECONDS
    TOP100_CACHE["results"] = rows
    TOP100_CACHE["retrieved_at"] = retrieved_at

    return {
        "kind": "top100",
        "results": rows,
        "retrieved_at": retrieved_at,
        "source": "Wikipedia + YouTube",
    }




def youtube_liked_videos(force=False):
    now_ts = time.time()

    with YOUTUBE_LIKED_VIDEOS_LOCK:
        cached_results = list(
            YOUTUBE_LIKED_VIDEOS_CACHE.get(
                "results",
                [],
            )
        )
        expires_at = float(
            YOUTUBE_LIKED_VIDEOS_CACHE.get(
                "expires_at",
                0,
            )
            or 0
        )
        retrieved_at = str(
            YOUTUBE_LIKED_VIDEOS_CACHE.get(
                "retrieved_at",
                "",
            )
            or ""
        )

    if (
        cached_results
        and not force
        and expires_at > now_ts
    ):
        return {
            "kind": "liked",
            "results": annotate_favourites(
                cached_results
            ),
            "retrieved_at": retrieved_at,
            "source": "YouTube liked videos",
        }

    creds = load_credentials()
    if not creds:
        raise RuntimeError(
            "Google account is not connected."
        )

    results = []
    channel_ids = []
    page_token = None
    seen_video_ids = set()

    while True:
        params = {
            "part": "snippet,statistics,contentDetails",
            "myRating": "like",
            "maxResults": 50,
        }

        if page_token:
            params["pageToken"] = page_token

        response = youtube_api_request(
            creds,
            "GET",
            "videos",
            "videos.list",
            1,
            params=params,
        )

        payload = response.json()

        for video in payload.get("items", []):
            video_id = str(
                video.get("id")
                or ""
            ).strip()

            if (
                not video_id
                or video_id in seen_video_ids
            ):
                continue

            seen_video_ids.add(video_id)

            snippet = video.get("snippet") or {}
            statistics = video.get("statistics") or {}
            content_details = (
                video.get("contentDetails")
                or {}
            )
            thumbnails = snippet.get("thumbnails") or {}

            thumbnail = (
                thumbnails.get("maxres")
                or thumbnails.get("standard")
                or thumbnails.get("high")
                or thumbnails.get("medium")
                or thumbnails.get("default")
                or {}
            )

            channel_id = str(
                snippet.get("channelId")
                or ""
            ).strip()

            channel_title = str(
                snippet.get("channelTitle")
                or "YouTube"
            ).strip()

            duration_raw = str(
                content_details.get("duration")
                or ""
            )

            duration_seconds = youtube_duration_seconds(
                duration_raw
            )

            results.append(
                {
                    "video_id": video_id,
                    "channel_id": channel_id,
                    "title": (
                        snippet.get("title")
                        or "YouTube video"
                    ),
                    "channel_title": channel_title,
                    "published_at": (
                        snippet.get("publishedAt")
                        or ""
                    ),
                    "description": (
                        snippet.get("description")
                        or ""
                    ),
                    "video_url": (
                        f"https://www.youtube.com/watch?v={video_id}"
                    ),
                    "shorts_url": (
                        f"https://www.youtube.com/shorts/{video_id}"
                    ),
                    "channel_url": (
                        f"https://www.youtube.com/channel/{channel_id}"
                        if channel_id
                        else "https://www.youtube.com"
                    ),
                    "thumbnail_url": (
                        thumbnail.get("url")
                        or ""
                    ),
                    "channel_avatar_url": "",
                    "channel_thumbnail_url": "",
                    "view_count": int(
                        statistics.get("viewCount")
                        or 0
                    ),
                    "duration": youtube_duration_label(
                        duration_raw
                    ),
                    "duration_seconds": duration_seconds,
                    "is_short": youtube_video_is_short(
                        snippet.get("title") or "",
                        snippet.get("description") or "",
                        duration_seconds,
                    ),
                    "is_youtube_liked": True,
                    "metadata_complete": True,
                }
            )

            if channel_id:
                channel_ids.append(channel_id)

        page_token = str(
            payload.get("nextPageToken")
            or ""
        ).strip()

        if not page_token:
            break

    # Add channel avatars so opening a Liked Videos tile gets the same rich
    # player information as Random Videos.
    avatar_by_channel = {}
    unique_channel_ids = list(
        dict.fromkeys(channel_ids)
    )

    for chunk_start in range(
        0,
        len(unique_channel_ids),
        50,
    ):
        chunk = unique_channel_ids[
            chunk_start:chunk_start + 50
        ]

        if not chunk:
            continue

        try:
            response = youtube_api_request(
                creds,
                "GET",
                "channels",
                "channels.list",
                1,
                params={
                    "part": "snippet",
                    "id": ",".join(chunk),
                    "maxResults": 50,
                },
            )

            for channel in response.json().get(
                "items",
                [],
            ):
                snippet = channel.get("snippet") or {}
                thumbnails = (
                    snippet.get("thumbnails")
                    or {}
                )
                image = (
                    thumbnails.get("high")
                    or thumbnails.get("medium")
                    or thumbnails.get("default")
                    or {}
                )

                avatar_by_channel[
                    channel.get("id")
                ] = image.get("url") or ""

        except Exception:
            # Liked videos themselves remain usable if a channel-avatar lookup
            # fails.
            continue

    for item in results:
        avatar = avatar_by_channel.get(
            item.get("channel_id"),
            "",
        )

        item["channel_avatar_url"] = avatar
        item["channel_thumbnail_url"] = avatar

    retrieved_at = now_iso()

    with YOUTUBE_LIKED_VIDEOS_LOCK:
        YOUTUBE_LIKED_VIDEOS_CACHE.update(
            {
                "expires_at": (
                    now_ts
                    + YOUTUBE_LIKED_VIDEOS_CACHE_SECONDS
                ),
                "results": [
                    dict(item)
                    for item in results
                ],
                "retrieved_at": retrieved_at,
            }
        )

    return {
        "kind": "liked",
        "results": annotate_favourites(
            results
        ),
        "retrieved_at": retrieved_at,
        "source": "YouTube liked videos",
    }



def youtube_disliked_videos(force=False):
    now_ts = time.time()

    with YOUTUBE_DISLIKED_VIDEOS_LOCK:
        cached_results = list(
            YOUTUBE_DISLIKED_VIDEOS_CACHE.get(
                "results",
                [],
            )
        )
        expires_at = float(
            YOUTUBE_DISLIKED_VIDEOS_CACHE.get(
                "expires_at",
                0,
            )
            or 0
        )
        retrieved_at = str(
            YOUTUBE_DISLIKED_VIDEOS_CACHE.get(
                "retrieved_at",
                "",
            )
            or ""
        )

    if (
        cached_results
        and not force
        and expires_at > now_ts
    ):
        return {
            "kind": "disliked",
            "results": annotate_favourites(
                cached_results
            ),
            "retrieved_at": retrieved_at,
            "source": "YouTube disliked videos",
        }

    creds = load_credentials()
    if not creds:
        raise RuntimeError(
            "Google account is not connected."
        )

    results = []
    channel_ids = []
    page_token = None
    seen_video_ids = set()

    while True:
        params = {
            "part": "snippet,statistics,contentDetails",
            "myRating": "dislike",
            "maxResults": 50,
        }

        if page_token:
            params["pageToken"] = page_token

        response = youtube_api_request(
            creds,
            "GET",
            "videos",
            "videos.list",
            1,
            params=params,
        )

        payload = response.json()

        for video in payload.get("items", []):
            video_id = str(
                video.get("id")
                or ""
            ).strip()

            if (
                not video_id
                or video_id in seen_video_ids
            ):
                continue

            seen_video_ids.add(video_id)

            snippet = video.get("snippet") or {}
            statistics = video.get("statistics") or {}
            content_details = (
                video.get("contentDetails")
                or {}
            )
            thumbnails = snippet.get("thumbnails") or {}

            thumbnail = (
                thumbnails.get("maxres")
                or thumbnails.get("standard")
                or thumbnails.get("high")
                or thumbnails.get("medium")
                or thumbnails.get("default")
                or {}
            )

            channel_id = str(
                snippet.get("channelId")
                or ""
            ).strip()

            channel_title = str(
                snippet.get("channelTitle")
                or "YouTube"
            ).strip()

            duration_raw = str(
                content_details.get("duration")
                or ""
            )

            duration_seconds = youtube_duration_seconds(
                duration_raw
            )

            results.append(
                {
                    "video_id": video_id,
                    "channel_id": channel_id,
                    "title": (
                        snippet.get("title")
                        or "YouTube video"
                    ),
                    "channel_title": channel_title,
                    "published_at": (
                        snippet.get("publishedAt")
                        or ""
                    ),
                    "description": (
                        snippet.get("description")
                        or ""
                    ),
                    "video_url": (
                        f"https://www.youtube.com/watch?v={video_id}"
                    ),
                    "shorts_url": (
                        f"https://www.youtube.com/shorts/{video_id}"
                    ),
                    "channel_url": (
                        f"https://www.youtube.com/channel/{channel_id}"
                        if channel_id
                        else "https://www.youtube.com"
                    ),
                    "thumbnail_url": (
                        thumbnail.get("url")
                        or ""
                    ),
                    "channel_avatar_url": "",
                    "channel_thumbnail_url": "",
                    "view_count": int(
                        statistics.get("viewCount")
                        or 0
                    ),
                    "duration": youtube_duration_label(
                        duration_raw
                    ),
                    "duration_seconds": duration_seconds,
                    "is_short": youtube_video_is_short(
                        snippet.get("title") or "",
                        snippet.get("description") or "",
                        duration_seconds,
                    ),
                    "is_youtube_disliked": True,
                    "metadata_complete": True,
                }
            )

            if channel_id:
                channel_ids.append(channel_id)

        page_token = str(
            payload.get("nextPageToken")
            or ""
        ).strip()

        if not page_token:
            break

    # Add channel avatars so opening a Disliked Videos tile gets the same rich
    # player information as Random Videos.
    avatar_by_channel = {}
    unique_channel_ids = list(
        dict.fromkeys(channel_ids)
    )

    for chunk_start in range(
        0,
        len(unique_channel_ids),
        50,
    ):
        chunk = unique_channel_ids[
            chunk_start:chunk_start + 50
        ]

        if not chunk:
            continue

        try:
            response = youtube_api_request(
                creds,
                "GET",
                "channels",
                "channels.list",
                1,
                params={
                    "part": "snippet",
                    "id": ",".join(chunk),
                    "maxResults": 50,
                },
            )

            for channel in response.json().get(
                "items",
                [],
            ):
                snippet = channel.get("snippet") or {}
                thumbnails = (
                    snippet.get("thumbnails")
                    or {}
                )
                image = (
                    thumbnails.get("high")
                    or thumbnails.get("medium")
                    or thumbnails.get("default")
                    or {}
                )

                avatar_by_channel[
                    channel.get("id")
                ] = image.get("url") or ""

        except Exception:
            # Disliked videos themselves remain usable if a channel-avatar lookup
            # fails.
            continue

    for item in results:
        avatar = avatar_by_channel.get(
            item.get("channel_id"),
            "",
        )

        item["channel_avatar_url"] = avatar
        item["channel_thumbnail_url"] = avatar

    retrieved_at = now_iso()

    with YOUTUBE_DISLIKED_VIDEOS_LOCK:
        YOUTUBE_DISLIKED_VIDEOS_CACHE.update(
            {
                "expires_at": (
                    now_ts
                    + YOUTUBE_DISLIKED_VIDEOS_CACHE_SECONDS
                ),
                "results": [
                    dict(item)
                    for item in results
                ],
                "retrieved_at": retrieved_at,
            }
        )

    return {
        "kind": "disliked",
        "results": annotate_favourites(
            results
        ),
        "retrieved_at": retrieved_at,
        "source": "YouTube disliked videos",
    }



def youtube_account_stats(force=False):
    """
    YouTube account/library statistics for Settings > YouTube.

    Deliberately excludes statistics for the user's own YouTube channel.
    Only account-level library information useful to this application is
    returned: subscriptions, liked videos and playlists.

    Personal viewer watch-history totals and total watch-time are not exposed
    through the YouTube Data API and are therefore not shown.
    """
    now_ts = time.time()

    with YOUTUBE_ACCOUNT_STATS_LOCK:
        cached = YOUTUBE_ACCOUNT_STATS_CACHE.get("data")
        expires_at = YOUTUBE_ACCOUNT_STATS_CACHE.get("expires_at", 0)

    if cached and not force and expires_at > now_ts:
        return dict(cached)

    result = {
        "available": False,
        "error": "",
        "subscription_count_text": "—",
        "liked_video_count_text": "—",
        "playlist_count_text": "—",
        "retrieved_at": "",
    }

    try:
        creds = load_credentials()
        if not creds:
            result["error"] = "Google is not connected."
            return result

        # The account is connected even if one of the individual statistic
        # calls below is unavailable.
        result["available"] = True

        # Channels the authenticated YouTube account currently subscribes to.
        try:
            response = youtube_api_request(
                creds,
                "GET",
                "subscriptions",
                "subscriptions.list",
                1,
                params={
                    "part": "id",
                    "mine": "true",
                    "maxResults": 1,
                },
            )
            total = int(
                (response.json().get("pageInfo") or {}).get(
                    "totalResults",
                    0,
                )
                or 0
            )
            result["subscription_count_text"] = f"{total:,}"
        except Exception:
            pass

        # Videos currently marked Like by the authenticated account.
        try:
            response = youtube_api_request(
                creds,
                "GET",
                "videos",
                "videos.list",
                1,
                params={
                    "part": "id",
                    "myRating": "like",
                    "maxResults": 1,
                },
            )
            total = int(
                (response.json().get("pageInfo") or {}).get(
                    "totalResults",
                    0,
                )
                or 0
            )
            result["liked_video_count_text"] = f"{total:,}"
        except Exception:
            pass

        # User-created playlists owned by the authenticated account.
        try:
            response = youtube_api_request(
                creds,
                "GET",
                "playlists",
                "playlists.list",
                1,
                params={
                    "part": "id",
                    "mine": "true",
                    "maxResults": 1,
                },
            )
            total = int(
                (response.json().get("pageInfo") or {}).get(
                    "totalResults",
                    0,
                )
                or 0
            )
            result["playlist_count_text"] = f"{total:,}"
        except Exception:
            pass

        result["retrieved_at"] = now_iso()

    except Exception as exc:
        result["error"] = str(exc)

    with YOUTUBE_ACCOUNT_STATS_LOCK:
        YOUTUBE_ACCOUNT_STATS_CACHE["data"] = dict(result)
        YOUTUBE_ACCOUNT_STATS_CACHE["expires_at"] = (
            now_ts + YOUTUBE_ACCOUNT_STATS_CACHE_SECONDS
        )

    return result


def youtube_duration_label(value):
    value = str(value or "").strip()
    if not value:
        return ""

    match = re.fullmatch(
        r"P(?:(\d+)D)?T(?:(\d+)H)?(?:(\d+)M)?(?:(\d+)S)?",
        value,
    )
    if not match:
        return ""

    days, hours, minutes, seconds = [
        int(part or 0)
        for part in match.groups()
    ]
    hours += days * 24

    if hours:
        return f"{hours}:{minutes:02d}:{seconds:02d}"

    return f"{minutes}:{seconds:02d}"


def youtube_duration_seconds(value):
    value = str(value or "").strip()
    if not value:
        return 0

    match = re.fullmatch(
        r"P(?:(\d+)D)?T(?:(\d+)H)?(?:(\d+)M)?(?:(\d+)S)?",
        value,
    )
    if not match:
        return 0

    days, hours, minutes, seconds = [
        int(part or 0)
        for part in match.groups()
    ]

    return (
        (days * 86400)
        + (hours * 3600)
        + (minutes * 60)
        + seconds
    )


def youtube_video_metadata(video_id, force=False):
    video_id = str(video_id or "").strip()

    if not re.fullmatch(r"[A-Za-z0-9_-]{11}", video_id):
        raise RuntimeError("A valid YouTube video ID is required.")

    now_ts = time.time()

    with YOUTUBE_VIDEO_METADATA_LOCK:
        cached = YOUTUBE_VIDEO_METADATA_CACHE.get(video_id)

    if (
        cached
        and not force
        and cached.get("expires_at", 0) > now_ts
    ):
        return annotate_favourites(
            [dict(cached["item"])]
        )[0]

    creds = load_credentials()
    if not creds:
        raise RuntimeError("Google account is not connected.")

    response = youtube_api_request(
        creds,
        "GET",
        "videos",
        "videos.list",
        1,
        params={
            "part": "snippet,statistics,contentDetails,status,topicDetails,liveStreamingDetails",
            "id": video_id,
            "maxResults": 1,
        },
    )

    videos = response.json().get("items", [])
    if not videos:
        raise RuntimeError(
            "YouTube did not return metadata for this video."
        )

    video = videos[0]
    snippet = video.get("snippet") or {}
    statistics = video.get("statistics") or {}
    content_details = video.get("contentDetails") or {}
    video_status = video.get("status") or {}
    topic_details = video.get("topicDetails") or {}
    live_details = video.get("liveStreamingDetails") or {}
    thumbnails = snippet.get("thumbnails") or {}

    thumbnail = (
        thumbnails.get("maxres")
        or thumbnails.get("standard")
        or thumbnails.get("high")
        or thumbnails.get("medium")
        or thumbnails.get("default")
        or {}
    )

    channel_id = snippet.get("channelId") or ""
    channel_title = snippet.get("channelTitle") or "YouTube channel"
    channel_thumbnail_url = ""
    channel_url = (
        f"https://www.youtube.com/channel/{channel_id}"
        if channel_id
        else "https://www.youtube.com"
    )
    is_subscribed = False

    if channel_id:
        with db() as conn:
            subscription = conn.execute(
                """
                SELECT channel_url, thumbnail_url, active
                FROM subscriptions
                WHERE channel_id = ?
                LIMIT 1
                """,
                (channel_id,),
            ).fetchone()

        if subscription:
            channel_url = (
                subscription["channel_url"]
                or channel_url
            )
            channel_thumbnail_url = (
                subscription["thumbnail_url"]
                or ""
            )
            is_subscribed = bool(
                subscription["active"]
            )

    if channel_id and not channel_thumbnail_url:
        try:
            channel_response = youtube_api_request(
                creds,
                "GET",
                "channels",
                "channels.list",
                1,
                params={
                    "part": "snippet",
                    "id": channel_id,
                    "maxResults": 1,
                },
            )

            channel_items = channel_response.json().get(
                "items",
                [],
            )

            if channel_items:
                channel_snippet = (
                    channel_items[0].get("snippet")
                    or {}
                )
                channel_thumbnails = (
                    channel_snippet.get("thumbnails")
                    or {}
                )
                channel_image = (
                    channel_thumbnails.get("high")
                    or channel_thumbnails.get("medium")
                    or channel_thumbnails.get("default")
                    or {}
                )
                channel_thumbnail_url = (
                    channel_image.get("url")
                    or ""
                )
        except Exception:
            pass

    raw_duration = (
        content_details.get("duration")
        or ""
    )
    duration_seconds = youtube_duration_seconds(
        raw_duration
    )

    item = {
        "video_id": video_id,
        "title": snippet.get("title") or "YouTube video",
        "description": snippet.get("description") or "",
        "video_url": (
            f"https://www.youtube.com/watch?v={video_id}"
        ),
        "shorts_url": (
            f"https://www.youtube.com/shorts/{video_id}"
        ),
        "channel_id": channel_id,
        "channel_title": channel_title,
        "channel_url": channel_url,
        "channel_thumbnail_url": channel_thumbnail_url,
        "thumbnail_url": thumbnail.get("url") or "",
        "published_at": snippet.get("publishedAt") or "",
        "view_count": int(statistics.get("viewCount") or 0),
        "like_count": int(statistics.get("likeCount") or 0),
        "comment_count": int(statistics.get("commentCount") or 0),
        "favourite_count": int(statistics.get("favoriteCount") or 0),
        "category_id": str(snippet.get("categoryId") or ""),
        "category": YOUTUBE_VIDEO_CATEGORIES.get(str(snippet.get("categoryId") or ""), ""),
        "tags": list(snippet.get("tags") or []),
        "default_language": snippet.get("defaultLanguage") or "",
        "default_audio_language": snippet.get("defaultAudioLanguage") or "",
        "definition": content_details.get("definition") or "",
        "caption": content_details.get("caption") or "",
        "licensed_content": bool(content_details.get("licensedContent")),
        "dimension": content_details.get("dimension") or "",
        "projection": content_details.get("projection") or "",
        "privacy_status": video_status.get("privacyStatus") or "",
        "embeddable": bool(video_status.get("embeddable", True)),
        "made_for_kids": video_status.get("madeForKids"),
        "topics": [youtube_topic_label(value) for value in (topic_details.get("topicCategories") or []) if youtube_topic_label(value)],
        "live": bool(live_details),
        "scheduled_start_time": live_details.get("scheduledStartTime") or "",
        "actual_start_time": live_details.get("actualStartTime") or "",
        "actual_end_time": live_details.get("actualEndTime") or "",
        "concurrent_viewers": int(live_details.get("concurrentViewers") or 0),
        "duration": youtube_duration_label(
            raw_duration
        ),
        "duration_seconds": duration_seconds,
        "is_short": youtube_video_is_short(
            snippet.get("title") or "",
            snippet.get("description") or "",
            duration_seconds,
        ),
        "is_subscribed": is_subscribed,
        "metadata_complete": True,
        "metadata_rich": True,
    }

    with YOUTUBE_VIDEO_METADATA_LOCK:
        YOUTUBE_VIDEO_METADATA_CACHE[video_id] = {
            "expires_at": (
                now_ts
                + YOUTUBE_VIDEO_METADATA_CACHE_SECONDS
            ),
            "item": dict(item),
        }

    return annotate_favourites([item])[0]


def youtube_video_is_short(title, description, duration_seconds):
    """
    YouTube does not expose a dedicated isShort field through videos.list.

    Treat videos up to 60 seconds as Shorts. Also accept videos up to three
    minutes when the creator explicitly tags the title or description #shorts.
    This follows YouTube's current three-minute Shorts maximum while avoiding
    classifying every ordinary two-minute video as a Short.
    """
    duration_seconds = int(duration_seconds or 0)

    if duration_seconds <= 0:
        return False

    if duration_seconds <= 60:
        return True

    text = f"{title or ''} {description or ''}".casefold()

    return (
        duration_seconds <= 180
        and "#shorts" in text
    )


def youtube_channel_feed(channel_id, force=False):
    """
    Return recent uploads from one subscribed channel's public YouTube Atom
    feed. This does not consume YouTube Data API quota.
    """
    channel_id = str(channel_id or "").strip()
    if not channel_id:
        return []

    now_ts = time.time()

    if not force:
        with YOUTUBE_CHANNEL_FEED_LOCK:
            cached = YOUTUBE_CHANNEL_FEED_CACHE.get(channel_id)

        if cached and cached.get("expires_at", 0) > now_ts:
            return list(cached.get("entries") or [])

    url = (
        "https://www.youtube.com/feeds/videos.xml"
        f"?channel_id={quote(channel_id)}"
    )

    response = requests.get(
        url,
        timeout=12,
        headers={
            "User-Agent": (
                "Mozilla/5.0 YouTube-Pinchflat-Sync/"
                f"{VERSION}"
            )
        },
    )
    response.raise_for_status()

    root = ET.fromstring(response.content)

    ns = {
        "atom": "http://www.w3.org/2005/Atom",
        "yt": "http://www.youtube.com/xml/schemas/2015",
        "media": "http://search.yahoo.com/mrss/",
    }

    entries = []

    for entry in root.findall("atom:entry", ns):
        video_id = (
            entry.findtext("yt:videoId", default="", namespaces=ns)
            or ""
        ).strip()

        if not video_id:
            continue

        title = (
            entry.findtext("atom:title", default="", namespaces=ns)
            or "YouTube video"
        ).strip()

        published = (
            entry.findtext("atom:published", default="", namespaces=ns)
            or ""
        ).strip()

        updated = (
            entry.findtext("atom:updated", default="", namespaces=ns)
            or ""
        ).strip()

        channel_title = (
            entry.findtext("atom:author/atom:name", default="", namespaces=ns)
            or ""
        ).strip()

        entries.append(
            {
                "video_id": video_id,
                "title": title,
                "published_at": published or updated,
                "channel_id": channel_id,
                "channel_title": channel_title,
                "video_url": (
                    f"https://www.youtube.com/watch?v={video_id}"
                ),
                "thumbnail_url": (
                    f"https://i.ytimg.com/vi/{video_id}/hqdefault.jpg"
                ),
            }
        )

    with YOUTUBE_CHANNEL_FEED_LOCK:
        YOUTUBE_CHANNEL_FEED_CACHE[channel_id] = {
            "expires_at": now_ts + YOUTUBE_CHANNEL_FEED_CACHE_SECONDS,
            "entries": entries,
        }

    return list(entries)


def youtube_latest_subscription_videos(limit=36, force=False):
    """
    Return the latest uploads across every active YouTube subscription.

    There is deliberately no date window. The app reads the recent public
    upload feed for every active subscribed channel, combines those entries,
    sorts them by publication time, and returns the newest N videos overall.
    """
    limit = min(max(int(limit or 36), 1), 48)
    now_ts = time.time()

    if (
        not force
        and LATEST_SUBSCRIPTIONS_CACHE["results"]
        and LATEST_SUBSCRIPTIONS_CACHE["expires_at"] > now_ts
    ):
        return {
            "results": LATEST_SUBSCRIPTIONS_CACHE["results"][:limit],
            "shorts": LATEST_SUBSCRIPTIONS_CACHE["shorts"][:8],
            "retrieved_at": LATEST_SUBSCRIPTIONS_CACHE["retrieved_at"],
            "source": "YouTube channel feeds",
        }

    creds = load_credentials()
    if not creds:
        raise RuntimeError("Google account is not connected.")

    with db() as conn:
        rows = conn.execute(
            """
            SELECT channel_id, title, channel_url, thumbnail_url,
                   download_enabled, pinchflat_source_id
            FROM subscriptions
            WHERE active = 1
            """
        ).fetchall()

    subscriptions = {
        row["channel_id"]: {
            "channel_title": row["title"] or "",
            "channel_url": row["channel_url"] or (
                f"https://www.youtube.com/channel/{row['channel_id']}"
            ),
            "channel_thumbnail_url": row["thumbnail_url"] or "",
            "download_enabled": bool(row["download_enabled"]),
            "pinchflat_source_id": str(row["pinchflat_source_id"] or ""),
        }
        for row in rows
        if row["channel_id"]
    }

    if not subscriptions:
        return {
            "results": [],
            "shorts": [],
            "retrieved_at": now_iso(),
            "source": "YouTube channel feeds",
        }

    combined = []
    failed_channels = 0

    # Fetch each channel in parallel. Cached channel feeds return immediately,
    # so routine page loads are cheap. A forced refresh refreshes every feed.
    with ThreadPoolExecutor(
        max_workers=YOUTUBE_CHANNEL_FEED_WORKERS
    ) as executor:
        futures = {
            executor.submit(
                youtube_channel_feed,
                channel_id,
                force,
            ): channel_id
            for channel_id in subscriptions
        }

        for future in as_completed(futures):
            channel_id = futures[future]

            try:
                feed_entries = future.result()
            except Exception:
                failed_channels += 1
                continue

            channel = subscriptions[channel_id]

            for item in feed_entries:
                item = dict(item)
                item["channel_title"] = (
                    item.get("channel_title")
                    or channel["channel_title"]
                    or "YouTube channel"
                )
                item["channel_url"] = channel["channel_url"]
                item["channel_thumbnail_url"] = (
                    channel["channel_thumbnail_url"]
                )
                combined.append(item)

    if not combined:
        raise RuntimeError(
            "No YouTube channel feeds returned recent uploads. "
            f"Feeds failed: {failed_channels} of {len(subscriptions)}."
        )

    # Deduplicate before sorting.
    unique = {}
    for item in combined:
        video_id = item.get("video_id")
        if video_id and video_id not in unique:
            unique[video_id] = item

    candidates = list(unique.values())
    candidates.sort(
        key=lambda item: item.get("published_at") or "",
        reverse=True,
    )

    # Enrich a larger candidate set so the home page can show both the
    # newest normal videos and a separate Shorts shelf. videos.list accepts
    # 50 IDs per request, so 150 candidates use three low-cost requests.
    candidate_ids = [
        item["video_id"]
        for item in candidates[:150]
    ]

    details_by_id = {}

    for start in range(0, len(candidate_ids), 50):
        chunk = candidate_ids[start:start + 50]
        if not chunk:
            continue

        response = youtube_api_request(
            creds,
            "GET",
            "videos",
            "videos.list",
            1,
            params={
                "part": "snippet,statistics,contentDetails",
                "id": ",".join(chunk),
                "maxResults": 50,
            },
        )

        for video in response.json().get("items", []):
            video_id = video.get("id") or ""
            snippet = video.get("snippet") or {}
            statistics = video.get("statistics") or {}
            content_details = video.get("contentDetails") or {}
            thumbnails = snippet.get("thumbnails") or {}
            thumbnail = (
                thumbnails.get("maxres")
                or thumbnails.get("standard")
                or thumbnails.get("high")
                or thumbnails.get("medium")
                or thumbnails.get("default")
                or {}
            )

            raw_duration = content_details.get("duration") or ""
            duration_seconds = youtube_duration_seconds(raw_duration)

            details_by_id[video_id] = {
                "title": snippet.get("title") or "",
                "description": snippet.get("description") or "",
                "channel_id": snippet.get("channelId") or "",
                "channel_title": snippet.get("channelTitle") or "",
                "published_at": snippet.get("publishedAt") or "",
                "thumbnail_url": thumbnail.get("url") or "",
                "view_count": int(statistics.get("viewCount") or 0),
                "duration": youtube_duration_label(raw_duration),
                "duration_seconds": duration_seconds,
                "is_short": youtube_video_is_short(
                    snippet.get("title") or "",
                    snippet.get("description") or "",
                    duration_seconds,
                ),
            }

    videos = []
    shorts = []

    for candidate in candidates:
        if len(videos) >= limit and len(shorts) >= 8:
            break

        video_id = candidate.get("video_id") or ""
        details = details_by_id.get(video_id)

        # Skip a feed entry if videos.list says the video no longer exists.
        if not details:
            continue

        channel_id = (
            details.get("channel_id")
            or candidate.get("channel_id")
            or ""
        )

        # This keeps the result authoritative to the current subscription DB.
        if channel_id not in subscriptions:
            continue

        channel = subscriptions[channel_id]

        item = {
            "video_id": video_id,
            "title": (
                details.get("title")
                or candidate.get("title")
                or "YouTube video"
            ),
            "description": details.get("description") or "",
            "video_url": (
                f"https://www.youtube.com/watch?v={video_id}"
            ),
            "shorts_url": (
                f"https://www.youtube.com/shorts/{video_id}"
            ),
            "channel_id": channel_id,
            "channel_title": (
                details.get("channel_title")
                or channel["channel_title"]
                or "YouTube channel"
            ),
            "channel_url": channel["channel_url"],
            "channel_thumbnail_url": (
                channel["channel_thumbnail_url"]
            ),
            "download_enabled": bool(channel.get("download_enabled")),
            "pinchflat_source_id": str(channel.get("pinchflat_source_id") or ""),
            "thumbnail_url": (
                details.get("thumbnail_url")
                or candidate.get("thumbnail_url")
                or ""
            ),
            "published_at": (
                details.get("published_at")
                or candidate.get("published_at")
                or ""
            ),
            "view_count": int(
                details.get("view_count") or 0
            ),
            "duration": details.get("duration") or "",
            "duration_seconds": int(
                details.get("duration_seconds") or 0
            ),
            "is_short": bool(details.get("is_short")),
        }

        if item["is_short"]:
            if len(shorts) < 8:
                shorts.append(item)
        elif len(videos) < limit:
            videos.append(item)

    # Sort once more using authoritative videos.list publication timestamps.
    videos.sort(
        key=lambda item: item.get("published_at") or "",
        reverse=True,
    )
    shorts.sort(
        key=lambda item: item.get("published_at") or "",
        reverse=True,
    )

    videos = annotate_favourites(videos[:limit])
    shorts = annotate_favourites(shorts[:8])
    for item in videos + shorts:
        item["is_subscribed"] = True

    retrieved_at = now_iso()
    LATEST_SUBSCRIPTIONS_CACHE.update(
        {
            "expires_at": now_ts + LATEST_SUBSCRIPTIONS_CACHE_SECONDS,
            "results": videos,
            "shorts": shorts,
            "retrieved_at": retrieved_at,
        }
    )

    return {
        "results": videos,
        "shorts": shorts,
        "retrieved_at": retrieved_at,
        "source": "YouTube channel feeds",
        "failed_channels": failed_channels,
    }



def discovery_interest_titles():
    """
    Build a weighted pool of interests from this user's own YouTube activity
    inside the app.

    Favourite channels and videos explicitly liked through this app get the
    strongest weight. Current active subscriptions provide the broad fallback.
    """
    user_id = current_user_id()
    weighted = []

    with db() as conn:
        subscriptions = conn.execute(
            """
            SELECT title
            FROM subscriptions
            WHERE active = 1
              AND title IS NOT NULL
              AND TRIM(title) != ''
            """
        ).fetchall()

        favourites = []
        likes = []

        if user_id:
            favourites = conn.execute(
                """
                SELECT channel_title
                FROM favourite_channels
                WHERE user_id = ?
                ORDER BY created_at DESC
                LIMIT 100
                """,
                (user_id,),
            ).fetchall()

            likes = conn.execute(
                """
                SELECT title, channel_title
                FROM discovery_likes
                WHERE user_id = ?
                ORDER BY created_at DESC
                LIMIT 100
                """,
                (user_id,),
            ).fetchall()

    # Strongest signal: explicit YouTube likes from Discover.
    for row in likes:
        channel_title = str(row["channel_title"] or "").strip()
        title = str(row["title"] or "").strip()

        if channel_title:
            weighted.extend([channel_title] * 6)

        # Video titles help the search move towards the subject rather than
        # always searching for the same creator.
        if title:
            title = re.sub(r"#\w+", " ", title)
            title = re.sub(r"\s+", " ", title).strip()
            if len(title) > 90:
                title = title[:90].rsplit(" ", 1)[0]
            if title:
                weighted.extend([title] * 3)

    # Second strongest signal: channels explicitly favourited in our app.
    for row in favourites:
        title = str(row["channel_title"] or "").strip()
        if title:
            weighted.extend([title] * 4)

    # Broad interest signal: all current YouTube subscriptions.
    for row in subscriptions:
        title = str(row["title"] or "").strip()
        if title:
            weighted.append(title)

    return weighted


def personalised_discovery_query(kind):
    """
    Build a discovery query from the user's own subscriptions and likes.

    Multiple seeds are ORed together so the result batch covers several of
    the user's interests rather than one fixed generic topic.
    """
    interests = discovery_interest_titles()

    seeds = []
    if interests:
        random.shuffle(interests)
        for value in interests:
            value = re.sub(r"[|]+", " ", str(value or "")).strip()
            value = re.sub(r"\s+", " ", value)
            if not value:
                continue
            if value.casefold() in {item.casefold() for item in seeds}:
                continue
            seeds.append(value)
            if len(seeds) >= 3:
                break

    if not seeds:
        seeds = [random.choice(DISCOVERY_TERMS)]

    if kind == "shorts":
        # Searching only for subscribed channel names often returns videos
        # from those exact channels. We deliberately exclude subscribed
        # channels from Discover, which could leave an empty Shorts batch.
        #
        # Keep the personal interest seeds, but add a broad topic as another
        # OR branch so the same search also has room to find related creators.
        broad_topic = random.choice(DISCOVERY_TERMS)
        personal = "|".join(seeds[:2])
        query = f"{personal}|{broad_topic} #shorts"
    else:
        query = "|".join(seeds)

    return query, seeds


def record_discovery_like(item):
    user_id = current_user_id()
    if not user_id:
        return

    video_id = str(item.get("video_id") or "").strip()
    if not video_id:
        return

    with db() as conn:
        conn.execute(
            """
            INSERT INTO discovery_likes (
                user_id,
                video_id,
                title,
                channel_id,
                channel_title,
                created_at
            )
            VALUES (?, ?, ?, ?, ?, ?)
            ON CONFLICT(user_id, video_id)
            DO UPDATE SET
                title = excluded.title,
                channel_id = excluded.channel_id,
                channel_title = excluded.channel_title,
                created_at = excluded.created_at
            """,
            (
                user_id,
                video_id,
                str(item.get("title") or "YouTube video")[:500],
                str(item.get("channel_id") or ""),
                str(item.get("channel_title") or "YouTube")[:300],
                now_iso(),
            ),
        )


def youtube_discovery_results(kind="videos", limit=24):
    creds = load_credentials()
    if not creds:
        raise RuntimeError("Google account is not connected.")

    stats = api_usage_stats()
    if stats["search_remaining"] <= 0:
        raise RuntimeError(
            "The YouTube discovery search limit has been reached for today."
        )

    kind = "shorts" if kind == "shorts" else "videos"
    max_limit = 40 if kind == "shorts" else 160
    default_limit = 24 if kind == "shorts" else 150
    limit = min(max(int(limit or default_limit), 1), max_limit)

    with db() as conn:
        subscribed_ids = {
            row["channel_id"]
            for row in conn.execute(
                "SELECT channel_id FROM subscriptions WHERE active = 1"
            ).fetchall()
        }

    personalised_query, interest_seeds = personalised_discovery_query(kind)

    if kind == "shorts":
        search_plans = [
            {
                "query": personalised_query,
                "order": "relevance",
                "source": "personalised",
            },
            {
                "query": personalised_query,
                "order": "date",
                "source": "personalised",
            },
        ]
    else:
        fallback_terms = random.sample(
            DISCOVERY_TERMS,
            k=min(5, len(DISCOVERY_TERMS)),
        )

        search_plans = [
            {
                "query": personalised_query,
                "order": "relevance",
                "source": "personalised",
            },
            {
                "query": personalised_query,
                "order": "viewCount",
                "source": "personalised",
            },
        ]

        fallback_orders = [
            "relevance",
            "date",
            "viewCount",
            "date",
            "relevance",
        ]

        # Normal Random Videos deliberately use only YouTube's medium and
        # long duration classes. This prevents Shorts and other very short
        # clips from entering the Random Videos grid.
        search_plans[0]["video_duration"] = "medium"
        search_plans[1]["video_duration"] = "long"

        fallback_durations = [
            "medium",
            "long",
            "medium",
            "long",
            "medium",
        ]

        for term, order, video_duration in zip(
            fallback_terms,
            fallback_orders,
            fallback_durations,
        ):
            search_plans.append(
                {
                    "query": term,
                    "order": order,
                    "source": "uk_fallback",
                    "video_duration": video_duration,
                }
            )

    raw_items = []
    seen_video_ids = set()
    search_calls = 0
    search_remaining = stats["search_remaining"]
    target_pool = 75 if kind == "shorts" else 220

    for plan_index, plan in enumerate(search_plans):
        if search_calls >= search_remaining:
            break

        params = {
            "part": "snippet",
            "type": "video",
            "maxResults": 50,
            "q": plan["query"],
            "safeSearch": "moderate",
            "videoEmbeddable": "true",
            "relevanceLanguage": "en",
            "regionCode": "GB",
            "order": plan["order"],
        }

        if kind == "shorts":
            params["videoDuration"] = "short"
        elif plan.get("video_duration"):
            params["videoDuration"] = plan["video_duration"]

        response = youtube_api_request(
            creds,
            "GET",
            "search",
            "search.list",
            1,
            params=params,
        )
        search_calls += 1

        for position, item in enumerate(response.json().get("items", [])):
            video_id = (item.get("id") or {}).get("videoId")
            if not video_id or video_id in seen_video_ids:
                continue

            seen_video_ids.add(video_id)
            raw_items.append(
                {
                    "search_item": item,
                    "source": plan["source"],
                    "plan_index": plan_index,
                    "position": position,
                }
            )

        if len(raw_items) >= target_pool:
            break

    video_ids = [
        (entry["search_item"].get("id") or {}).get("videoId")
        for entry in raw_items
        if (entry["search_item"].get("id") or {}).get("videoId")
    ]

    details_by_video = {}

    for chunk_start in range(0, len(video_ids), 50):
        chunk = video_ids[chunk_start:chunk_start + 50]
        if not chunk:
            continue

        details_response = youtube_api_request(
            creds,
            "GET",
            "videos",
            "videos.list",
            1,
            params={
                "part": "snippet,statistics,contentDetails",
                "id": ",".join(chunk),
                "maxResults": 50,
            },
        )

        for video in details_response.json().get("items", []):
            video_id = video.get("id") or ""
            snippet = video.get("snippet") or {}
            statistics = video.get("statistics") or {}
            content_details = video.get("contentDetails") or {}
            thumbnails = snippet.get("thumbnails") or {}

            thumbnail = (
                thumbnails.get("maxres")
                or thumbnails.get("standard")
                or thumbnails.get("high")
                or thumbnails.get("medium")
                or thumbnails.get("default")
                or {}
            )

            details_by_video[video_id] = {
                "default_audio_language": (
                    snippet.get("defaultAudioLanguage") or ""
                ),
                "default_language": snippet.get("defaultLanguage") or "",
                "description": snippet.get("description") or "",
                "channel_id": snippet.get("channelId") or "",
                "channel_title": snippet.get("channelTitle") or "",
                "title": snippet.get("title") or "",
                "published_at": snippet.get("publishedAt") or "",
                "thumbnail_url": thumbnail.get("url") or "",
                "view_count": int(statistics.get("viewCount") or 0),
                "duration": youtube_duration_label(
                    content_details.get("duration") or ""
                ),
                "duration_seconds": youtube_duration_seconds(
                    content_details.get("duration") or ""
                ),
            }

    candidates = []
    channel_ids = []

    for entry in raw_items:
        item = entry["search_item"]
        snippet = item.get("snippet") or {}
        video_id = (item.get("id") or {}).get("videoId")
        details = details_by_video.get(video_id, {})

        channel_id = (
            details.get("channel_id")
            or snippet.get("channelId")
            or ""
        )

        if not video_id or not channel_id:
            continue

        if channel_id in subscribed_ids:
            continue

        explicit_language = (
            details.get("default_audio_language")
            or details.get("default_language")
            or ""
        )

        if (
            explicit_language
            and not english_language_code(explicit_language)
        ):
            continue

        title = (
            details.get("title")
            or snippet.get("title")
            or "YouTube video"
        )
        channel_title = (
            details.get("channel_title")
            or snippet.get("channelTitle")
            or "YouTube"
        )

        if (
            not explicit_language
            and (
                has_obvious_non_latin_title(title)
                or has_obvious_non_latin_title(channel_title)
            )
        ):
            continue

        duration_seconds = int(
            details.get("duration_seconds") or 0
        )

        if kind == "videos" and duration_seconds <= 180:
            continue

        candidate = {
            "video_id": video_id,
            "channel_id": channel_id,
            "title": title,
            "channel_title": channel_title,
            "published_at": (
                details.get("published_at")
                or snippet.get("publishedAt")
                or ""
            ),
            "description": details.get("description") or "",
            "video_url": (
                f"https://www.youtube.com/watch?v={video_id}"
            ),
            "shorts_url": (
                f"https://www.youtube.com/shorts/{video_id}"
            ),
            "channel_url": (
                f"https://www.youtube.com/channel/{channel_id}"
            ),
            "thumbnail_url": (
                details.get("thumbnail_url")
                or (
                    (
                        (snippet.get("thumbnails") or {}).get("high")
                        or {}
                    ).get("url")
                )
                or ""
            ),
            "view_count": int(details.get("view_count") or 0),
            "duration": details.get("duration") or "",
            "duration_seconds": duration_seconds,
            "recommendation_source": entry["source"],
            "is_subscribed": False,
            "_plan_index": entry["plan_index"],
            "_position": entry["position"],
        }

        candidates.append(candidate)
        channel_ids.append(channel_id)

    avatar_by_channel = {}
    unique_channel_ids = list(dict.fromkeys(channel_ids))

    for chunk_start in range(0, len(unique_channel_ids), 50):
        chunk = unique_channel_ids[chunk_start:chunk_start + 50]
        if not chunk:
            continue

        response = youtube_api_request(
            creds,
            "GET",
            "channels",
            "channels.list",
            1,
            params={
                "part": "snippet",
                "id": ",".join(chunk),
                "maxResults": 50,
            },
        )

        for channel in response.json().get("items", []):
            snippet = channel.get("snippet") or {}
            thumbnails = snippet.get("thumbnails") or {}
            image = (
                thumbnails.get("high")
                or thumbnails.get("medium")
                or thumbnails.get("default")
                or {}
            )
            avatar_by_channel[channel.get("id")] = image.get("url", "")

    grouped = {}
    for item in candidates:
        grouped.setdefault(item["_plan_index"], []).append(item)

    ordered = []
    seen_result_ids = set()
    personalised_count = 0
    fallback_count = 0

    for plan_index in sorted(grouped):
        batch = grouped[plan_index]
        random.shuffle(batch)

        for item in batch:
            if item["video_id"] in seen_result_ids:
                continue

            seen_result_ids.add(item["video_id"])

            avatar = avatar_by_channel.get(item["channel_id"], "")
            item["channel_avatar_url"] = avatar
            item["channel_thumbnail_url"] = avatar

            item.pop("_plan_index", None)
            item.pop("_position", None)

            if item["recommendation_source"] == "personalised":
                personalised_count += 1
            else:
                fallback_count += 1

            ordered.append(item)

            if len(ordered) >= limit:
                break

        if len(ordered) >= limit:
            break

    return {
        "kind": kind,
        "query": personalised_query,
        "interest_seeds": interest_seeds,
        "results": ordered,
        "personalised_count": personalised_count,
        "fallback_count": fallback_count,
        "search_calls_used": search_calls,
        "search_remaining": max(
            0,
            stats["search_remaining"] - search_calls,
        ),
    }


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


def safe_relative_download_folder(value, default):
    value = str(value or "").strip().replace("\\", "/").strip("/")
    if not value:
        value = default

    candidate = Path(value)
    if candidate.is_absolute() or ".." in candidate.parts:
        raise RuntimeError("Download folders must be relative to the shared /downloads directory.")

    return "/".join(part for part in candidate.parts if part not in {"", "."})


def profile_values_for_update(settings):
    return {
        "name": settings.get("name", ""),
        "output_path_template": settings.get(
            "output_path_template",
            EMBY_OUTPUT_PATH_TEMPLATE,
        ),
        "download_subs": bool(settings.get("download_subs")),
        "embed_subs": bool(settings.get("embed_subs")),
        "download_thumbnail": bool(settings.get("download_thumbnail")),
        "embed_thumbnail": bool(settings.get("embed_thumbnail")),
        "download_metadata": bool(settings.get("download_metadata")),
        "embed_metadata": bool(settings.get("embed_metadata")),
        "include_shorts": bool(settings.get("include_shorts")),
        "include_livestreams": bool(settings.get("include_livestreams", True)),
        "preferred_resolution": settings.get("preferred_resolution", ""),
        "redownload_delay_days": settings.get("redownload_delay_days", ""),
        "download_nfo": bool(settings.get("download_nfo", True)),
        "download_source_images": bool(
            settings.get("download_source_images", True)
        ),
        "sponsorblock_behaviour": settings.get(
            "sponsorblock_behaviour",
            "disabled",
        ),
        "sponsorblock_categories": list(
            settings.get("sponsorblock_categories") or []
        ),
    }


def subscription_folder_parent(output_template=None):
    template = str(
        output_template
        or media_profile_settings(
            effective_media_profile_id()
        ).get("output_path_template")
        or EMBY_OUTPUT_PATH_TEMPLATE
    )

    marker = "{{ source_custom_name }}"
    if marker not in template:
        return None

    prefix = template.split(marker, 1)[0].strip().replace("\\", "/").strip("/")
    if not prefix:
        return DOWNLOAD_ROOT

    try:
        safe_prefix = safe_relative_download_folder(prefix, "")
    except RuntimeError:
        return None

    parent = (DOWNLOAD_ROOT / safe_prefix).resolve()
    root = DOWNLOAD_ROOT.resolve()
    if parent != root and root not in parent.parents:
        return None
    return parent


def delete_subscription_download_folder(channel_title, output_template=None):
    """
    Remove only the channel folder used by the selected Pinchflat profile.
    This runs after Pinchflat is asked to delete the source and media.
    """
    parent = subscription_folder_parent(output_template)
    if parent is None or not parent.exists():
        return None

    target_name = normalise_storage_name(channel_title)
    if not target_name:
        return None

    root = DOWNLOAD_ROOT.resolve()
    for candidate in parent.iterdir():
        if not candidate.is_dir():
            continue
        if normalise_storage_name(candidate.name) != target_name:
            continue

        resolved = candidate.resolve()
        if resolved == root or root not in resolved.parents:
            raise RuntimeError("Refusing to delete a folder outside /downloads.")

        shutil.rmtree(resolved)
        storage_snapshot(force=True)
        return str(resolved)

    return None


def schedule_unsubscribe_cleanup(
    channel_id,
    channel_title,
    output_template=None,
    source_id=None,
    delete_files=True,
    delay_seconds=300,
    checks=6,
):
    with db() as conn:
        conn.execute(
            """
            DELETE FROM cleanup_jobs
            WHERE channel_id = ? AND status = 'pending'
            """,
            (channel_id,),
        )
        conn.execute(
            """
            INSERT INTO cleanup_jobs (
                channel_id,
                channel_title,
                output_template,
                source_id,
                delete_files,
                source_deleted,
                due_at,
                checks_remaining,
                interval_seconds,
                status,
                created_at
            )
            VALUES (?, ?, ?, ?, ?, 0, ?, ?, 300, 'pending', ?)
            """,
            (
                channel_id,
                channel_title,
                output_template or EMBY_OUTPUT_PATH_TEMPLATE,
                str(source_id) if source_id else None,
                1 if delete_files else 0,
                time.time() + max(1, int(delay_seconds)),
                max(1, int(checks)),
                now_iso(),
            ),
        )


def clear_subscription_pinchflat_link(channel_id, source_id=None):
    with db() as conn:
        conn.execute(
            """
            UPDATE subscriptions
            SET pinchflat_added = 0,
                pinchflat_source_id = NULL,
                last_error = NULL,
                retry_count = 0
            WHERE channel_id = ?
            """,
            (channel_id,),
        )


def process_deferred_unsubscribe_cleanups():
    now_ts = time.time()

    with db() as conn:
        rows = conn.execute(
            """
            SELECT *
            FROM cleanup_jobs
            WHERE status = 'pending'
              AND due_at <= ?
            ORDER BY due_at ASC
            LIMIT 25
            """,
            (now_ts,),
        ).fetchall()

    processed = 0

    for job in rows:
        processed += 1
        job = dict(job)

        try:
            with db() as conn:
                sub = conn.execute(
                    "SELECT * FROM subscriptions WHERE channel_id = ?",
                    (job["channel_id"],),
                ).fetchone()

            sub = dict(sub) if sub else None

            if sub and sub.get("active"):
                with db() as conn:
                    conn.execute(
                        """
                        UPDATE cleanup_jobs
                        SET status = 'cancelled',
                            finished_at = ?,
                            last_error = NULL
                        WHERE id = ?
                        """,
                        (now_iso(), job["id"]),
                    )
                continue

            source_id = job.get("source_id")
            if not source_id and sub:
                source_id = resolve_pinchflat_source_id(sub)

            delete_files = bool(job.get("delete_files"))
            source_gone = not source_id

            if source_id:
                if pinchflat_source_exists(source_id):
                    if sub:
                        removal_row = dict(sub)
                        removal_row["pinchflat_source_id"] = str(source_id)
                        removal_row["pinchflat_added"] = 1
                        prepare_pinchflat_source_for_removal(removal_row)

                    delete_pinchflat_source(
                        source_id,
                        delete_files=delete_files,
                        subscription=sub,
                        channel_id=job["channel_id"],
                    )

                source_gone = not pinchflat_source_exists(source_id)

            if source_gone:
                clear_subscription_pinchflat_link(
                    job["channel_id"],
                    source_id,
                )

            deleted_folder = None
            if delete_files:
                deleted_folder = delete_subscription_download_folder(
                    job["channel_title"],
                    job.get("output_template"),
                )

            remaining = max(0, int(job["checks_remaining"] or 1) - 1)

            # Keep source reconciliation alive until Pinchflat really deletes
            # the source. File follow-up remains limited to the 30-minute
            # cleanup window.
            if not source_gone:
                next_remaining = max(1, remaining)
                with db() as conn:
                    conn.execute(
                        """
                        UPDATE cleanup_jobs
                        SET source_id = ?,
                            source_deleted = 0,
                            due_at = ?,
                            checks_remaining = ?,
                            last_error = ?
                        WHERE id = ?
                        """,
                        (
                            str(source_id),
                            time.time() + 300,
                            next_remaining,
                            "Pinchflat source removal is still in progress.",
                            job["id"],
                        ),
                    )

                    conn.execute(
                        """
                        UPDATE subscriptions
                        SET pinchflat_added = 1,
                            pinchflat_source_id = ?,
                            download_enabled = 0,
                            last_error = ?
                        WHERE channel_id = ?
                        """,
                        (
                            str(source_id),
                            "Pinchflat source removal is still in progress.",
                            job["channel_id"],
                        ),
                    )

            elif remaining > 0:
                with db() as conn:
                    conn.execute(
                        """
                        UPDATE cleanup_jobs
                        SET source_id = ?,
                            source_deleted = 1,
                            due_at = ?,
                            checks_remaining = ?,
                            last_error = NULL
                        WHERE id = ?
                        """,
                        (
                            str(source_id) if source_id else None,
                            time.time() + 300,
                            remaining,
                            job["id"],
                        ),
                    )

            else:
                with db() as conn:
                    conn.execute(
                        """
                        UPDATE cleanup_jobs
                        SET source_id = ?,
                            source_deleted = 1,
                            status = 'complete',
                            checks_remaining = 0,
                            last_error = NULL,
                            finished_at = ?
                        WHERE id = ?
                        """,
                        (
                            str(source_id) if source_id else None,
                            now_iso(),
                            job["id"],
                        ),
                    )

            log_activity(
                "cleanup",
                "Unsubscribe reconciliation",
                (
                    f"{job['channel_title']}: Pinchflat source "
                    f"{'removed' if source_gone else 'still pending removal'}."
                    + (
                        f" Removed leftover folder {deleted_folder}."
                        if deleted_folder
                        else ""
                    )
                ),
                "success" if source_gone else "warning",
                job["channel_id"],
            )

        except Exception as exc:
            with db() as conn:
                conn.execute(
                    """
                    UPDATE cleanup_jobs
                    SET due_at = ?,
                        last_error = ?
                    WHERE id = ?
                    """,
                    (time.time() + 300, str(exc)[:1000], job["id"]),
                )

            log_activity(
                "cleanup",
                "Unsubscribe reconciliation error",
                f"{job['channel_title']}: {exc}",
                "error",
                job["channel_id"],
            )

    return {"processed": processed}


def reconcile_removed_pinchflat_sources():
    """
    Ensure inactive YouTube subscriptions do not remain Pinchflat sources.

    The read-only Pinchflat DB fallback also finds orphan sources left by older
    app versions which cleared pinchflat_source_id before deletion completed.
    """
    if not pinchflat_health():
        return {"checked": 0, "scheduled": 0}

    policy = unsubscribe_policy()
    if policy not in {"remove", "remove_delete"}:
        return {"checked": 0, "scheduled": 0}

    delete_files = policy == "remove_delete"

    with db() as conn:
        rows = conn.execute(
            """
            SELECT *
            FROM subscriptions
            WHERE active = 0
              AND removed_at IS NOT NULL
            ORDER BY removed_at DESC
            LIMIT 500
            """
        ).fetchall()

    checked = 0
    scheduled = 0

    for row in rows:
        checked += 1
        row = dict(row)
        source_id = resolve_pinchflat_source_id(row)

        if not source_id:
            clear_subscription_pinchflat_link(row["channel_id"])
            continue

        with db() as conn:
            pending = conn.execute(
                """
                SELECT id
                FROM cleanup_jobs
                WHERE channel_id = ?
                  AND status = 'pending'
                LIMIT 1
                """,
                (row["channel_id"],),
            ).fetchone()

        if pending:
            continue

        output_template = media_profile_settings(
            subscription_media_profile_id(row)
        ).get(
            "output_path_template",
            EMBY_OUTPUT_PATH_TEMPLATE,
        )

        removal_row = dict(row)
        removal_row["pinchflat_source_id"] = str(source_id)
        removal_row["pinchflat_added"] = 1

        prepare_pinchflat_source_for_removal(removal_row)
        source_gone = delete_pinchflat_source(
            source_id,
            delete_files=delete_files,
            subscription=row,
        )

        if source_gone:
            clear_subscription_pinchflat_link(
                row["channel_id"],
                source_id,
            )
        else:
            with db() as conn:
                conn.execute(
                    """
                    UPDATE subscriptions
                    SET pinchflat_added = 1,
                        pinchflat_source_id = ?,
                        download_enabled = 0,
                        last_error = ?
                    WHERE channel_id = ?
                    """,
                    (
                        str(source_id),
                        "Pinchflat source removal is in progress. Waiting for Pinchflat deletion worker.",
                        row["channel_id"],
                    ),
                )

        schedule_unsubscribe_cleanup(
            row["channel_id"],
            row.get("title") or row["channel_id"],
            output_template,
            source_id=source_id,
            delete_files=delete_files,
            delay_seconds=300,
            checks=6,
        )
        scheduled += 1

    return {"checked": checked, "scheduled": scheduled}



def prepare_pinchflat_source_for_removal(row):
    """
    Stop the source from adding more download work before asking Pinchflat to
    remove it. Existing work already queued inside Pinchflat is handled by the
    delayed cleanup window.
    """
    source_id = resolve_pinchflat_source_id(row)
    if not source_id:
        return

    try:
        update_pinchflat_source_settings(
            source_id,
            cutoff=subscription_cutoff(row),
            download_enabled=False,
            media_profile_id=subscription_media_profile_id(row),
        )
    except Exception as exc:
        # Continue to source deletion even when the disable request fails.
        log_activity(
            "pinchflat",
            "Could not pre-disable source",
            f"{row.get('title') or row.get('channel_id')}: {exc}",
            "warning",
            row.get("channel_id"),
        )


def migrate_legacy_subscription_output_path(profile_settings):
    """
    v1.8.1 restores /shows/ as the default parent folder. Only the exact
    v1.7/v1.8 generated template is migrated. Custom templates are untouched.
    """
    if not profile_settings or profile_settings.get("error"):
        return profile_settings

    current = str(profile_settings.get("output_path_template") or "").strip()
    if current != LEGACY_EMBY_OUTPUT_PATH_TEMPLATE:
        return profile_settings

    profile_id = effective_media_profile_id()
    if not profile_id:
        return profile_settings

    try:
        values = profile_values_for_update(profile_settings)
        values["output_path_template"] = EMBY_OUTPUT_PATH_TEMPLATE
        update_media_profile_settings(profile_id, values)
        log_activity(
            "settings",
            "Subscription path migrated",
            (
                "Updated the selected Pinchflat profile to "
                f"{EMBY_OUTPUT_PATH_TEMPLATE}"
            ),
            "success",
        )
        return media_profile_settings(profile_id)
    except Exception as exc:
        log_activity(
            "settings",
            "Subscription path migration failed",
            str(exc),
            "error",
        )
        return profile_settings


def remove_subscription_source_keep_files(row):
    """
    Disabled is authoritative.

    A disabled channel must not exist as a Pinchflat source.
    Downloaded files are retained. Pinchflat deletion is asynchronous, so
    retain the source link until disappearance is verified.
    """
    row = dict(row)
    source_id = resolve_pinchflat_source_id(row)

    if not source_id:
        clear_subscription_pinchflat_link(row["channel_id"])
        return {
            "source_id": None,
            "removed": True,
            "pending": False,
        }

    removal_row = dict(row)
    removal_row["pinchflat_source_id"] = str(source_id)
    removal_row["pinchflat_added"] = 1

    prepare_pinchflat_source_for_removal(removal_row)

    source_gone = delete_pinchflat_source(
        source_id,
        delete_files=False,
        subscription=row,
    )

    if source_gone:
        docker_state = pinchflat_container_status()

        if docker_state["control_available"] and docker_state["running"]:
            if pinchflat_source_exists_direct(
                source_id=source_id,
                channel_id=row.get("channel_id"),
                channel_url=row.get("channel_url"),
            ):
                raise RuntimeError(
                    "Pinchflat still contains this source after deletion."
                )

        clear_subscription_pinchflat_link(
            row["channel_id"],
            source_id,
        )
        return {
            "source_id": str(source_id),
            "removed": True,
            "pending": False,
        }

    with db() as conn:
        conn.execute(
            """
            UPDATE subscriptions
            SET pinchflat_added = 1,
                pinchflat_source_id = ?,
                download_enabled = 0,
                last_error = ?
            WHERE channel_id = ?
            """,
            (
                str(source_id),
                "Pinchflat source removal is in progress. Waiting for Pinchflat deletion worker.",
                row["channel_id"],
            ),
        )

    return {
        "source_id": str(source_id),
        "removed": False,
        "pending": True,
    }


def ensure_enabled_subscription_source(row, apply_settings=True):
    """
    Enabled is authoritative.

    An active and enabled subscription must exist in Pinchflat.
    Missing or stale source links are repaired automatically.
    """
    row = dict(row)

    if (
        not row.get("active")
        or not subscription_download_enabled(row)
        or not subscription_source_authorised(row)
    ):
        return {
            "created": False,
            "source_id": resolve_pinchflat_source_id(row),
        }

    source_id = resolve_pinchflat_source_id(row)

    if source_id and pinchflat_source_exists(source_id):
        with db() as conn:
            conn.execute(
                """
                UPDATE subscriptions
                SET pinchflat_added = 1,
                    pinchflat_source_id = ?,
                    last_error = NULL,
                    retry_count = 0
                WHERE channel_id = ?
                """,
                (str(source_id), row["channel_id"]),
            )

        if apply_settings:
            update_pinchflat_source_settings(
                source_id,
                cutoff=subscription_cutoff(row),
                download_enabled=True,
                media_profile_id=subscription_media_profile_id(row),
            )

        return {
            "created": False,
            "source_id": str(source_id),
        }

    clear_subscription_pinchflat_link(row["channel_id"])

    _result, new_source_id = add_pinchflat_source(row)

    with db() as conn:
        conn.execute(
            """
            UPDATE subscriptions
            SET pinchflat_added = 1,
                pinchflat_source_id = ?,
                last_error = NULL,
                retry_count = 0
            WHERE channel_id = ?
            """,
            (new_source_id, row["channel_id"]),
        )

    return {
        "created": True,
        "source_id": new_source_id,
    }


def apply_subscription_source_authority(row, apply_settings=True):
    """
    Enabled is the source-of-truth for Pinchflat membership.

    Enabled -> source exists.
    Disabled -> source does not exist.
    """
    row = dict(row)

    if not row.get("active"):
        return {"state": "inactive"}

    desired_in_pinchflat = (
        subscription_download_enabled(row)
        and subscription_source_authorised(row)
    )

    if desired_in_pinchflat:
        result = ensure_enabled_subscription_source(
            row,
            apply_settings=apply_settings,
        )
        return {
            "state": "enabled",
            **result,
        }

    result = remove_subscription_source_keep_files(row)
    return {
        "state": "disabled",
        **result,
    }


def reconcile_active_source_authority(max_changes=25):
    """
    Repair legacy app/Pinchflat mismatches in controlled batches.

    Older releases allowed disabled channels to remain as Pinchflat sources.
    At most max_changes source mutations are performed per pass.
    """
    if not pinchflat_health():
        return {
            "checked": 0,
            "changed": 0,
            "errors": 0,
        }

    with db() as conn:
        rows = [
            dict(row)
            for row in conn.execute(
                """
                SELECT *
                FROM subscriptions
                WHERE active = 1
                ORDER BY
                    CASE
                        WHEN download_enabled = 0 AND pinchflat_added = 1
                        THEN 0
                        WHEN download_enabled = 1 AND pinchflat_added = 0
                        THEN 1
                        ELSE 2
                    END,
                    title COLLATE NOCASE ASC
                """
            ).fetchall()
        ]

    checked = 0
    changed = 0
    errors = 0

    for row in rows:
        checked += 1

        desired = (
            subscription_download_enabled(row)
            and subscription_source_authorised(row)
        )
        source_id = resolve_pinchflat_source_id(row)
        source_exists = bool(
            source_id and pinchflat_source_exists(source_id)
        )

        mismatch = (
            (desired and not source_exists)
            or ((not desired) and source_exists)
        )

        if not mismatch:
            if source_exists and (
                not row.get("pinchflat_added")
                or str(row.get("pinchflat_source_id") or "")
                != str(source_id)
            ):
                with db() as conn:
                    conn.execute(
                        """
                        UPDATE subscriptions
                        SET pinchflat_added = 1,
                            pinchflat_source_id = ?
                        WHERE channel_id = ?
                        """,
                        (str(source_id), row["channel_id"]),
                    )
            elif not source_exists and row.get("pinchflat_added"):
                clear_subscription_pinchflat_link(row["channel_id"])
            continue

        if changed >= max_changes:
            continue

        try:
            apply_subscription_source_authority(
                row,
                apply_settings=False,
            )
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

    if changed or errors:
        log_activity(
            "pinchflat",
            "Source authority reconciliation",
            (
                f"Checked {checked} active subscription(s). "
                f"Changed {changed}. Errors {errors}."
            ),
            "success" if errors == 0 else "warning",
        )

    return {
        "checked": checked,
        "changed": changed,
        "errors": errors,
    }


def pinchflat_stats_summary(profiles=None, storage=None):
    profiles = profiles if profiles is not None else pinchflat_profiles()
    storage = storage if storage is not None else storage_snapshot()

    with db() as conn:
        row = conn.execute(
            """
            SELECT
                SUM(CASE WHEN pinchflat_added = 1 THEN 1 ELSE 0 END) AS linked,
                SUM(CASE WHEN pinchflat_added = 1 AND download_enabled = 1 THEN 1 ELSE 0 END) AS enabled,
                SUM(CASE WHEN pinchflat_added = 1 AND download_enabled = 0 THEN 1 ELSE 0 END) AS disabled,
                SUM(CASE WHEN active = 1 AND pinchflat_added = 0 THEN 1 ELSE 0 END) AS pending
            FROM subscriptions
            """
        ).fetchone()

    return {
        "profiles": len(profiles),
        "linked": int(row["linked"] or 0),
        "enabled": int(row["enabled"] or 0),
        "disabled": int(row["disabled"] or 0),
        "pending": int(row["pending"] or 0),
        "storage": format_bytes(storage["total"]),
    }


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


def download_filesystem_snapshot():
    """Return capacity information for the filesystem backing /downloads."""
    try:
        usage = shutil.disk_usage(DOWNLOAD_ROOT)
        return {
            "total": int(usage.total or 0),
            "used": int(usage.used or 0),
            "free": int(usage.free or 0),
        }
    except OSError:
        return {"total": 0, "used": 0, "free": 0}


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


def youtube_video_id_from_url(value):
    """Extract a YouTube video ID from the common public URL formats."""
    try:
        parsed = urlparse(str(value or "").strip())
    except Exception:
        return ""

    host = (parsed.hostname or "").casefold()
    path_parts = [part for part in (parsed.path or "").split("/") if part]

    if host == "youtu.be" and path_parts:
        candidate = path_parts[0]
    elif host == "youtube.com" or host.endswith(".youtube.com"):
        if parsed.path == "/watch":
            candidate = (parse_qs(parsed.query).get("v") or [""])[0]
        elif path_parts and path_parts[0] in {"shorts", "embed", "live"} and len(path_parts) > 1:
            candidate = path_parts[1]
        else:
            candidate = ""
    else:
        candidate = ""

    candidate = str(candidate or "").strip()
    return candidate if re.fullmatch(r"[A-Za-z0-9_-]{6,20}", candidate) else ""


def single_download_file_exists(row):
    """Return True only while a completed one-time download still exists on disk."""
    if not row or str(row.get("status") or "") != "completed":
        return False

    raw_path = str(row.get("output_path") or "").strip()
    if not raw_path:
        return False

    path = Path(raw_path)
    if path.exists() and path.is_file():
        return True

    # Some yt-dlp post-processors change the final extension after the path was
    # first reported. Search only the recorded parent folder, never all of
    # /downloads, and match the YouTube ID embedded by the default template.
    video_id = str(row.get("video_id") or "").strip()
    parent = path.parent
    if video_id and parent.exists() and parent.is_dir():
        try:
            return any(
                child.is_file() and video_id in child.name
                for child in parent.iterdir()
            )
        except OSError:
            return False
    return False


def completed_single_download_rows():
    with db() as conn:
        rows = conn.execute(
            """
            SELECT job_id, video_id, output_path, status, finished_at
            FROM downloads
            WHERE source_type = 'single'
              AND status = 'completed'
              AND COALESCE(video_id, '') <> ''
            ORDER BY id DESC
            """
        ).fetchall()
    return [dict(row) for row in rows]


def completed_single_download_video_ids():
    seen = set()
    for row in completed_single_download_rows():
        video_id = str(row.get("video_id") or "").strip()
        if video_id and video_id not in seen and single_download_file_exists(row):
            seen.add(video_id)
    return seen


def completed_single_download_for_video(video_id):
    video_id = str(video_id or "").strip()
    if not video_id:
        return None
    with db() as conn:
        rows = conn.execute(
            """
            SELECT job_id, video_id, output_path, status, finished_at
            FROM downloads
            WHERE source_type = 'single'
              AND video_id = ?
              AND status = 'completed'
            ORDER BY id DESC
            """,
            (video_id,),
        ).fetchall()
    for row in rows:
        item = dict(row)
        if single_download_file_exists(item):
            return item
    return None


def enqueue_download(
    youtube_url,
    source_type="single",
    video_id=None,
    title=None,
    channel_title=None,
    playlist_item_id=None,
    remove_playlist_item=False,
    channel_id=None,
    published_at=None,
    profile_id=None,
    redownload=False,
):
    if not valid_youtube_url(youtube_url):
        raise RuntimeError("Enter a valid YouTube video URL.")

    # Never create duplicate active jobs for the same video/source. Completed
    # subscription downloads are also skipped unless an explicit redownload
    # was requested.
    if video_id:
        with db() as conn:
            existing = conn.execute(
                """
                SELECT job_id, status, output_path
                FROM downloads
                WHERE video_id = ?
                  AND (
                    source_type = ?
                    OR (? LIKE 'subscription%' AND source_type LIKE 'subscription%')
                  )
                ORDER BY id DESC
                LIMIT 1
                """,
                (video_id, source_type, source_type),
            ).fetchone()
        if existing and existing["status"] in {"queued", "downloading", "processing"}:
            return existing["job_id"], False
        if existing and existing["status"] == "completed" and not redownload:
            path = Path(str(existing["output_path"] or ""))
            if path.exists():
                return existing["job_id"], False

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
        if existing and existing["status"] in {"queued", "downloading", "processing", "completed"}:
            return existing["job_id"], False

    job_id = secrets.token_hex(12)
    with db() as conn:
        conn.execute(
            """
            INSERT INTO downloads (
                job_id, source_type, youtube_url, video_id, title, channel_title,
                playlist_item_id, status, progress, remove_playlist_item, created_at,
                channel_id, published_at, profile_id, failure_code, auth_mode
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, 'queued', 0, ?, ?, ?, ?, ?, NULL, 'anonymous')
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
                channel_id,
                published_at,
                profile_id,
            ),
        )

    download_queue.put(job_id)
    log_activity(
        "download",
        "Download queued",
        f"{title or youtube_url} queued from {source_type}.",
        "info",
        channel_id,
    )
    return job_id, True

def update_download_job(job_id, **values):
    if not values:
        return
    allowed = {
        "video_id", "title", "channel_title", "status", "phase", "progress", "speed",
        "eta", "downloaded_bytes", "total_bytes", "output_path", "error",
        "started_at", "finished_at", "channel_id", "published_at", "profile_id",
        "failure_code", "auth_mode",
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


def _download_progress_hook(job_id, progress_ceiling=100.0):
    ceiling = max(1.0, min(100.0, float(progress_ceiling or 100.0)))

    def hook(data):
        status = data.get("status")
        if status == "downloading":
            downloaded = int(data.get("downloaded_bytes") or 0)
            total = int(data.get("total_bytes") or data.get("total_bytes_estimate") or 0)
            raw_progress = (downloaded / total * 100.0) if total else 0.0
            progress = raw_progress * ceiling / 100.0
            speed = data.get("_speed_str") or (
                f"{format_bytes(data.get('speed'))}/s" if data.get("speed") else ""
            )
            eta = data.get("_eta_str") or (
                str(data.get("eta")) + "s" if data.get("eta") is not None else ""
            )
            update_download_job(
                job_id,
                status="downloading",
                phase="Downloading from YouTube",
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
                phase="Merging and processing media",
                progress=ceiling,
                speed="",
                eta="",
                output_path=data.get("filename") or "",
            )
    return hook


def _download_postprocessor_hook(job_id, progress_ceiling=100.0):
    ceiling = max(1.0, min(100.0, float(progress_ceiling or 100.0)))

    def hook(data):
        status = str(data.get("status") or "").lower()
        postprocessor = str(data.get("postprocessor") or "").strip()
        if status in {"started", "processing"}:
            label = "Processing downloaded media"
            if postprocessor:
                label = f"Processing media · {postprocessor}"
            update_download_job(
                job_id,
                status="processing",
                phase=label,
                progress=ceiling,
                speed="",
                eta="",
            )
        elif status == "finished":
            update_download_job(
                job_id,
                status="processing",
                phase="Checking final media",
                progress=ceiling,
                speed="",
                eta="",
            )
    return hook


def _best_thumbnail_url(info):
    thumbnail = str(info.get("thumbnail") or "").strip()
    if thumbnail:
        return thumbnail

    for item in reversed(info.get("thumbnails") or []):
        url = str((item or {}).get("url") or "").strip()
        if url:
            return url
    return ""


def _write_jpeg_variant(image, path, size):
    rendered = ImageOps.fit(
        image.convert("RGB"),
        size,
        method=Image.Resampling.LANCZOS,
    )
    rendered.save(path, format="JPEG", quality=90, optimize=True)


def write_direct_download_series_metadata(info, output_path, write_nfo=True):
    """Write Emby-friendly artwork and optional NFO beside direct downloads."""
    if not output_path:
        return

    channel_dir = Path(output_path).parent
    channel_dir.mkdir(parents=True, exist_ok=True)

    channel_title = (
        info.get("uploader")
        or info.get("channel")
        or "YouTube"
    )
    channel_id = str(info.get("channel_id") or "").strip()
    description = str(info.get("channel_follower_count") or "")
    video_description = str(info.get("description") or "").strip()
    if video_description:
        description = video_description[:2000]

    if write_nfo:
        root = ET.Element("tvshow")
        ET.SubElement(root, "title").text = str(channel_title)
        ET.SubElement(root, "sorttitle").text = str(channel_title)
        ET.SubElement(root, "plot").text = description
        ET.SubElement(root, "studio").text = "YouTube"
        ET.SubElement(root, "genre").text = "YouTube"
        if channel_id:
            unique = ET.SubElement(
                root,
                "uniqueid",
                {"type": "youtube", "default": "true"},
            )
            unique.text = channel_id

        tree = ET.ElementTree(root)
        try:
            ET.indent(tree, space="  ")
        except AttributeError:
            pass
        tree.write(
            channel_dir / "tvshow.nfo",
            encoding="utf-8",
            xml_declaration=True,
        )

    thumbnail_url = _best_thumbnail_url(info)
    if not thumbnail_url:
        return

    response = requests.get(
        thumbnail_url,
        timeout=30,
        headers={"User-Agent": f"youtube-pinchflat-sync/{VERSION}"},
    )
    response.raise_for_status()

    with Image.open(io.BytesIO(response.content)) as image:
        _write_jpeg_variant(image, channel_dir / "fanart.jpg", (1920, 1080))
        _write_jpeg_variant(image, channel_dir / "poster.jpg", (1000, 1500))
        _write_jpeg_variant(image, channel_dir / "banner.jpg", (1920, 480))



def single_download_compatibility_profile():
    value = get_setting("single_download_compatibility_profile", "emby_tv").strip().lower()
    return value if value in {"emby_tv", "automatic"} else "emby_tv"


def single_download_ydl_settings():
    mode = get_setting("single_download_format", "best").strip()
    audio_format = get_setting("single_download_audio_format", "m4a").strip().lower()

    if mode == "audio":
        return {
            "format": "bestaudio/best",
            "postprocessors": [
                {
                    "key": "FFmpegExtractAudio",
                    "preferredcodec": audio_format,
                    "preferredquality": "0",
                }
            ],
        }

    heights = {
        "2160p": 2160,
        "1440p": 1440,
        "1080p": 1080,
        "720p": 720,
        "480p": 480,
        "360p": 360,
    }
    height = heights.get(mode)

    # Prefer streams which are already LG/Emby friendly so the compatibility
    # pass normally only remuxes or converts audio, rather than re-encoding
    # the video.  A final ffmpeg verification pass below guarantees H.264/AAC.
    if single_download_compatibility_profile() == "emby_tv":
        limit = f"[height<={height}]" if height else ""
        return {
            "format": (
                f"bv*[vcodec^=avc1]{limit}+ba[acodec^=mp4a]/"
                f"b[vcodec^=avc1][acodec^=mp4a]{limit}/"
                f"bv*{limit}+ba/b{limit}/best{limit}"
            ),
            "merge_output_format": "mp4",
        }

    if height:
        return {
            "format": f"bestvideo*[height<={height}]+bestaudio/best[height<={height}]/best",
            "merge_output_format": "mp4",
        }
    return {
        "format": "bestvideo*+bestaudio/best",
        "merge_output_format": "mp4",
    }


def _probe_single_download_media(path):
    result = subprocess.run(
        [
            "ffprobe", "-v", "error",
            "-show_entries", "stream=codec_type,codec_name:format=duration",
            "-of", "json", str(path),
        ],
        capture_output=True, text=True, timeout=30, check=True,
    )
    payload = json.loads(result.stdout or "{}")
    video = ""
    audio = ""
    for stream in payload.get("streams") or []:
        kind = str(stream.get("codec_type") or "")
        codec = str(stream.get("codec_name") or "").lower()
        if kind == "video" and not video:
            video = codec
        elif kind == "audio" and not audio:
            audio = codec
    try:
        duration = float((payload.get("format") or {}).get("duration") or 0)
    except (TypeError, ValueError):
        duration = 0.0
    return video, audio, duration


def _probe_single_download_codecs(path):
    video, audio, _duration = _probe_single_download_media(path)
    return video, audio


def resolve_direct_download_output_path(info, ydl, output_dir, current_path=""):
    """Return the final media file after yt-dlp merging/post-processing."""
    candidates = [
        current_path,
        info.get("filepath"),
        info.get("_filename"),
    ]
    for requested in info.get("requested_downloads") or []:
        candidates.extend([requested.get("filepath"), requested.get("filename")])
    try:
        candidates.append(ydl.prepare_filename(info))
    except Exception:
        pass

    ignored_suffixes = {".part", ".json", ".jpg", ".jpeg", ".png", ".webp", ".nfo"}
    for candidate in candidates:
        if not candidate:
            continue
        path = Path(str(candidate))
        if path.exists() and path.is_file() and path.suffix.lower() not in ignored_suffixes:
            return str(path)

    video_id = str(info.get("id") or "").strip()
    if video_id:
        matches = []
        try:
            for path in Path(output_dir).rglob(f"*[{video_id}]*"):
                if not path.is_file() or path.suffix.lower() in ignored_suffixes:
                    continue
                matches.append(path)
        except Exception:
            matches = []
        if matches:
            matches.sort(key=lambda item: item.stat().st_mtime, reverse=True)
            return str(matches[0])

    return str(current_path or "")


def ensure_single_download_emby_compatibility(output_path, job_id=None):
    """Guarantee H.264 + AAC in MP4 for One-time Download video jobs only."""
    path = Path(str(output_path or ""))
    if not path.exists() or single_download_compatibility_profile() != "emby_tv":
        return str(path)

    video_codec, audio_codec, duration = _probe_single_download_media(path)
    video_ok = video_codec == "h264"
    audio_ok = (not audio_codec) or audio_codec == "aac"
    container_ok = path.suffix.lower() == ".mp4"
    if video_ok and audio_ok and container_ok:
        if job_id:
            update_download_job(
                job_id,
                status="processing",
                phase="Direct Play compatible · finalising",
                progress=99.0,
                speed="",
                eta="",
            )
        return str(path)

    final_path = path.with_suffix(".mp4")
    temp_path = final_path.with_name(f".{final_path.stem}.compat-{secrets.token_hex(4)}.mp4")
    command = [
        "ffmpeg", "-y", "-i", str(path),
        "-map", "0:v:0", "-map", "0:a?",
    ]

    if video_ok:
        command += ["-c:v", "copy"]
    else:
        command += [
            "-c:v", "libx264", "-preset", "medium", "-crf", "20",
            "-pix_fmt", "yuv420p",
        ]

    if audio_ok:
        command += ["-c:a", "copy"]
    else:
        command += ["-c:a", "aac", "-b:a", "192k"]

    command += [
        "-map_metadata", "0", "-movflags", "+faststart",
        "-progress", "pipe:1", "-nostats", str(temp_path),
    ]

    if job_id:
        update_download_job(
            job_id,
            status="processing",
            phase="Converting for Emby / Smart TV",
            progress=90.0,
            speed="",
            eta="",
        )

    process = None
    try:
        process = subprocess.Popen(
            command,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            bufsize=1,
        )
        if process.stdout is not None:
            for raw_line in process.stdout:
                line = raw_line.strip()
                if not line or "=" not in line:
                    continue
                key, value = line.split("=", 1)
                if key not in {"out_time_us", "out_time_ms"} or not job_id or duration <= 0:
                    continue
                try:
                    elapsed_us = float(value or 0)
                    # ffmpeg currently reports both out_time_us and out_time_ms
                    # in microseconds on supported builds.  Clamp aggressively so
                    # an unexpected unit cannot push the UI beyond the conversion band.
                    elapsed_seconds = elapsed_us / 1_000_000.0
                    ratio = max(0.0, min(1.0, elapsed_seconds / duration))
                    update_download_job(
                        job_id,
                        status="processing",
                        phase="Converting for Emby / Smart TV",
                        progress=round(90.0 + ratio * 9.0, 2),
                    )
                except (TypeError, ValueError):
                    pass
        stderr = process.stderr.read() if process.stderr is not None else ""
        return_code = process.wait(timeout=7200)
        if return_code != 0:
            raise RuntimeError((stderr or f"ffmpeg exited with code {return_code}")[-1800:])

        if final_path != path and final_path.exists():
            final_path.unlink()
        os.replace(temp_path, final_path)
        if path != final_path and path.exists():
            path.unlink()
        if job_id:
            update_download_job(
                job_id,
                status="processing",
                phase="Compatibility conversion complete",
                progress=99.0,
            )
        return str(final_path)
    finally:
        if process is not None and process.poll() is None:
            try:
                process.kill()
            except Exception:
                pass
        if temp_path.exists():
            temp_path.unlink(missing_ok=True)


def _v3_subscription_info_date(info, fallback=""):
    upload_date = str((info or {}).get("upload_date") or "").strip()
    if re.fullmatch(r"\d{8}", upload_date):
        return f"{upload_date[:4]}-{upload_date[4:6]}-{upload_date[6:8]}"
    timestamp = (info or {}).get("timestamp") or (info or {}).get("release_timestamp")
    if timestamp:
        try:
            return datetime.fromtimestamp(float(timestamp), tz=timezone.utc).date().isoformat()
        except (TypeError, ValueError, OSError):
            pass
    return str(fallback or "")


def _v3_download_with_auth_retry(job, ydl_opts):
    """Run yt-dlp anonymously first and retry with configured auth only when useful."""
    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(job["youtube_url"], download=True)
            return info, ydl, "anonymous"
    except Exception as anonymous_error:
        if not setting_bool("downloader_auth_retry", True):
            raise
        if not should_retry_with_cookies(anonymous_error):
            raise

        status = _v3_cookie_status()
        if not status.get("valid"):
            raise

        update_download_job(
            job["job_id"],
            phase="Retrying with YouTube authentication",
            auth_mode="cookies",
        )
        authenticated = _v3_authenticated_options(ydl_opts)
        with yt_dlp.YoutubeDL(authenticated) as ydl:
            info = ydl.extract_info(job["youtube_url"], download=True)
            return info, ydl, "cookies"


def run_download_job(job_id):
    job = download_job_row(job_id)
    if not job:
        return

    source_type = str(job.get("source_type") or "")
    subscription_job = source_type.startswith("subscription")

    if subscription_job:
        output_dir = DOWNLOAD_ROOT / "shows"
        output_template = _v3_subscription_template()
    else:
        folder_setting = (
            get_setting("emby_download_folder", "Emby Download")
            if source_type == "emby_download"
            else get_setting("single_download_folder", "Single Downloads")
        )
        folder_setting = folder_setting.strip().strip("/\\") or "Single Downloads"
        output_dir = DOWNLOAD_ROOT / folder_setting
        relative_template = (
            get_setting(
                "single_download_output_template",
                "%(uploader,channel|Unknown Channel).80B/%(title).180B [%(id)s].%(ext)s",
            )
            if source_type == "single"
            else "%(uploader,channel|Unknown Channel).80B/%(title).180B [%(id)s].%(ext)s"
        )
        output_template = str(output_dir / relative_template)

    output_dir.mkdir(parents=True, exist_ok=True)

    update_download_job(
        job_id,
        status="downloading",
        phase="Preparing YouTube download",
        started_at=now_iso(),
        error=None,
        failure_code=None,
        progress=0,
        auth_mode="anonymous",
    )

    compatibility_video = (
        source_type == "single"
        and get_setting("single_download_format", "best") != "audio"
        and single_download_compatibility_profile() == "emby_tv"
    )
    download_progress_ceiling = 85.0 if compatibility_video else 100.0

    ydl_opts = {
        "outtmpl": output_template,
        "noplaylist": True,
        "continuedl": True,
        "overwrites": False,
        "writethumbnail": True,
        "writeinfojson": True,
        "embedmetadata": True,
        "embedthumbnail": True,
        "progress_hooks": [_download_progress_hook(job_id, download_progress_ceiling)],
        "postprocessor_hooks": [_download_postprocessor_hook(job_id, download_progress_ceiling)],
        "quiet": True,
        "no_warnings": True,
        "socket_timeout": 30,
    }

    if source_type == "single":
        ydl_opts.update(single_download_ydl_settings())
    elif subscription_job:
        ydl_opts.update(_v3_profile_ydl_options(job.get("profile_id")))
        # Subscription files are the long-term Emby library. Keep the sidecars
        # required for migration/reconciliation even if metadata embedding fails.
        ydl_opts.update({
            "writeinfojson": True,
            "writethumbnail": True,
            "embedmetadata": True,
        })
    else:
        ydl_opts.update({
            "format": "bestvideo*+bestaudio/best",
            "merge_output_format": "mp4",
        })

    # Expert custom options apply to native subscription downloads as well as
    # authenticated retries, but managed path/progress/cookie settings cannot
    # be overridden by the JSON editor.
    if subscription_job:
        ydl_opts.update(_v3_custom_yt_dlp_options())

    try:
        info, ydl, auth_mode = _v3_download_with_auth_retry(job, ydl_opts)

        output_path = ""
        requested = info.get("requested_downloads") or []
        if requested:
            output_path = requested[0].get("filepath") or requested[0].get("filename") or ""
        if not output_path:
            try:
                output_path = ydl.prepare_filename(info)
            except Exception:
                output_path = job.get("output_path") or ""

        output_path = resolve_direct_download_output_path(info, ydl, output_dir, output_path)

        if source_type == "single" and get_setting("single_download_format", "best") != "audio":
            try:
                update_download_job(
                    job_id,
                    status="processing",
                    phase="Checking Emby / Smart TV compatibility",
                    progress=max(download_progress_ceiling, 88.0),
                    speed="",
                    eta="",
                )
                compatible_path = ensure_single_download_emby_compatibility(output_path, job_id=job_id)
                if compatible_path and compatible_path != output_path:
                    log_activity(
                        "download",
                        "One-time Download converted for Emby",
                        f"{info.get('title') or job['youtube_url']} converted to H.264 + AAC in MP4.",
                        "success",
                    )
                output_path = compatible_path or output_path
            except Exception as exc:
                raise RuntimeError(f"Emby compatibility conversion failed: {exc}") from exc

        resolved_channel_id = (
            str(info.get("channel_id") or "").strip()
            or str(job.get("channel_id") or "").strip()
        )
        published_at = _v3_subscription_info_date(info, job.get("published_at"))

        update_download_job(
            job_id,
            video_id=info.get("id") or job.get("video_id"),
            title=info.get("title") or job.get("title"),
            channel_title=(
                info.get("uploader")
                or info.get("channel")
                or job.get("channel_title")
            ),
            channel_id=resolved_channel_id or None,
            published_at=published_at or None,
            status="completed",
            phase="Completed",
            progress=100.0,
            output_path=output_path,
            finished_at=now_iso(),
            error=None,
            failure_code=None,
            auth_mode=auth_mode,
        )

        if source_type in {"single", "emby_download"} or subscription_job:
            try:
                write_direct_download_series_metadata(
                    info,
                    output_path,
                    write_nfo=(
                        setting_bool("single_download_write_nfo", True)
                        if source_type == "single"
                        else True
                    ),
                )
            except Exception as exc:
                log_activity(
                    "download_metadata",
                    "Download metadata warning",
                    f"{info.get('title') or job['youtube_url']}: {exc}",
                    "warning",
                    resolved_channel_id or None,
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
                resolved_channel_id or None,
            )

        storage_snapshot(force=True)

        if emby_configured():
            try:
                if source_type == "single":
                    direct_folder = get_setting("single_download_folder", "Single Downloads")
                    direct_label = "One-time Download"
                    emby_refresh_download_library(direct_folder, direct_label)
                elif source_type == "emby_download":
                    direct_folder = get_setting("emby_download_folder", "Emby Download")
                    direct_label = "Emby Download"
                    emby_refresh_download_library(direct_folder, direct_label)
                elif subscription_job:
                    direct_label = "Subscription Download"
                    emby_refresh_library(
                        channel_id=resolved_channel_id,
                        channel_title=info.get("uploader") or info.get("channel") or job.get("channel_title") or "",
                    )
                log_activity(
                    "emby",
                    f"{direct_label} refresh queued",
                    f"Queued the targeted Emby scan and metadata refresh after {info.get('title') or job['youtube_url']} completed.",
                    "success",
                    resolved_channel_id or None,
                )
            except Exception as exc:
                log_activity(
                    "emby",
                    "Emby refresh failed",
                    f"{info.get('title') or job['youtube_url']}: {exc}",
                    "warning",
                    resolved_channel_id or None,
                )

    except Exception as exc:
        failure_code = classify_yt_dlp_error(exc)
        update_download_job(
            job_id,
            status="failed",
            phase={
                "membership_required": "Membership required",
                "age_restricted": "Age restricted",
                "authentication_required": "Authentication required",
                "rate_limited": "YouTube rate limited",
                "private": "Private video",
                "unavailable": "Unavailable",
            }.get(failure_code, "Failed"),
            failure_code=failure_code,
            error=str(exc)[:1500],
            finished_at=now_iso(),
        )
        log_activity(
            "download",
            "Download failed",
            f"{job.get('title') or job['youtube_url']}: {exc}",
            "error",
            job.get("channel_id"),
        )

def download_worker():
    while True:
        job_id = download_queue.get()
        try:
            run_download_job(job_id)
        finally:
            download_queue.task_done()


def start_download_worker():
    global download_worker_started, download_worker_count

    desired = setting_int("downloader_worker_concurrency", 1, 1, 8)

    if not download_worker_started:
        download_worker_started = True
        with db() as conn:
            conn.execute(
                """
                UPDATE downloads
                SET status = 'queued', phase = 'Queued', started_at = NULL
                WHERE status IN ('downloading', 'processing')
                """
            )
            queued = conn.execute(
                "SELECT job_id FROM downloads WHERE status = 'queued' ORDER BY id ASC"
            ).fetchall()
        for row in queued:
            download_queue.put(row["job_id"])

    # Existing worker threads are intentionally not killed when concurrency is
    # lowered. They drain naturally; a container restart applies a lower limit
    # immediately. Increasing concurrency takes effect without a restart.
    while download_worker_count < desired:
        download_worker_count += 1
        thread = threading.Thread(
            target=download_worker,
            name=f"youtube-download-worker-{download_worker_count}",
            daemon=True,
        )
        thread.start()

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


def current_user_id():
    user = current_user_record()
    if not user:
        return None
    return int(user["id"])


def favourite_channel_ids(user_id=None):
    user_id = user_id or current_user_id()
    if not user_id:
        return set()
    with db() as conn:
        rows = conn.execute(
            "SELECT channel_id FROM favourite_channels WHERE user_id = ?",
            (user_id,),
        ).fetchall()
    return {row["channel_id"] for row in rows}


def all_favourite_channel_ids():
    """Return channel favourites across users for server-wide storage policies."""
    with db() as conn:
        rows = conn.execute("SELECT DISTINCT channel_id FROM favourite_channels").fetchall()
    return {row["channel_id"] for row in rows if row["channel_id"]}


def set_channel_favourite_state(channel_id, favourite, user_id=None):
    user_id = user_id or current_user_id()
    channel_id = str(channel_id or "").strip()

    if not user_id or not channel_id:
        raise RuntimeError("Channel information is missing.")

    with db() as conn:
        existing = conn.execute(
            "SELECT 1 FROM favourite_channels WHERE user_id = ? AND channel_id = ?",
            (user_id, channel_id),
        ).fetchone()

        if favourite:
            if not existing:
                sub = conn.execute(
                    "SELECT title, channel_url, thumbnail_url FROM subscriptions WHERE channel_id = ?",
                    (channel_id,),
                ).fetchone()

                title = str(
                    (sub["title"] if sub else None)
                    or "YouTube channel"
                ).strip()
                url = str(
                    (sub["channel_url"] if sub else None)
                    or f"https://www.youtube.com/channel/{channel_id}"
                ).strip()
                thumb = str(
                    (sub["thumbnail_url"] if sub else None)
                    or ""
                ).strip()

                conn.execute(
                    """
                    INSERT INTO favourite_channels (
                        user_id, channel_id, channel_title, channel_url,
                        thumbnail_url, created_at
                    ) VALUES (?, ?, ?, ?, ?, ?)
                    """,
                    (
                        user_id,
                        channel_id,
                        title[:300],
                        url,
                        thumb,
                        now_iso(),
                    ),
                )
        elif existing:
            conn.execute(
                "DELETE FROM favourite_channels WHERE user_id = ? AND channel_id = ?",
                (user_id, channel_id),
            )

    return bool(favourite)


def favourite_video_ids(user_id=None):
    user_id = user_id or current_user_id()
    if not user_id:
        return set()
    with db() as conn:
        rows = conn.execute(
            "SELECT video_id FROM saved_videos WHERE user_id = ? AND favourite = 1",
            (user_id,),
        ).fetchall()
    return {row["video_id"] for row in rows}


def all_favourite_video_ids():
    """Return favourite videos across users for server-wide storage policies."""
    with db() as conn:
        rows = conn.execute(
            "SELECT DISTINCT video_id FROM saved_videos WHERE favourite = 1"
        ).fetchall()
    return {row["video_id"] for row in rows if row["video_id"]}


def annotate_favourites(items, user_id=None):
    user_id = user_id or current_user_id()
    channel_ids = favourite_channel_ids(user_id)
    video_ids = favourite_video_ids(user_id)
    with db() as conn:
        subscribed_ids = {
            row["channel_id"]
            for row in conn.execute(
                "SELECT channel_id FROM subscriptions WHERE active = 1"
            ).fetchall()
        }
    annotated = []
    for item in items or []:
        row = dict(item)
        row["is_favourite_channel"] = row.get("channel_id") in channel_ids
        row["is_favourite_video"] = row.get("video_id") in video_ids
        row["is_subscribed"] = row.get("channel_id") in subscribed_ids
        annotated.append(row)
    return annotated


def normalise_saved_video(payload):
    video_id = str(payload.get("video_id") or "").strip()
    if not video_id:
        raise RuntimeError("A YouTube video ID is required.")
    video_url = str(payload.get("video_url") or "").strip()
    if not video_url:
        video_url = f"https://www.youtube.com/watch?v={video_id}"
    return {
        "video_id": video_id,
        "title": str(payload.get("title") or "YouTube video").strip()[:500],
        "channel_id": str(payload.get("channel_id") or "").strip(),
        "channel_title": str(payload.get("channel_title") or "YouTube").strip()[:300],
        "video_url": video_url,
        "thumbnail_url": str(payload.get("thumbnail_url") or "").strip(),
    }


def upsert_saved_video(user_id, payload, favourite=None):
    item = normalise_saved_video(payload)
    now = now_iso()
    with db() as conn:
        existing = conn.execute(
            "SELECT * FROM saved_videos WHERE user_id = ? AND video_id = ?",
            (user_id, item["video_id"]),
        ).fetchone()
        if existing:
            new_favourite = int(existing["favourite"] or 0) if favourite is None else (1 if favourite else 0)
            conn.execute(
                """
                UPDATE saved_videos
                SET title = ?, channel_id = ?, channel_title = ?, video_url = ?,
                    thumbnail_url = ?, favourite = ?, updated_at = ?
                WHERE user_id = ? AND video_id = ?
                """,
                (
                    item["title"], item["channel_id"], item["channel_title"],
                    item["video_url"], item["thumbnail_url"], new_favourite,
                    now, user_id, item["video_id"],
                ),
            )
        else:
            conn.execute(
                """
                INSERT INTO saved_videos (
                    user_id, video_id, title, channel_id, channel_title,
                    video_url, thumbnail_url, favourite, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    user_id, item["video_id"], item["title"], item["channel_id"],
                    item["channel_title"], item["video_url"], item["thumbnail_url"],
                    1 if favourite is not False else 0, now, now,
                ),
            )
        saved = conn.execute(
            "SELECT * FROM saved_videos WHERE user_id = ? AND video_id = ?",
            (user_id, item["video_id"]),
        ).fetchone()
    return dict(saved)


def youtube_subscribe(channel_id):
    creds = load_credentials()
    if not creds:
        raise RuntimeError("Google account is not connected.")
    if not google_write_scope_ready(creds):
        raise RuntimeError("Reconnect Google to grant permission to subscribe to channels.")
    response = youtube_api_request(
        creds,
        "POST",
        "subscriptions",
        "subscriptions.insert",
        50,
        params={"part": "snippet"},
        json={
            "snippet": {
                "resourceId": {
                    "kind": "youtube#channel",
                    "channelId": channel_id,
                }
            }
        },
    )
    return response.json()


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


def current_youtube_sync_interval():
    return setting_int(
        "youtube_sync_interval_minutes",
        setting_int("sync_interval_minutes", SYNC_INTERVAL_MINUTES, 5, 1440),
        5,
        1440,
    )


def current_pinchflat_sync_interval():
    return setting_int(
        "pinchflat_sync_interval_minutes",
        setting_int("sync_interval_minutes", SYNC_INTERVAL_MINUTES, 5, 1440),
        5,
        1440,
    )


PINCHFLAT_FORCE_INDEX_FAVOURITE_OPTIONS = (
    (0, "Off"),
    (15, "Every 15 minutes"),
    (30, "Every 30 minutes"),
    (60, "Every hour"),
    (120, "Every 2 hours"),
    (180, "Every 3 hours"),
    (360, "Every 6 hours"),
    (720, "Every 12 hours"),
    (1440, "Every 24 hours"),
)
PINCHFLAT_FORCE_INDEX_NONFAVOURITE_OPTIONS = (
    (0, "Off"),
    (180, "Every 3 hours"),
    (360, "Every 6 hours"),
    (720, "Every 12 hours"),
    (1440, "Every 24 hours"),
    (2880, "Every 2 days"),
    (4320, "Every 3 days"),
    (10080, "Every 7 days"),
)
PINCHFLAT_FORCE_INDEX_FAVOURITE_VALUES = {value for value, _label in PINCHFLAT_FORCE_INDEX_FAVOURITE_OPTIONS}
PINCHFLAT_FORCE_INDEX_NONFAVOURITE_VALUES = {value for value, _label in PINCHFLAT_FORCE_INDEX_NONFAVOURITE_OPTIONS}


def current_pinchflat_force_index_interval(favourite=False):
    key = (
        "pinchflat_force_index_favourite_minutes"
        if favourite
        else "pinchflat_force_index_nonfavourite_minutes"
    )
    allowed = (
        PINCHFLAT_FORCE_INDEX_FAVOURITE_VALUES
        if favourite
        else PINCHFLAT_FORCE_INDEX_NONFAVOURITE_VALUES
    )
    try:
        value = int(get_setting(key, "0") or 0)
    except (TypeError, ValueError):
        value = 0
    return value if value in allowed else 0


def _pinchflat_force_index_group_rows(favourite=False):
    favourite_clause = "f.channel_id IS NOT NULL" if favourite else "f.channel_id IS NULL"
    with db() as conn:
        return [
            dict(row)
            for row in conn.execute(
                f"""
                SELECT
                    s.channel_id,
                    s.title,
                    s.pinchflat_source_id,
                    COALESCE(fi.last_forced_at, 0) AS last_forced_at,
                    fi.last_status,
                    fi.last_error
                FROM subscriptions s
                LEFT JOIN (
                    SELECT DISTINCT channel_id
                    FROM favourite_channels
                ) f ON f.channel_id = s.channel_id
                LEFT JOIN pinchflat_force_index_state fi
                    ON fi.channel_id = s.channel_id
                WHERE s.active = 1
                  AND s.download_enabled = 1
                  AND s.pinchflat_added = 1
                  AND s.pinchflat_source_id IS NOT NULL
                  AND TRIM(s.pinchflat_source_id) != ''
                  AND {favourite_clause}
                ORDER BY
                    COALESCE(fi.last_forced_at, 0) ASC,
                    LOWER(COALESCE(s.title, '')) ASC
                """
            ).fetchall()
        ]


def pinchflat_force_index_status():
    favourite_rows = _pinchflat_force_index_group_rows(True)
    other_rows = _pinchflat_force_index_group_rows(False)

    def summarise(rows):
        completed = [float(row.get("last_forced_at") or 0) for row in rows if float(row.get("last_forced_at") or 0) > 0]
        last_ts = max(completed) if completed else 0
        return {
            "eligible": len(rows),
            "last_forced_at": (
                datetime.fromtimestamp(last_ts, timezone.utc).isoformat()
                if last_ts
                else ""
            ),
        }

    return {
        "favourites": summarise(favourite_rows),
        "non_favourites": summarise(other_rows),
    }


def _record_pinchflat_force_index_result(row, ok, error=""):
    now_ts = time.time()
    with db() as conn:
        conn.execute(
            """
            INSERT INTO pinchflat_force_index_state (
                channel_id, source_id, last_forced_at, last_status, last_error, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?)
            ON CONFLICT(channel_id) DO UPDATE SET
                source_id = excluded.source_id,
                last_forced_at = excluded.last_forced_at,
                last_status = excluded.last_status,
                last_error = excluded.last_error,
                updated_at = excluded.updated_at
            """,
            (
                row.get("channel_id", ""),
                str(row.get("pinchflat_source_id") or ""),
                now_ts,
                "ok" if ok else "error",
                "" if ok else str(error)[:1000],
                now_iso(),
            ),
        )


def _scheduled_pinchflat_force_index_group(favourite=False):
    interval_minutes = current_pinchflat_force_index_interval(favourite)
    if interval_minutes <= 0:
        return {"enabled": False, "eligible": 0, "processed": 0, "errors": 0}

    rows = _pinchflat_force_index_group_rows(favourite)
    total = len(rows)
    if not total:
        return {"enabled": True, "eligible": 0, "processed": 0, "errors": 0}

    now_ts = time.time()
    due_before = now_ts - (interval_minutes * 60)
    due_rows = [
        row
        for row in rows
        if float(row.get("last_forced_at") or 0) <= due_before
    ]
    if not due_rows:
        return {"enabled": True, "eligible": total, "processed": 0, "errors": 0}

    # Spread a complete sweep across the requested interval instead of firing
    # every source together. The cap keeps a large library from causing a
    # sudden burst of Pinchflat/YouTube requests.
    target_per_minute = max(1, (total + interval_minutes - 1) // interval_minutes)
    target_per_minute = min(target_per_minute, 8)
    batch = due_rows[:target_per_minute]

    processed = 0
    errors = 0
    for index, row in enumerate(batch):
        try:
            with pinchflat_source_action_lock:
                execute_pinchflat_source_action(
                    row.get("pinchflat_source_id"),
                    "force_scan",
                )
            _record_pinchflat_force_index_result(row, True)
            processed += 1
        except Exception as exc:
            _record_pinchflat_force_index_result(row, False, str(exc))
            errors += 1
            log_activity(
                "pinchflat",
                "Scheduled Force Index failed",
                f"{row.get('title') or row.get('channel_id')}: {exc}",
                "error",
            )

        if index < len(batch) - 1:
            time.sleep(2)

    return {
        "enabled": True,
        "eligible": total,
        "processed": processed,
        "errors": errors,
    }


def scheduled_pinchflat_force_index():
    if (
        current_pinchflat_force_index_interval(True) <= 0
        and current_pinchflat_force_index_interval(False) <= 0
    ):
        return

    if not pinchflat_health():
        return

    _scheduled_pinchflat_force_index_group(True)
    _scheduled_pinchflat_force_index_group(False)


RETENTION_DAY_OPTIONS = (
    (0, "Keep forever"),
    (30, "30 days"),
    (60, "60 days"),
    (90, "3 months"),
    (180, "6 months"),
    (270, "9 months"),
    (365, "1 year"),
    (730, "2 years"),
    (1095, "3 years"),
)
RETENTION_CLEANUP_INTERVAL_OPTIONS = (
    (24, "Daily"),
    (72, "Every 3 days"),
    (168, "Weekly"),
)


def retention_settings():
    return {
        "enabled": setting_bool("retention_enabled", False),
        "favourite_days": setting_int("retention_favourite_days", 365, 0, 3650),
        "favourite_min_videos": setting_int("retention_favourite_min_videos", 20, 0, 10000),
        "nonfavourite_days": setting_int("retention_nonfavourite_days", 90, 0, 3650),
        "nonfavourite_min_videos": setting_int("retention_nonfavourite_min_videos", 5, 0, 10000),
        "grace_days": setting_int("retention_grace_days", 7, 0, 365),
        "cleanup_interval_hours": setting_int("retention_cleanup_interval_hours", 24, 1, 744),
        "protect_favourite_videos": setting_bool("retention_protect_favourite_videos", True),
        "last_run_at": get_setting("retention_last_run_at", "").strip(),
    }


def retention_override(channel_id):
    channel_id = str(channel_id or "").strip()
    if not channel_id:
        return None
    with db() as conn:
        row = conn.execute(
            "SELECT * FROM video_retention_overrides WHERE channel_id = ? LIMIT 1",
            (channel_id,),
        ).fetchone()
    return dict(row) if row else None


def retention_policy_for_channel(channel_id, favourite=None):
    settings = retention_settings()
    channel_id = str(channel_id or "").strip()
    if favourite is None:
        favourite = channel_id in all_favourite_channel_ids()
    override = retention_override(channel_id)
    if override:
        days = int(override.get("retention_days") or 0)
        minimum = int(override.get("minimum_videos") or 0)
        source = "Channel override"
    elif favourite:
        days = int(settings["favourite_days"] or 0)
        minimum = int(settings["favourite_min_videos"] or 0)
        source = "Favourite channel policy"
    else:
        days = int(settings["nonfavourite_days"] or 0)
        minimum = int(settings["nonfavourite_min_videos"] or 0)
        source = "Non-favourite channel policy"
    return {
        "enabled": bool(settings["enabled"]),
        "days": max(0, days),
        "minimum_videos": max(0, minimum),
        "source": source,
        "override": bool(override),
        "favourite": bool(favourite),
    }


def retention_days_label(days):
    try:
        days = int(days)
    except (TypeError, ValueError):
        days = 0
    if days <= 0:
        return "Keep forever"
    if days == 365:
        return "1 year"
    if days % 365 == 0:
        years = days // 365
        return f"{years} years"
    if days == 30:
        return "30 days"
    if days == 60:
        return "60 days"
    if days % 30 == 0:
        months = days // 30
        return f"{months} month" + ("" if months == 1 else "s")
    return f"{days} days"


def _retention_datetime(value):
    value = str(value or "").strip()
    if not value:
        return None
    candidates = [value]
    if len(value) == 8 and value.isdigit():
        candidates.insert(0, f"{value[:4]}-{value[4:6]}-{value[6:8]}")
    for candidate in candidates:
        try:
            parsed = datetime.fromisoformat(candidate.replace("Z", "+00:00"))
            if parsed.tzinfo is None:
                parsed = parsed.replace(tzinfo=timezone.utc)
            return parsed.astimezone(timezone.utc)
        except (TypeError, ValueError):
            try:
                parsed_date = date.fromisoformat(candidate[:10])
                return datetime.combine(parsed_date, datetime.min.time(), tzinfo=timezone.utc)
            except (TypeError, ValueError):
                continue
    return None


def _retention_subtitle_paths(value):
    if not value:
        return []
    data = value
    if isinstance(value, str):
        try:
            data = json.loads(value)
        except Exception:
            return []
    paths = []
    if isinstance(data, (list, tuple)):
        for item in data:
            if isinstance(item, (list, tuple)) and len(item) >= 2:
                paths.append(item[-1])
            elif isinstance(item, str):
                paths.append(item)
    return [str(path) for path in paths if path]


def _retention_media_paths(media):
    values = []
    for field in (
        "media_filepath", "filepath", "file_path", "thumbnail_filepath",
        "metadata_filepath", "nfo_filepath",
    ):
        value = media.get(field)
        if value:
            values.append(str(value))
    values.extend(_retention_subtitle_paths(media.get("subtitle_filepaths")))
    seen = set()
    result = []
    for value in values:
        path = pinchflat_shared_download_path(value)
        if path is None:
            continue
        key = str(path)
        if key in seen:
            continue
        seen.add(key)
        result.append(path)
    return result


def _retention_media_size(media):
    total = 0
    for path in _retention_media_paths(media):
        try:
            if path.is_file():
                total += int(path.stat().st_size)
        except OSError:
            pass
    if total <= 0:
        try:
            total = int(media.get("media_size_bytes") or 0)
        except (TypeError, ValueError):
            total = 0
    return max(0, total)


def pinchflat_retention_inventory(channel_id=""):
    """Return downloaded Pinchflat media with source and on-disk metadata."""
    requested_channel_id = str(channel_id or "").strip()
    conn = pinchflat_db_readonly()
    if conn is None:
        return []
    try:
        tables = pinchflat_table_names(conn)
        if "media_items" not in tables:
            return []
        media_columns = pinchflat_table_columns(conn, "media_items")
        source_columns = pinchflat_table_columns(conn, "sources") if "sources" in tables else set()
        filepath_column = next(
            (name for name in ("media_filepath", "filepath", "file_path") if name in media_columns),
            None,
        )
        if not filepath_column:
            return []
        wanted_media = [
            name for name in (
                "id", "uuid", "title", "media_id", "youtube_id", "youtube_video_id",
                "video_id", "original_url", "webpage_url", "url", "media_url", "source_id",
                "media_filepath", "filepath", "file_path", "thumbnail_filepath",
                "metadata_filepath", "nfo_filepath", "subtitle_filepaths", "media_size_bytes",
                "uploaded_at", "upload_date", "media_downloaded_at", "downloaded_at",
                "inserted_at", "updated_at", "prevent_download", "prevent_culling", "culled_at",
            ) if name in media_columns
        ]
        query = (
            f"SELECT {', '.join(wanted_media)} FROM media_items "
            f"WHERE {filepath_column} IS NOT NULL AND TRIM({filepath_column}) != ''"
        )
        rows = conn.execute(query).fetchall()
        media_rows = [dict(row) for row in rows]
        source_ids = {int(row["source_id"]) for row in media_rows if row.get("source_id") not in (None, "")}
        source_map = {}
        if source_ids and source_columns:
            wanted_source = [
                name for name in (
                    "id", "custom_name", "collection_name", "collection_id", "original_url", "collection_type"
                ) if name in source_columns
            ]
            placeholders = ",".join("?" for _ in source_ids)
            source_rows = conn.execute(
                f"SELECT {', '.join(wanted_source)} FROM sources WHERE id IN ({placeholders})",
                tuple(sorted(source_ids)),
            ).fetchall()
            source_map = {int(row["id"]): dict(row) for row in source_rows}
        result = []
        for media in media_rows:
            # Skip media already marked not to download. Pinchflat's native
            # Prevent Automatic Deletion flag stays in the inventory so the
            # preview can count it as protected rather than silently hiding it.
            if bool(media.get("prevent_download")):
                continue
            source = {}
            try:
                if media.get("source_id") not in (None, ""):
                    source = source_map.get(int(media["source_id"]), {})
            except Exception:
                source = {}
            channel_id = str(source.get("collection_id") or "").strip()
            if not channel_id:
                continue
            if requested_channel_id and channel_id != requested_channel_id:
                continue
            paths = _retention_media_paths(media)
            if not any(path.exists() for path in paths):
                continue
            uploaded = _retention_datetime(
                pinchflat_row_value(media, "uploaded_at", "upload_date")
            )
            downloaded = _retention_datetime(
                pinchflat_row_value(media, "media_downloaded_at", "downloaded_at", "updated_at", "inserted_at")
            )
            video_id = pinchflat_extract_youtube_id(media)
            result.append({
                "media_item_id": int(media.get("id") or 0),
                "media_uuid": str(media.get("uuid") or ""),
                "video_id": video_id,
                "title": str(media.get("title") or "YouTube video"),
                "channel_id": channel_id,
                "channel_title": str(source.get("custom_name") or source.get("collection_name") or channel_id),
                "source_id": str(media.get("source_id") or ""),
                "prevent_culling": bool(media.get("prevent_culling")),
                "uploaded_at": uploaded,
                "downloaded_at": downloaded,
                "size_bytes": _retention_media_size(media),
                "thumbnail_url": f"https://i.ytimg.com/vi/{video_id}/hqdefault.jpg" if video_id else "",
                "video_url": f"https://www.youtube.com/watch?v={video_id}" if video_id else str(media.get("original_url") or ""),
            })
        return result
    finally:
        conn.close()


def retention_protected_video_ids():
    with db() as conn:
        rows = conn.execute("SELECT video_id FROM retention_protected_videos").fetchall()
    return {str(row["video_id"]) for row in rows if row["video_id"]}


def retention_preview(channel_id="", limit=250):
    settings = retention_settings()
    now = datetime.now(timezone.utc)
    grace_before = now - timedelta(days=int(settings["grace_days"] or 0))
    favourite_channels = all_favourite_channel_ids()
    favourite_videos = all_favourite_video_ids() if settings["protect_favourite_videos"] else set()
    protected_videos = retention_protected_video_ids()
    inventory = pinchflat_retention_inventory(channel_id=channel_id)

    grouped = {}
    for item in inventory:
        grouped.setdefault(item["channel_id"], []).append(item)

    candidates = []
    protected_count = 0
    protected_bytes = 0
    unknown_date_count = 0
    minimum_kept_count = 0
    keep_forever_count = 0
    channel_summaries = []

    for cid, items in grouped.items():
        favourite = cid in favourite_channels
        policy = retention_policy_for_channel(cid, favourite=favourite)
        sorted_items = sorted(
            items,
            key=lambda item: item.get("uploaded_at") or item.get("downloaded_at") or datetime.min.replace(tzinfo=timezone.utc),
            reverse=True,
        )
        minimum_ids = {
            item.get("media_item_id")
            for item in sorted_items[: int(policy["minimum_videos"] or 0)]
        }
        cutoff = now - timedelta(days=policy["days"]) if policy["days"] > 0 else None
        channel_candidates = []
        for item in sorted_items:
            # Preview remains useful while automatic retention is disabled.
            # The actual cleanup endpoint still refuses to delete until the
            # master retention switch is enabled.
            if policy["days"] <= 0:
                keep_forever_count += 1
                continue
            if item.get("prevent_culling"):
                protected_count += 1
                protected_bytes += int(item.get("size_bytes") or 0)
                continue
            if item.get("video_id") and item["video_id"] in protected_videos:
                protected_count += 1
                protected_bytes += int(item.get("size_bytes") or 0)
                continue
            if item.get("video_id") and item["video_id"] in favourite_videos:
                protected_count += 1
                protected_bytes += int(item.get("size_bytes") or 0)
                continue
            if item.get("media_item_id") in minimum_ids:
                minimum_kept_count += 1
                continue
            if not item.get("uploaded_at"):
                unknown_date_count += 1
                continue
            if item["uploaded_at"] >= cutoff:
                continue
            if item.get("downloaded_at") and item["downloaded_at"] > grace_before:
                continue
            age_days = max(0, (now - item["uploaded_at"]).days)
            item = dict(item)
            item.update({
                "age_days": age_days,
                "policy_days": policy["days"],
                "minimum_videos": policy["minimum_videos"],
                "policy_source": policy["source"],
                "policy_label": retention_days_label(policy["days"]),
                "reason": f"Published {age_days} days ago; policy keeps {retention_days_label(policy['days'])}",
                "uploaded_at_text": item["uploaded_at"].date().isoformat(),
                "downloaded_at_text": item["downloaded_at"].date().isoformat() if item.get("downloaded_at") else "",
                "size_text": format_bytes(item.get("size_bytes") or 0),
            })
            candidates.append(item)
            channel_candidates.append(item)
        if sorted_items:
            channel_summaries.append({
                "channel_id": cid,
                "channel_title": sorted_items[0].get("channel_title") or cid,
                "favourite": favourite,
                "policy_days": policy["days"],
                "policy_label": retention_days_label(policy["days"]),
                "minimum_videos": policy["minimum_videos"],
                "policy_source": policy["source"],
                "stored": len(sorted_items),
                "eligible": len(channel_candidates),
                "reclaimable_bytes": sum(int(item.get("size_bytes") or 0) for item in channel_candidates),
            })

    candidates.sort(key=lambda item: item.get("uploaded_at") or datetime.min.replace(tzinfo=timezone.utc))
    total_bytes = sum(int(item.get("size_bytes") or 0) for item in candidates)
    result_candidates = candidates if limit is None or limit < 0 else candidates[: max(0, int(limit))]
    return {
        "enabled": bool(settings["enabled"]),
        "candidate_count": len(candidates),
        "candidate_bytes": total_bytes,
        "candidate_size": format_bytes(total_bytes),
        "protected_count": protected_count,
        "protected_bytes": protected_bytes,
        "protected_size": format_bytes(protected_bytes),
        "unknown_date_count": unknown_date_count,
        "minimum_kept_count": minimum_kept_count,
        "keep_forever_count": keep_forever_count,
        "channels_affected": sum(1 for row in channel_summaries if row["eligible"] > 0),
        "inventory_count": len(inventory),
        "candidates": result_candidates,
        "channels": sorted(channel_summaries, key=lambda row: (-row["eligible"], row["channel_title"].casefold())),
    }


def _retention_delete_media_batch(media_ids):
    media_ids = [int(value) for value in media_ids if int(value or 0) > 0]
    if not media_ids:
        return {"deleted": [], "errors": {}}
    ids_literal = "[" + ",".join(str(value) for value in media_ids) + "]"
    expression = (
        f"ids = {ids_literal}\n"
        "Enum.each(ids, fn id ->\n"
        "  try do\n"
        "    item = Pinchflat.Media.get_media_item!(id)\n"
        "    case Pinchflat.Media.delete_media_files(item, %{prevent_download: true}) do\n"
        "      {:ok, _} -> IO.puts(\"RETENTION_DELETED=\" <> Integer.to_string(id))\n"
        "      other -> IO.puts(\"RETENTION_ERROR=\" <> Integer.to_string(id) <> \"|\" <> inspect(other))\n"
        "    end\n"
        "  rescue\n"
        "    error -> IO.puts(\"RETENTION_ERROR=\" <> Integer.to_string(id) <> \"|\" <> Exception.message(error))\n"
        "  end\n"
        "end)\n"
    )
    output = docker_exec_in_pinchflat(["bin/pinchflat", "rpc", expression], timeout=300)
    deleted = [int(value) for value in re.findall(r"RETENTION_DELETED=(\d+)", output)]
    errors = {}
    for match in re.finditer(r"RETENTION_ERROR=(\d+)\|([^\r\n]+)", output):
        errors[int(match.group(1))] = match.group(2)[:500]
    return {"deleted": deleted, "errors": errors, "output": output}


def run_retention_cleanup(trigger="manual"):
    if not retention_cleanup_lock.acquire(blocking=False):
        return {"ok": False, "message": "A video retention cleanup is already running."}
    run_id = None
    try:
        settings = retention_settings()
        if not settings["enabled"]:
            return {"ok": False, "message": "Video retention is disabled."}
        preview = retention_preview(limit=-1)
        with db() as conn:
            cursor = conn.execute(
                "INSERT INTO retention_runs (started_at, status, candidate_count, message) VALUES (?, 'running', ?, ?)",
                (now_iso(), int(preview["candidate_count"]), f"Started by {trigger}."),
            )
            run_id = cursor.lastrowid
        candidates = preview["candidates"]
        deleted_ids = set()
        error_map = {}
        for offset in range(0, len(candidates), 25):
            batch = candidates[offset: offset + 25]
            result = _retention_delete_media_batch([item["media_item_id"] for item in batch])
            deleted_ids.update(result["deleted"])
            error_map.update(result["errors"])
            if offset + 25 < len(candidates):
                time.sleep(1)
        deleted_items = [item for item in candidates if item["media_item_id"] in deleted_ids]
        reclaimed = sum(int(item.get("size_bytes") or 0) for item in deleted_items)
        with db() as conn:
            for item in deleted_items:
                conn.execute(
                    """
                    INSERT INTO retention_deletions (
                        deleted_at, video_id, media_item_id, channel_id, channel_title,
                        title, size_bytes, reason
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        now_iso(), item.get("video_id") or "", item.get("media_item_id"),
                        item.get("channel_id") or "", item.get("channel_title") or "",
                        item.get("title") or "", int(item.get("size_bytes") or 0), item.get("reason") or "",
                    ),
                )
            status = "completed_with_errors" if error_map else "completed"
            message = (
                f"Removed {len(deleted_items)} video(s) and reclaimed {format_bytes(reclaimed)}."
                + (f" {len(error_map)} item(s) could not be removed." if error_map else "")
            )
            conn.execute(
                """
                UPDATE retention_runs
                SET finished_at = ?, status = ?, deleted_count = ?, reclaimed_bytes = ?, errors = ?, message = ?
                WHERE id = ?
                """,
                (now_iso(), status, len(deleted_items), reclaimed, len(error_map), message, run_id),
            )
        set_setting("retention_last_run_at", now_iso())
        with storage_cache_lock:
            storage_cache["updated_at"] = 0.0
        if deleted_items and emby_configured():
            try:
                emby_refresh_library()
            except Exception as exc:
                log_activity("retention", "Emby refresh after retention failed", str(exc), "error")
        log_activity(
            "retention",
            "Video retention cleanup",
            message,
            "warning" if error_map else "success",
        )
        return {
            "ok": not bool(error_map),
            "message": message,
            "deleted_count": len(deleted_items),
            "reclaimed_bytes": reclaimed,
            "reclaimed_size": format_bytes(reclaimed),
            "errors": len(error_map),
        }
    except Exception as exc:
        if run_id:
            with db() as conn:
                conn.execute(
                    "UPDATE retention_runs SET finished_at = ?, status = 'failed', errors = 1, message = ? WHERE id = ?",
                    (now_iso(), str(exc)[:1000], run_id),
                )
        log_activity("retention", "Video retention cleanup failed", str(exc), "error")
        return {"ok": False, "message": f"Video retention cleanup failed: {exc}"}
    finally:
        retention_cleanup_lock.release()


def retention_cleanup_due():
    settings = retention_settings()
    if not settings["enabled"]:
        return False
    last_run = _retention_datetime(settings.get("last_run_at"))
    if last_run is None:
        return True
    due_at = last_run + timedelta(hours=int(settings["cleanup_interval_hours"] or 24))
    return datetime.now(timezone.utc) >= due_at


def scheduled_retention_cleanup():
    if not retention_cleanup_due() or retention_cleanup_lock.locked():
        return
    run_retention_cleanup(trigger="scheduled")


def retention_channel_summary(channel_id):
    policy = retention_policy_for_channel(channel_id)
    preview = retention_preview(channel_id=channel_id, limit=0)
    return {
        **policy,
        "label": retention_days_label(policy["days"]),
        "stored": int(preview.get("inventory_count") or 0),
        "eligible": int(preview.get("candidate_count") or 0),
        "reclaimable_bytes": int(preview.get("candidate_bytes") or 0),
        "reclaimable_size": preview.get("candidate_size") or "0 B",
    }


def current_sync_interval():
    # Backwards-compatible alias for older code and settings.
    return current_youtube_sync_interval()


def current_emby_poll_interval():
    """Return the configured Emby Download playlist polling interval."""
    return setting_int("emby_download_poll_minutes", 5, 1, 1440)


def new_subscription_policy():
    value = get_setting("new_subscription_policy", "auto_enable").strip()
    if value == "review":
        value = "disabled"
    if value not in {"auto_enable", "disabled"}:
        return "auto_enable"
    return value


def unsubscribe_policy():
    value = get_setting("unsubscribe_policy", "keep").strip()
    if value not in {"keep", "disable", "remove", "remove_delete"}:
        return "keep"
    return value


def effective_app_url():
    # APP_URL from Docker/YAML wins when supplied. This keeps Google OAuth
    # tied to the intended public hostname rather than the ZimaOS local tile.
    if ENV_APP_URL:
        return ENV_APP_URL

    value = get_setting("app_url", "").strip()
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
    first_import = not setting_bool(
        "youtube_baseline_complete",
        False,
    )

    new_count = 0
    reactivated_count = 0
    reactivated_rows = []
    removed_rows = []

    with db() as conn:
        manual_deleted_rows = conn.execute(
            """
            SELECT *
            FROM manually_deleted_channels
            """
        ).fetchall()

        manual_deleted = {
            row["channel_id"]: dict(row)
            for row in manual_deleted_rows
        }

        # A destructive delete should disappear from the app immediately.
        # YouTube can briefly return the old subscription after an unsubscribe.
        # Keep suppressing it until at least one refresh sees it absent.
        for deleted_channel_id, deleted_row in manual_deleted.items():
            if (
                deleted_channel_id not in current_ids
                and not bool(deleted_row.get("absence_confirmed"))
            ):
                conn.execute(
                    """
                    UPDATE manually_deleted_channels
                    SET absence_confirmed = 1
                    WHERE channel_id = ?
                    """,
                    (deleted_channel_id,),
                )
                deleted_row["absence_confirmed"] = 1

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

        for sub in subs:
            deleted_marker = manual_deleted.get(
                sub["channel_id"]
            )

            if deleted_marker:
                if not bool(
                    deleted_marker.get(
                        "absence_confirmed"
                    )
                ):
                    # YouTube has not yet reflected the explicit unsubscribe.
                    # Do not recreate the deleted app row.
                    continue

                # We previously observed this channel absent and it has now
                # appeared again. Treat this as a genuine future re-subscribe.
                conn.execute(
                    """
                    DELETE FROM manually_deleted_channels
                    WHERE channel_id = ?
                    """,
                    (sub["channel_id"],),
                )
                manual_deleted.pop(
                    sub["channel_id"],
                    None,
                )

            existing = conn.execute(
                """
                SELECT *
                FROM subscriptions
                WHERE channel_id = ?
                """,
                (sub["channel_id"],),
            ).fetchone()

            if existing is None:
                new_count += 1

                # First connection establishes a safe baseline. Existing
                # subscriptions are not treated as newly subscribed channels.
                if first_import:
                    enabled = 0
                    needs_review = 0
                    source_authorised = 0
                else:
                    enabled = 1 if policy == "auto_enable" else 0
                    needs_review = 0
                    source_authorised = 1 if enabled else 0

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
                        source_authorised,
                        needs_review,
                        removed_at,
                        youtube_subscription_id,
                        thumbnail_url
                    )
                    VALUES (?, ?, ?, ?, ?, 1, 'default', ?, ?, ?, NULL, ?, ?)
                    """,
                    (
                        sub["channel_id"],
                        sub["title"],
                        sub["channel_url"],
                        sub["subscribed_at"],
                        first_seen,
                        enabled,
                        source_authorised,
                        needs_review,
                        sub.get("youtube_subscription_id"),
                        sub.get("thumbnail_url", ""),
                    ),
                )
            else:
                was_inactive = (
                    not bool(existing["active"])
                    and bool(existing["removed_at"])
                )

                if was_inactive:
                    reactivated_count += 1
                    enabled = 1 if policy == "auto_enable" else 0
                    needs_review = 0
                    source_authorised = 1 if enabled else 0

                    conn.execute(
                        """
                        UPDATE subscriptions
                        SET title = ?,
                            channel_url = ?,
                            subscribed_at = ?,
                            youtube_subscription_id = ?,
                            thumbnail_url = ?,
                            active = 1,
                            removed_at = NULL,
                            download_enabled = ?,
                            source_authorised = ?,
                            needs_review = ?,
                            last_error = NULL,
                            retry_count = 0
                        WHERE channel_id = ?
                        """,
                        (
                            sub["title"],
                            sub["channel_url"],
                            sub["subscribed_at"],
                            sub.get("youtube_subscription_id"),
                            sub.get("thumbnail_url", ""),
                            enabled,
                            source_authorised,
                            needs_review,
                            sub["channel_id"],
                        ),
                    )

                    # A re-subscribe must cancel the delayed cleanup window
                    # created by a previous remove+delete action.
                    conn.execute(
                        """
                        UPDATE cleanup_jobs
                        SET status = 'cancelled',
                            finished_at = ?,
                            last_error = NULL
                        WHERE channel_id = ?
                          AND status = 'pending'
                        """,
                        (now_iso(), sub["channel_id"]),
                    )

                    restored = dict(existing)
                    restored.update(
                        {
                            "title": sub["title"],
                            "channel_url": sub["channel_url"],
                            "subscribed_at": sub["subscribed_at"],
                            "youtube_subscription_id": sub.get(
                                "youtube_subscription_id"
                            ),
                            "thumbnail_url": sub.get("thumbnail_url", ""),
                            "active": 1,
                            "removed_at": None,
                            "download_enabled": enabled,
                            "source_authorised": source_authorised,
                            "needs_review": needs_review,
                            "last_error": None,
                            "retry_count": 0,
                        }
                    )
                    reactivated_rows.append(restored)

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

    if first_import:
        set_setting("youtube_baseline_complete", "1")
        log_activity(
            "youtube_refresh",
            "Initial YouTube baseline imported",
            (
                f"Imported {len(subs)} existing subscription(s) as disabled "
                "and waiting for approval. Future new subscriptions follow "
                "the configured new-subscription policy."
            ),
            "success",
        )

    policy_errors = 0

    # Reconcile channels which have been subscribed to again. A source which
    # was previously deleted from Pinchflat can leave a stale source ID in an
    # older app database. If the source no longer exists, clear the stale link
    # so the normal pending-source importer creates a fresh source.
    for row in reactivated_rows:
        try:
            source_id = row.get("pinchflat_source_id")
            source_added = bool(row.get("pinchflat_added"))

            if source_added and source_id:
                if pinchflat_source_exists(source_id):
                    update_pinchflat_source_settings(
                        source_id,
                        cutoff=subscription_cutoff(row),
                        download_enabled=bool(row["download_enabled"]),
                        media_profile_id=subscription_media_profile_id(row),
                    )
                else:
                    with db() as conn:
                        conn.execute(
                            """
                            UPDATE subscriptions
                            SET pinchflat_added = 0,
                                pinchflat_source_id = NULL,
                                last_error = NULL,
                                retry_count = 0
                            WHERE channel_id = ?
                            """,
                            (row["channel_id"],),
                        )

            elif source_added and not source_id:
                with db() as conn:
                    conn.execute(
                        """
                        UPDATE subscriptions
                        SET pinchflat_added = 0,
                            last_error = NULL,
                            retry_count = 0
                        WHERE channel_id = ?
                        """,
                        (row["channel_id"],),
                    )

            log_activity(
                "youtube_refresh",
                "YouTube subscription restored",
                (
                    f"{row.get('title') or row['channel_id']} was subscribed "
                    "to again. Any previous cleanup job was cancelled."
                ),
                "success",
                row["channel_id"],
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

            elif unsubscribe_policy() in {"remove", "remove_delete"}:
                policy = unsubscribe_policy()
                delete_files = policy == "remove_delete"

                output_template = media_profile_settings(
                    subscription_media_profile_id(row)
                ).get(
                    "output_path_template",
                    EMBY_OUTPUT_PATH_TEMPLATE,
                )

                source_id = resolve_pinchflat_source_id(row)
                source_gone = not source_id

                if source_id:
                    removal_row = dict(row)
                    removal_row["pinchflat_source_id"] = str(source_id)
                    removal_row["pinchflat_added"] = 1

                    prepare_pinchflat_source_for_removal(removal_row)
                    source_gone = delete_pinchflat_source(
                        source_id,
                        delete_files=delete_files,
                        subscription=row,
                    )

                deleted_folder = None
                if delete_files:
                    deleted_folder = delete_subscription_download_folder(
                        row.get("title") or row["channel_id"],
                        output_template,
                    )

                if source_gone:
                    clear_subscription_pinchflat_link(
                        row["channel_id"],
                        source_id,
                    )
                else:
                    with db() as conn:
                        conn.execute(
                            """
                            UPDATE subscriptions
                            SET pinchflat_added = 1,
                                pinchflat_source_id = ?,
                                download_enabled = 0,
                                last_error = ?
                            WHERE channel_id = ?
                            """,
                            (
                                str(source_id),
                                "Pinchflat source removal is in progress. Waiting for Pinchflat deletion worker.",
                                row["channel_id"],
                            ),
                        )

                schedule_unsubscribe_cleanup(
                    row["channel_id"],
                    row.get("title") or row["channel_id"],
                    output_template,
                    source_id=source_id,
                    delete_files=delete_files,
                    delay_seconds=300,
                    checks=6,
                )

                if delete_files:
                    log_activity(
                        "pinchflat",
                        "Removed source and downloaded files",
                        (
                            f"{row.get('title') or row['channel_id']} removed. "
                            + (
                                f"Deleted folder {deleted_folder}."
                                if deleted_folder
                                else "Pinchflat media deletion requested; no remaining channel folder was found."
                            )
                            + " Follow-up cleanup will run every 5 minutes for 30 minutes."
                        ),
                        "success",
                        row["channel_id"],
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

    if reactivated_count:
        log_activity(
            "youtube_refresh",
            "Re-subscribed YouTube channels",
            (
                f"Detected {reactivated_count} genuinely re-subscribed channel(s)."
            ),
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

    try:
        record_missing_channel_stat_snapshots(current_ids, creds=creds)
    except Exception as exc:
        log_activity(
            "youtube_refresh",
            "Channel statistics snapshot failed",
            str(exc),
            "warning",
        )

    return {
        "total": len(subs),
        "new": new_count,
        "reactivated": reactivated_count,
        "removed": len(removed_rows),
        "policy_errors": policy_errors,
    }


class DockerUnixHTTPConnection(http.client.HTTPConnection):
    def __init__(self, socket_path, timeout=30):
        super().__init__("localhost", timeout=timeout)
        self.socket_path = str(socket_path)

    def connect(self):
        sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        sock.settimeout(self.timeout)
        sock.connect(self.socket_path)
        self.sock = sock


def docker_request(method, path, payload=None, timeout=30, versioned=True):
    if not DOCKER_SOCKET_PATH.exists():
        raise RuntimeError("Docker socket is not mounted into the app.")

    body = None
    headers = {"Host": "localhost"}

    if payload is not None:
        body = json.dumps(payload).encode("utf-8")
        headers["Content-Type"] = "application/json"
        headers["Content-Length"] = str(len(body))

    if versioned:
        version_status, _headers, version_body = docker_request(
            "GET",
            "/version",
            timeout=timeout,
            versioned=False,
        )
        if version_status >= 400:
            raise RuntimeError("Docker Engine version could not be read.")
        api_version = json.loads(
            version_body.decode("utf-8", "replace")
        ).get("ApiVersion", "1.41")
        path = f"/v{api_version}{path}"

    conn = DockerUnixHTTPConnection(
        DOCKER_SOCKET_PATH,
        timeout=timeout,
    )

    try:
        conn.request(
            method,
            path,
            body=body,
            headers=headers,
        )
        response = conn.getresponse()
        response_body = response.read()
        response_headers = dict(response.getheaders())
        return response.status, response_headers, response_body
    finally:
        conn.close()


def decode_docker_log_stream(body):
    """
    Decode Docker's multiplexed stdout/stderr stream.

    Containers created with TTY enabled return plain text instead, so this
    falls back to normal UTF-8 decoding when the frame structure is absent.
    """
    if not body:
        return ""

    chunks = []
    offset = 0
    framed = False

    while offset + 8 <= len(body):
        stream_type = body[offset]
        size = int.from_bytes(
            body[offset + 4:offset + 8],
            "big",
        )

        if (
            stream_type not in (0, 1, 2)
            or size < 0
            or offset + 8 + size > len(body)
        ):
            break

        framed = True
        chunks.append(
            body[offset + 8:offset + 8 + size]
        )
        offset += 8 + size

    if framed and chunks:
        return b"".join(chunks).decode(
            "utf-8",
            "replace",
        )

    return body.decode(
        "utf-8",
        "replace",
    )


def docker_container_inspect(container_name):
    name = quote(
        str(container_name or "").strip(),
        safe="",
    )

    if not name:
        raise RuntimeError(
            "Docker container name is empty."
        )

    status, _headers, body = docker_request(
        "GET",
        f"/containers/{name}/json",
        timeout=20,
    )

    if status == 404:
        raise RuntimeError(
            f"Docker container {container_name!r} was not found."
        )

    if status >= 400:
        raise RuntimeError(
            f"Docker returned HTTP {status}: "
            f"{body.decode('utf-8', 'replace')[:500]}"
        )

    return json.loads(
        body.decode(
            "utf-8",
            "replace",
        )
    )


def docker_env_dict(env_values):
    result = {}

    for entry in env_values or []:
        text = str(entry or "")

        if "=" in text:
            key, value = text.split(
                "=",
                1,
            )
        else:
            key, value = text, ""

        key = key.strip()

        if key:
            result[key] = value

    return result


def docker_env_list_with_updates(env_values, updates):
    current = docker_env_dict(
        env_values
    )

    for key, value in updates.items():
        current[str(key)] = str(value)

    return [
        f"{key}={value}"
        for key, value in current.items()
    ]


def pinchflat_worker_concurrency_from_info(info):
    env = docker_env_dict(
        (info.get("Config") or {}).get(
            "Env",
            [],
        )
    )

    raw = str(
        env.get(
            "YT_DLP_WORKER_CONCURRENCY",
            "2",
        )
        or "2"
    ).strip()

    try:
        value = int(raw)
    except (TypeError, ValueError):
        value = 2

    return max(
        1,
        min(
            value,
            32,
        ),
    )


def docker_rename_container(
    current_name,
    new_name,
):
    status, _headers, body = docker_request(
        "POST",
        (
            f"/containers/{quote(current_name, safe='')}/rename?"
            + urlencode(
                {
                    "name": new_name,
                }
            )
        ),
        timeout=30,
    )

    if status not in (204,):
        raise RuntimeError(
            f"Docker could not rename {current_name!r}. "
            f"HTTP {status}: "
            f"{body.decode('utf-8', 'replace')[:500]}"
        )


def docker_remove_container(
    container_name,
    force=False,
):
    query = urlencode(
        {
            "force": "1" if force else "0",
            "v": "0",
        }
    )

    status, _headers, body = docker_request(
        "DELETE",
        (
            f"/containers/{quote(container_name, safe='')}"
            f"?{query}"
        ),
        timeout=30,
    )

    if status not in (
        204,
        404,
    ):
        raise RuntimeError(
            f"Docker could not remove {container_name!r}. "
            f"HTTP {status}: "
            f"{body.decode('utf-8', 'replace')[:500]}"
        )


def docker_start_named_container(
    container_name,
):
    status, _headers, body = docker_request(
        "POST",
        f"/containers/{quote(container_name, safe='')}/start",
        timeout=30,
    )

    if status not in (
        204,
        304,
    ):
        raise RuntimeError(
            f"Docker could not start {container_name!r}. "
            f"HTTP {status}: "
            f"{body.decode('utf-8', 'replace')[:500]}"
        )


def docker_stop_named_container(
    container_name,
    timeout_seconds=20,
):
    status, _headers, body = docker_request(
        "POST",
        (
            f"/containers/{quote(container_name, safe='')}/stop?"
            + urlencode(
                {
                    "t": str(
                        max(
                            1,
                            int(timeout_seconds),
                        )
                    ),
                }
            )
        ),
        timeout=max(
            30,
            int(timeout_seconds) + 10,
        ),
    )

    if status not in (
        204,
        304,
    ):
        raise RuntimeError(
            f"Docker could not stop {container_name!r}. "
            f"HTTP {status}: "
            f"{body.decode('utf-8', 'replace')[:500]}"
        )


def pinchflat_recreate_with_worker_concurrency(
    concurrency,
):
    concurrency = int(concurrency)

    if not 1 <= concurrency <= 16:
        raise RuntimeError(
            "Concurrent downloads must be between 1 and 16."
        )

    if not DOCKER_SOCKET_PATH.exists():
        raise RuntimeError(
            "Docker control is unavailable."
        )

    original_name = PINCHFLAT_CONTAINER_NAME
    info = docker_container_inspect(
        original_name
    )

    old_concurrency = (
        pinchflat_worker_concurrency_from_info(
            info
        )
    )

    if old_concurrency == concurrency:
        return {
            "changed": False,
            "old": old_concurrency,
            "new": concurrency,
            "state": pinchflat_container_status(),
        }

    state = info.get("State") or {}
    was_running = bool(
        state.get("Running")
    )

    old_host_config = (
        info.get("HostConfig")
        or {}
    )

    if old_host_config.get("AutoRemove"):
        raise RuntimeError(
            "Pinchflat uses Docker AutoRemove and cannot be recreated safely."
        )

    config_source = (
        info.get("Config")
        or {}
    )

    config_keys = (
        "Domainname",
        "User",
        "AttachStdin",
        "AttachStdout",
        "AttachStderr",
        "ExposedPorts",
        "Tty",
        "OpenStdin",
        "StdinOnce",
        "Cmd",
        "Healthcheck",
        "ArgsEscaped",
        "Image",
        "Volumes",
        "WorkingDir",
        "Entrypoint",
        "NetworkDisabled",
        "MacAddress",
        "OnBuild",
        "Labels",
        "StopSignal",
        "StopTimeout",
        "Shell",
    )

    create_payload = {
        key: config_source.get(key)
        for key in config_keys
        if key in config_source
    }

    create_payload["Env"] = (
        docker_env_list_with_updates(
            config_source.get(
                "Env",
                [],
            ),
            {
                "YT_DLP_WORKER_CONCURRENCY":
                    str(concurrency),
            },
        )
    )

    # HostConfig returned by Docker closely matches the HostConfig accepted
    # by /containers/create and preserves bind mounts, published ports,
    # resource limits, restart policy and the Compose network mode.
    create_payload["HostConfig"] = json.loads(
        json.dumps(
            old_host_config
        )
    )

    network_settings = (
        info.get("NetworkSettings")
        or {}
    )

    old_networks = (
        network_settings.get("Networks")
        or {}
    )

    endpoints = {}

    for network_name, endpoint in old_networks.items():
        endpoint = endpoint or {}
        endpoint_config = {}

        aliases = [
            alias
            for alias in (
                endpoint.get("Aliases")
                or []
            )
            if alias
        ]

        if aliases:
            endpoint_config["Aliases"] = aliases

        ipam = endpoint.get(
            "IPAMConfig"
        )

        if ipam:
            endpoint_config["IPAMConfig"] = ipam

        links = endpoint.get(
            "Links"
        )

        if links:
            endpoint_config["Links"] = links

        driver_opts = endpoint.get(
            "DriverOpts"
        )

        if driver_opts:
            endpoint_config["DriverOpts"] = (
                driver_opts
            )

        endpoints[
            network_name
        ] = endpoint_config

    if endpoints:
        create_payload[
            "NetworkingConfig"
        ] = {
            "EndpointsConfig": endpoints,
        }

    backup_name = (
        f"{original_name}-worker-backup-"
        f"{int(time.time())}"
    )

    old_renamed = False
    new_created = False

    try:
        if was_running:
            docker_stop_named_container(
                original_name,
                20,
            )

        docker_rename_container(
            original_name,
            backup_name,
        )

        old_renamed = True

        status, _headers, body = docker_request(
            "POST",
            (
                "/containers/create?"
                + urlencode(
                    {
                        "name": original_name,
                    }
                )
            ),
            payload=create_payload,
            timeout=60,
        )

        if status not in (
            201,
        ):
            raise RuntimeError(
                "Docker could not create the replacement Pinchflat "
                f"container. HTTP {status}: "
                f"{body.decode('utf-8', 'replace')[:1000]}"
            )

        new_created = True

        if was_running:
            docker_start_named_container(
                original_name
            )

            deadline = time.time() + 90

            while time.time() < deadline:
                if pinchflat_health_http_only(
                    timeout=3
                ):
                    break

                time.sleep(1)
            else:
                raise RuntimeError(
                    "The replacement Pinchflat container started but "
                    "did not become available within 90 seconds."
                )

        new_info = docker_container_inspect(
            original_name
        )

        applied = (
            pinchflat_worker_concurrency_from_info(
                new_info
            )
        )

        if applied != concurrency:
            raise RuntimeError(
                "Pinchflat restarted, but Docker did not report the "
                "requested worker concurrency."
            )

        # The old stopped container is no longer required. Its bind-mounted
        # Pinchflat config and downloaded media are not removed.
        docker_remove_container(
            backup_name,
            force=True,
        )

        return {
            "changed": True,
            "old": old_concurrency,
            "new": applied,
            "state": pinchflat_container_status(),
        }

    except Exception:
        # Roll back to the original container if any part of recreation fails.
        try:
            if new_created:
                try:
                    docker_stop_named_container(
                        original_name,
                        5,
                    )
                except Exception:
                    pass

                docker_remove_container(
                    original_name,
                    force=True,
                )
        except Exception:
            pass

        if old_renamed:
            try:
                docker_rename_container(
                    backup_name,
                    original_name,
                )

                if was_running:
                    docker_start_named_container(
                        original_name
                    )
            except Exception:
                pass

        raise



def pinchflat_container_logs(tail=250):
    if not DOCKER_SOCKET_PATH.exists():
        raise RuntimeError(
            "Docker socket is not mounted. Pinchflat container logs "
            "are unavailable."
        )

    try:
        tail = int(tail)
    except (TypeError, ValueError):
        tail = 250

    tail = max(20, min(tail, 1000))

    name = quote(
        PINCHFLAT_CONTAINER_NAME,
        safe="",
    )

    query = urlencode(
        {
            "stdout": "1",
            "stderr": "1",
            "timestamps": "1",
            "tail": str(tail),
        }
    )

    status, _headers, body = docker_request(
        "GET",
        f"/containers/{name}/logs?{query}",
        timeout=20,
    )

    if status == 404:
        raise RuntimeError(
            f"Docker container {PINCHFLAT_CONTAINER_NAME!r} was not found."
        )

    if status >= 400:
        raise RuntimeError(
            f"Docker returned HTTP {status}: "
            f"{body.decode('utf-8', 'replace')[:300]}"
        )

    text = decode_docker_log_stream(body)
    lines = text.splitlines()

    # Protect the browser from very long individual log messages.
    cleaned = [
        line[:5000]
        for line in lines[-tail:]
    ]

    return "\n".join(cleaned)


def pinchflat_container_status():
    if not DOCKER_SOCKET_PATH.exists():
        return {
            "control_available": False,
            "exists": False,
            "running": pinchflat_health_http_only(),
            "status": "unavailable",
            "error": "Docker socket is not mounted.",
            "worker_concurrency": None,
        }

    try:
        name = quote(PINCHFLAT_CONTAINER_NAME, safe="")
        status, _headers, body = docker_request(
            "GET",
            f"/containers/{name}/json",
            timeout=10,
        )

        if status == 404:
            return {
                "control_available": True,
                "exists": False,
                "running": False,
                "status": "not found",
                "error": "",
                "worker_concurrency": None,
            }

        if status >= 400:
            raise RuntimeError(
                f"Docker returned HTTP {status}: "
                f"{body.decode('utf-8', 'replace')[:300]}"
            )

        info = json.loads(body.decode("utf-8", "replace"))
        state = info.get("State") or {}

        return {
            "control_available": True,
            "exists": True,
            "running": bool(state.get("Running")),
            "status": state.get("Status") or "unknown",
            "error": state.get("Error") or "",
            "worker_concurrency": (
                pinchflat_worker_concurrency_from_info(
                    info
                )
            ),
        }

    except Exception as exc:
        return {
            "control_available": False,
            "exists": False,
            "running": pinchflat_health_http_only(),
            "status": "unavailable",
            "error": str(exc),
            "worker_concurrency": None,
        }


def set_pinchflat_container_power(running):
    state = pinchflat_container_status()
    if not state["control_available"]:
        raise RuntimeError(
            "Docker control is unavailable. Recreate the app with the "
            "/var/run/docker.sock mount from the v1.9.0 YAML."
        )
    if not state["exists"]:
        raise RuntimeError(
            f"Docker container {PINCHFLAT_CONTAINER_NAME!r} was not found."
        )

    name = quote(PINCHFLAT_CONTAINER_NAME, safe="")

    if running:
        status, _headers, body = docker_request(
            "POST",
            f"/containers/{name}/start",
            timeout=30,
        )
        if status not in (204, 304):
            raise RuntimeError(
                f"Docker could not start Pinchflat. HTTP {status}: "
                f"{body.decode('utf-8', 'replace')[:300]}"
            )

        deadline = time.time() + 45
        while time.time() < deadline:
            if pinchflat_health_http_only(timeout=3):
                break
            time.sleep(1)

    else:
        status, _headers, body = docker_request(
            "POST",
            f"/containers/{name}/stop?t=20",
            timeout=30,
        )
        if status not in (204, 304):
            raise RuntimeError(
                f"Docker could not stop Pinchflat. HTTP {status}: "
                f"{body.decode('utf-8', 'replace')[:300]}"
            )

    return pinchflat_container_status()


def docker_exec_in_pinchflat(command, timeout=180):
    state = pinchflat_container_status()
    if not state["control_available"]:
        raise RuntimeError("Docker control is unavailable.")
    if not state["exists"]:
        raise RuntimeError("The Pinchflat Docker container was not found.")
    if not state["running"]:
        raise RuntimeError("Pinchflat is stopped.")

    name = quote(PINCHFLAT_CONTAINER_NAME, safe="")
    create_payload = {
        "AttachStdout": True,
        "AttachStderr": True,
        "Tty": True,
        "Cmd": list(command),
    }

    status, _headers, body = docker_request(
        "POST",
        f"/containers/{name}/exec",
        payload=create_payload,
        timeout=30,
    )
    if status not in (200, 201):
        raise RuntimeError(
            f"Docker exec could not be created. HTTP {status}: "
            f"{body.decode('utf-8', 'replace')[:500]}"
        )

    exec_id = json.loads(
        body.decode("utf-8", "replace")
    ).get("Id")
    if not exec_id:
        raise RuntimeError("Docker did not return an exec ID.")

    status, _headers, output = docker_request(
        "POST",
        f"/exec/{quote(exec_id, safe='')}/start",
        payload={"Detach": False, "Tty": True},
        timeout=timeout,
    )
    if status not in (200, 201):
        raise RuntimeError(
            f"Docker exec could not start. HTTP {status}: "
            f"{output.decode('utf-8', 'replace')[:500]}"
        )

    status, _headers, inspect_body = docker_request(
        "GET",
        f"/exec/{quote(exec_id, safe='')}/json",
        timeout=30,
    )
    if status >= 400:
        raise RuntimeError(
            f"Docker exec status could not be read. HTTP {status}."
        )

    inspect = json.loads(
        inspect_body.decode("utf-8", "replace")
    )
    exit_code = inspect.get("ExitCode")

    decoded = output.decode("utf-8", "replace").strip()
    if exit_code not in (0, None):
        raise RuntimeError(
            f"Pinchflat command exited with code {exit_code}. "
            f"{decoded[:1000]}"
        )

    return decoded



def pinchflat_task_block_enabled():
    return setting_bool("pinchflat_task_block_enabled", False)


def pinchflat_pending_task_count():
    conn = pinchflat_db_readonly()
    if conn is None:
        return 0
    try:
        tables = pinchflat_table_names(conn)
        if "oban_jobs" not in tables:
            return 0
        row = conn.execute(
            """
            SELECT COUNT(*) AS count
            FROM oban_jobs
            WHERE state IN ('executing', 'available', 'scheduled', 'retryable')
            """
        ).fetchone()
        return int(row["count"] or 0) if row else 0
    except Exception:
        return 0
    finally:
        conn.close()


def pinchflat_delete_all_tasks():
    """Cancel running Oban work and remove every non-completed queued task."""
    global pinchflat_task_block_last
    with pinchflat_task_block_lock:
        expression = r'''
import Ecto.Query

pause_result =
  if function_exported?(Oban, :pause_all_queues, 0) do
    Oban.pause_all_queues()
  else
    :unsupported
  end

query = from j in Oban.Job, where: j.state in ["executing", "available", "scheduled", "retryable"]

cancelled =
  case Oban.cancel_all_jobs(query) do
    {:ok, count} -> count
    other ->
      IO.inspect(other, label: "CANCEL_RESULT")
      0
  end

Process.sleep(350)

delete_query = from j in Oban.Job, where: j.state in ["cancelled", "discarded", "available", "scheduled", "retryable"]

deleted =
  case Oban.delete_all_jobs(delete_query) do
    {:ok, count} -> count
    other ->
      IO.inspect(other, label: "DELETE_RESULT")
      0
  end

remaining = Pinchflat.Repo.aggregate(query, :count, :id)
IO.puts("TASKS_CANCELLED=" <> Integer.to_string(cancelled))
IO.puts("TASKS_DELETED=" <> Integer.to_string(deleted))
IO.puts("TASKS_REMAINING=" <> Integer.to_string(remaining))
IO.puts("QUEUES_PAUSED=" <> if(pause_result == :unsupported, do: "0", else: "1"))
'''
        output = docker_exec_in_pinchflat(
            ["bin/pinchflat", "rpc", expression],
            timeout=120,
        )
        cancelled_match = re.search(r"TASKS_CANCELLED=(\d+)", output)
        deleted_match = re.search(r"TASKS_DELETED=(\d+)", output)
        remaining_match = re.search(r"TASKS_REMAINING=(\d+)", output)
        paused_match = re.search(r"QUEUES_PAUSED=(\d+)", output)
        if not cancelled_match or not deleted_match or not remaining_match:
            raise RuntimeError(
                "Pinchflat did not return task cancellation verification markers. "
                f"Output: {output[:1200] or 'No output'}"
            )
        result = {
            "cancelled": int(cancelled_match.group(1)),
            "deleted": int(deleted_match.group(1)),
            "remaining": int(remaining_match.group(1)),
            "queues_paused": bool(int(paused_match.group(1))) if paused_match else False,
            "output": output,
        }
        pinchflat_task_block_last = {
            "at": now_iso(),
            "cancelled": result["cancelled"],
            "deleted": result["deleted"],
            "remaining": result["remaining"],
            "error": "",
        }
        return result


def pinchflat_resume_all_tasks():
    expression = r'''
result =
  if function_exported?(Oban, :resume_all_queues, 0) do
    Oban.resume_all_queues()
  else
    :unsupported
  end
IO.puts("QUEUES_RESUMED=" <> if(result == :unsupported, do: "0", else: "1"))
'''
    output = docker_exec_in_pinchflat(
        ["bin/pinchflat", "rpc", expression],
        timeout=60,
    )
    match = re.search(r"QUEUES_RESUMED=(\d+)", output)
    return {
        "resumed": bool(int(match.group(1))) if match else False,
        "output": output,
    }


def pinchflat_task_blocker_loop():
    global pinchflat_task_block_last
    last_pause_refresh = 0.0
    while True:
        if not pinchflat_task_block_enabled():
            last_pause_refresh = 0.0
            time.sleep(5)
            continue
        try:
            pending = pinchflat_pending_task_count()
            now_ts = time.time()
            # Re-assert the queue pause periodically. This matters after a
            # Pinchflat container restart because the app setting persists but
            # Oban's in-memory paused state does not.
            if pending > 0 or now_ts - last_pause_refresh >= 15:
                result = pinchflat_delete_all_tasks()
                last_pause_refresh = now_ts
                if result.get("cancelled") or result.get("deleted"):
                    log_activity(
                        "pinchflat",
                        "Pinchflat tasks blocked",
                        f"Cancelled {result.get('cancelled', 0)} and deleted {result.get('deleted', 0)} Pinchflat tasks.",
                        "warning",
                    )
        except Exception as exc:
            pinchflat_task_block_last = {
                "at": now_iso(),
                "cancelled": 0,
                "deleted": 0,
                "remaining": 0,
                "error": str(exc)[:1000],
            }
        time.sleep(2)


def start_pinchflat_task_blocker():
    global pinchflat_task_blocker_started
    if pinchflat_task_blocker_started:
        return
    pinchflat_task_blocker_started = True
    thread = threading.Thread(
        target=pinchflat_task_blocker_loop,
        name="pinchflat-task-blocker",
        daemon=True,
    )
    thread.start()



def _elixir_b64(value):
    if value is None:
        return ""
    return base64.b64encode(
        str(value).encode("utf-8")
    ).decode("ascii")


def delete_pinchflat_source_direct(
    source_id=None,
    delete_files=False,
    channel_id=None,
    channel_url=None,
):
    # Delete through Pinchflat's own Sources context and verify the live list.
    delete_literal = "true" if delete_files else "false"

    source_id_literal = (
        str(int(source_id))
        if source_id not in (None, "")
        else "nil"
    )

    channel_id_b64 = _elixir_b64(channel_id)
    channel_url_b64 = _elixir_b64(channel_url)

    expression = (
        'channel_id = Base.decode64!("' + channel_id_b64 + '")\n'
        'channel_url = Base.decode64!("' + channel_url_b64 + '")\n'
        'source_id = ' + source_id_literal + '\n'
        '\n'
        'matches =\n'
        '  Pinchflat.Sources.list_sources()\n'
        '  |> Enum.filter(fn source ->\n'
        '    cond do\n'
        '      channel_id != "" ->\n'
        '        source.collection_id == channel_id or\n'
        '          (channel_url != "" and source.original_url == channel_url)\n'
        '      channel_url != "" ->\n'
        '        source.original_url == channel_url\n'
        '      not is_nil(source_id) ->\n'
        '        source.id == source_id\n'
        '      true ->\n'
        '        false\n'
        '    end\n'
        '  end)\n'
        '\n'
        'IO.puts("MATCH_COUNT=" <> Integer.to_string(length(matches)))\n'
        '\n'
        'Enum.each(matches, fn source ->\n'
        '  case Pinchflat.Sources.delete_source(source, delete_files: ' + delete_literal + ') do\n'
        '    {:ok, _deleted} -> :ok\n'
        '    other -> IO.inspect(other, label: "DELETE_ERROR")\n'
        '  end\n'
        'end)\n'
        '\n'
        'remaining =\n'
        '  Pinchflat.Sources.list_sources()\n'
        '  |> Enum.filter(fn source ->\n'
        '    cond do\n'
        '      channel_id != "" ->\n'
        '        source.collection_id == channel_id or\n'
        '          (channel_url != "" and source.original_url == channel_url)\n'
        '      channel_url != "" ->\n'
        '        source.original_url == channel_url\n'
        '      not is_nil(source_id) ->\n'
        '        source.id == source_id\n'
        '      true ->\n'
        '        false\n'
        '    end\n'
        '  end)\n'
        '\n'
        'IO.puts("REMAINING_COUNT=" <> Integer.to_string(length(remaining)))\n'
    )

    output = docker_exec_in_pinchflat(
        ["bin/pinchflat", "rpc", expression],
        timeout=300,
    )

    matched = re.search(r"MATCH_COUNT=(\d+)", output)
    remaining = re.search(r"REMAINING_COUNT=(\d+)", output)

    if not matched or not remaining:
        raise RuntimeError(
            "Pinchflat direct deletion did not return verification markers. "
            f"Output: {output[:1200] or 'No output'}"
        )

    match_count = int(matched.group(1))
    remaining_count = int(remaining.group(1))

    if "DELETE_ERROR" in output:
        raise RuntimeError(
            "Pinchflat returned an error while deleting the source. "
            f"Output: {output[:1200]}"
        )

    if remaining_count != 0:
        raise RuntimeError(
            "Pinchflat still reports the source after direct deletion. "
            f"Matched {match_count}, remaining {remaining_count}. "
            f"Output: {output[:1200]}"
        )

    return {
        "removed": True,
        "matched": match_count,
        "remaining": 0,
        "output": output,
    }


def pinchflat_source_exists_direct(
    source_id=None,
    channel_id=None,
    channel_url=None,
):
    source_id_literal = (
        str(int(source_id))
        if source_id not in (None, "")
        else "nil"
    )

    channel_id_b64 = _elixir_b64(channel_id)
    channel_url_b64 = _elixir_b64(channel_url)

    expression = (
        'channel_id = Base.decode64!("' + channel_id_b64 + '")\n'
        'channel_url = Base.decode64!("' + channel_url_b64 + '")\n'
        'source_id = ' + source_id_literal + '\n'
        '\n'
        'count =\n'
        '  Pinchflat.Sources.list_sources()\n'
        '  |> Enum.count(fn source ->\n'
        '    cond do\n'
        '      channel_id != "" ->\n'
        '        source.collection_id == channel_id or\n'
        '          (channel_url != "" and source.original_url == channel_url)\n'
        '      channel_url != "" ->\n'
        '        source.original_url == channel_url\n'
        '      not is_nil(source_id) ->\n'
        '        source.id == source_id\n'
        '      true ->\n'
        '        false\n'
        '    end\n'
        '  end)\n'
        '\n'
        'IO.puts("SOURCE_COUNT=" <> Integer.to_string(count))\n'
    )

    output = docker_exec_in_pinchflat(
        ["bin/pinchflat", "rpc", expression],
        timeout=60,
    )

    match = re.search(r"SOURCE_COUNT=(\d+)", output)

    if not match:
        raise RuntimeError(
            "Pinchflat source verification returned no SOURCE_COUNT marker. "
            f"Output: {output[:1000] or 'No output'}"
        )

    return int(match.group(1)) > 0



def pinchflat_table_columns(conn, table_name):
    try:
        rows = conn.execute(
            f'PRAGMA table_info("{table_name}")'
        ).fetchall()
        return {
            str(row["name"])
            for row in rows
        }
    except Exception:
        return set()


def pinchflat_table_names(conn):
    try:
        rows = conn.execute(
            """
            SELECT name
            FROM sqlite_master
            WHERE type = 'table'
            """
        ).fetchall()
        return {
            str(row["name"])
            for row in rows
        }
    except Exception:
        return set()


def pinchflat_json_value(value):
    if isinstance(value, (dict, list)):
        return value

    if value in (None, ""):
        return {}

    try:
        return json.loads(value)
    except Exception:
        return {}


def pinchflat_media_item_id_from_args(value):
    payload = pinchflat_json_value(value)

    if isinstance(payload, dict):
        for key in (
            "id",
            "media_item_id",
            "media_id",
        ):
            candidate = payload.get(key)
            if candidate not in (None, ""):
                try:
                    return int(candidate)
                except (TypeError, ValueError):
                    pass

        for nested in payload.values():
            found = pinchflat_media_item_id_from_args(
                nested
            )
            if found is not None:
                return found

    elif isinstance(payload, list):
        for nested in payload:
            found = pinchflat_media_item_id_from_args(
                nested
            )
            if found is not None:
                return found

    return None


def pinchflat_row_value(row, *names):
    if row is None:
        return None

    data = (
        dict(row)
        if not isinstance(row, dict)
        else row
    )

    for name in names:
        if name in data:
            value = data.get(name)
            if value not in (None, ""):
                return value

    return None


def pinchflat_extract_youtube_id(media):
    if not media:
        return ""

    for key in (
        "media_id",
        "youtube_id",
        "youtube_video_id",
        "video_id",
        "collection_id",
    ):
        value = str(media.get(key) or "").strip()
        if re.fullmatch(r"[A-Za-z0-9_-]{11}", value):
            return value

    for key in (
        "original_url",
        "webpage_url",
        "url",
        "media_url",
    ):
        value = str(media.get(key) or "").strip()
        if not value:
            continue

        match = re.search(
            r"(?:v=|youtu\.be/|shorts/|embed/)([A-Za-z0-9_-]{11})",
            value,
        )
        if match:
            return match.group(1)

    return ""


def pinchflat_shared_download_path(value):
    if not value:
        return None

    raw = str(value).strip()
    if not raw:
        return None

    if raw.startswith("/downloads/"):
        return DOWNLOAD_ROOT / raw[len("/downloads/"):]

    if raw == "/downloads":
        return DOWNLOAD_ROOT

    path = Path(raw)
    if path.is_absolute():
        return path

    return DOWNLOAD_ROOT / raw.lstrip("/")


def pinchflat_file_size(value):
    path = pinchflat_shared_download_path(value)
    if path is None:
        return 0

    try:
        if path.is_file():
            return path.stat().st_size
    except Exception:
        pass

    return 0


def pinchflat_humanize_worker(worker):
    """Return a short, readable label for a Pinchflat/Oban worker."""
    raw = str(worker or "").strip()
    if not raw:
        return "Pinchflat task"

    short = raw.rsplit(".", 1)[-1]
    short = re.sub(r"Worker$", "", short)
    short = re.sub(r"([a-z0-9])([A-Z])", r"\1 \2", short)
    short = short.replace("YT DLP", "yt-dlp")
    return short.strip() or "Pinchflat task"


def pinchflat_active_file_size(media):
    """Best-effort size of the file yt-dlp is currently writing."""
    filepath = pinchflat_row_value(
        media or {},
        "media_filepath",
        "filepath",
        "file_path",
    )
    if not filepath:
        return 0

    path = pinchflat_shared_download_path(filepath)
    if path is None:
        return 0

    candidates = [path, Path(str(path) + ".part")]

    # yt-dlp normally appends .part to the final filename while downloading.
    # Some post-processors use a temporary sibling file, so include matching
    # part files from the same directory without recursively scanning storage.
    try:
        if path.parent.exists():
            candidates.extend(path.parent.glob(path.name + "*.part"))
    except Exception:
        pass

    largest = 0
    seen = set()
    for candidate in candidates:
        try:
            key = str(candidate)
            if key in seen:
                continue
            seen.add(key)
            if candidate.is_file():
                largest = max(largest, int(candidate.stat().st_size or 0))
        except Exception:
            continue
    return largest


def pinchflat_estimated_file_speed(job_id, media):
    """Estimate bytes/sec from the growing .part/final file between polls."""
    try:
        job_key = str(job_id)
    except Exception:
        return None

    current_bytes = pinchflat_active_file_size(media)
    now = time.monotonic()

    with pinchflat_speed_samples_lock:
        previous = pinchflat_speed_samples.get(job_key)
        pinchflat_speed_samples[job_key] = {
            "at": now,
            "bytes": current_bytes,
            "speed": (previous or {}).get("speed"),
        }

        # Drop old jobs so a long-running app does not accumulate stale IDs.
        stale = [
            key for key, value in pinchflat_speed_samples.items()
            if now - float(value.get("at") or now) > 180
        ]
        for key in stale:
            if key != job_key:
                pinchflat_speed_samples.pop(key, None)

        if not previous:
            return None

        elapsed = now - float(previous.get("at") or now)
        previous_bytes = int(previous.get("bytes") or 0)
        delta = current_bytes - previous_bytes

        if elapsed >= 0.5 and delta > 0:
            speed = delta / elapsed
            pinchflat_speed_samples[job_key]["speed"] = speed
            return speed

        # Keep the previous estimate briefly when filesystem writes arrive in
        # bursts between the four-second dashboard polls.
        previous_speed = previous.get("speed")
        if previous_speed and elapsed < 12:
            return float(previous_speed)

    return None


def pinchflat_download_progress_from_logs(active_count):
    """
    Pinchflat normally runs yt-dlp with --no-progress, so percentage data is
    often unavailable. If a current/future Pinchflat build emits standard
    yt-dlp progress lines, use the latest line when only one download is
    active. Otherwise the UI uses an indeterminate progress bar.
    """
    if int(active_count or 0) != 1:
        return None

    try:
        logs = pinchflat_container_logs(500)
    except Exception:
        return None

    progress_re = re.compile(
        r"\[download\]\s+"
        r"(?P<percent>\d{1,3}(?:\.\d+)?)%"
        r"(?:\s+of\s+(?P<total>~?\S+))?"
        r"(?:\s+at\s+(?P<speed>\S+/s))?"
        r"(?:\s+ETA\s+(?P<eta>\S+))?",
        re.IGNORECASE,
    )

    for line in reversed(logs.splitlines()):
        match = progress_re.search(line)
        if not match:
            continue

        # Docker log lines are timestamped. Ignore old progress records so a
        # previous download cannot make the current job appear to have a stale
        # transfer speed.
        stamp_match = re.match(
            r"^(\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2})(?:\.\d+)?Z\s+",
            line,
        )
        if stamp_match:
            try:
                stamp = datetime.fromisoformat(
                    stamp_match.group(1) + "+00:00"
                )
                if (datetime.now(timezone.utc) - stamp).total_seconds() > 30:
                    continue
            except Exception:
                pass

        try:
            percent = max(
                0.0,
                min(
                    100.0,
                    float(match.group("percent")),
                ),
            )
        except Exception:
            percent = None

        return {
            "percent": percent,
            "total": match.group("total") or "",
            "speed": match.group("speed") or "",
            "eta": match.group("eta") or "",
        }

    return None


def pinchflat_download_overview(queue_limit=100):
    conn = pinchflat_db_readonly()

    if conn is None:
        checked_paths = []

        if PINCHFLAT_DB_PATH_OVERRIDE:
            checked_paths.append(
                PINCHFLAT_DB_PATH_OVERRIDE
            )

        checked_paths.extend(
            str(path)
            for path in PINCHFLAT_DB_CANDIDATES
        )

        raise RuntimeError(
            "Pinchflat database is unavailable. Checked: "
            + ", ".join(
                dict.fromkeys(
                    checked_paths
                )
            )
        )

    try:
        tables = pinchflat_table_names(conn)

        if "oban_jobs" not in tables:
            raise RuntimeError(
                "Pinchflat Oban job table was not found."
            )

        job_columns = pinchflat_table_columns(
            conn,
            "oban_jobs",
        )

        required = {
            "id",
            "state",
            "worker",
            "args",
        }

        if not required.issubset(job_columns):
            raise RuntimeError(
                "Pinchflat job table does not contain the expected columns."
            )

        optional_job_columns = [
            name
            for name in (
                "attempt",
                "max_attempts",
                "attempted_at",
                "scheduled_at",
                "inserted_at",
                "updated_at",
                "queue",
                "errors",
                "tags",
            )
            if name in job_columns
        ]

        selected_job_columns = [
            "id",
            "state",
            "worker",
            "args",
            *optional_job_columns,
        ]

        media_worker = (
            "Pinchflat.Downloading.MediaDownloadWorker"
        )

        # Oban schemas vary between Pinchflat / Oban releases. Build the
        # ordering expression only from columns which really exist.
        order_time_columns = [
            name
            for name in (
                "scheduled_at",
                "inserted_at",
                "attempted_at",
            )
            if name in job_columns
        ]

        if len(order_time_columns) > 1:
            order_time_expr = (
                "COALESCE("
                + ", ".join(order_time_columns)
                + ")"
            )
        elif order_time_columns:
            order_time_expr = order_time_columns[0]
        else:
            order_time_expr = "id"

        # Count the full queue independently from the display LIMIT so the
        # summary tiles remain correct even with a large Pinchflat queue.
        state_count_rows = conn.execute(
            """
            SELECT state, COUNT(*) AS count
            FROM oban_jobs
            WHERE worker = ?
              AND state IN (
                'executing',
                'available',
                'scheduled'
              )
            GROUP BY state
            """,
            (media_worker,),
        ).fetchall()

        state_counts = {
            str(row["state"]): int(row["count"] or 0)
            for row in state_count_rows
        }

        total_active_count = state_counts.get(
            "executing",
            0,
        )

        total_waiting_count = sum(
            state_counts.get(state, 0)
            for state in (
                "available",
                "scheduled",
            )
        )

        # The Pinchflat dashboard contains many Oban jobs besides media
        # downloads, such as source indexing and metadata work.  Surface those
        # separately so the home-page task tile does not duplicate the
        # dedicated Pinchflat downloads section.
        task_state_rows = conn.execute(
            """
            SELECT state, COUNT(*) AS count
            FROM oban_jobs
            WHERE worker != ?
              AND state IN ('executing', 'available', 'scheduled')
            GROUP BY state
            """,
            (media_worker,),
        ).fetchall()

        task_state_counts = {
            str(row["state"]): int(row["count"] or 0)
            for row in task_state_rows
        }
        total_task_active = task_state_counts.get("executing", 0)
        total_task_waiting = sum(
            task_state_counts.get(state, 0)
            for state in ("available", "scheduled")
        )

        # yt-dlp reports members-only videos with a stable message such as
        # "Join this channel to get access to members-only content". Oban
        # stores the failed attempt text in its errors column. Count current
        # non-completed media-download jobs carrying that message so the
        # dashboard can distinguish membership failures from ordinary queue
        # activity without exposing every failed download in the queue.
        membership_error_count = 0
        if "errors" in job_columns:
            try:
                membership_error_row = conn.execute(
                    """
                    SELECT COUNT(*) AS count
                    FROM oban_jobs
                    WHERE worker = ?
                      AND state != 'completed'
                      AND errors IS NOT NULL
                      AND LOWER(CAST(errors AS TEXT)) LIKE ?
                    """,
                    (
                        media_worker,
                        "%join this channel%",
                    ),
                ).fetchone()
                membership_error_count = int(
                    membership_error_row["count"] or 0
                ) if membership_error_row else 0
            except Exception:
                membership_error_count = 0

        task_rows = conn.execute(
            f"""
            SELECT {", ".join(selected_job_columns)}
            FROM oban_jobs
            WHERE worker != ?
              AND state IN ('executing', 'available', 'scheduled')
            ORDER BY
              CASE state
                WHEN 'executing' THEN 0
                WHEN 'available' THEN 1
                WHEN 'scheduled' THEN 2
                ELSE 9
              END,
              {order_time_expr} ASC,
              id ASC
            LIMIT 20
            """,
            (media_worker,),
        ).fetchall()

        pinchflat_tasks = [
            {
                "job_id": row["id"],
                "worker": str(row["worker"] or ""),
                "label": pinchflat_humanize_worker(row["worker"]),
                "state": str(row["state"] or ""),
                "status": {
                    "executing": "Running",
                    "available": "Waiting",
                    "scheduled": "Scheduled",
                }.get(str(row["state"] or ""), str(row["state"] or "").title()),
                "started_at": (row["attempted_at"] if "attempted_at" in row.keys() else "") or "",
                "scheduled_at": (row["scheduled_at"] if "scheduled_at" in row.keys() else "") or "",
            }
            for row in task_rows
        ]

        job_rows = conn.execute(
            f"""
            SELECT {", ".join(selected_job_columns)}
            FROM oban_jobs
            WHERE worker = ?
              AND state IN (
                'executing',
                'available',
                'scheduled'
              )
            ORDER BY
              CASE state
                WHEN 'executing' THEN 0
                WHEN 'available' THEN 1
                WHEN 'scheduled' THEN 2
                ELSE 9
              END,
              {order_time_expr} ASC,
              id ASC
            LIMIT ?
            """,
            (
                media_worker,
                (
                    1000000
                    if int(queue_limit or 0) < 0
                    else max(
                        20,
                        min(
                            int(queue_limit or 0) + 20,
                            500,
                        ),
                    )
                ),
            ),
        ).fetchall()

        jobs = [
            dict(row)
            for row in job_rows
        ]

        media_ids = []
        for job in jobs:
            media_id = pinchflat_media_item_id_from_args(
                job.get("args")
            )
            job["media_item_id"] = media_id
            if media_id is not None:
                media_ids.append(media_id)

        media_map = {}
        media_columns = set()

        if (
            "media_items" in tables
            and media_ids
        ):
            media_columns = pinchflat_table_columns(
                conn,
                "media_items",
            )

            wanted = [
                column
                for column in (
                    "id",
                    "uuid",
                    "title",
                    "media_id",
                    "youtube_id",
                    "youtube_video_id",
                    "video_id",
                    "original_url",
                    "webpage_url",
                    "url",
                    "media_url",
                    "source_id",
                    "media_filepath",
                    "filepath",
                    "file_path",
                    "thumbnail_filepath",
                    "inserted_at",
                    "updated_at",
                    "downloaded_at",
                    "upload_date",
                    "duration_seconds",
                )
                if column in media_columns
            ]

            placeholders = ",".join(
                "?"
                for _ in set(media_ids)
            )

            if wanted and placeholders:
                rows = conn.execute(
                    f"""
                    SELECT {", ".join(wanted)}
                    FROM media_items
                    WHERE id IN ({placeholders})
                    """,
                    tuple(
                        sorted(
                            set(media_ids)
                        )
                    ),
                ).fetchall()

                media_map = {
                    int(row["id"]): dict(row)
                    for row in rows
                }

        source_map = {}
        source_ids = {
            int(media.get("source_id"))
            for media in media_map.values()
            if media.get("source_id")
            not in (None, "")
        }

        if (
            "sources" in tables
            and source_ids
        ):
            source_columns = pinchflat_table_columns(
                conn,
                "sources",
            )

            source_wanted = [
                column
                for column in (
                    "id",
                    "custom_name",
                    "collection_name",
                    "collection_id",
                    "original_url",
                )
                if column in source_columns
            ]

            placeholders = ",".join(
                "?"
                for _ in source_ids
            )

            rows = conn.execute(
                f"""
                SELECT {", ".join(source_wanted)}
                FROM sources
                WHERE id IN ({placeholders})
                """,
                tuple(
                    sorted(source_ids)
                ),
            ).fetchall()

            source_map = {
                int(row["id"]): dict(row)
                for row in rows
            }

        def job_view(job):
            media_id = job.get("media_item_id")
            media = media_map.get(
                int(media_id)
                if media_id is not None
                else -1,
                {},
            )

            source = {}
            source_id = media.get("source_id")

            if source_id not in (None, ""):
                try:
                    source = source_map.get(
                        int(source_id),
                        {},
                    )
                except Exception:
                    source = {}

            title = (
                pinchflat_row_value(
                    media,
                    "title",
                )
                or (
                    f"Media item #{media_id}"
                    if media_id is not None
                    else "Pinchflat media"
                )
            )

            channel = (
                pinchflat_row_value(
                    source,
                    "custom_name",
                    "collection_name",
                )
                or "Pinchflat"
            )

            state = str(
                job.get("state")
                or ""
            )

            status_labels = {
                "executing": "Downloading",
                "available": "Waiting",
                "scheduled": "Scheduled",
                "retryable": "Retry",
            }

            youtube_id = pinchflat_extract_youtube_id(
                media
            )

            channel_id = str(
                pinchflat_row_value(
                    source,
                    "collection_id",
                )
                or ""
            )

            channel_url = str(
                pinchflat_row_value(
                    source,
                    "original_url",
                )
                or (
                    f"https://www.youtube.com/channel/{channel_id}"
                    if channel_id
                    else ""
                )
            )

            video_url = (
                f"https://www.youtube.com/watch?v={youtube_id}"
                if youtube_id
                else ""
            )

            return {
                "job_id": job.get("id"),
                "media_item_id": media_id,
                "title": str(title),
                "channel": str(channel),
                "channel_id": channel_id,
                "channel_url": channel_url,
                "state": state,
                "status": status_labels.get(
                    state,
                    state.title() or "Waiting",
                ),
                "attempt": int(
                    job.get("attempt")
                    or 0
                ),
                "max_attempts": int(
                    job.get("max_attempts")
                    or 0
                ),
                "started_at": (
                    job.get("attempted_at")
                    or ""
                ),
                "queued_at": (
                    job.get("inserted_at")
                    or ""
                ),
                "scheduled_at": (
                    job.get("scheduled_at")
                    or ""
                ),
                "youtube_id": youtube_id,
                "video_url": video_url,
                "thumbnail_url": (
                    f"https://i.ytimg.com/vi/"
                    f"{youtube_id}/hqdefault.jpg"
                    if youtube_id
                    else ""
                ),
            }

        active = [
            job_view(job)
            for job in jobs
            if job.get("state") == "executing"
        ]

        # Add best-effort live transfer information.  File growth works even
        # when Pinchflat starts yt-dlp with --no-progress.  If yt-dlp does emit
        # a standard progress line, use its richer speed/ETA values instead.
        for item in active:
            media = media_map.get(
                int(item.get("media_item_id"))
                if item.get("media_item_id") is not None
                else -1,
                {},
            )
            current_bytes = pinchflat_active_file_size(media)
            estimated_bps = pinchflat_estimated_file_speed(item.get("job_id"), media)
            item["downloaded_bytes"] = current_bytes
            item["downloaded_text"] = format_bytes(current_bytes) if current_bytes else ""
            item["speed_bps"] = estimated_bps or 0
            item["speed"] = (
                f"{format_bytes(estimated_bps)}/s"
                if estimated_bps
                else ""
            )
            item["progress_percent"] = None
            item["progress_total"] = ""
            item["eta"] = ""

        log_progress = pinchflat_download_progress_from_logs(len(active))
        if len(active) == 1 and log_progress:
            item = active[0]
            if log_progress.get("speed"):
                item["speed"] = str(log_progress["speed"])
            item["progress_percent"] = log_progress.get("percent")
            item["progress_total"] = str(log_progress.get("total") or "")
            item["eta"] = str(log_progress.get("eta") or "")

        waiting_all = [
            job_view(job)
            for job in jobs
            if job.get("state") != "executing"
        ]

        requested_queue_limit = int(
            queue_limit
            if queue_limit is not None
            else 100
        )

        if requested_queue_limit < 0:
            waiting = waiting_all
        elif requested_queue_limit == 0:
            waiting = []
        else:
            waiting = waiting_all[
                :requested_queue_limit
            ]

        active_media_ids = {
            int(item["media_item_id"])
            for item in active
            if item.get("media_item_id") is not None
        }

        last_downloaded = None

        if "media_items" in tables:
            if not media_columns:
                media_columns = pinchflat_table_columns(
                    conn,
                    "media_items",
                )

            filepath_column = next(
                (
                    name
                    for name in (
                        "media_filepath",
                        "filepath",
                        "file_path",
                    )
                    if name in media_columns
                ),
                None,
            )

            if filepath_column:
                last_wanted = [
                    column
                    for column in (
                        "id",
                        "uuid",
                        "title",
                        "media_id",
                        "youtube_id",
                        "youtube_video_id",
                        "video_id",
                        "original_url",
                        "webpage_url",
                        "url",
                        "media_url",
                        "source_id",
                        "media_filepath",
                        "filepath",
                        "file_path",
                        "thumbnail_filepath",
                        "inserted_at",
                        "updated_at",
                        "downloaded_at",
                        "upload_date",
                        "duration_seconds",
                    )
                    if column in media_columns
                ]

                order_column = next(
                    (
                        name
                        for name in (
                            "downloaded_at",
                            "updated_at",
                            "inserted_at",
                            "id",
                        )
                        if name in media_columns
                    ),
                    "id",
                )

                excluded_clause = ""
                params = []

                if active_media_ids:
                    placeholders = ",".join(
                        "?"
                        for _ in active_media_ids
                    )
                    excluded_clause = (
                        f" AND id NOT IN ({placeholders})"
                    )
                    params.extend(
                        sorted(active_media_ids)
                    )

                row = conn.execute(
                    f"""
                    SELECT {", ".join(last_wanted)}
                    FROM media_items
                    WHERE {filepath_column} IS NOT NULL
                      AND TRIM({filepath_column}) != ''
                      {excluded_clause}
                    ORDER BY {order_column} DESC, id DESC
                    LIMIT 1
                    """,
                    tuple(params),
                ).fetchone()

                if row:
                    media = dict(row)
                    source = {}
                    source_id = media.get("source_id")

                    if (
                        source_id not in (None, "")
                        and "sources" in tables
                    ):
                        try:
                            source_columns = pinchflat_table_columns(
                                conn,
                                "sources",
                            )
                            source_wanted = [
                                name
                                for name in (
                                    "id",
                                    "custom_name",
                                    "collection_name",
                                    "collection_id",
                                    "original_url",
                                )
                                if name in source_columns
                            ]

                            source_row = conn.execute(
                                f"""
                                SELECT {", ".join(source_wanted)}
                                FROM sources
                                WHERE id = ?
                                LIMIT 1
                                """,
                                (source_id,),
                            ).fetchone()

                            if source_row:
                                source = dict(source_row)
                        except Exception:
                            source = {}

                    filepath = pinchflat_row_value(
                        media,
                        filepath_column,
                    )

                    youtube_id = pinchflat_extract_youtube_id(
                        media
                    )

                    channel_id = str(
                        pinchflat_row_value(
                            source,
                            "collection_id",
                        )
                        or ""
                    )

                    channel_url = str(
                        pinchflat_row_value(
                            source,
                            "original_url",
                        )
                        or (
                            f"https://www.youtube.com/channel/{channel_id}"
                            if channel_id
                            else ""
                        )
                    )

                    video_url = (
                        f"https://www.youtube.com/watch?v={youtube_id}"
                        if youtube_id
                        else ""
                    )

                    last_downloaded = {
                        "media_item_id": media.get("id"),
                        "title": (
                            pinchflat_row_value(
                                media,
                                "title",
                            )
                            or "Downloaded media"
                        ),
                        "channel": (
                            pinchflat_row_value(
                                source,
                                "custom_name",
                                "collection_name",
                            )
                            or "Pinchflat"
                        ),
                        "channel_id": channel_id,
                        "channel_url": channel_url,
                        "video_url": video_url,
                        "completed_at": (
                            pinchflat_row_value(
                                media,
                                "downloaded_at",
                                "updated_at",
                                "inserted_at",
                            )
                            or ""
                        ),
                        "filepath": str(
                            filepath
                            or ""
                        ),
                        "file_size": pinchflat_file_size(
                            filepath
                        ),
                        "file_size_text": format_bytes(
                            pinchflat_file_size(
                                filepath
                            )
                        ),
                        "youtube_id": youtube_id,
                        "thumbnail_url": (
                            f"https://i.ytimg.com/vi/"
                            f"{youtube_id}/hqdefault.jpg"
                            if youtube_id
                            else ""
                        ),
                    }

        return {
            "active": active,
            "waiting": waiting,
            "summary": {
                "active": total_active_count,
                "waiting": total_waiting_count,
                "tasks_active": total_task_active,
                "tasks_waiting": total_task_waiting,
                "membership_errors": membership_error_count,
            },
            "tasks": pinchflat_tasks,
            "task_block": {
                "enabled": pinchflat_task_block_enabled(),
                "last": dict(pinchflat_task_block_last),
            },
            "last_downloaded": last_downloaded,
            "worker": media_worker,
            "schema": {
                "job_columns": sorted(job_columns),
                "order_expression": order_time_expr,
            },
        }

    finally:
        conn.close()


def pinchflat_recent_downloaded_videos(limit=100):
    conn = pinchflat_db_readonly()

    if conn is None:
        raise RuntimeError(
            "Pinchflat database is unavailable."
        )

    try:
        tables = pinchflat_table_names(conn)

        if "media_items" not in tables:
            return []

        media_columns = pinchflat_table_columns(
            conn,
            "media_items",
        )

        filepath_column = next(
            (
                name
                for name in (
                    "media_filepath",
                    "filepath",
                    "file_path",
                )
                if name in media_columns
            ),
            None,
        )

        if not filepath_column:
            return []

        wanted = [
            column
            for column in (
                "id",
                "title",
                "media_id",
                "youtube_id",
                "youtube_video_id",
                "video_id",
                "original_url",
                "webpage_url",
                "url",
                "media_url",
                "source_id",
                "media_filepath",
                "filepath",
                "file_path",
                "inserted_at",
                "updated_at",
                "downloaded_at",
                "upload_date",
                "duration_seconds",
            )
            if column in media_columns
        ]

        order_column = next(
            (
                name
                for name in (
                    "downloaded_at",
                    "updated_at",
                    "inserted_at",
                    "id",
                )
                if name in media_columns
            ),
            "id",
        )

        rows = conn.execute(
            f"""
            SELECT {", ".join(wanted)}
            FROM media_items
            WHERE {filepath_column} IS NOT NULL
              AND TRIM({filepath_column}) != ''
            ORDER BY {order_column} DESC, id DESC
            LIMIT ?
            """,
            (
                max(
                    1,
                    min(
                        int(limit or 100),
                        500,
                    ),
                ),
            ),
        ).fetchall()

        media_rows = [
            dict(row)
            for row in rows
        ]

        source_ids = {
            int(row["source_id"])
            for row in media_rows
            if row.get("source_id")
            not in (None, "")
        }

        source_map = {}

        if (
            source_ids
            and "sources" in tables
        ):
            source_columns = pinchflat_table_columns(
                conn,
                "sources",
            )

            source_wanted = [
                column
                for column in (
                    "id",
                    "custom_name",
                    "collection_name",
                    "collection_id",
                    "original_url",
                )
                if column in source_columns
            ]

            placeholders = ",".join(
                "?"
                for _ in source_ids
            )

            source_rows = conn.execute(
                f"""
                SELECT {", ".join(source_wanted)}
                FROM sources
                WHERE id IN ({placeholders})
                """,
                tuple(sorted(source_ids)),
            ).fetchall()

            source_map = {
                int(row["id"]): dict(row)
                for row in source_rows
            }

        results = []

        for media in media_rows:
            youtube_id = pinchflat_extract_youtube_id(
                media
            )

            if not youtube_id:
                continue

            source = {}
            source_id = media.get("source_id")

            if source_id not in (None, ""):
                try:
                    source = source_map.get(
                        int(source_id),
                        {},
                    )
                except Exception:
                    source = {}

            channel_id = str(
                pinchflat_row_value(
                    source,
                    "collection_id",
                )
                or ""
            )

            channel_title = str(
                pinchflat_row_value(
                    source,
                    "custom_name",
                    "collection_name",
                )
                or "YouTube channel"
            )

            channel_url = str(
                pinchflat_row_value(
                    source,
                    "original_url",
                )
                or (
                    f"https://www.youtube.com/channel/{channel_id}"
                    if channel_id
                    else "https://www.youtube.com"
                )
            )

            completed_at = str(
                pinchflat_row_value(
                    media,
                    "downloaded_at",
                    "updated_at",
                    "inserted_at",
                )
                or ""
            )

            results.append(
                {
                    "video_id": youtube_id,
                    "title": (
                        pinchflat_row_value(
                            media,
                            "title",
                        )
                        or "YouTube video"
                    ),
                    "description": "",
                    "video_url": (
                        f"https://www.youtube.com/watch?v={youtube_id}"
                    ),
                    "shorts_url": (
                        f"https://www.youtube.com/shorts/{youtube_id}"
                    ),
                    "channel_id": channel_id,
                    "channel_title": channel_title,
                    "channel_url": channel_url,
                    "channel_thumbnail_url": "",
                    "thumbnail_url": (
                        f"https://i.ytimg.com/vi/{youtube_id}/hqdefault.jpg"
                    ),
                    "published_at": completed_at,
                    "downloaded_at": completed_at,
                    "view_count": 0,
                    "duration": "",
                    "duration_seconds": int(
                        media.get("duration_seconds")
                        or 0
                    ),
                    "is_short": False,
                    "metadata_complete": False,
                    "from_pinchflat": True,
                }
            )

        return annotate_favourites(
            results[:limit]
        )

    finally:
        conn.close()


def pinchflat_db_readonly():
    db_path = resolve_pinchflat_db_path()

    if not db_path.exists():
        return None

    try:
        conn = sqlite3.connect(
            f"file:{db_path}?mode=ro",
            uri=True,
            timeout=5,
        )
        conn.row_factory = sqlite3.Row
        return conn
    except Exception:
        return None


def find_pinchflat_source_id(channel_id, channel_url=None):
    conn = pinchflat_db_readonly()
    if conn is None:
        return None

    try:
        row = conn.execute(
            """
            SELECT id
            FROM sources
            WHERE collection_id = ?
               OR original_url = ?
            ORDER BY id DESC
            LIMIT 1
            """,
            (channel_id, channel_url or ""),
        ).fetchone()
        return str(row["id"]) if row else None
    except Exception:
        return None
    finally:
        conn.close()


def pinchflat_source_exists_in_db(source_id):
    if not source_id:
        return False

    conn = pinchflat_db_readonly()
    if conn is None:
        return None

    try:
        row = conn.execute(
            "SELECT id FROM sources WHERE id = ? LIMIT 1",
            (str(source_id),),
        ).fetchone()
        return bool(row)
    except Exception:
        return None
    finally:
        conn.close()


def resolve_pinchflat_source_id(row):
    source_id = row.get("pinchflat_source_id")
    if source_id:
        state = pinchflat_source_exists_in_db(source_id)
        if state is not False:
            return str(source_id)

    return find_pinchflat_source_id(
        row.get("channel_id"),
        row.get("channel_url"),
    )


def pinchflat_session():
    session_obj = requests.Session()

    if PINCHFLAT_USER and PINCHFLAT_PASS:
        session_obj.auth = (PINCHFLAT_USER, PINCHFLAT_PASS)

    session_obj.headers.update(
        {"User-Agent": f"youtube-pinchflat-sync/{VERSION}"}
    )

    return session_obj


def pinchflat_source_exists(source_id):
    if not source_id:
        return False

    db_state = pinchflat_source_exists_in_db(source_id)
    if db_state is not None:
        return db_state

    response = pinchflat_session().get(
        f"{PINCHFLAT_URL}/sources/{source_id}/edit",
        timeout=30,
        allow_redirects=False,
    )

    if response.status_code == 404:
        return False

    if response.status_code in (301, 302, 303):
        return True

    response.raise_for_status()
    return True


def clear_stale_pinchflat_link(channel_id):
    with db() as conn:
        conn.execute(
            """
            UPDATE subscriptions
            SET pinchflat_added = 0,
                pinchflat_source_id = NULL,
                last_error = NULL,
                retry_count = 0
            WHERE channel_id = ?
            """,
            (channel_id,),
        )


def pinchflat_health_http_only(timeout=10):
    try:
        response = requests.get(
            f"{PINCHFLAT_URL}/healthcheck",
            timeout=timeout,
        )
        return response.ok
    except requests.RequestException:
        return False


def pinchflat_health():
    if DOCKER_SOCKET_PATH.exists():
        try:
            state = pinchflat_container_status()
            if state["control_available"] and not state["running"]:
                return False
        except Exception:
            pass

    return pinchflat_health_http_only(timeout=10)


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


def profile_form_has_field(form, field_name):
    return form.find(attrs={"name": field_name}) is not None


def profile_form_value(form, field_name, default=""):
    field = form.find(attrs={"name": field_name})
    if field is None:
        return default

    if field.name == "select":
        selected = field.find("option", selected=True)
        if selected is None:
            selected = field.find("option")
        return selected.get("value", "") if selected else default

    if field.name == "textarea":
        return field.text or default

    field_type = (field.get("type") or "text").lower()
    if field_type == "checkbox":
        return "true" if field.has_attr("checked") else "false"

    return field.get("value", default)


def _pinchflat_alpine_toggle_value(field):
    """
    Pinchflat renders boolean toggles as hidden inputs wrapped in an Alpine
    component such as: x-data="{ enabled: true }".

    The hidden input's value is populated by browser-side JavaScript, so a
    requests/BeautifulSoup scrape does not see the live value attribute.
    Read the initial Alpine state instead.
    """
    node = field
    for _depth in range(8):
        if node is None:
            break

        x_data = node.get("x-data") if hasattr(node, "get") else None
        if x_data:
            match = re.search(
                r"\benabled\s*:\s*(true|false)\b",
                str(x_data),
                re.IGNORECASE,
            )
            if match:
                return match.group(1).lower() == "true"

        node = getattr(node, "parent", None)

    return None


def profile_form_bool(form, field_name, default=False):
    fields = form.find_all(attrs={"name": field_name})

    # Standard HTML checkboxes, including SponsorBlock-style checkbox groups.
    checkboxes = [
        field
        for field in fields
        if field.name == "input"
        and (field.get("type") or "").lower() == "checkbox"
    ]
    if checkboxes:
        return any(field.has_attr("checked") for field in checkboxes)

    # Pinchflat's custom toggle component uses an Alpine x-data wrapper.
    for field in fields:
        alpine_value = _pinchflat_alpine_toggle_value(field)
        if alpine_value is not None:
            return alpine_value

    # Fall back to a static value when Pinchflat renders one directly.
    for field in fields:
        value = field.get("value") if hasattr(field, "get") else None
        if value not in (None, ""):
            return str(value).strip().lower() in {
                "1",
                "true",
                "yes",
                "on",
            }

    value = profile_form_value(form, field_name, "")
    if value == "":
        return default
    return str(value).strip().lower() in {"1", "true", "yes", "on"}


def profile_form_select_options(form, field_name):
    field = form.find("select", attrs={"name": field_name})
    if field is None:
        return []

    options = []
    for option in field.find_all("option"):
        value = option.get("value", "")
        label = " ".join(option.stripped_strings).strip() or value
        options.append({"value": value, "label": label})
    return options


def profile_form_multi_values(form, field_fragment):
    values = []
    for field in form.find_all(attrs={"name": True}):
        name = field.get("name") or ""
        if field_fragment not in name:
            continue

        if field.name == "input":
            field_type = (field.get("type") or "").lower()
            value = field.get("value", "")
            if (
                field_type in {"checkbox", "radio"}
                and field.has_attr("checked")
                and value
            ):
                values.append(value)

        elif field.name == "select":
            for option in field.find_all("option", selected=True):
                value = option.get("value", "")
                if value:
                    values.append(value)

    return list(dict.fromkeys(values))



def media_profile_extra_fields(form):
    """Return Pinchflat profile fields not already represented by our friendly controls."""
    known = {
        "media_profile[name]",
        "media_profile[output_path_template]",
        "media_profile[download_subs]",
        "media_profile[embed_subs]",
        "media_profile[download_thumbnail]",
        "media_profile[embed_thumbnail]",
        "media_profile[download_metadata]",
        "media_profile[embed_metadata]",
        "media_profile[shorts_behaviour]",
        "media_profile[livestream_behaviour]",
        "media_profile[preferred_resolution]",
        "media_profile[redownload_delay_days]",
        "media_profile[download_nfo]",
        "media_profile[download_source_images]",
        "media_profile[sponsorblock_behaviour]",
    }

    results = []
    seen = set()

    for field in form.find_all(["input", "select", "textarea"], attrs={"name": True}):
        name = str(field.get("name") or "").strip()
        if not name or name in known or "sponsorblock_categories" in name:
            continue
        if not name.startswith("media_profile["):
            continue
        if name in seen:
            continue
        seen.add(name)

        field_type = (field.get("type") or "text").lower() if field.name == "input" else field.name
        if field_type in {"hidden", "submit", "button", "file", "image", "radio"}:
            continue

        key = name[len("media_profile["):-1] if name.endswith("]") else name
        label = key.replace("_", " ").strip().title()
        label_node = field.find_parent("label")
        if label_node:
            label_text = " ".join(label_node.stripped_strings).strip()
            if label_text:
                label = label_text[:120]

        search_text = f"{key} {label}".casefold()
        if "subtitle" in search_text or "subtitles" in search_text:
            category = "subtitles"
        elif "thumbnail" in search_text or "image" in search_text:
            category = "thumbnails"
        elif "metadata" in search_text or "nfo" in search_text:
            category = "metadata"
        elif "short" in search_text or "livestream" in search_text or "live stream" in search_text:
            category = "content"
        elif "resolution" in search_text or "quality" in search_text or "redownload" in search_text:
            category = "quality"
        elif "sponsor" in search_text:
            category = "sponsorblock"
        else:
            category = "advanced"

        entry = {
            "name": name,
            "key": key,
            "label": label,
            "type": field_type,
            "value": profile_form_value(form, name, ""),
            "checked": profile_form_bool(form, name, False),
            "options": profile_form_select_options(form, name) if field.name == "select" else [],
            "category": category,
        }
        results.append(entry)

    return results

def load_media_profile_form(profile_id, session_obj=None):
    session_obj = session_obj or pinchflat_session()
    page = session_obj.get(
        f"{PINCHFLAT_URL}/media_profiles/{profile_id}/edit",
        timeout=30,
    )
    page.raise_for_status()

    soup = BeautifulSoup(page.text, "html.parser")
    form = None

    for candidate in soup.find_all("form"):
        if candidate.find(
            attrs={"name": "media_profile[output_path_template]"}
        ):
            form = candidate
            break

    if form is None:
        raise RuntimeError(
            f"Pinchflat Media Profile {profile_id} edit form was not found."
        )

    return session_obj, form


def media_profile_settings(profile_id):
    default_resolutions = [
        {"value": "2160p", "label": "2160p / 4K"},
        {"value": "1440p", "label": "1440p"},
        {"value": "1080p", "label": "1080p"},
        {"value": "720p", "label": "720p"},
        {"value": "480p", "label": "480p"},
        {"value": "360p", "label": "360p"},
        {"value": "audio", "label": "Audio Only"},
    ]

    settings = {
        "id": str(profile_id or ""),
        "name": "",
        "output_path_template": EMBY_OUTPUT_PATH_TEMPLATE,
        "extra_fields": [],
        "download_subs": False,
        "embed_subs": False,
        "download_thumbnail": False,
        "embed_thumbnail": False,
        "download_metadata": False,
        "embed_metadata": False,
        "include_shorts": False,
        "include_livestreams": True,
        "preferred_resolution": "1080p",
        "resolution_options": default_resolutions,
        "redownload_delay_days": "",
        "download_nfo": True,
        "download_source_images": True,
        "sponsorblock_behaviour": "remove",
        "sponsorblock_categories": ["sponsor"],
        "available": {},
        "error": "",
    }

    if not profile_id:
        settings["error"] = "No Media Profile is selected."
        return settings

    try:
        _session_obj, form = load_media_profile_form(profile_id)

        field_map = {
            "output_path_template": "media_profile[output_path_template]",
            "download_subs": "media_profile[download_subs]",
            "embed_subs": "media_profile[embed_subs]",
            "download_thumbnail": "media_profile[download_thumbnail]",
            "embed_thumbnail": "media_profile[embed_thumbnail]",
            "download_metadata": "media_profile[download_metadata]",
            "embed_metadata": "media_profile[embed_metadata]",
            "shorts_behaviour": "media_profile[shorts_behaviour]",
            "livestream_behaviour": "media_profile[livestream_behaviour]",
            "preferred_resolution": "media_profile[preferred_resolution]",
            "redownload_delay_days": "media_profile[redownload_delay_days]",
            "download_nfo": "media_profile[download_nfo]",
            "download_source_images": "media_profile[download_source_images]",
            "sponsorblock_behaviour": "media_profile[sponsorblock_behaviour]",
        }

        settings["available"] = {
            key: profile_form_has_field(form, field_name)
            for key, field_name in field_map.items()
        }

        settings["name"] = profile_form_value(
            form,
            "media_profile[name]",
            f"Media Profile {profile_id}",
        )
        settings["extra_fields"] = media_profile_extra_fields(form)
        settings["output_path_template"] = profile_form_value(
            form,
            field_map["output_path_template"],
            EMBY_OUTPUT_PATH_TEMPLATE,
        )

        for key in [
            "download_subs",
            "embed_subs",
            "download_thumbnail",
            "embed_thumbnail",
            "download_metadata",
            "embed_metadata",
            "download_nfo",
            "download_source_images",
        ]:
            settings[key] = profile_form_bool(
                form,
                field_map[key],
                settings[key],
            )

        settings["include_shorts"] = (
            profile_form_value(
                form,
                field_map["shorts_behaviour"],
                "exclude",
            )
            == "include"
        )
        settings["include_livestreams"] = (
            profile_form_value(
                form,
                field_map["livestream_behaviour"],
                "include",
            )
            == "include"
        )

        settings["preferred_resolution"] = profile_form_value(
            form,
            field_map["preferred_resolution"],
            "1080p",
        )
        options = profile_form_select_options(
            form,
            field_map["preferred_resolution"],
        )
        if options:
            settings["resolution_options"] = options

        settings["redownload_delay_days"] = profile_form_value(
            form,
            field_map["redownload_delay_days"],
            "",
        )
        settings["sponsorblock_behaviour"] = profile_form_value(
            form,
            field_map["sponsorblock_behaviour"],
            "remove",
        )
        settings["sponsorblock_categories"] = profile_form_multi_values(
            form,
            "sponsorblock_categories",
        )

    except Exception as exc:
        settings["error"] = str(exc)

    return settings


def _profile_set_bool(payload, form, field_name, enabled):
    if profile_form_has_field(form, field_name):
        payload[field_name] = "true" if enabled else "false"


def update_media_profile_settings(profile_id, values):
    session_obj, form = load_media_profile_form(profile_id)
    payload = scrape_form_payload(form)

    def set_if_supported(field_name, value):
        if profile_form_has_field(form, field_name):
            payload[field_name] = value

    set_if_supported(
        "media_profile[name]",
        values.get("name", profile_form_value(form, "media_profile[name]", "")),
    )
    set_if_supported(
        "media_profile[output_path_template]",
        values.get("output_path_template", EMBY_OUTPUT_PATH_TEMPLATE),
    )

    for key in [
        "download_subs",
        "embed_subs",
        "download_thumbnail",
        "embed_thumbnail",
        "download_metadata",
        "embed_metadata",
        "download_nfo",
        "download_source_images",
    ]:
        _profile_set_bool(
            payload,
            form,
            f"media_profile[{key}]",
            bool(values.get(key)),
        )

    set_if_supported(
        "media_profile[shorts_behaviour]",
        "include" if values.get("include_shorts") else "exclude",
    )
    set_if_supported(
        "media_profile[livestream_behaviour]",
        "include" if values.get("include_livestreams") else "exclude",
    )
    set_if_supported(
        "media_profile[preferred_resolution]",
        values.get("preferred_resolution", ""),
    )
    set_if_supported(
        "media_profile[redownload_delay_days]",
        values.get("redownload_delay_days", ""),
    )
    set_if_supported(
        "media_profile[sponsorblock_behaviour]",
        values.get("sponsorblock_behaviour", "remove"),
    )

    category_field_names = {
        field.get("name")
        for field in form.find_all(attrs={"name": True})
        if "sponsorblock_categories" in (field.get("name") or "")
    }
    category_field_names.discard(None)
    if category_field_names:
        for key in list(payload):
            if "sponsorblock_categories" in key:
                payload.pop(key, None)
        category_name = next(
            (
                name
                for name in category_field_names
                if name.endswith("[]")
            ),
            next(iter(category_field_names)),
        )
        categories = values.get("sponsorblock_categories") or []
        payload[category_name] = categories if categories else [""]

    extra_values = values.get("extra_values") or {}
    for field_name, field_value in extra_values.items():
        if not str(field_name).startswith("media_profile["):
            continue
        field = form.find(attrs={"name": field_name})
        if field is None:
            continue
        if field.name == "input" and (field.get("type") or "").lower() == "checkbox":
            truthy = str(field_value).strip().lower() in {"1", "true", "yes", "on"}
            payload[field_name] = "true" if truthy else "false"
        else:
            payload[field_name] = str(field_value)

    action = form.get("action") or f"/media_profiles/{profile_id}"
    if action.startswith(("http://", "https://")):
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

    if response.status_code in (301, 302, 303):
        return True

    body = " ".join(
        BeautifulSoup(response.text, "html.parser").stripped_strings
    )
    if response.status_code >= 400:
        raise RuntimeError(
            f"Pinchflat returned HTTP {response.status_code}. "
            f"{body[:400] or 'No error text returned.'}"
        )

    raise RuntimeError(
        "Pinchflat did not confirm the Media Profile update. "
        f"{body[:400] or 'No response message returned.'}"
    )


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


def create_media_profile(
    name,
    preferred_resolution="1080p",
    session_obj=None,
    set_as_default=False,
):
    """Create one Pinchflat Media Profile using Pinchflat's own form."""
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
    payload["media_profile[name]"] = name
    payload["media_profile[output_path_template]"] = EMBY_OUTPUT_PATH_TEMPLATE

    if profile_form_has_field(form, "media_profile[preferred_resolution]"):
        payload["media_profile[preferred_resolution]"] = preferred_resolution
    if profile_form_has_field(form, "media_profile[shorts_behaviour]"):
        payload["media_profile[shorts_behaviour]"] = "exclude"
    if profile_form_has_field(form, "media_profile[livestream_behaviour]"):
        payload["media_profile[livestream_behaviour]"] = "include"
    if profile_form_has_field(form, "media_profile[sponsorblock_behaviour]"):
        payload["media_profile[sponsorblock_behaviour]"] = "remove"

    for field_name, enabled in [
        ("media_profile[download_nfo]", True),
        ("media_profile[download_source_images]", True),
        ("media_profile[download_thumbnail]", True),
        ("media_profile[embed_thumbnail]", True),
        ("media_profile[download_metadata]", True),
        ("media_profile[embed_metadata]", True),
    ]:
        _profile_set_bool(payload, form, field_name, enabled)

    sponsor_fields = {
        field.get("name")
        for field in form.find_all(attrs={"name": True})
        if "sponsorblock_categories" in (field.get("name") or "")
    }
    sponsor_fields.discard(None)
    if sponsor_fields:
        for key in list(payload):
            if "sponsorblock_categories" in key:
                payload.pop(key, None)
        sponsor_name = next(
            (name for name in sponsor_fields if name.endswith("[]")),
            next(iter(sponsor_fields)),
        )
        payload[sponsor_name] = ["sponsor"]

    action = form.get("action") or "/media_profiles"
    if action.startswith(("http://", "https://")):
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
        body = " ".join(
            BeautifulSoup(response.text, "html.parser").stripped_strings
        )
        raise RuntimeError(
            f"Pinchflat could not create Media Profile {name}. "
            f"Response: {body[:350] or 'No error text returned.'}"
        )

    source_form, profiles = load_new_source_form(session_obj)
    created = next(
        (
            profile
            for profile in profiles
            if profile["name"].strip().casefold() == name.strip().casefold()
        ),
        None,
    )

    if created is None:
        raise RuntimeError(
            f"Media Profile {name} was created, but its ID could not be identified."
        )

    if set_as_default:
        set_setting("pinchflat_media_profile_id", created["id"])

    return created, source_form, profiles


def delete_media_profile(profile_id):
    profile_id = str(profile_id or "").strip()
    if not profile_id:
        raise RuntimeError("Choose a Media Profile to delete.")

    profiles = pinchflat_profiles()
    existing_ids = [str(profile["id"]) for profile in profiles]

    if profile_id not in existing_ids:
        raise RuntimeError("The selected Media Profile no longer exists.")

    if len(existing_ids) <= 1:
        raise RuntimeError(
            "Pinchflat must keep at least one Media Profile."
        )

    # Protect profiles currently used by sources managed by this app.
    with db() as conn:
        if profile_id == str(effective_media_profile_id()):
            usage = conn.execute(
                """
                SELECT COUNT(*) AS count
                FROM subscriptions
                WHERE active = 1
                  AND pinchflat_added = 1
                  AND download_enabled = 1
                  AND (
                    media_profile_id = ?
                    OR media_profile_id IS NULL
                    OR TRIM(media_profile_id) = ''
                  )
                """,
                (profile_id,),
            ).fetchone()["count"]
        else:
            usage = conn.execute(
                """
                SELECT COUNT(*) AS count
                FROM subscriptions
                WHERE active = 1
                  AND pinchflat_added = 1
                  AND download_enabled = 1
                  AND media_profile_id = ?
                """,
                (profile_id,),
            ).fetchone()["count"]

    if int(usage or 0) > 0:
        raise RuntimeError(
            f"This Media Profile is currently used by {usage} enabled "
            "Pinchflat source(s). Move those sources to another profile first."
        )

    session_obj = pinchflat_session()
    edit_url = f"{PINCHFLAT_URL}/media_profiles/{profile_id}/edit"
    response = session_obj.get(edit_url, timeout=30)
    response.raise_for_status()

    soup = BeautifulSoup(response.text, "html.parser")
    csrf_token = ""

    for field in soup.find_all("input", attrs={"name": "_csrf_token"}):
        csrf_token = field.get("value", "")
        if csrf_token:
            break

    delete_form = None
    for candidate in soup.find_all("form"):
        action = candidate.get("action") or ""
        method_field = candidate.find(
            "input",
            attrs={"name": "_method", "value": "delete"},
        )
        text = " ".join(candidate.stripped_strings).casefold()

        if (
            f"/media_profiles/{profile_id}" in action
            and (
                method_field is not None
                or "delete" in text
            )
        ):
            delete_form = candidate
            break

    if delete_form is not None:
        payload = scrape_form_payload(delete_form)
        action = delete_form.get("action") or f"/media_profiles/{profile_id}"
    else:
        # The delete button is not always rendered as its own form. The
        # REST route still accepts Phoenix's method override.
        payload = {}
        action = f"/media_profiles/{profile_id}"

    payload["_method"] = "delete"
    if csrf_token:
        payload["_csrf_token"] = csrf_token

    if action.startswith(("http://", "https://")):
        target = action
    else:
        target = (
            f"{PINCHFLAT_URL}"
            f"{action if action.startswith('/') else '/' + action}"
        )

    result = session_obj.post(
        target,
        data=payload,
        timeout=60,
        allow_redirects=False,
    )

    if result.status_code not in (200, 204, 301, 302, 303):
        body = " ".join(
            BeautifulSoup(result.text, "html.parser").stripped_strings
        )
        raise RuntimeError(
            f"Pinchflat returned HTTP {result.status_code}. "
            f"{body[:400] or 'No error text returned.'}"
        )

    remaining = pinchflat_profiles()
    remaining_ids = [str(profile["id"]) for profile in remaining]

    if profile_id in remaining_ids:
        raise RuntimeError(
            "Pinchflat accepted the delete request but the profile still exists."
        )

    if str(effective_media_profile_id()) == profile_id:
        set_setting(
            "pinchflat_media_profile_id",
            remaining_ids[0],
        )

    return remaining


def create_default_media_profile(session_obj=None):
    return create_media_profile(
        "YouTube Sync",
        "1080p",
        session_obj=session_obj,
        set_as_default=True,
    )


def ensure_standard_media_profiles(session_obj=None):
    """Create the standard v2 quality profiles if they do not already exist."""
    session_obj = session_obj or pinchflat_session()
    _form, profiles = load_new_source_form(session_obj)
    existing = {
        profile["name"].strip().casefold()
        for profile in profiles
    }

    created = []
    for definition in STANDARD_MEDIA_PROFILES:
        name = definition["name"]
        if name.casefold() in existing:
            continue
        profile, _form, profiles = create_media_profile(
            name,
            definition["resolution"],
            session_obj=session_obj,
            set_as_default=False,
        )
        existing.add(name.casefold())
        created.append(profile)

    return created



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


def pinchflat_profile_status(known_online=None):
    """Return whether Pinchflat has a usable profile, creating one if needed."""
    online = pinchflat_health() if known_online is None else bool(known_online)
    if not online:
        return {
            "ready": False,
            "message": "Pinchflat is offline or unreachable.",
            "profile_ids": [],
        }

    try:
        _session, _form, profile_ids = get_new_source_form(
            auto_create_profile=setting_bool("auto_create_media_profile", True)
        )
        if setting_bool("auto_create_media_profile", True):
            try:
                ensure_standard_media_profiles(_session)
                _form, profiles = load_new_source_form(_session)
                profile_ids = [profile["id"] for profile in profiles]
            except Exception as exc:
                log_activity(
                    "pinchflat",
                    "Standard Media Profile warning",
                    str(exc),
                    "warning",
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


def subscription_source_authorised(sub):
    # v2.6: the Enabled toggle is the single authority for Pinchflat membership.
    return bool(row_value(sub, "active", 1)) and subscription_download_enabled(sub)


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




PINCHFLAT_SOURCE_ACTION_LABELS = {
    "download_pending": (
        "download pending",
        "download pending media",
    ),
    "redownload_existing": (
        "re-download existing",
        "redownload existing",
        "re-download downloaded",
        "redownload downloaded",
    ),
    "force_scan": (
        "force index",
        "force scan",
    ),
    "refresh_metadata": (
        "refresh metadata",
    ),
    "sync_files": (
        "sync files on disk",
        "sync files",
    ),
}


def _normalise_action_text(value):
    return re.sub(
        r"\\s+",
        " ",
        str(value or "").strip().casefold(),
    )


def _pinchflat_action_control_text(control):
    if control is None:
        return ""

    values = [
        control.get_text(" ", strip=True)
        if hasattr(control, "get_text")
        else "",
        control.get("value") or "",
        control.get("title") or "",
        control.get("aria-label") or "",
        control.get("data-confirm") or "",
    ]

    return _normalise_action_text(
        " ".join(str(value) for value in values if value)
    )


def _pinchflat_action_matches(text, labels):
    text = _normalise_action_text(text)
    return any(label in text for label in labels)


PINCHFLAT_SOURCE_ACTION_ROUTES = {
    "download_pending": "force_download_pending",
    "redownload_existing": "force_redownload",
    "force_scan": "force_index",
    "refresh_metadata": "force_metadata_refresh",
    "sync_files": "sync_files_on_disk",
}


PINCHFLAT_SOURCE_ACTION_NAMES = {
    "download_pending": "Download Pending",
    "redownload_existing": "Re-Download Existing",
    "force_scan": "Force Scan",
    "refresh_metadata": "Refresh Media",
    "sync_files": "Sync Files on Disk",
}


def _pinchflat_csrf_token_from_html(html):
    soup = BeautifulSoup(
        html or "",
        "html.parser",
    )

    csrf = soup.find(
        "input",
        attrs={
            "name": "_csrf_token",
        },
    )

    if csrf is not None:
        value = str(
            csrf.get("value")
            or ""
        ).strip()

        if value:
            return value

    # Phoenix can also expose a CSRF token in a meta tag depending on the
    # template/layout in use.
    for attrs in (
        {"name": "csrf-token"},
        {"name": "_csrf_token"},
    ):
        meta = soup.find(
            "meta",
            attrs=attrs,
        )

        if meta is None:
            continue

        value = str(
            meta.get("content")
            or ""
        ).strip()

        if value:
            return value

    return ""


def _pinchflat_error_text(response):
    text = str(
        getattr(
            response,
            "text",
            "",
        )
        or ""
    )

    if not text:
        return ""

    try:
        soup = BeautifulSoup(
            text,
            "html.parser",
        )

        # Prefer common Phoenix error containers/titles before falling back to
        # the complete page text.
        candidates = []

        for selector in (
            "main",
            ".alert",
            ".error",
            ".flash",
            "pre",
        ):
            for node in soup.select(selector):
                value = " ".join(
                    node.stripped_strings
                )

                if value:
                    candidates.append(
                        value
                    )

        if candidates:
            text = max(
                candidates,
                key=len,
            )
        else:
            text = " ".join(
                soup.stripped_strings
            )

    except Exception:
        pass

    text = re.sub(
        r"\s+",
        " ",
        text,
    ).strip()

    return text[:700]


def _recent_pinchflat_log_hint(limit=40):
    try:
        logs = pinchflat_container_logs(
            tail=max(
                20,
                min(
                    int(limit),
                    120,
                ),
            )
        )
    except Exception:
        return ""

    lines = [
        line.strip()
        for line in str(
            logs or ""
        ).splitlines()
        if line.strip()
    ]

    if not lines:
        return ""

    # Keep only the final handful so an action error remains readable in the UI
    # and Activity log.
    return " | ".join(
        lines[-6:]
    )[:900]


def execute_pinchflat_source_action(source_id, action_key):
    source_id = str(
        source_id
        or ""
    ).strip()

    action_key = str(
        action_key
        or ""
    ).strip()

    route = (
        PINCHFLAT_SOURCE_ACTION_ROUTES.get(
            action_key
        )
    )

    friendly = (
        PINCHFLAT_SOURCE_ACTION_NAMES.get(
            action_key
        )
    )

    if not source_id:
        raise RuntimeError(
            "This channel is not linked to a Pinchflat source."
        )

    if not route or not friendly:
        raise RuntimeError(
            "Unknown Pinchflat source action."
        )

    if not pinchflat_health():
        raise RuntimeError(
            "Pinchflat is not available."
        )

    session_obj = pinchflat_session()

    source_url = (
        f"{PINCHFLAT_URL}/sources/"
        f"{quote(source_id, safe='')}"
    )

    # First load the source page. Apart from validating the source, this gives
    # the Session the Phoenix cookie and supplies the CSRF token needed by the
    # browser pipeline.
    source_response = session_obj.get(
        source_url,
        timeout=30,
        allow_redirects=True,
    )

    if source_response.status_code == 404:
        raise RuntimeError(
            "The Pinchflat source no longer exists."
        )

    if source_response.status_code >= 400:
        detail = _pinchflat_error_text(
            source_response
        )

        raise RuntimeError(
            "Pinchflat could not open this source"
            + (
                f": {detail}"
                if detail
                else "."
            )
        )

    csrf_token = (
        _pinchflat_csrf_token_from_html(
            source_response.text
        )
    )

    target = (
        f"{PINCHFLAT_URL}/sources/"
        f"{quote(source_id, safe='')}/"
        f"{route}"
    )

    payload = {}

    if csrf_token:
        payload["_csrf_token"] = (
            csrf_token
        )

    # Pinchflat's SourceController actions take source_id from the path. They do
    # not need source form fields. Posting the whole edit/source form was the
    # cause of unreliable action matching in v2.12.0-v2.12.2.
    result = session_obj.post(
        target,
        data=payload,
        headers={
            "Referer": source_url,
        },
        timeout=180,
        allow_redirects=False,
    )

    # A successful Pinchflat forced action redirects back to the source page.
    if result.status_code in (
        200,
        201,
        202,
        204,
        302,
        303,
    ):
        return True

    detail = _pinchflat_error_text(
        result
    )

    if result.status_code in (
        404,
        405,
    ):
        raise RuntimeError(
            f"Pinchflat does not expose the {friendly} route on this version. "
            f"HTTP {result.status_code} from /sources/{source_id}/{route}."
        )

    if result.status_code == 403:
        raise RuntimeError(
            f"Pinchflat rejected {friendly}. "
            "The Pinchflat session or CSRF token was not accepted."
        )

    if result.status_code >= 500:
        log_hint = (
            _recent_pinchflat_log_hint()
        )

        message = (
            f"Pinchflat returned HTTP {result.status_code} while running "
            f"{friendly} using its official /sources/{source_id}/{route} route."
        )

        if detail:
            message += (
                f" Response: {detail}"
            )

        if log_hint:
            message += (
                f" Recent Pinchflat log: {log_hint}"
            )

        raise RuntimeError(
            message
        )

    raise RuntimeError(
        f"Pinchflat returned HTTP {result.status_code} while running "
        f"{friendly}."
        + (
            f" Response: {detail}"
            if detail
            else ""
        )
    )


def youtube_channel_age(published_at):
    value = str(published_at or "").strip()
    if not value:
        return {"years": 0, "months": 0, "label": ""}

    try:
        created = datetime.fromisoformat(value.replace("Z", "+00:00"))
        now = datetime.now(timezone.utc)
        delta = relativedelta(now, created)
        years = max(int(delta.years or 0), 0)
        months = max(int(delta.months or 0), 0)

        if years:
            label = f"{years} yr" + ("s" if years != 1 else "")
        elif months:
            label = f"{months} mo" + ("s" if months != 1 else "")
        else:
            label = "New channel"

        return {"years": years, "months": months, "label": label}
    except Exception:
        return {"years": 0, "months": 0, "label": ""}


def youtube_topic_label(value):
    value = str(value or "").strip().rstrip("/")
    if not value:
        return ""
    slug = value.rsplit("/", 1)[-1]
    try:
        from urllib.parse import unquote
        slug = unquote(slug)
    except Exception:
        pass
    return slug.replace("_", " ").replace("-", " ").strip()


def record_channel_stat_snapshot(channel_id, subscriber_count, view_count, video_count, recorded_at=None):
    channel_id = str(channel_id or "").strip()
    if not channel_id:
        return

    recorded_at = str(recorded_at or now_iso())
    snapshot_date = recorded_at[:10]

    with db() as conn:
        conn.execute(
            """
            INSERT INTO channel_stats_history (
                channel_id,
                snapshot_date,
                recorded_at,
                subscriber_count,
                view_count,
                video_count
            )
            VALUES (?, ?, ?, ?, ?, ?)
            ON CONFLICT(channel_id, snapshot_date) DO UPDATE SET
                recorded_at = excluded.recorded_at,
                subscriber_count = excluded.subscriber_count,
                view_count = excluded.view_count,
                video_count = excluded.video_count
            """,
            (
                channel_id,
                snapshot_date,
                recorded_at,
                int(subscriber_count or 0),
                int(view_count or 0),
                int(video_count or 0),
            ),
        )


def channel_stats_history(channel_id, limit=730):
    channel_id = str(channel_id or "").strip()
    if not channel_id:
        return []

    with db() as conn:
        rows = conn.execute(
            """
            SELECT snapshot_date, recorded_at, subscriber_count, view_count, video_count
            FROM channel_stats_history
            WHERE channel_id = ?
            ORDER BY snapshot_date DESC
            LIMIT ?
            """,
            (channel_id, max(1, min(int(limit or 730), 5000))),
        ).fetchall()

    return [dict(row) for row in reversed(rows)]


def record_missing_channel_stat_snapshots(channel_ids, creds=None):
    ids = [str(item or "").strip() for item in channel_ids if str(item or "").strip()]
    ids = list(dict.fromkeys(ids))
    if not ids:
        return 0

    today = date.today().isoformat()
    with db() as conn:
        existing = {
            row["channel_id"]
            for row in conn.execute(
                """
                SELECT channel_id
                FROM channel_stats_history
                WHERE snapshot_date = ?
                """,
                (today,),
            ).fetchall()
        }

    pending = [channel_id for channel_id in ids if channel_id not in existing]
    if not pending:
        return 0

    creds = creds or load_credentials()
    if not creds:
        return 0

    recorded = 0
    for offset in range(0, len(pending), 50):
        batch = pending[offset:offset + 50]
        response = youtube_api_request(
            creds,
            "GET",
            "channels",
            "channels.list",
            1,
            params={
                "part": "statistics",
                "id": ",".join(batch),
                "maxResults": 50,
            },
        )
        for item in response.json().get("items", []):
            stats = item.get("statistics") or {}
            record_channel_stat_snapshot(
                item.get("id") or "",
                stats.get("subscriberCount") or 0,
                stats.get("viewCount") or 0,
                stats.get("videoCount") or 0,
            )
            recorded += 1

    return recorded


def youtube_channel_recent_videos(creds, uploads_playlist_id, limit=5):
    uploads_playlist_id = str(uploads_playlist_id or "").strip()
    if not uploads_playlist_id:
        return []

    response = youtube_api_request(
        creds,
        "GET",
        "playlistItems",
        "playlistItems.list",
        1,
        params={
            "part": "snippet,contentDetails",
            "playlistId": uploads_playlist_id,
            "maxResults": max(1, min(int(limit or 5), 20)),
        },
    )
    playlist_items = response.json().get("items", [])
    video_ids = [
        str((item.get("contentDetails") or {}).get("videoId") or "").strip()
        for item in playlist_items
    ]
    video_ids = [item for item in video_ids if item]
    if not video_ids:
        return []

    details_response = youtube_api_request(
        creds,
        "GET",
        "videos",
        "videos.list",
        1,
        params={
            "part": "snippet,statistics,contentDetails",
            "id": ",".join(video_ids),
            "maxResults": len(video_ids),
        },
    )
    by_id = {item.get("id"): item for item in details_response.json().get("items", [])}
    results = []
    for video_id in video_ids:
        item = by_id.get(video_id) or {}
        snippet = item.get("snippet") or {}
        stats = item.get("statistics") or {}
        details = item.get("contentDetails") or {}
        thumbs = snippet.get("thumbnails") or {}
        thumb = thumbs.get("medium") or thumbs.get("high") or thumbs.get("default") or {}
        category_id = str(snippet.get("categoryId") or "")
        results.append({
            "video_id": video_id,
            "title": snippet.get("title") or "YouTube video",
            "published_at": snippet.get("publishedAt") or "",
            "thumbnail_url": thumb.get("url") or f"https://i.ytimg.com/vi/{video_id}/mqdefault.jpg",
            "view_count": int(stats.get("viewCount") or 0),
            "like_count": int(stats.get("likeCount") or 0),
            "comment_count": int(stats.get("commentCount") or 0),
            "duration": youtube_duration_label(details.get("duration") or ""),
            "category_id": category_id,
            "category": YOUTUBE_VIDEO_CATEGORIES.get(category_id, ""),
            "video_url": f"https://www.youtube.com/watch?v={video_id}",
        })
    return results


def youtube_channel_popular_videos(creds, channel_id, limit=5):
    stats = api_usage_stats()
    if stats.get("search_remaining", 0) <= 0:
        return [], "Daily YouTube search limit reached."

    try:
        search_response = youtube_api_request(
            creds,
            "GET",
            "search",
            "search.list",
            1,
            params={
                "part": "snippet",
                "channelId": channel_id,
                "type": "video",
                "order": "viewCount",
                "maxResults": max(1, min(int(limit or 5), 10)),
                "safeSearch": "moderate",
            },
        )
        ids = [
            str((item.get("id") or {}).get("videoId") or "").strip()
            for item in search_response.json().get("items", [])
        ]
        ids = [item for item in ids if item]
        if not ids:
            return [], ""

        details_response = youtube_api_request(
            creds,
            "GET",
            "videos",
            "videos.list",
            1,
            params={
                "part": "snippet,statistics,contentDetails",
                "id": ",".join(ids),
                "maxResults": len(ids),
            },
        )
        by_id = {item.get("id"): item for item in details_response.json().get("items", [])}
        rows = []
        for video_id in ids:
            item = by_id.get(video_id) or {}
            snippet = item.get("snippet") or {}
            vstats = item.get("statistics") or {}
            details = item.get("contentDetails") or {}
            thumbs = snippet.get("thumbnails") or {}
            thumb = thumbs.get("medium") or thumbs.get("high") or thumbs.get("default") or {}
            category_id = str(snippet.get("categoryId") or "")
            rows.append({
                "video_id": video_id,
                "title": snippet.get("title") or "YouTube video",
                "published_at": snippet.get("publishedAt") or "",
                "thumbnail_url": thumb.get("url") or f"https://i.ytimg.com/vi/{video_id}/mqdefault.jpg",
                "view_count": int(vstats.get("viewCount") or 0),
                "like_count": int(vstats.get("likeCount") or 0),
                "comment_count": int(vstats.get("commentCount") or 0),
                "duration": youtube_duration_label(details.get("duration") or ""),
                "category_id": category_id,
                "category": YOUTUBE_VIDEO_CATEGORIES.get(category_id, ""),
                "video_url": f"https://www.youtube.com/watch?v={video_id}",
            })
        return rows, ""
    except Exception as exc:
        return [], str(exc)


def youtube_public_featured_channel_ids(channel_id, limit=10):
    """Best-effort fallback for public Featured Channels shown on YouTube.

    YouTube's channelSections API does not return every public shelf consistently.
    This fallback reads the public channel page and only keeps channel renderers
    found below a section whose heading contains "featured".
    """
    channel_id = str(channel_id or "").strip()
    if not channel_id:
        return []

    try:
        response = requests.get(
            f"https://www.youtube.com/channel/{quote(channel_id)}/featured",
            headers={
                "User-Agent": (
                    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) "
                    "Chrome/142.0 Safari/537.36"
                ),
                "Accept-Language": "en-GB,en;q=0.9",
            },
            timeout=12,
        )
        response.raise_for_status()
        html = response.text
    except Exception:
        return []

    initial_data = None
    patterns = (
        r"var\s+ytInitialData\s*=\s*(\{.*?\});\s*</script>",
        r"ytInitialData\s*=\s*(\{.*?\});\s*</script>",
        r'"ytInitialData"\s*:\s*(\{.*?\})\s*,\s*"',
    )
    for pattern in patterns:
        match = re.search(pattern, html, re.DOTALL)
        if not match:
            continue
        try:
            initial_data = json.loads(match.group(1))
            break
        except Exception:
            continue

    if not initial_data:
        return []

    found = []

    def text_value(value):
        if isinstance(value, str):
            return value
        if not isinstance(value, dict):
            return ""
        if value.get("simpleText"):
            return str(value.get("simpleText") or "")
        runs = value.get("runs") or []
        if isinstance(runs, list):
            return "".join(str(run.get("text") or "") for run in runs if isinstance(run, dict))
        return ""

    def visit(node, featured_context=False):
        if len(found) >= max(1, min(int(limit or 10), 25)):
            return
        if isinstance(node, list):
            for item in node:
                visit(item, featured_context)
            return
        if not isinstance(node, dict):
            return

        headings = []
        for key in ("title", "headline", "header", "label"):
            if key in node:
                value = text_value(node.get(key))
                if value:
                    headings.append(value)
        local_featured = featured_context or any("featured" in value.casefold() for value in headings)

        renderer = node.get("channelRenderer")
        if local_featured and isinstance(renderer, dict):
            candidate = str(renderer.get("channelId") or "").strip()
            if candidate and candidate != channel_id and candidate not in found:
                found.append(candidate)

        for value in node.values():
            if isinstance(value, (dict, list)):
                visit(value, local_featured)

    visit(initial_data)
    return found[:max(1, min(int(limit or 10), 25))]


def youtube_channel_featured_channels(creds, channel_id, branding_channel=None, limit=10):
    channel_id = str(channel_id or "").strip()
    if not channel_id:
        return []

    featured_ids = []
    section_titles = {}

    try:
        response = youtube_api_request(
            creds,
            "GET",
            "channelSections",
            "channelSections.list",
            1,
            params={
                "part": "snippet,contentDetails",
                "channelId": channel_id,
            },
        )

        for section in response.json().get("items", []):
            snippet = section.get("snippet") or {}
            content = section.get("contentDetails") or {}
            if snippet.get("type") != "multipleChannels":
                continue

            section_title = str(snippet.get("title") or "Featured channels").strip()
            for featured_id in content.get("channels") or []:
                featured_id = str(featured_id or "").strip()
                if not featured_id or featured_id == channel_id:
                    continue
                if featured_id not in featured_ids:
                    featured_ids.append(featured_id)
                section_titles.setdefault(featured_id, section_title)
    except Exception:
        pass

    branding_channel = branding_channel or {}
    for featured_id in branding_channel.get("featuredChannelsUrls") or []:
        featured_id = str(featured_id or "").strip()
        if not featured_id or featured_id == channel_id:
            continue
        if featured_id not in featured_ids:
            featured_ids.append(featured_id)
        section_titles.setdefault(featured_id, "Featured channels")

    if not featured_ids:
        for featured_id in youtube_public_featured_channel_ids(channel_id, limit=limit):
            if featured_id not in featured_ids:
                featured_ids.append(featured_id)
            section_titles.setdefault(featured_id, "Featured channels")

    featured_ids = featured_ids[:max(1, min(int(limit or 10), 25))]
    if not featured_ids:
        return []

    try:
        response = youtube_api_request(
            creds,
            "GET",
            "channels",
            "channels.list",
            1,
            params={
                "part": "snippet,statistics",
                "id": ",".join(featured_ids),
                "maxResults": len(featured_ids),
            },
        )
    except Exception:
        return []

    rows_by_id = {
        str(item.get("id") or ""): item
        for item in response.json().get("items", [])
    }

    with db() as conn:
        placeholders = ",".join("?" for _ in featured_ids)
        subscription_states = {}
        if placeholders:
            subscription_states = {
                str(row["channel_id"]): dict(row)
                for row in conn.execute(
                    f"""
                    SELECT channel_id, active, download_enabled, pinchflat_added, pinchflat_source_id
                    FROM subscriptions
                    WHERE channel_id IN ({placeholders})
                    """,
                    featured_ids,
                ).fetchall()
            }
    favourite_ids = favourite_channel_ids()

    results = []
    for featured_id in featured_ids:
        item = rows_by_id.get(featured_id) or {}
        snippet = item.get("snippet") or {}
        statistics = item.get("statistics") or {}
        thumbnails = snippet.get("thumbnails") or {}
        image = (
            thumbnails.get("high")
            or thumbnails.get("medium")
            or thumbnails.get("default")
            or {}
        )

        if not item:
            continue

        results.append(
            {
                "channel_id": featured_id,
                "title": snippet.get("title") or "YouTube channel",
                "handle": snippet.get("customUrl") or "",
                "thumbnail_url": image.get("url") or "",
                "subscriber_count": int(statistics.get("subscriberCount") or 0),
                "hidden_subscriber_count": bool(statistics.get("hiddenSubscriberCount")),
                "channel_url": f"https://www.youtube.com/channel/{featured_id}",
                "subscribed": bool(subscription_states.get(featured_id, {}).get("active")),
                "favourite": featured_id in favourite_ids,
                "download_enabled": bool(subscription_states.get(featured_id, {}).get("download_enabled")),
                "pinchflat_source_id": str(subscription_states.get(featured_id, {}).get("pinchflat_source_id") or ""),
                "section_title": section_titles.get(featured_id, "Featured channels"),
            }
        )

    return results


def youtube_channel_summary(channel_id, include_videos=True, include_popular=True, force=False):
    channel_id = str(channel_id or "").strip()
    if not channel_id:
        return {}

    now_ts = time.time()
    cache_key = f"{channel_id}:{1 if include_videos else 0}:{1 if include_popular else 0}"
    with YOUTUBE_CHANNEL_DETAILS_LOCK:
        cached = YOUTUBE_CHANNEL_DETAILS_CACHE.get(cache_key)
    if cached and not force and cached.get("expires_at", 0) > now_ts:
        result = dict(cached.get("data") or {})
        result["history"] = channel_stats_history(channel_id)
        return result

    try:
        creds = load_credentials()
    except Exception:
        creds = None

    if not creds:
        return {}

    try:
        response = youtube_api_request(
            creds,
            "GET",
            "channels",
            "channels.list",
            1,
            params={
                "part": "snippet,statistics,contentDetails,topicDetails,brandingSettings,status",
                "id": channel_id,
                "maxResults": 1,
            },
        )

        items = response.json().get("items", [])
        if not items:
            return {}

        item = items[0]
        snippet = item.get("snippet") or {}
        stats = item.get("statistics") or {}
        content = item.get("contentDetails") or {}
        topics = item.get("topicDetails") or {}
        branding = item.get("brandingSettings") or {}
        branding_channel = branding.get("channel") or {}
        branding_image = branding.get("image") or {}
        status = item.get("status") or {}
        thumbs = snippet.get("thumbnails") or {}
        image = thumbs.get("high") or thumbs.get("medium") or thumbs.get("default") or {}
        uploads_playlist = ((content.get("relatedPlaylists") or {}).get("uploads") or "")
        published_at = snippet.get("publishedAt") or ""

        record_channel_stat_snapshot(
            channel_id,
            stats.get("subscriberCount") or 0,
            stats.get("viewCount") or 0,
            stats.get("videoCount") or 0,
        )

        recent_videos = []
        popular_videos = []
        popular_error = ""
        featured_channels = []
        if include_videos:
            try:
                recent_videos = youtube_channel_recent_videos(creds, uploads_playlist, 5)
            except Exception:
                recent_videos = []
            if include_popular:
                popular_videos, popular_error = youtube_channel_popular_videos(creds, channel_id, 5)
            try:
                featured_channels = youtube_channel_featured_channels(
                    creds,
                    channel_id,
                    branding_channel=branding_channel,
                    limit=10,
                )
            except Exception:
                featured_channels = []

        category_counts = {}
        for video in recent_videos:
            category = video.get("category") or ""
            if category:
                category_counts[category] = category_counts.get(category, 0) + 1
        primary_category = ""
        if category_counts:
            primary_category = sorted(category_counts.items(), key=lambda pair: (-pair[1], pair[0]))[0][0]

        topic_categories = [
            youtube_topic_label(value)
            for value in (topics.get("topicCategories") or [])
        ]
        topic_categories = [item for item in topic_categories if item]
        if not primary_category and topic_categories:
            primary_category = topic_categories[0]

        subscriber_count = int(stats.get("subscriberCount") or 0)
        view_count = int(stats.get("viewCount") or 0)
        video_count = int(stats.get("videoCount") or 0)
        avg_views = int(view_count / video_count) if video_count else 0
        views_per_subscriber = round(view_count / subscriber_count, 1) if subscriber_count else 0
        recent_view_values = [int(video.get("view_count") or 0) for video in recent_videos]
        recent_like_values = [int(video.get("like_count") or 0) for video in recent_videos]
        recent_comment_values = [int(video.get("comment_count") or 0) for video in recent_videos]
        recent_average_views = int(sum(recent_view_values) / len(recent_view_values)) if recent_view_values else 0
        recent_average_likes = int(sum(recent_like_values) / len(recent_like_values)) if recent_like_values else 0
        recent_average_comments = int(sum(recent_comment_values) / len(recent_comment_values)) if recent_comment_values else 0
        latest_upload_at = recent_videos[0].get("published_at") if recent_videos else ""

        result = {
            "channel_id": channel_id,
            "title": snippet.get("title") or "",
            "description": snippet.get("description") or "",
            "handle": snippet.get("customUrl") or "",
            "custom_url": snippet.get("customUrl") or "",
            "published_at": published_at,
            "age": youtube_channel_age(published_at),
            "country": snippet.get("country") or branding_channel.get("country") or "",
            "default_language": snippet.get("defaultLanguage") or branding_channel.get("defaultLanguage") or "",
            "thumbnail_url": image.get("url") or "",
            "banner_url": branding_image.get("bannerExternalUrl") or "",
            "subscriber_count": subscriber_count,
            "view_count": view_count,
            "video_count": video_count,
            "average_views_per_video": avg_views,
            "views_per_subscriber": views_per_subscriber,
            "recent_average_views": recent_average_views,
            "recent_average_likes": recent_average_likes,
            "recent_average_comments": recent_average_comments,
            "latest_upload_at": latest_upload_at,
            "hidden_subscriber_count": bool(stats.get("hiddenSubscriberCount")),
            "privacy_status": status.get("privacyStatus") or "",
            "made_for_kids": status.get("madeForKids"),
            "keywords": branding_channel.get("keywords") or "",
            "topics": topic_categories,
            "category": primary_category,
            "uploads_playlist_id": uploads_playlist,
            "recent_videos": recent_videos,
            "popular_videos": popular_videos,
            "popular_error": popular_error,
            "featured_channels": featured_channels,
            "history": channel_stats_history(channel_id),
        }

        with YOUTUBE_CHANNEL_DETAILS_LOCK:
            cached_data = dict(result)
            cached_data.pop("history", None)
            YOUTUBE_CHANNEL_DETAILS_CACHE[cache_key] = {
                "expires_at": now_ts + YOUTUBE_CHANNEL_DETAILS_CACHE_SECONDS,
                "data": cached_data,
            }

        return result
    except Exception:
        return {}

def delete_pinchflat_source(
    source_id=None,
    delete_files=False,
    subscription=None,
    channel_id=None,
    channel_url=None,
):
    subscription = dict(subscription or {})

    channel_id = channel_id or subscription.get("channel_id") or ""
    channel_url = channel_url or subscription.get("channel_url") or ""

    if not source_id and subscription:
        source_id = resolve_pinchflat_source_id(subscription)

    docker_state = pinchflat_container_status()

    if docker_state["control_available"]:
        if not docker_state["running"]:
            raise RuntimeError(
                "Pinchflat is stopped. Start Pinchflat before removing "
                "the source."
            )

        result = delete_pinchflat_source_direct(
            source_id=source_id,
            delete_files=delete_files,
            channel_id=channel_id,
            channel_url=channel_url,
        )

        if pinchflat_source_exists_direct(
            source_id=source_id,
            channel_id=channel_id,
            channel_url=channel_url,
        ):
            raise RuntimeError(
                "Pinchflat direct deletion completed but the source is still "
                "present in the live Pinchflat source list."
            )

        return bool(result["removed"])

    if not source_id:
        return True

    if not pinchflat_source_exists(source_id):
        return True

    session_obj = pinchflat_session()
    source_url = f"{PINCHFLAT_URL}/sources/{source_id}"
    response = session_obj.get(
        source_url,
        timeout=30,
        allow_redirects=False,
    )

    if response.status_code == 404:
        return True

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
        return not pinchflat_source_exists(source_id)

    payload = scrape_form_payload(delete_form)
    payload.pop("_method", None)
    payload["delete_files"] = "true" if delete_files else "false"

    action = delete_form.get("action") or f"/sources/{source_id}"
    target = (
        action
        if action.startswith(("http://", "https://"))
        else (
            f"{PINCHFLAT_URL}"
            f"{action if action.startswith('/') else '/' + action}"
        )
    )

    result = session_obj.delete(
        target,
        data=payload,
        timeout=180,
        allow_redirects=False,
    )

    if result.status_code == 404:
        return True

    if result.status_code not in (301, 302, 303):
        body = " ".join(
            BeautifulSoup(
                result.text,
                "html.parser",
            ).stripped_strings
        )
        raise RuntimeError(
            f"Pinchflat could not remove source {source_id}. "
            f"HTTP {result.status_code}. "
            f"Response: {body[:500] or 'No error text returned.'}"
        )

    deadline = time.time() + 30

    while time.time() < deadline:
        if not pinchflat_source_exists(source_id):
            return True
        time.sleep(1)

    return False



def pinchflat_profiles(known_online=None):
    online = pinchflat_health() if known_online is None else bool(known_online)
    if not online:
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
              AND TRIM(COALESCE(last_error, '')) <> ''
              AND COALESCE(last_error, '') NOT LIKE
                  'Pinchflat source removal is in progress%'
            ORDER BY retry_count ASC, title COLLATE NOCASE ASC
            """
        ).fetchall()

    attempted = 0
    fixed = 0
    errors = 0

    for row in rows:
        attempted += 1
        row_dict = dict(row)

        try:
            apply_subscription_source_authority(
                row_dict,
                apply_settings=True,
            )

            with db() as conn:
                conn.execute(
                    """
                    UPDATE subscriptions
                    SET last_error = NULL,
                        retry_count = 0
                    WHERE channel_id = ?
                    """,
                    (row_dict["channel_id"],),
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
                    (str(exc)[:1000], row_dict["channel_id"]),
                )

    if attempted:
        log_activity(
            "retry",
            "Automatic retry",
            (
                f"Retried {attempted} source reconciliation(s). "
                f"Fixed {fixed}. Errors {errors}."
            ),
            "success" if errors == 0 else "warning",
        )

    return {
        "attempted": attempted,
        "fixed": fixed,
        "errors": errors,
    }



def add_pending_sources():
    with db() as conn:
        pending = conn.execute(
            """
            SELECT *
            FROM subscriptions
            WHERE active = 1
              AND pinchflat_added = 0
              AND COALESCE(download_enabled, 0) = 1
              AND COALESCE(source_authorised, 0) = 1
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


def youtube_sync_once():
    if not sync_lock.acquire(blocking=False):
        return {"status": "busy", "message": "Another sync is running."}

    try:
        refresh = refresh_subscriptions()
        message = (
            f"YouTube refreshed {refresh['total']} subscriptions. "
            f"New {refresh['new']}. Re-subscribed {refresh.get('reactivated', 0)}. "
            f"Removed {refresh['removed']}. Policy errors {refresh['policy_errors']}."
        )
        log_activity(
            "youtube_sync",
            "YouTube subscription sync completed",
            message,
            "success" if refresh["policy_errors"] == 0 else "warning",
        )
        return {"status": "ok", "message": message, **refresh}
    except Exception as exc:
        log_activity(
            "youtube_sync",
            "YouTube subscription sync failed",
            str(exc),
            "error",
        )
        return {"status": "error", "message": str(exc)}
    finally:
        sync_lock.release()


def pinchflat_sync_once():
    if not sync_lock.acquire(blocking=False):
        return {"status": "busy", "message": "Another sync is running."}

    try:
        if not pinchflat_health():
            return {
                "status": "offline",
                "message": "Pinchflat is stopped or unreachable.",
            }

        removed = reconcile_removed_pinchflat_sources()
        authority = reconcile_active_source_authority()
        result = add_pending_sources()
        retry = retry_failed_source_updates()
        errors = authority["errors"] + result["errors"] + retry["errors"]
        message = (
            f"Pinchflat authority changes {authority['changed']}. "
            f"Added {result['added']} source(s). Retry fixes {retry['fixed']}. "
            f"Removed-source checks {removed.get('checked', 0)}. Errors {errors}."
        )
        log_activity(
            "pinchflat_sync",
            "Pinchflat sync completed",
            message,
            "success" if errors == 0 else "warning",
        )
        return {
            "status": "ok" if errors == 0 else "completed_with_errors",
            "message": message,
            "errors": errors,
        }
    except Exception as exc:
        log_activity(
            "pinchflat_sync",
            "Pinchflat sync failed",
            str(exc),
            "error",
        )
        return {"status": "error", "message": str(exc), "errors": 1}
    finally:
        sync_lock.release()


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

        if pinchflat_health():
            authority = reconcile_active_source_authority()
            result = add_pending_sources()
            retry = retry_failed_source_updates()
        else:
            authority = {"checked": 0, "changed": 0, "errors": 0}
            result = {"added": 0, "skipped": 0, "errors": 0}
            retry = {"attempted": 0, "fixed": 0, "errors": 0}

        emby = sync_emby_download_playlist()

        total_errors = (
            refresh["policy_errors"]
            + authority["errors"]
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
            f"New {refresh['new']}. Re-subscribed {refresh.get('reactivated', 0)}. "
            f"Removed {refresh['removed']}. "
            f"Authority changes {authority['changed']}. "
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
    item["needs_review"] = False

    if not item.get("active"):
        item["ui_status"] = "removed"
    elif item.get("last_error"):
        item["ui_status"] = "error"
    elif not item.get("pinchflat_added"):
        item["ui_status"] = "pending"
    elif item["download_enabled"]:
        item["ui_status"] = "enabled"
    else:
        item["ui_status"] = "disabled"

    return item


def is_ajax_request():
    return (
        request.headers.get(
            "X-Requested-With",
            "",
        ).lower() == "xmlhttprequest"
        or "application/json"
        in request.headers.get(
            "Accept",
            "",
        ).lower()
    )


def subscription_ajax_payload(channel_id):
    with db() as conn:
        row = conn.execute(
            """
            SELECT *
            FROM subscriptions
            WHERE channel_id = ?
            LIMIT 1
            """,
            (channel_id,),
        ).fetchone()

    if not row:
        return None

    item = subscription_view(row)

    return {
        "channel_id": item.get("channel_id"),
        "title": item.get("title") or "",
        "active": bool(item.get("active")),
        "download_enabled": bool(
            item.get("download_enabled")
        ),
        "pinchflat_added": bool(
            item.get("pinchflat_added")
        ),
        "ui_status": item.get("ui_status") or "",
        "last_error": item.get("last_error") or "",
        "cutoff": item.get("cutoff") or "",
        "history_label": (
            item.get("history_label")
            or ""
        ),
        "history_mode": (
            item.get("history_mode")
            or "default"
        ),
        "history_custom_date": (
            item.get("history_custom_date")
            or ""
        ),
        "media_profile_id": str(
            item.get("media_profile_id")
            or ""
        ),
        "pinchflat_source_id": str(
            item.get("pinchflat_source_id")
            or ""
        ),
        "is_favourite": bool(
            item.get("channel_id")
            in favourite_channel_ids()
        ),
    }


@app.after_request
def security_headers(response):
    response.headers.setdefault("X-Content-Type-Options", "nosniff")
    response.headers.setdefault("X-Frame-Options", "DENY")
    response.headers.setdefault("Referrer-Policy", "strict-origin-when-cross-origin")
    response.headers.setdefault(
        "Content-Security-Policy",
        "default-src 'self'; img-src 'self' https: data:; "
        "style-src 'self' 'unsafe-inline'; "
        "script-src 'self' 'unsafe-inline' https://www.youtube.com https://s.ytimg.com; "
        "connect-src 'self' https://www.youtube.com; "
        "frame-src https://www.youtube.com https://www.youtube-nocookie.com; "
        "frame-ancestors 'none'; base-uri 'self'",
    )
    return response


PUBLIC_ENDPOINTS = {
    "health",
    "static",
    "setup_admin",
    "login",
    "login_2fa",
}
VIEWER_POST_ENDPOINTS = {
    "logout",
    "change_password",
    "two_factor_setup",
    "two_factor_disable",
    "regenerate_recovery_codes",
    "logout_all_sessions",
    "toggle_favourite_channel",
    "toggle_favourite_video",
    "create_favourite_list",
    "delete_favourite_list",
    "add_video_to_favourite_list",
    "remove_video_from_favourite_list",
}
ADMIN_ONLY_GET_ENDPOINTS = {
    "google_login",
    "google_callback",
    "pinchflat_logs_api",
}


@app.before_request
def redirect_to_canonical_app_url():
    if not CANONICAL_REDIRECT or not ENV_APP_URL:
        return None

    if request.method not in {"GET", "HEAD"}:
        return None

    if request.endpoint in {"health", "static"}:
        return None

    canonical = urlparse(ENV_APP_URL)
    current_scheme = (request.scheme or "").lower()
    current_host = (request.host or "").lower()
    canonical_scheme = (canonical.scheme or "").lower()
    canonical_host = (canonical.netloc or "").lower()

    if (
        current_scheme == canonical_scheme
        and current_host == canonical_host
    ):
        return None

    target = f"{ENV_APP_URL}{request.path}"
    if request.query_string:
        target += "?" + request.query_string.decode("utf-8", "replace")

    return redirect(target, code=302)


@app.before_request
def require_authentication():
    endpoint = request.endpoint
    if endpoint is None:
        return None

    if request.method == "POST":
        expected = session.get("_csrf_token")
        supplied = request.form.get("_csrf") or request.headers.get("X-CSRF-Token")
        if not expected or not supplied or not hmac.compare_digest(str(expected), str(supplied)):
            abort(400, description="Invalid or missing CSRF token.")

    if endpoint in {"health", "static"}:
        return None

    has_users = users_exist()
    if not has_users:
        if endpoint != "setup_admin":
            return redirect(url_for("setup_admin"))
        return None

    if endpoint == "setup_admin":
        if session.get("auth_user_id"):
            return redirect(url_for("index"))
        return redirect(url_for("login"))

    if endpoint in {"login", "login_2fa"}:
        if session.get("auth_user_id") and endpoint == "login":
            return redirect(url_for("index"))
        return None

    user = current_user_record()
    if not user or not user["active"]:
        session.clear()
        return redirect(url_for("login"))

    if int(session.get("auth_session_version") or 0) != int(user["session_version"] or 1):
        session.clear()
        flash("Your session has expired. Sign in again.", "error")
        return redirect(url_for("login"))

    # Upgrade sessions created before persistent login support so the next
    # response writes an Expires value to the browser cookie.
    if not session.permanent or not session.get("auth_remember_until"):
        session.permanent = True
        session["auth_remember_until"] = time.time() + (remember_login_days() * 86400)

    remember_until = float(session.get("auth_remember_until") or 0)
    if remember_until and time.time() > remember_until:
        record_auth_event("session_expired", True, user=user, message="Remembered login period expired.")
        session.clear()
        flash("Your remembered login expired. Sign in again.", "error")
        return redirect(url_for("login"))

    last_seen = float(session.get("auth_last_seen") or 0)
    timeout_seconds = session_timeout_minutes() * 60
    if last_seen and time.time() - last_seen > timeout_seconds:
        record_auth_event("session_timeout", True, user=user, message="Session expired due to inactivity.")
        session.clear()
        flash("Your session expired due to inactivity.", "error")
        return redirect(url_for("login"))

    session["auth_last_seen"] = time.time()

    if user["role"] != "admin":
        if endpoint in ADMIN_ONLY_GET_ENDPOINTS:
            flash("Administrator access is required.", "error")
            return redirect(url_for("index"))
        if request.method not in {"GET", "HEAD", "OPTIONS"} and endpoint not in VIEWER_POST_ENDPOINTS:
            flash("Your account has read-only access.", "error")
            return redirect(url_for("index"))

    return None



# ---------------------------------------------------------------------------
# V3 native YouTube Subscription Downloader
# ---------------------------------------------------------------------------

V3_MEDIA_PROFILES = [
    {"id": "2160p", "name": "YouTube 4K", "resolution": "2160p"},
    {"id": "1080p", "name": "YouTube 1080p", "resolution": "1080p"},
    {"id": "720p", "name": "YouTube 720p", "resolution": "720p"},
    {"id": "audio", "name": "YouTube Audio Only", "resolution": "audio"},
]
V3_MEDIA_PROFILE_MAP = {item["id"]: item for item in V3_MEDIA_PROFILES}


def v3_profile_id(value=None):
    value = str(value or "").strip()
    if value in V3_MEDIA_PROFILE_MAP:
        return value
    default = get_setting("downloader_default_profile", "1080p").strip()
    return default if default in V3_MEDIA_PROFILE_MAP else "1080p"


def pinchflat_profiles(known_online=None):
    """Compatibility name retained for V2 database/template upgrades."""
    return [dict(item) for item in V3_MEDIA_PROFILES]


def effective_media_profile_id():
    return v3_profile_id(get_setting("downloader_default_profile", "1080p"))


def subscription_media_profile_id(sub):
    return v3_profile_id(row_value(sub, "media_profile_id", ""))


def media_profile_settings(profile_id=None):
    profile = V3_MEDIA_PROFILE_MAP[v3_profile_id(profile_id)]
    resolution = profile["resolution"]
    return {
        "id": profile["id"],
        "name": profile["name"],
        "preferred_resolution": resolution,
        "output_path_template": (
            "/shows/{{ source_custom_name }}/"
            "{{ season_by_year__episode_by_date_and_index }} - {{ title }}.{{ ext }}"
        ),
        "download_subtitles": True,
        "embed_subtitles": True,
        "download_thumbnail": True,
        "embed_thumbnail": True,
        "download_metadata": True,
        "embed_metadata": True,
        "download_nfo": True,
        "download_source_images": True,
        "shorts_behaviour": "exclude",
        "livestream_behaviour": "include",
        "sponsorblock_behaviour": "mark",
        "sponsorblock_categories": ["sponsor", "outro", "preview"],
        "redownload_delay_days": 0,
        "extra_fields": [],
    }


def pinchflat_profile_status(known_online=None):
    return {
        "ready": True,
        "message": "Native yt-dlp profiles are managed by YouTube Subscription Downloader.",
    }


def pinchflat_health():
    return True


def pinchflat_container_status():
    concurrency = setting_int("downloader_worker_concurrency", 1, 1, 8)
    return {
        "exists": True,
        "running": True,
        "status": "running",
        "control_available": True,
        "worker_concurrency": concurrency,
        "name": "youtube-subscription-downloader",
    }


def pinchflat_recreate_with_worker_concurrency(concurrency):
    concurrency = max(1, min(8, int(concurrency)))
    old = setting_int("downloader_worker_concurrency", 1, 1, 8)
    set_setting("downloader_worker_concurrency", str(concurrency))
    start_download_worker()
    return {"changed": old != concurrency, "old": old, "new": concurrency}


def pinchflat_stats_summary(profiles=None, storage=None):
    storage = storage if storage is not None else storage_snapshot()
    with db() as conn:
        row = conn.execute(
            """
            SELECT
                SUM(CASE WHEN active = 1 AND download_enabled = 1 THEN 1 ELSE 0 END) AS enabled,
                SUM(CASE WHEN active = 1 AND download_enabled = 0 THEN 1 ELSE 0 END) AS disabled,
                SUM(CASE WHEN active = 1 THEN 1 ELSE 0 END) AS linked
            FROM subscriptions
            """
        ).fetchone()
        pending = conn.execute(
            "SELECT COUNT(*) AS c FROM subscription_scan_jobs WHERE status IN ('queued','running')"
        ).fetchone()["c"]
    return {
        "profiles": len(V3_MEDIA_PROFILES),
        "linked": int(row["linked"] or 0),
        "enabled": int(row["enabled"] or 0),
        "disabled": int(row["disabled"] or 0),
        "pending": int(pending or 0),
        "storage": format_bytes(storage["total"]),
    }


def _v3_cookie_status():
    return cookie_file_status(YOUTUBE_COOKIE_PATH)


def _v3_custom_yt_dlp_options():
    return parse_custom_yt_dlp_options(
        get_setting("downloader_custom_yt_dlp_options", "{}")
    )


def _v3_authenticated_options(base):
    status = _v3_cookie_status()
    cookie = YOUTUBE_COOKIE_PATH if status.get("valid") else None
    return authenticated_ydl_options(
        base,
        cookie_path=cookie,
        po_token=get_setting("downloader_po_token", ""),
        custom_options=_v3_custom_yt_dlp_options(),
    )


def _v3_profile_ydl_options(profile_id):
    profile_id = v3_profile_id(profile_id)
    if profile_id == "audio":
        return {
            "format": "bestaudio/best",
            "postprocessors": [
                {"key": "FFmpegExtractAudio", "preferredcodec": "m4a", "preferredquality": "0"}
            ],
        }
    height = int(profile_id[:-1]) if profile_id.endswith("p") else 1080
    return {
        "format": f"bestvideo*[height<={height}]+bestaudio/best[height<={height}]/best",
        "merge_output_format": "mp4",
    }


def _v3_subscription_template():
    return str(
        DOWNLOAD_ROOT
        / "shows"
        / "%(uploader,channel|Unknown Channel).80B"
        / "Season %(upload_date>%Y)s"
        / "s%(upload_date>%Y)sE%(upload_date>%m%d)s00 - %(title).180B [%(id)s].%(ext)s"
    )


def _v3_parse_entry_date(entry):
    upload_date = str((entry or {}).get("upload_date") or "").strip()
    if re.fullmatch(r"\d{8}", upload_date):
        try:
            return date(int(upload_date[:4]), int(upload_date[4:6]), int(upload_date[6:8]))
        except ValueError:
            pass
    timestamp = (entry or {}).get("timestamp") or (entry or {}).get("release_timestamp")
    if timestamp:
        try:
            return datetime.fromtimestamp(float(timestamp), tz=timezone.utc).date()
        except (TypeError, ValueError, OSError):
            pass
    published = str((entry or {}).get("published_at") or "").strip()
    if published:
        try:
            return datetime.fromisoformat(published.replace("Z", "+00:00")).date()
        except ValueError:
            pass
    return None


def _v3_queue_entry(sub, entry, redownload=False):
    video_id = str((entry or {}).get("id") or (entry or {}).get("video_id") or "").strip()
    if not video_id:
        return False
    cutoff = date.fromisoformat(subscription_cutoff(sub))
    entry_date = _v3_parse_entry_date(entry)
    if entry_date and entry_date < cutoff:
        return False
    video_url = str((entry or {}).get("webpage_url") or (entry or {}).get("url") or "").strip()
    if not video_url.startswith("http"):
        video_url = f"https://www.youtube.com/watch?v={video_id}"
    published_at = entry_date.isoformat() if entry_date else str((entry or {}).get("published_at") or "")
    _job_id, created = enqueue_download(
        video_url,
        source_type="subscription",
        video_id=video_id,
        title=str((entry or {}).get("title") or "YouTube video"),
        channel_title=str((entry or {}).get("channel") or (entry or {}).get("uploader") or sub.get("title") or ""),
        channel_id=str(sub.get("channel_id") or ""),
        published_at=published_at,
        profile_id=subscription_media_profile_id(sub),
        redownload=redownload,
    )
    return bool(created)


def v3_scan_subscription(channel_id, deep=False, redownload=False):
    with db() as conn:
        row = conn.execute(
            "SELECT * FROM subscriptions WHERE channel_id = ? AND active = 1",
            (channel_id,),
        ).fetchone()
    if not row:
        raise RuntimeError("Subscription was not found.")
    sub = dict(row)
    if not subscription_download_enabled(sub):
        return {"found": 0, "queued": 0, "message": "Downloads are disabled for this channel."}

    entries = []
    if not deep:
        entries = youtube_channel_feed(channel_id, force=True)
        entries = [
            {
                "id": item.get("video_id"),
                "title": item.get("title"),
                "url": item.get("video_url"),
                "published_at": item.get("published_at"),
                "channel": item.get("channel_title") or sub.get("title"),
            }
            for item in entries
        ]
    else:
        channel_url = str(sub.get("channel_url") or f"https://www.youtube.com/channel/{channel_id}").rstrip("/")
        if not channel_url.endswith("/videos"):
            channel_url += "/videos"
        limit = setting_int("downloader_deep_scan_limit", 500, 25, 5000)
        options = {
            "quiet": True,
            "no_warnings": True,
            "skip_download": True,
            "extract_flat": "in_playlist",
            "playlistend": limit,
            "socket_timeout": 30,
        }
        try:
            with yt_dlp.YoutubeDL(options) as ydl:
                info = ydl.extract_info(channel_url, download=False)
        except Exception as exc:
            if setting_bool("downloader_auth_retry", True) and should_retry_with_cookies(exc):
                with yt_dlp.YoutubeDL(_v3_authenticated_options(options)) as ydl:
                    info = ydl.extract_info(channel_url, download=False)
            else:
                raise
        entries = list((info or {}).get("entries") or [])

    queued = 0
    cutoff = date.fromisoformat(subscription_cutoff(sub))
    for entry in entries:
        entry_date = _v3_parse_entry_date(entry)
        # Channel playlists are newest first. Once a dated entry is older than
        # the cutoff during a deep scan there is no value walking further back.
        if deep and entry_date and entry_date < cutoff:
            break
        if _v3_queue_entry(sub, entry, redownload=redownload):
            queued += 1
    return {"found": len(entries), "queued": queued}


def enqueue_subscription_scan(channel_id, deep=False, redownload=False):
    with db() as conn:
        existing = conn.execute(
            """
            SELECT id FROM subscription_scan_jobs
            WHERE channel_id = ? AND status IN ('queued','running')
              AND deep = ? AND redownload = ?
            ORDER BY id DESC LIMIT 1
            """,
            (channel_id, 1 if deep else 0, 1 if redownload else 0),
        ).fetchone()
        if existing:
            return int(existing["id"]), False
        cur = conn.execute(
            """
            INSERT INTO subscription_scan_jobs
                (channel_id, deep, redownload, status, created_at)
            VALUES (?, ?, ?, 'queued', ?)
            """,
            (channel_id, 1 if deep else 0, 1 if redownload else 0, now_iso()),
        )
        job_id = int(cur.lastrowid)
    scan_queue.put(job_id)
    return job_id, True


def _v3_scan_worker():
    while True:
        scan_id = scan_queue.get()
        try:
            with db() as conn:
                job = conn.execute(
                    "SELECT * FROM subscription_scan_jobs WHERE id = ?",
                    (scan_id,),
                ).fetchone()
                if not job:
                    continue
                conn.execute(
                    "UPDATE subscription_scan_jobs SET status='running', started_at=? WHERE id=?",
                    (now_iso(), scan_id),
                )
            try:
                result = v3_scan_subscription(
                    job["channel_id"],
                    deep=bool(job["deep"]),
                    redownload=bool(job["redownload"]),
                )
                with db() as conn:
                    conn.execute(
                        """
                        UPDATE subscription_scan_jobs
                        SET status='completed', finished_at=?, found=?, queued=?, error=NULL
                        WHERE id=?
                        """,
                        (now_iso(), result["found"], result["queued"], scan_id),
                    )
            except Exception as exc:
                with db() as conn:
                    conn.execute(
                        """
                        UPDATE subscription_scan_jobs
                        SET status='failed', finished_at=?, error=?
                        WHERE id=?
                        """,
                        (now_iso(), str(exc)[:1500], scan_id),
                    )
                log_activity(
                    "scan",
                    "Channel scan failed",
                    f"{job['channel_id']}: {exc}",
                    "error",
                    job["channel_id"],
                )
        finally:
            scan_queue.task_done()


def start_scan_worker():
    global scan_worker_started
    if scan_worker_started:
        return
    scan_worker_started = True
    with db() as conn:
        conn.execute(
            "UPDATE subscription_scan_jobs SET status='queued', started_at=NULL WHERE status='running'"
        )
        rows = conn.execute(
            "SELECT id FROM subscription_scan_jobs WHERE status='queued' ORDER BY id"
        ).fetchall()
    threading.Thread(
        target=_v3_scan_worker,
        name="youtube-subscription-scan-worker",
        daemon=True,
    ).start()
    for row in rows:
        scan_queue.put(int(row["id"]))


def v3_scan_all_enabled():
    with db() as conn:
        rows = [
            dict(row)
            for row in conn.execute(
                """
                SELECT * FROM subscriptions
                WHERE active=1 AND download_enabled=1
                ORDER BY title COLLATE NOCASE
                """
            ).fetchall()
        ]
    workers = setting_int("downloader_scan_workers", 4, 1, 12)
    found = queued = errors = 0

    def scan(row):
        return v3_scan_subscription(row["channel_id"], deep=False, redownload=False)

    with ThreadPoolExecutor(max_workers=workers) as pool:
        futures = [pool.submit(scan, row) for row in rows]
        for future in as_completed(futures):
            try:
                result = future.result()
                found += int(result.get("found") or 0)
                queued += int(result.get("queued") or 0)
            except Exception:
                errors += 1
    return {"checked": len(rows), "found": found, "queued": queued, "errors": errors}


def add_pending_sources():
    # V3 "source registration" is local-only. Mark enabled rows registered and
    # queue one serial deep scan so the chosen history window can be honoured.
    with db() as conn:
        rows = [
            dict(row)
            for row in conn.execute(
                """
                SELECT * FROM subscriptions
                WHERE active=1 AND download_enabled=1 AND pinchflat_added=0
                ORDER BY first_seen_at, title COLLATE NOCASE
                """
            ).fetchall()
        ]
        for row in rows:
            conn.execute(
                """
                UPDATE subscriptions
                SET pinchflat_added=1, pinchflat_source_id=channel_id,
                    source_authorised=1, last_error=NULL
                WHERE channel_id=?
                """,
                (row["channel_id"],),
            )
    for row in rows:
        enqueue_subscription_scan(row["channel_id"], deep=True)
    return {"pending": len(rows), "added": len(rows), "errors": 0}


def apply_subscription_source_authority(sub, apply_settings=False):
    channel_id = str(sub.get("channel_id") or "")
    enabled = bool(sub.get("active")) and bool(sub.get("download_enabled"))
    with db() as conn:
        conn.execute(
            """
            UPDATE subscriptions
            SET pinchflat_added=?, pinchflat_source_id=?, source_authorised=?,
                last_error=NULL
            WHERE channel_id=?
            """,
            (1 if enabled else 0, channel_id if enabled else None, 1 if enabled else 0, channel_id),
        )
        if not enabled:
            conn.execute(
                """
                UPDATE downloads SET status='cancelled', phase='Cancelled'
                WHERE channel_id=? AND status='queued' AND source_type LIKE 'subscription%'
                """,
                (channel_id,),
            )
    if enabled:
        enqueue_subscription_scan(channel_id, deep=True)
        return {"state": "enabled", "pending": False}
    return {"state": "disabled", "pending": False}


def resolve_pinchflat_source_id(sub, *args, **kwargs):
    if bool(row_value(sub, "active", 0)) and bool(row_value(sub, "download_enabled", 0)):
        return str(row_value(sub, "channel_id", "") or "")
    return None


def update_pinchflat_source_settings(*args, **kwargs):
    return True


def prepare_pinchflat_source_for_removal(*args, **kwargs):
    return True


def delete_pinchflat_source(*args, **kwargs):
    return True


def clear_subscription_pinchflat_link(channel_id, source_id=None):
    with db() as conn:
        conn.execute(
            """
            UPDATE subscriptions
            SET pinchflat_added=0, pinchflat_source_id=NULL, source_authorised=0
            WHERE channel_id=?
            """,
            (channel_id,),
        )


def reconcile_removed_pinchflat_sources():
    return {"checked": 0, "removed": 0, "errors": 0}


def reconcile_active_source_authority():
    with db() as conn:
        rows = [dict(row) for row in conn.execute("SELECT * FROM subscriptions WHERE active=1").fetchall()]
    changed = errors = 0
    for row in rows:
        expected = bool(row.get("download_enabled"))
        actual = bool(row.get("pinchflat_added"))
        if expected != actual:
            apply_subscription_source_authority(row)
            changed += 1
    return {"checked": len(rows), "changed": changed, "errors": errors}


def retry_failed_source_updates():
    with db() as conn:
        rows = conn.execute(
            "SELECT channel_id FROM subscriptions WHERE active=1 AND COALESCE(last_error,'')!=''"
        ).fetchall()
        conn.execute(
            "UPDATE subscriptions SET last_error=NULL, retry_count=0 WHERE active=1"
        )
    return {"attempted": len(rows), "fixed": len(rows), "errors": 0}


def execute_pinchflat_source_action(source_id, action):
    channel_id = str(source_id or "")
    if action in {"force_scan", "download_pending"}:
        enqueue_subscription_scan(channel_id, deep=True)
        return {"queued": True}
    if action == "redownload_existing":
        enqueue_subscription_scan(channel_id, deep=True, redownload=True)
        return {"queued": True}
    if action == "refresh_metadata":
        with db() as conn:
            row = conn.execute("SELECT title FROM subscriptions WHERE channel_id=?", (channel_id,)).fetchone()
        if row and emby_configured():
            emby_refresh_library(channel_id=channel_id, channel_title=row["title"])
        return {"queued": True}
    if action == "sync_files":
        storage_snapshot(force=True)
        return {"queued": True}
    raise RuntimeError("Unknown downloader action.")


def pinchflat_sync_once():
    if not sync_lock.acquire(blocking=False):
        return {"status": "busy", "message": "Another sync is running."}
    try:
        add_pending_sources()
        result = v3_scan_all_enabled()
        message = (
            f"Downloader scanned {result['checked']} enabled channel(s), "
            f"found {result['found']} recent item(s), queued {result['queued']} download(s). "
            f"Errors {result['errors']}."
        )
        log_activity(
            "downloader_sync",
            "Subscription downloader scan completed",
            message,
            "success" if result["errors"] == 0 else "warning",
        )
        return {
            "status": "ok" if result["errors"] == 0 else "completed_with_errors",
            "message": message,
            **result,
        }
    except Exception as exc:
        log_activity("downloader_sync", "Subscription downloader scan failed", str(exc), "error")
        return {"status": "error", "message": str(exc), "errors": 1}
    finally:
        sync_lock.release()


def scheduled_pinchflat_force_index():
    # V2 compatibility scheduler: scheduled channel scans are lightweight RSS
    # checks. Deep scans are explicit/manual so hundreds of channels can never
    # create the force-index storm that prompted the V3 rewrite.
    return {"status": "native", "message": "Native scheduled scans are handled by the downloader sync."}


def pinchflat_force_index_status():
    with db() as conn:
        fav = conn.execute(
            """
            SELECT COUNT(*) AS c FROM subscriptions s
            WHERE s.active=1 AND s.download_enabled=1
              AND EXISTS (SELECT 1 FROM favourite_channels f WHERE f.channel_id=s.channel_id)
            """
        ).fetchone()["c"]
        other = conn.execute(
            """
            SELECT COUNT(*) AS c FROM subscriptions s
            WHERE s.active=1 AND s.download_enabled=1
              AND NOT EXISTS (SELECT 1 FROM favourite_channels f WHERE f.channel_id=s.channel_id)
            """
        ).fetchone()["c"]
    return {
        "favourites": {"eligible": int(fav or 0)},
        "non_favourites": {"eligible": int(other or 0)},
    }


def pinchflat_retention_inventory(channel_id=""):
    query = """
        SELECT id, video_id, channel_id, channel_title, title, output_path,
               published_at, finished_at
        FROM downloads
        WHERE status='completed' AND source_type LIKE 'subscription%'
    """
    params = []
    if channel_id:
        query += " AND channel_id=?"
        params.append(channel_id)
    with db() as conn:
        rows = [dict(row) for row in conn.execute(query, params).fetchall()]
    result = []
    for row in rows:
        path = Path(str(row.get("output_path") or ""))
        if not path.exists() or not path.is_file():
            continue
        try:
            size = path.stat().st_size
        except OSError:
            size = 0
        result.append({
            "media_item_id": int(row["id"]),
            "media_uuid": str(row["id"]),
            "video_id": str(row.get("video_id") or ""),
            "title": str(row.get("title") or "YouTube video"),
            "channel_id": str(row.get("channel_id") or ""),
            "channel_title": str(row.get("channel_title") or row.get("channel_id") or ""),
            "source_id": str(row.get("channel_id") or ""),
            "prevent_culling": False,
            "uploaded_at": _retention_datetime(row.get("published_at")),
            "downloaded_at": _retention_datetime(row.get("finished_at")),
            "size_bytes": size,
            "thumbnail_url": (
                f"https://i.ytimg.com/vi/{row['video_id']}/hqdefault.jpg"
                if row.get("video_id") else ""
            ),
            "video_url": (
                f"https://www.youtube.com/watch?v={row['video_id']}"
                if row.get("video_id") else ""
            ),
        })
    return result


def _retention_delete_media_batch(media_ids):
    deleted = []
    errors = {}
    with db() as conn:
        rows = {
            int(row["id"]): dict(row)
            for row in conn.execute(
                f"SELECT * FROM downloads WHERE id IN ({','.join('?' for _ in media_ids)})",
                media_ids,
            ).fetchall()
        } if media_ids else {}
    for media_id in media_ids:
        row = rows.get(int(media_id))
        if not row:
            errors[int(media_id)] = "Download record not found."
            continue
        try:
            path = Path(str(row.get("output_path") or ""))
            if path.exists() and path.is_file():
                stem = path.with_suffix("")
                path.unlink()
                for suffix in (".info.json", ".jpg", ".jpeg", ".webp", ".png", ".nfo"):
                    candidate = Path(str(stem) + suffix)
                    if candidate.exists() and candidate.is_file():
                        candidate.unlink()
            with db() as conn:
                conn.execute(
                    "UPDATE downloads SET status='retention_deleted', phase='Removed by retention' WHERE id=?",
                    (media_id,),
                )
            deleted.append(int(media_id))
        except Exception as exc:
            errors[int(media_id)] = str(exc)[:500]
    return {"deleted": deleted, "errors": errors}


def pinchflat_download_overview(queue_limit=100):
    with db() as conn:
        active_rows = [
            dict(row) for row in conn.execute(
                """
                SELECT * FROM downloads
                WHERE status IN ('downloading','processing')
                ORDER BY id
                """
            ).fetchall()
        ]
        waiting_rows = [
            dict(row) for row in conn.execute(
                """
                SELECT * FROM downloads
                WHERE status='queued'
                ORDER BY id
                LIMIT ?
                """,
                (1000000 if int(queue_limit or 0) < 0 else max(20, min(int(queue_limit or 0) or 100, 500)),),
            ).fetchall()
        ]
        scan_rows = [
            dict(row) for row in conn.execute(
                """
                SELECT * FROM subscription_scan_jobs
                WHERE status IN ('queued','running')
                ORDER BY CASE status WHEN 'running' THEN 0 ELSE 1 END, id
                LIMIT 20
                """
            ).fetchall()
        ]
        last = conn.execute(
            """
            SELECT * FROM downloads
            WHERE status='completed'
            ORDER BY finished_at DESC, id DESC LIMIT 1
            """
        ).fetchone()
        membership_errors = conn.execute(
            "SELECT COUNT(*) AS c FROM downloads WHERE failure_code='membership_required'"
        ).fetchone()["c"]

    def item(row):
        return {
            "job_id": row.get("job_id"),
            "title": row.get("title") or row.get("youtube_url") or "YouTube video",
            "channel_title": row.get("channel_title") or "",
            "state": row.get("status") or "",
            "status": row.get("phase") or str(row.get("status") or "").title(),
            "started_at": row.get("started_at") or "",
            "attempt": 1,
            "speed": row.get("speed") or "",
            "progress": float(row.get("progress") or 0),
            "thumbnail_url": (
                f"https://i.ytimg.com/vi/{row['video_id']}/hqdefault.jpg"
                if row.get("video_id") else ""
            ),
            "video_id": row.get("video_id") or "",
        }

    tasks = [
        {
            "job_id": f"scan-{row['id']}",
            "worker": "Channel Scanner",
            "label": "Channel Scan",
            "state": row["status"],
            "status": "Running" if row["status"] == "running" else "Waiting",
            "started_at": row.get("started_at") or "",
            "scheduled_at": row.get("created_at") or "",
        }
        for row in scan_rows
    ]
    return {
        "active": [item(row) for row in active_rows],
        "waiting": [item(row) for row in waiting_rows],
        "summary": {
            "active": len(active_rows),
            "waiting": len(waiting_rows),
            "tasks_active": sum(1 for row in scan_rows if row["status"] == "running"),
            "tasks_waiting": sum(1 for row in scan_rows if row["status"] == "queued"),
            "membership_errors": int(membership_errors or 0),
        },
        "tasks": tasks,
        "last_downloaded": item(dict(last)) if last else None,
    }


def pinchflat_pending_task_count():
    with db() as conn:
        return int(conn.execute(
            "SELECT COUNT(*) AS c FROM subscription_scan_jobs WHERE status IN ('queued','running')"
        ).fetchone()["c"] or 0)


def pinchflat_task_block_enabled():
    return setting_bool("pinchflat_task_block_enabled", False)


def pinchflat_delete_all_tasks():
    with db() as conn:
        scan = conn.execute(
            "UPDATE subscription_scan_jobs SET status='cancelled', finished_at=? WHERE status IN ('queued','running')",
            (now_iso(),),
        ).rowcount
        downloads = conn.execute(
            "UPDATE downloads SET status='cancelled', phase='Cancelled' WHERE status='queued' AND source_type LIKE 'subscription%'"
        ).rowcount
    return {"cancelled": int(scan or 0) + int(downloads or 0), "deleted": 0}


def pinchflat_resume_all_tasks():
    return {"resumed": True}


def start_pinchflat_task_blocker():
    # No external task database exists in V3. Task suppression is enforced
    # when native scan/download work is queued.
    return None


def _v3_import_existing_library():
    if setting_bool("v3_library_import_complete", False):
        return
    imported = 0
    shows_root = DOWNLOAD_ROOT / "shows"
    if not shows_root.exists():
        set_setting("v3_library_import_complete", "1")
        return
    try:
        for info_path in shows_root.rglob("*.info.json"):
            try:
                info = json.loads(info_path.read_text(encoding="utf-8"))
                video_id = str(info.get("id") or "").strip()
                if not video_id:
                    continue
                with db() as conn:
                    exists = conn.execute(
                        "SELECT 1 FROM downloads WHERE video_id=? AND source_type LIKE 'subscription%' LIMIT 1",
                        (video_id,),
                    ).fetchone()
                if exists:
                    continue
                base = str(info_path)[:-10]  # strip .info.json
                media_path = ""
                for candidate in info_path.parent.glob(Path(base).name + ".*"):
                    if candidate.suffix.lower() in {".mp4", ".mkv", ".webm", ".m4a", ".mp3", ".opus", ".flac"}:
                        media_path = str(candidate)
                        break
                if not media_path:
                    continue
                upload_date = str(info.get("upload_date") or "")
                published = (
                    f"{upload_date[:4]}-{upload_date[4:6]}-{upload_date[6:8]}"
                    if re.fullmatch(r"\d{8}", upload_date) else ""
                )
                with db() as conn:
                    conn.execute(
                        """
                        INSERT INTO downloads (
                            job_id, source_type, youtube_url, video_id, title,
                            channel_title, status, phase, progress, output_path,
                            created_at, started_at, finished_at, channel_id,
                            published_at, profile_id, auth_mode
                        ) VALUES (?, 'subscription_import', ?, ?, ?, ?, 'completed',
                                  'Imported existing library', 100, ?, ?, ?, ?, ?, ?, ?, 'import')
                        """,
                        (
                            "import-" + secrets.token_hex(10),
                            str(info.get("webpage_url") or f"https://www.youtube.com/watch?v={video_id}"),
                            video_id,
                            str(info.get("title") or "YouTube video"),
                            str(info.get("channel") or info.get("uploader") or ""),
                            media_path,
                            now_iso(), now_iso(), now_iso(),
                            str(info.get("channel_id") or ""),
                            published,
                            "1080p",
                        ),
                    )
                imported += 1
            except Exception:
                continue
        set_setting("v3_library_import_complete", "1")
        log_activity(
            "migration",
            "Existing YouTube library imported",
            f"Imported {imported} existing media item(s) into the V3 downloader database.",
            "success",
        )
    except Exception as exc:
        log_activity("migration", "Existing library import failed", str(exc), "warning")


@app.post("/settings/downloader/auth/upload")
def downloader_cookie_upload():
    try:
        stats = save_cookie_upload(request.files.get("cookie_file"), YOUTUBE_COOKIE_PATH)
        log_activity(
            "downloader_auth",
            "YouTube cookies uploaded",
            f"Stored {stats['youtube_cookies']} YouTube cookie(s).",
            "success",
        )
        flash("YouTube cookie file uploaded and validated.", "success")
    except Exception as exc:
        flash(f"Cookie file could not be saved: {exc}", "error")
    return redirect(url_for("index") + "#pinchflat")


@app.post("/settings/downloader/auth/remove")
def downloader_cookie_remove():
    try:
        YOUTUBE_COOKIE_PATH.unlink(missing_ok=True)
        flash("YouTube cookie file removed.", "success")
    except Exception as exc:
        flash(f"Cookie file could not be removed: {exc}", "error")
    return redirect(url_for("index") + "#pinchflat")


@app.post("/settings/downloader/auth/test")
def downloader_cookie_test():
    try:
        result = test_cookie_authentication(
            YOUTUBE_COOKIE_PATH,
            po_token=get_setting("downloader_po_token", ""),
            custom_options=_v3_custom_yt_dlp_options(),
        )
        flash(f"Authenticated yt-dlp test succeeded ({result['title']}).", "success")
    except Exception as exc:
        flash(f"Authenticated yt-dlp test failed: {exc}", "error")
    return redirect(url_for("index") + "#pinchflat")


@app.post("/settings/downloader/advanced")
def save_downloader_advanced():
    profile_id = v3_profile_id(request.form.get("downloader_default_profile"))
    concurrency = max(1, min(8, int(request.form.get("downloader_worker_concurrency", "1") or 1)))
    scan_workers = max(1, min(12, int(request.form.get("downloader_scan_workers", "4") or 4)))
    deep_limit = max(25, min(5000, int(request.form.get("downloader_deep_scan_limit", "500") or 500)))
    custom = str(request.form.get("downloader_custom_yt_dlp_options", "{}") or "{}").strip()
    parse_custom_yt_dlp_options(custom)
    set_setting("downloader_default_profile", profile_id)
    set_setting("downloader_worker_concurrency", str(concurrency))
    set_setting("downloader_scan_workers", str(scan_workers))
    set_setting("downloader_deep_scan_limit", str(deep_limit))
    set_setting("downloader_po_token", str(request.form.get("downloader_po_token", "") or "").strip())
    set_setting("downloader_custom_yt_dlp_options", custom or "{}")
    set_setting("downloader_auth_retry", "1" if request.form.get("downloader_auth_retry") == "1" else "0")
    start_download_worker()
    flash("Downloader settings saved.", "success")
    return redirect(url_for("index") + "#pinchflat")



@app.route("/setup", methods=["GET", "POST"])
def setup_admin():
    if users_exist():
        return redirect(url_for("login"))

    if request.method == "POST":
        username_raw = request.form.get("username", "").strip()
        username = normalise_username(username_raw)
        display_name = request.form.get("display_name", "").strip()
        password = request.form.get("password", "")
        confirm = request.form.get("confirm_password", "")
        enable_2fa = request.form.get("enable_2fa") == "1"

        if not valid_username(username_raw):
            flash("Use 3 to 64 letters, numbers, dots, dashes or underscores for the username.", "error")
        elif not valid_password(password):
            flash(f"Use a password of at least {PASSWORD_MIN_LENGTH} characters.", "error")
        elif password != confirm:
            flash("The passwords do not match.", "error")
        else:
            with db() as conn:
                cur = conn.execute(
                    """
                    INSERT INTO users (
                        username, display_name, password_hash, role, active,
                        created_at, session_version
                    ) VALUES (?, ?, ?, 'admin', 1, ?, 1)
                    """,
                    (username, display_name or username_raw, hash_password(password), now_iso()),
                )
                user_id = cur.lastrowid
            user = get_user_by_id(user_id)
            complete_login(user, "first-run setup")
            record_auth_event("admin_created", True, user=user, message="Initial administrator account created.")
            if enable_2fa:
                return redirect(url_for("two_factor_setup"))
            return redirect(url_for("index"))

    return render_template("setup.html", version=VERSION, password_min=PASSWORD_MIN_LENGTH)


@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        if login_ip_blocked():
            record_auth_event("login_rate_limited", False, username="", message="Too many failed sign-in attempts from this IP address.")
            flash("Too many failed sign-in attempts from this address. Try again in a few minutes.", "error")
            return render_template("login.html", version=VERSION)

        username = normalise_username(request.form.get("username", ""))
        password = request.form.get("password", "")
        user = get_user_by_username(username)
        generic_error = "The username or password is incorrect."

        if not user or not user["active"]:
            record_auth_event("login_failed", False, username=username, message="Unknown or inactive account.")
            flash(generic_error, "error")
            return render_template("login.html", version=VERSION)

        now = time.time()
        locked_until = float(user["locked_until"] or 0)
        if locked_until > now:
            remaining = max(1, int((locked_until - now + 59) // 60))
            record_auth_event("login_locked", False, user=user, message="Login attempted during lockout.")
            flash(f"Too many failed attempts. Try again in about {remaining} minute(s).", "error")
            return render_template("login.html", version=VERSION)

        if not verify_password(user["password_hash"], password):
            attempts = int(user["failed_attempts"] or 0) + 1
            lock_until = None
            if attempts >= lockout_attempt_limit():
                lock_until = now + lockout_minutes() * 60
                attempts = 0
            with db() as conn:
                conn.execute(
                    "UPDATE users SET failed_attempts = ?, locked_until = ? WHERE id = ?",
                    (attempts, lock_until, user["id"]),
                )
            record_auth_event("login_failed", False, user=user, message="Incorrect password.")
            flash(generic_error, "error")
            return render_template("login.html", version=VERSION)

        maybe_rehash_password(user["id"], user["password_hash"], password)
        with db() as conn:
            conn.execute("UPDATE users SET failed_attempts = 0, locked_until = NULL WHERE id = ?", (user["id"],))

        if user["totp_enabled"]:
            session.clear()
            session["pending_2fa_user_id"] = int(user["id"])
            session["pending_2fa_started"] = time.time()
            return redirect(url_for("login_2fa"))

        complete_login(user)
        return redirect(url_for("index"))

    return render_template("login.html", version=VERSION)


@app.route("/login/2fa", methods=["GET", "POST"])
def login_2fa():
    user_id = session.get("pending_2fa_user_id")
    started = float(session.get("pending_2fa_started") or 0)
    if not user_id or not started or time.time() - started > 600:
        session.clear()
        flash("The two-factor sign-in expired. Start again.", "error")
        return redirect(url_for("login"))

    user = get_user_by_id(user_id)
    if not user or not user["active"]:
        session.clear()
        return redirect(url_for("login"))

    if request.method == "POST":
        code = request.form.get("code", "")
        ok, method = verify_user_second_factor(user, code)
        if ok:
            complete_login(user, method or "two-factor authentication")
            return redirect(url_for("index"))
        record_auth_event("2fa_failed", False, user=user, message="Incorrect authenticator or recovery code.")
        flash("The authenticator or recovery code is incorrect.", "error")

    return render_template("two_factor_login.html", version=VERSION, username=user["username"])


@app.post("/logout")
def logout():
    user = current_user_record()
    if user:
        record_auth_event("logout", True, user=user, message="Signed out.")
    session.clear()
    return redirect(url_for("login"))


@app.post("/account/password")
def change_password():
    user = current_user_record()
    current = request.form.get("current_password", "")
    new = request.form.get("new_password", "")
    confirm = request.form.get("confirm_password", "")

    if not user or not verify_password(user["password_hash"], current):
        flash("The current password is incorrect.", "error")
    elif not valid_password(new):
        flash(f"Use a new password of at least {PASSWORD_MIN_LENGTH} characters.", "error")
    elif new != confirm:
        flash("The new passwords do not match.", "error")
    else:
        new_version = int(user["session_version"] or 1) + 1
        with db() as conn:
            conn.execute(
                "UPDATE users SET password_hash = ?, session_version = ? WHERE id = ?",
                (hash_password(new), new_version, user["id"]),
            )
        session["auth_session_version"] = new_version
        record_auth_event("password_changed", True, user=user, message="Password changed.")
        flash("Password changed. Other signed-in sessions were invalidated.", "success")
    return redirect(url_for("index") + "#security")


@app.route("/account/2fa/setup", methods=["GET", "POST"])
def two_factor_setup():
    user = current_user_record()
    if not user:
        return redirect(url_for("login"))
    if user["totp_enabled"]:
        flash("Two-factor authentication is already enabled.", "success")
        return redirect(url_for("index") + "#security")

    secret = session.get("totp_setup_secret")
    if not secret:
        secret = generate_totp_secret()
        session["totp_setup_secret"] = secret

    if request.method == "POST":
        code = request.form.get("code", "")
        if not verify_totp(secret, code):
            flash("The authenticator code is incorrect. Try the current six-digit code.", "error")
        else:
            codes = generate_recovery_codes()
            hashes = [recovery_code_hash(code) for code in codes]
            new_version = int(user["session_version"] or 1) + 1
            with db() as conn:
                conn.execute(
                    """
                    UPDATE users
                    SET totp_secret = ?, totp_enabled = 1,
                        recovery_code_hashes = ?, session_version = ?
                    WHERE id = ?
                    """,
                    (secret, json.dumps(hashes), new_version, user["id"]),
                )
            session["auth_session_version"] = new_version
            session.pop("totp_setup_secret", None)
            session["new_recovery_codes"] = codes
            record_auth_event("2fa_enabled", True, user=user, message="TOTP two-factor authentication enabled.")
            return redirect(url_for("show_recovery_codes"))

    return render_template(
        "two_factor_setup.html",
        version=VERSION,
        username=user["username"],
        secret=secret,
        qr_data=totp_qr_data_uri(user["username"], secret),
        provisioning_uri=totp_provisioning_uri(user["username"], secret),
    )


@app.get("/account/2fa/recovery-codes")
def show_recovery_codes():
    codes = session.get("new_recovery_codes")
    if not codes:
        return redirect(url_for("index") + "#security")
    return render_template("recovery_codes.html", version=VERSION, recovery_codes=codes)


@app.post("/account/2fa/recovery-codes/ack")
def acknowledge_recovery_codes():
    session.pop("new_recovery_codes", None)
    return redirect(url_for("index") + "#security")


@app.post("/account/2fa/disable")
def two_factor_disable():
    user = current_user_record()
    password = request.form.get("current_password", "")
    code = request.form.get("code", "")
    if not user or not user["totp_enabled"]:
        flash("Two-factor authentication is not enabled.", "error")
    elif not verify_password(user["password_hash"], password):
        flash("The current password is incorrect.", "error")
    else:
        ok, _ = verify_user_second_factor(user, code)
        if not ok:
            flash("The authenticator or recovery code is incorrect.", "error")
        else:
            new_version = int(user["session_version"] or 1) + 1
            with db() as conn:
                conn.execute(
                    """
                    UPDATE users
                    SET totp_secret = NULL, totp_enabled = 0,
                        recovery_code_hashes = '[]', session_version = ?
                    WHERE id = ?
                    """,
                    (new_version, user["id"]),
                )
            session["auth_session_version"] = new_version
            record_auth_event("2fa_disabled", True, user=user, message="Two-factor authentication disabled.")
            flash("Two-factor authentication disabled.", "success")
    return redirect(url_for("index") + "#security")


@app.post("/account/2fa/recovery-codes/regenerate")
def regenerate_recovery_codes():
    user = current_user_record()
    password = request.form.get("current_password", "")
    code = request.form.get("code", "")
    if not user or not user["totp_enabled"]:
        flash("Enable two-factor authentication first.", "error")
    elif not verify_password(user["password_hash"], password):
        flash("The current password is incorrect.", "error")
    elif not verify_totp(user["totp_secret"], code):
        flash("The authenticator code is incorrect.", "error")
    else:
        codes = generate_recovery_codes()
        hashes = [recovery_code_hash(value) for value in codes]
        with db() as conn:
            conn.execute(
                "UPDATE users SET recovery_code_hashes = ? WHERE id = ?",
                (json.dumps(hashes), user["id"]),
            )
        session["new_recovery_codes"] = codes
        record_auth_event("recovery_codes_regenerated", True, user=user, message="Recovery codes regenerated.")
        return redirect(url_for("show_recovery_codes"))
    return redirect(url_for("index") + "#security")


@app.post("/account/logout-all")
def logout_all_sessions():
    user = current_user_record()
    if user:
        with db() as conn:
            conn.execute(
                "UPDATE users SET session_version = session_version + 1 WHERE id = ?",
                (user["id"],),
            )
        record_auth_event("logout_all", True, user=user, message="All sessions invalidated.")
    session.clear()
    flash("All sessions were signed out. Sign in again.", "success")
    return redirect(url_for("login"))


@app.post("/settings/security")
def save_security_settings():
    try:
        remember_days = int(request.form.get("remember_login_days", "30") or 30)
        timeout = int(request.form.get("session_timeout_minutes", "720") or 720)
        attempts = int(request.form.get("lockout_attempts", "5") or 5)
        duration = int(request.form.get("lockout_minutes", "15") or 15)
    except ValueError:
        flash("Security settings must be whole numbers.", "error")
        return redirect(url_for("index") + "#security")

    remember_days = max(1, min(365, remember_days))
    set_setting("auth_remember_login_days", str(remember_days))
    set_setting("auth_session_timeout_minutes", str(max(5, min(10080, timeout))))

    if session.get("auth_user_id"):
        session.permanent = True
        session["auth_remember_until"] = time.time() + (remember_days * 86400)
    set_setting("auth_lockout_attempts", str(max(3, min(50, attempts))))
    set_setting("auth_lockout_minutes", str(max(1, min(1440, duration))))
    user = current_user_record()
    record_auth_event("security_settings", True, user=user, message="Authentication settings updated.")
    flash("Security settings saved.", "success")
    return redirect(url_for("index") + "#security")


@app.post("/users/create")
def create_user():
    username_raw = request.form.get("username", "").strip()
    username = normalise_username(username_raw)
    display_name = request.form.get("display_name", "").strip()
    password = request.form.get("password", "")
    role = request.form.get("role", "viewer")
    if role not in {"admin", "viewer"}:
        role = "viewer"

    if not valid_username(username_raw):
        flash("Use 3 to 64 letters, numbers, dots, dashes or underscores for the username.", "error")
    elif not valid_password(password):
        flash(f"Use a password of at least {PASSWORD_MIN_LENGTH} characters.", "error")
    else:
        try:
            with db() as conn:
                conn.execute(
                    """
                    INSERT INTO users (
                        username, display_name, password_hash, role, active,
                        created_at, session_version
                    ) VALUES (?, ?, ?, ?, 1, ?, 1)
                    """,
                    (username, display_name or username_raw, hash_password(password), role, now_iso()),
                )
            admin = current_user_record()
            record_auth_event("user_created", True, user=admin, username=username, message=f"Created {role} user {username}.")
            flash(f"User {username} created.", "success")
        except sqlite3.IntegrityError:
            flash("That username already exists.", "error")
    return redirect(url_for("index") + "#security")


@app.post("/users/<int:user_id>/toggle")
def toggle_user(user_id):
    admin = current_user_record()
    target = get_user_by_id(user_id)
    if not target:
        flash("User not found.", "error")
    elif admin and int(admin["id"]) == int(user_id):
        flash("You cannot disable your own account.", "error")
    else:
        new_active = 0 if target["active"] else 1
        with db() as conn:
            conn.execute(
                """
                UPDATE users
                SET active = ?, session_version = session_version + 1
                WHERE id = ?
                """,
                (new_active, user_id),
            )
        record_auth_event(
            "user_status",
            True,
            user=admin,
            username=target["username"],
            message=f"Set {target['username']} active={bool(new_active)}.",
        )
        flash(f"User {target['username']} {'enabled' if new_active else 'disabled'}.", "success")
    return redirect(url_for("index") + "#security")


@app.post("/users/<int:user_id>/delete")
def delete_user(user_id):
    admin = current_user_record()
    target = get_user_by_id(user_id)

    if not target:
        flash("User not found.", "error")
        return redirect(url_for("index") + "#security")

    if admin and int(admin["id"]) == int(user_id):
        flash("You cannot delete your own account.", "error")
        return redirect(url_for("index") + "#security")

    if target["role"] == "admin":
        with db() as conn:
            row = conn.execute(
                """
                SELECT COUNT(*) AS count
                FROM users
                WHERE role = 'admin' AND active = 1
                """
            ).fetchone()
        active_admins = int(row["count"] or 0)
        if target["active"] and active_admins <= 1:
            flash(
                "You cannot delete the last active Administrator account.",
                "error",
            )
            return redirect(url_for("index") + "#security")

    target_username = target["username"]
    record_auth_event(
        "user_deleted",
        True,
        user=admin,
        username=target_username,
        message=f"Deleted user {target_username}.",
    )

    with db() as conn:
        conn.execute("DELETE FROM users WHERE id = ?", (user_id,))

    flash(f"User {target_username} deleted.", "success")
    return redirect(url_for("index") + "#security")


@app.route("/")
def index():
    page_view = {
        "load_summary": setting_bool("page_load_summary", True),
        "load_pinchflat_downloads": setting_bool(
            "page_load_pinchflat_downloads",
            True,
        ),
        "load_latest_videos": setting_bool(
            "page_load_latest_videos",
            True,
        ),
        "load_subscriptions": setting_bool(
            "page_load_subscriptions",
            True,
        ),

        "min_pinchflat_downloads": setting_bool(
            "page_min_pinchflat_downloads",
            True,
        ),
        "min_latest_videos": setting_bool(
            "page_min_latest_videos",
            True,
        ),
        "min_subscriptions": setting_bool(
            "page_min_subscriptions",
            True,
        ),

        "show_summary_google": setting_bool(
            "page_show_summary_google",
            True,
        ),
        "show_summary_pinchflat": setting_bool(
            "page_show_summary_pinchflat",
            True,
        ),
        "show_summary_pinchflat_tasks": setting_bool(
            "page_show_summary_pinchflat_tasks",
            True,
        ),
        "show_summary_subscriptions": setting_bool(
            "page_show_summary_subscriptions",
            True,
        ),
        "show_summary_downloads": setting_bool(
            "page_show_summary_downloads",
            True,
        ),
        "show_summary_errors": setting_bool(
            "page_show_summary_errors",
            True,
        ),
        "show_summary_latest_download": setting_bool(
            "page_show_summary_latest_download",
            True,
        ),

        "button_sync": setting_bool(
            "page_button_sync",
            True,
        ),
        "button_refresh_youtube": setting_bool(
            "page_button_refresh_youtube",
            True,
        ),
        "button_single_download": setting_bool(
            "page_button_single_download",
            True,
        ),
        "button_discover": setting_bool(
            "page_button_discover",
            True,
        ),
        "button_favourites": setting_bool(
            "page_button_favourites",
            True,
        ),
        "button_logout": setting_bool(
            "page_button_logout",
            True,
        ),

        "channel_controls": setting_bool(
            "page_channel_controls",
            True,
        ),
        "channel_control_favourite": setting_bool(
            "page_channel_control_favourite",
            True,
        ),
        "channel_control_downloads": setting_bool(
            "page_channel_control_downloads",
            True,
        ),
        "channel_control_scan": setting_bool(
            "page_channel_control_scan",
            True,
        ),
        "channel_control_delete": setting_bool(
            "page_channel_control_delete",
            True,
        ),
        "channel_control_retention": setting_bool(
            "page_channel_control_retention",
            True,
        ),
    }

    page_section_order = setting_order(
        "page_section_order",
        (
            "summary",
            "pinchflat",
            "latest",
            "subscriptions",
        ),
        (
            "summary",
            "pinchflat",
            "latest",
            "subscriptions",
        ),
    )

    page_summary_order = setting_order(
        "page_summary_order",
        (
            "google",
            "pinchflat",
            "pinchflat_tasks",
            "latest_download",
            "subscriptions",
            "downloads",
            "errors",
        ),
        (
            "google",
            "pinchflat",
            "pinchflat_tasks",
            "latest_download",
            "subscriptions",
            "downloads",
            "errors",
        ),
    )

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
        if page_view["load_subscriptions"]:
            rows = conn.execute(
                """
                SELECT *
                FROM subscriptions
                ORDER BY active DESC, title COLLATE NOCASE ASC
                """
            ).fetchall()
        else:
            # Do not build hundreds of subscription rows when the section is
            # disabled in Page View. Summary counts are fetched separately.
            rows = []

        subscription_counts_row = conn.execute(
            """
            SELECT
                SUM(CASE WHEN active = 1 THEN 1 ELSE 0 END) AS active,
                SUM(CASE WHEN active = 1 AND download_enabled = 1 THEN 1 ELSE 0 END) AS enabled,
                SUM(CASE WHEN active = 1 AND download_enabled = 0 THEN 1 ELSE 0 END) AS disabled,
                SUM(CASE WHEN active = 1 AND pinchflat_added = 0 THEN 1 ELSE 0 END) AS pending,
                SUM(CASE WHEN last_error IS NOT NULL AND TRIM(last_error) != '' THEN 1 ELSE 0 END) AS errors,
                SUM(CASE WHEN active = 0 THEN 1 ELSE 0 END) AS removed
            FROM subscriptions
            """
        ).fetchone()

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
    fav_channel_ids = favourite_channel_ids()
    for sub in subs:
        sub["is_favourite"] = sub.get("channel_id") in fav_channel_ids

    if setting_bool("pin_favourites_to_top", True):
        subs.sort(
            key=lambda sub: (
                0 if sub.get("active") else 1,
                0 if sub.get("is_favourite") else 1,
                str(sub.get("title") or "").lower(),
            )
        )

    defaults = default_history_settings()
    pinchflat_container = pinchflat_container_status()
    # Resolve Pinchflat health once during the initial page request. Profile
    # checks and profile loading reuse the result instead of repeating the
    # Docker/HTTP health probe several times before the first page render.
    pinchflat_online = pinchflat_health()
    profile_status = pinchflat_profile_status(known_online=pinchflat_online)
    profiles = pinchflat_profiles(known_online=pinchflat_online)
    profile_settings = media_profile_settings(effective_media_profile_id())
    profile_settings = migrate_legacy_subscription_output_path(
        profile_settings
    )
    storage = storage_snapshot()
    storage_filesystem = download_filesystem_snapshot()
    storage_capacity = int(storage_filesystem.get("total") or 0)
    storage_content_percent = round(
        min(100.0, (storage["total"] / storage_capacity) * 100.0),
        2,
    ) if storage_capacity else 0.0
    pinchflat_stats = pinchflat_stats_summary(profiles, storage)
    for sub in subs:
        sub["disk_bytes"] = channel_disk_usage(sub.get("title"), storage)
        sub["disk_usage"] = format_bytes(sub["disk_bytes"])

    download_counts = {
        "queued": int(download_counts_row["queued"] or 0),
        "running": int(download_counts_row["running"] or 0),
        "failed": int(download_counts_row["failed"] or 0),
    }
    youtube_account = (
        youtube_account_stats()
        if google_connected
        else {
            "available": False,
            "error": "",
        }
    )
    api_stats = api_usage_stats()
    emby_playlist_id = get_setting("emby_download_playlist_id", "")
    auth = auth_context()
    with db() as conn:
        security_users = conn.execute(
            "SELECT id, username, display_name, role, active, totp_enabled, created_at, last_login_at FROM users ORDER BY username"
        ).fetchall()
        auth_events = conn.execute(
            "SELECT * FROM auth_events ORDER BY id DESC LIMIT 40"
        ).fetchall()

    counts = {
        "active": int(subscription_counts_row["active"] or 0),
        "enabled": int(subscription_counts_row["enabled"] or 0),
        "disabled": int(subscription_counts_row["disabled"] or 0),
        "pending": int(subscription_counts_row["pending"] or 0),
        "errors": int(subscription_counts_row["errors"] or 0),
        "removed": int(subscription_counts_row["removed"] or 0),
    }

    next_youtube_sync = None
    next_pinchflat_sync = None
    next_emby_sync = None
    for job_id, target_name in [
        ("youtube-subscription-sync", "youtube"),
        ("pinchflat-source-sync", "pinchflat"),
        ("emby-download-sync", "emby"),
    ]:
        try:
            job = scheduler.get_job(job_id)
            value = job.next_run_time.isoformat() if job and job.next_run_time else None
            if target_name == "youtube":
                next_youtube_sync = value
            elif target_name == "pinchflat":
                next_pinchflat_sync = value
            else:
                next_emby_sync = value
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
        app_url_from_yaml=bool(ENV_APP_URL),
        canonical_redirect=CANONICAL_REDIRECT,
        media_profile_id=effective_media_profile_id(),
        profiles=profiles,
        media_profile_settings=profile_settings,
        emby_output_path_template=EMBY_OUTPUT_PATH_TEMPLATE,
        sponsorblock_common_categories=SPONSORBLOCK_COMMON_CATEGORIES,
        pinchflat_online=pinchflat_online,
        pinchflat_container=pinchflat_container,
        pinchflat_worker_concurrency=(
            pinchflat_container.get(
                "worker_concurrency"
            )
            or setting_int(
                "pinchflat_worker_concurrency",
                2,
                1,
                16,
            )
        ),
        pinchflat_worker_concurrency_options=(
            1,
            2,
            3,
            4,
            5,
            6,
            8,
            10,
            12,
            16,
        ),
        pinchflat_profile_ready=profile_status["ready"],
        pinchflat_profile_message=profile_status["message"],
        pinchflat_stats=pinchflat_stats,
        pinchflat_public_url=effective_app_url(),
        pinchflat_open_url=effective_app_url(),
        subs=subs,
        counts=counts,
        last_run=last_run,
        recent_runs=recent_runs,
        activity_rows=activity_rows,
        dry_run=DRY_RUN,
        youtube_sync_interval=current_youtube_sync_interval(),
        pinchflat_sync_interval=current_pinchflat_sync_interval(),
        pinchflat_force_index_favourite_minutes=current_pinchflat_force_index_interval(True),
        pinchflat_force_index_nonfavourite_minutes=current_pinchflat_force_index_interval(False),
        pinchflat_force_index_favourite_options=PINCHFLAT_FORCE_INDEX_FAVOURITE_OPTIONS,
        pinchflat_force_index_nonfavourite_options=PINCHFLAT_FORCE_INDEX_NONFAVOURITE_OPTIONS,
        pinchflat_force_index_status=pinchflat_force_index_status(),
        emby_download_poll_minutes=current_emby_poll_interval(),
        next_youtube_sync=next_youtube_sync,
        next_pinchflat_sync=next_pinchflat_sync,
        next_emby_sync=next_emby_sync,
        default_history_mode=defaults["mode"],
        default_history_years=defaults["years"],
        default_history_custom_date=defaults["custom_date"],
        default_history_cutoff=resolve_history_cutoff(),
        new_subscription_policy=new_subscription_policy(),
        unsubscribe_policy=unsubscribe_policy(),
        show_removed=setting_bool("show_removed", False),
        pin_favourites_to_top=setting_bool("pin_favourites_to_top", True),
        auto_retry=setting_bool("auto_retry", True),
        auto_create_media_profile=setting_bool("auto_create_media_profile", True),
        api_stats=api_stats,
        youtube_account_stats=youtube_account,
        storage_total_bytes=storage["total"],
        storage_total=format_bytes(storage["total"]),
        storage_capacity_bytes=storage_capacity,
        storage_capacity=format_bytes(storage_capacity) if storage_capacity else "Unavailable",
        storage_free=format_bytes(storage_filesystem.get("free") or 0) if storage_capacity else "Unavailable",
        storage_content_percent=storage_content_percent,
        download_counts=download_counts,
        recent_downloads=recent_downloads,
        emby_download_enabled=setting_bool("emby_download_enabled", True),
        emby_download_playlist_name=get_setting("emby_download_playlist_name", "Emby Download"),
        emby_download_playlist_id=emby_playlist_id,
        emby_download_remove_after_success=setting_bool("emby_download_remove_after_success", True),
        emby_download_folder=get_setting("emby_download_folder", "Emby Download"),
        emby_server_url=emby_server_url(),
        emby_api_configured=emby_configured(),
        emby_api_key_saved=bool(emby_api_key()),
        emby_auto_refresh_after_download=setting_bool("emby_auto_refresh_after_download", True),
        emby_library_path=get_setting("emby_library_path", "/media/Storage/Media/YouTube"),
        single_download_folder=get_setting("single_download_folder", "Single Downloads"),
        single_download_format=get_setting("single_download_format", "best"),
        single_download_compatibility_profile=get_setting("single_download_compatibility_profile", "emby_tv"),
        single_download_audio_format=get_setting("single_download_audio_format", "m4a"),
        single_download_write_nfo=setting_bool("single_download_write_nfo", True),
        single_download_output_template=get_setting(
            "single_download_output_template",
            "%(uploader,channel|Unknown Channel).80B/%(title).180B [%(id)s].%(ext)s",
        ),
        subscription_download_template=profile_settings.get(
            "output_path_template",
            EMBY_OUTPUT_PATH_TEMPLATE,
        ),
        youtube_daily_quota=setting_int("youtube_daily_quota", 10000, 100, 100000000),
        current_user=auth["current_user"],
        is_admin=auth["is_admin"],
        security_users=security_users,
        auth_events=auth_events,
        remember_login_days=remember_login_days(),
        session_timeout_minutes=session_timeout_minutes(),
        lockout_attempts=lockout_attempt_limit(),
        lockout_minutes=lockout_minutes(),
        password_min=PASSWORD_MIN_LENGTH,
        retention=retention_settings(),
        retention_day_options=RETENTION_DAY_OPTIONS,
        retention_cleanup_interval_options=RETENTION_CLEANUP_INTERVAL_OPTIONS,
        downloader_auth_status=_v3_cookie_status(),
        downloader_po_token=get_setting("downloader_po_token", ""),
        downloader_custom_options=get_setting("downloader_custom_yt_dlp_options", "{}"),
        downloader_auth_retry=setting_bool("downloader_auth_retry", True),
        downloader_default_profile=effective_media_profile_id(),
        downloader_worker_concurrency=setting_int("downloader_worker_concurrency", 1, 1, 8),
        downloader_scan_workers=setting_int("downloader_scan_workers", 4, 1, 12),
        downloader_deep_scan_limit=setting_int("downloader_deep_scan_limit", 500, 25, 5000),

        page_view=page_view,
        page_section_order=page_section_order,
        page_summary_order=page_summary_order,
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

    if app_url and not ENV_APP_URL:
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
    return redirect(url_for("index") + "#downloads")


@app.post("/subscriptions/<channel_id>/save")
def save_subscription_row(channel_id):
    """Save one source. Enabled is authoritative for Pinchflat membership."""
    ajax = is_ajax_request()

    mode = request.form.get(
        "history_mode",
        "default",
    ).strip()

    custom_date = request.form.get(
        "history_custom_date",
        "",
    ).strip()

    profile_id = request.form.get(
        "media_profile_id",
        "",
    ).strip()

    enabled = (
        "1"
        in request.form.getlist(
            "download_enabled"
        )
    )

    def fail(message, status=400):
        if ajax:
            return jsonify(
                {
                    "ok": False,
                    "error": message,
                    "subscription": (
                        subscription_ajax_payload(
                            channel_id
                        )
                    ),
                }
            ), status

        flash(message, "error")
        return redirect(
            url_for("index")
            + "#subscriptions"
        )

    if mode not in HISTORY_MODES:
        return fail(
            "Unknown source download range."
        )

    if mode == "custom_date":
        try:
            parsed = date.fromisoformat(
                custom_date
            )
            if parsed > date.today():
                raise ValueError
        except ValueError:
            return fail(
                "Choose a valid custom date which is not in the future."
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
        return fail(
            "The YouTube subscription was not found.",
            404,
        )

    current = dict(row)
    prospective = dict(current)

    prospective.update(
        {
            "download_enabled": (
                1 if enabled else 0
            ),
            "source_authorised": (
                1 if enabled else 0
            ),
            "history_mode": mode,
            "history_custom_date": (
                custom_date
            ),
            "media_profile_id": (
                profile_id or None
            ),
            "needs_review": 0,
        }
    )

    with db() as conn:
        conn.execute(
            """
            UPDATE subscriptions
            SET download_enabled = ?,
                source_authorised = ?,
                history_mode = ?,
                history_custom_date = ?,
                media_profile_id = ?,
                needs_review = 0,
                last_error = NULL
            WHERE channel_id = ?
            """,
            (
                1 if enabled else 0,
                1 if enabled else 0,
                mode,
                custom_date,
                profile_id or None,
                channel_id,
            ),
        )

    ok = True
    status_code = 200

    try:
        with pinchflat_source_action_lock:
            result = apply_subscription_source_authority(
                prospective,
                apply_settings=True,
            )

        with db() as conn:
            conn.execute(
                """
                UPDATE subscriptions
                SET retry_count = 0
                WHERE channel_id = ?
                """,
                (channel_id,),
            )

        if (
            result["state"] == "disabled"
            and result.get("pending")
        ):
            message = (
                f"{current['title']} saved. "
                "Pinchflat source removal is in progress."
            )
        elif enabled:
            message = (
                f"{current['title']} saved and enabled in Pinchflat."
            )
        else:
            message = (
                f"{current['title']} saved and removed from Pinchflat. "
                "Existing downloaded files were kept."
            )

    except Exception as exc:
        ok = False
        status_code = 409
        message = (
            "Your choices were saved locally, but Pinchflat could not "
            f"be reconciled: {exc}"
        )

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
                    channel_id,
                ),
            )

    payload = (
        subscription_ajax_payload(
            channel_id
        )
    )

    if ajax:
        return jsonify(
            {
                "ok": ok,
                "saved_locally": True,
                "message": message,
                "subscription": payload,
            }
        ), status_code

    flash(
        message,
        "success" if ok else "error",
    )

    return redirect(
        url_for("index")
        + "#subscriptions"
    )


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
    jobs = [
        (
            "youtube-subscription-sync",
            current_youtube_sync_interval(),
        ),
        (
            "pinchflat-source-sync",
            current_pinchflat_sync_interval(),
        ),
        (
            "emby-download-sync",
            current_emby_poll_interval(),
        ),
    ]

    for job_id, minutes in jobs:
        try:
            scheduler.reschedule_job(
                job_id,
                trigger="interval",
                minutes=minutes,
            )
        except Exception:
            pass


@app.post("/settings/general")
def save_general_settings():
    new_policy = request.form.get("new_subscription_policy", "auto_enable").strip()
    removed_policy = request.form.get("unsubscribe_policy", "keep").strip()

    if new_policy == "review":
        new_policy = "disabled"
    if new_policy not in {"auto_enable", "disabled"}:
        new_policy = "auto_enable"
    if removed_policy not in {"keep", "disable", "remove", "remove_delete"}:
        removed_policy = "keep"

    set_setting("new_subscription_policy", new_policy)
    set_setting("unsubscribe_policy", removed_policy)
    set_setting(
        "show_removed",
        "1" if request.form.get("show_removed") == "1" else "0",
    )
    set_setting(
        "pin_favourites_to_top",
        "1" if request.form.get("pin_favourites_to_top") == "1" else "0",
    )

    log_activity(
        "settings",
        "General settings updated",
        f"New subscriptions: {new_policy}. Removed subscriptions: {removed_policy}.",
    )
    flash("General settings saved.", "success")
    return redirect(url_for("index") + "#subscriptions")


@app.post("/settings/page-view")
def save_page_view_settings():
    boolean_settings = {
        "page_load_summary",
        "page_load_pinchflat_downloads",
        "page_load_latest_videos",
        "page_load_subscriptions",

        "page_min_pinchflat_downloads",
        "page_min_latest_videos",
        "page_min_subscriptions",

        "page_show_summary_google",
        "page_show_summary_pinchflat",
        "page_show_summary_pinchflat_tasks",
        "page_show_summary_subscriptions",
        "page_show_summary_downloads",
        "page_show_summary_errors",
        "page_show_summary_latest_download",

        "page_button_sync",
        "page_button_refresh_youtube",
        "page_button_single_download",
        "page_button_discover",
        "page_button_favourites",
        "page_button_logout",

        "page_channel_controls",
        "page_channel_control_favourite",
        "page_channel_control_downloads",
        "page_channel_control_scan",
        "page_channel_control_delete",
        "page_channel_control_retention",
    }

    for key in boolean_settings:
        set_setting(
            key,
            "1" if request.form.get(key) == "1" else "0",
        )

    section_order = [
        item
        for item in (
            request.form.get(
                "page_section_order",
                "",
            )
            or ""
        ).split(",")
        if item
        in {
            "summary",
            "pinchflat",
            "latest",
            "subscriptions",
        }
    ]

    summary_order = [
        item
        for item in (
            request.form.get(
                "page_summary_order",
                "",
            )
            or ""
        ).split(",")
        if item
        in {
            "google",
            "pinchflat",
            "pinchflat_tasks",
            "latest_download",
            "subscriptions",
            "downloads",
            "errors",
        }
    ]

    # Preserve the validated drag-and-drop order and append any missing
    # sections so future upgrades remain backwards compatible.
    valid_sections = [
        "summary",
        "pinchflat",
        "latest",
        "subscriptions",
    ]
    section_order = [
        item
        for item in section_order
        if item in valid_sections
    ]
    for item in valid_sections:
        if item not in section_order:
            section_order.append(item)

    valid_summary = [
        "google",
        "pinchflat",
        "pinchflat_tasks",
        "latest_download",
        "subscriptions",
        "downloads",
        "errors",
    ]
    summary_order = [
        item
        for item in summary_order
        if item in valid_summary
    ]
    for item in valid_summary:
        if item not in summary_order:
            summary_order.append(item)

    set_setting(
        "page_section_order",
        ",".join(section_order),
    )
    set_setting(
        "page_summary_order",
        ",".join(summary_order),
    )

    log_activity(
        "settings",
        "Dashboard settings updated",
        "Dashboard sections, header buttons and page order were updated.",
    )

    flash(
        "Dashboard settings saved.",
        "success",
    )

    return redirect(
        url_for("index")
        + "#pageview"
    )


@app.post("/settings/automation")
def save_automation_settings():
    def parse_interval(name, default, minimum=5):
        try:
            value = int(request.form.get(name, str(default)))
        except ValueError:
            value = default
        return min(max(value, minimum), 1440)

    youtube_interval = parse_interval(
        "youtube_sync_interval_minutes",
        current_youtube_sync_interval(),
        5,
    )
    pinchflat_interval = parse_interval(
        "pinchflat_sync_interval_minutes",
        current_pinchflat_sync_interval(),
        5,
    )
    emby_interval = parse_interval(
        "emby_download_poll_minutes",
        current_emby_poll_interval(),
        1,
    )

    set_setting("youtube_sync_interval_minutes", str(youtube_interval))
    set_setting("pinchflat_sync_interval_minutes", str(pinchflat_interval))
    set_setting("sync_interval_minutes", str(youtube_interval))
    set_setting("emby_download_poll_minutes", str(emby_interval))
    set_setting(
        "auto_retry",
        "1" if request.form.get("auto_retry") == "1" else "0",
    )
    set_setting(
        "emby_download_enabled",
        "1" if request.form.get("emby_download_enabled") == "1" else "0",
    )
    set_setting(
        "emby_download_remove_after_success",
        "1"
        if request.form.get("emby_download_remove_after_success") == "1"
        else "0",
    )
    set_setting("emby_download_playlist_name", "Emby Download")
    try:
        emby_folder = safe_relative_download_folder(
            request.form.get("emby_download_folder", get_setting("emby_download_folder", "Emby Download")),
            "Emby Download",
        )
        set_setting("emby_download_folder", emby_folder)
    except Exception as exc:
        flash(f"Automation settings could not save the Emby Download folder: {exc}", "error")
        return redirect(url_for("index") + "#automation")

    if setting_bool("emby_download_enabled", True) and google_write_scope_ready():
        try:
            ensure_emby_download_playlist()
        except Exception as exc:
            flash(
                f"Automation saved, but Emby Download needs attention: {exc}",
                "error",
            )

    reschedule_sync_job()

    log_activity(
        "settings",
        "Automation settings updated",
        (
            f"YouTube every {youtube_interval} minutes. "
            f"Pinchflat every {pinchflat_interval} minutes. "
            f"Emby Download every {emby_interval} minutes."
        ),
    )
    flash("Automation settings saved.", "success")
    return redirect(url_for("index") + "#automation")


@app.post("/settings/download-paths")
def save_download_paths():
    profile_id = effective_media_profile_id()
    subscription_template = (
        request.form.get(
            "subscription_download_template",
            EMBY_OUTPUT_PATH_TEMPLATE,
        ).strip()
        or EMBY_OUTPUT_PATH_TEMPLATE
    )

    try:
        emby_folder = safe_relative_download_folder(
            request.form.get("emby_download_folder", ""),
            "Emby Download",
        )
        current = media_profile_settings(profile_id)
        if current.get("error"):
            raise RuntimeError(current["error"])

        values = profile_values_for_update(current)
        values["output_path_template"] = subscription_template
        update_media_profile_settings(profile_id, values)

        set_setting("emby_download_folder", emby_folder)

        log_activity(
            "settings",
            "Download paths updated",
            (
                f"Subscriptions: {subscription_template}. "
                f"Emby Download: {emby_folder}."
            ),
            "success",
        )
        flash("Download paths saved.", "success")
    except Exception as exc:
        flash(f"Download paths could not be saved: {exc}", "error")

    return redirect(url_for("index") + "#downloads")


@app.post("/settings/single-download")
def save_single_download_settings():
    download_format = request.form.get("single_download_format", "best").strip()
    audio_format = request.form.get("single_download_audio_format", "m4a").strip().lower()
    compatibility_profile = request.form.get("single_download_compatibility_profile", "emby_tv").strip().lower()
    allowed_formats = {"best", "2160p", "1440p", "1080p", "720p", "480p", "360p", "audio"}
    allowed_audio = {"m4a", "mp3", "opus", "flac", "wav"}
    if download_format not in allowed_formats:
        download_format = "best"
    if audio_format not in allowed_audio:
        audio_format = "m4a"
    if compatibility_profile not in {"emby_tv", "automatic"}:
        compatibility_profile = "emby_tv"

    try:
        folder = safe_relative_download_folder(
            request.form.get("single_download_folder", ""),
            "Single Downloads",
        )
        template = request.form.get(
            "single_download_output_template",
            "%(uploader,channel|Unknown Channel).80B/%(title).180B [%(id)s].%(ext)s",
        ).strip()
        if not template:
            template = "%(uploader,channel|Unknown Channel).80B/%(title).180B [%(id)s].%(ext)s"
        if template.startswith(("/", "\\")) or ".." in Path(template).parts:
            raise RuntimeError("The yt-dlp output template must stay inside the selected /downloads folder.")

        set_setting("single_download_folder", folder)
        set_setting("single_download_format", download_format)
        set_setting("single_download_compatibility_profile", compatibility_profile)
        set_setting("single_download_audio_format", audio_format)
        set_setting("single_download_write_nfo", "1" if request.form.get("single_download_write_nfo") == "1" else "0")
        set_setting("single_download_output_template", template)
        flash("One-time download settings saved.", "success")
    except Exception as exc:
        flash(f"One-time download settings could not be saved: {exc}", "error")
    return redirect(url_for("index") + "#downloads")


@app.post("/pinchflat/power")
def pinchflat_power():
    action = request.form.get("action", "").strip().lower()

    if action not in {"start", "stop"}:
        flash("Unknown Pinchflat power action.", "error")
        return redirect(url_for("index") + "#top")

    try:
        running = action == "start"
        state = set_pinchflat_container_power(running)

        log_activity(
            "pinchflat",
            f"Pinchflat {'started' if running else 'stopped'}",
            (
                f"Docker container {PINCHFLAT_CONTAINER_NAME} is "
                f"{state['status']}."
            ),
            "success",
        )

        flash(
            f"Pinchflat {'started' if running else 'stopped'}.",
            "success",
        )
    except Exception as exc:
        log_activity(
            "pinchflat",
            "Pinchflat power control failed",
            str(exc),
            "error",
        )
        flash(f"Pinchflat power control failed: {exc}", "error")

    return redirect(url_for("index") + "#top")


@app.post("/settings/video-retention")
def save_video_retention_settings():
    previous_settings = retention_settings()

    def parse_int(name, default, minimum, maximum):
        try:
            value = int(str(request.form.get(name, default) or default).strip())
        except (TypeError, ValueError):
            value = default
        return max(minimum, min(maximum, value))

    favourite_days = parse_int("retention_favourite_days", 365, 0, 3650)
    favourite_min = parse_int("retention_favourite_min_videos", 20, 0, 10000)
    nonfavourite_days = parse_int("retention_nonfavourite_days", 90, 0, 3650)
    nonfavourite_min = parse_int("retention_nonfavourite_min_videos", 5, 0, 10000)
    grace_days = parse_int("retention_grace_days", 7, 0, 365)
    interval_hours = parse_int("retention_cleanup_interval_hours", 24, 1, 744)
    allowed_intervals = {value for value, _label in RETENTION_CLEANUP_INTERVAL_OPTIONS}
    if interval_hours not in allowed_intervals:
        interval_hours = 24

    retention_enabled = request.form.get("retention_enabled") == "1"
    set_setting("retention_enabled", "1" if retention_enabled else "0")
    # Give a newly enabled policy one full configured interval before the first
    # automatic cleanup. The user can still use Preview and Run cleanup now
    # immediately, but enabling the switch itself never starts deletion.
    if retention_enabled and not previous_settings.get("enabled") and not previous_settings.get("last_run_at"):
        set_setting("retention_last_run_at", now_iso())
    set_setting("retention_favourite_days", str(favourite_days))
    set_setting("retention_favourite_min_videos", str(favourite_min))
    set_setting("retention_nonfavourite_days", str(nonfavourite_days))
    set_setting("retention_nonfavourite_min_videos", str(nonfavourite_min))
    set_setting("retention_grace_days", str(grace_days))
    set_setting("retention_cleanup_interval_hours", str(interval_hours))
    set_setting(
        "retention_protect_favourite_videos",
        "1" if request.form.get("retention_protect_favourite_videos") == "1" else "0",
    )

    log_activity(
        "settings",
        "Video retention settings updated",
        (
            f"Favourite channels: {retention_days_label(favourite_days)}, keep at least {favourite_min}. "
            f"Other channels: {retention_days_label(nonfavourite_days)}, keep at least {nonfavourite_min}."
        ),
        "success",
    )
    flash("Video retention settings saved.", "success")
    return redirect(url_for("index") + "#retention")


@app.get("/api/retention/channels")
def retention_channels_api():
    query = str(request.args.get("q") or "").strip()
    like = f"%{query}%"
    with db() as conn:
        rows = conn.execute(
            """
            SELECT s.channel_id, s.title, s.thumbnail_url, s.active, s.download_enabled,
                   s.pinchflat_source_id,
                   CASE WHEN f.channel_id IS NULL THEN 0 ELSE 1 END AS favourite,
                   o.retention_days AS override_days,
                   o.minimum_videos AS override_minimum
            FROM subscriptions s
            LEFT JOIN (SELECT DISTINCT channel_id FROM favourite_channels) f
                ON f.channel_id = s.channel_id
            LEFT JOIN video_retention_overrides o
                ON o.channel_id = s.channel_id
            WHERE s.active = 1
              AND (? = '' OR s.title LIKE ? OR s.channel_id LIKE ?)
            ORDER BY favourite DESC, LOWER(s.title) ASC
            LIMIT 80
            """,
            (query, like, like),
        ).fetchall()

    result = []
    for row in rows:
        item = dict(row)
        policy = retention_policy_for_channel(item["channel_id"], favourite=bool(item["favourite"]))
        result.append({
            "channel_id": item["channel_id"],
            "title": item["title"],
            "thumbnail_url": item.get("thumbnail_url") or "",
            "favourite": bool(item["favourite"]),
            "download_enabled": bool(item["download_enabled"]),
            "source_id": str(item.get("pinchflat_source_id") or ""),
            "override": item.get("override_days") is not None,
            "override_days": item.get("override_days"),
            "override_minimum": item.get("override_minimum"),
            "effective_days": policy["days"],
            "effective_label": retention_days_label(policy["days"]),
            "effective_minimum": policy["minimum_videos"],
            "policy_source": policy["source"],
        })
    return jsonify({"ok": True, "channels": result})


@app.post("/api/retention/channels/<channel_id>")
def save_retention_channel_override_api(channel_id):
    mode = str(request.form.get("mode") or "override").strip().lower()
    if mode == "inherit":
        with db() as conn:
            conn.execute("DELETE FROM video_retention_overrides WHERE channel_id = ?", (channel_id,))
        policy = retention_policy_for_channel(channel_id)
        return jsonify({
            "ok": True,
            "message": "Channel retention now follows its group policy.",
            "policy": {**policy, "label": retention_days_label(policy["days"])},
        })

    try:
        days = int(request.form.get("retention_days", "0") or 0)
        minimum = int(request.form.get("minimum_videos", "0") or 0)
    except (TypeError, ValueError):
        return jsonify({"ok": False, "error": "Retention values must be whole numbers."}), 400
    days = max(0, min(3650, days))
    minimum = max(0, min(10000, minimum))
    with db() as conn:
        exists = conn.execute(
            "SELECT 1 FROM subscriptions WHERE channel_id = ? LIMIT 1",
            (channel_id,),
        ).fetchone()
        if not exists:
            return jsonify({"ok": False, "error": "Channel was not found."}), 404
        conn.execute(
            """
            INSERT INTO video_retention_overrides (channel_id, retention_days, minimum_videos, updated_at)
            VALUES (?, ?, ?, ?)
            ON CONFLICT(channel_id) DO UPDATE SET
                retention_days = excluded.retention_days,
                minimum_videos = excluded.minimum_videos,
                updated_at = excluded.updated_at
            """,
            (channel_id, days, minimum, now_iso()),
        )
    policy = retention_policy_for_channel(channel_id)
    return jsonify({
        "ok": True,
        "message": f"Channel retention set to {retention_days_label(days)} with at least {minimum} newest videos kept.",
        "policy": {**policy, "label": retention_days_label(policy["days"])},
    })


@app.get("/api/retention/preview")
def retention_preview_api():
    try:
        preview = retention_preview(limit=250)
        return jsonify({"ok": True, **preview})
    except Exception as exc:
        return jsonify({"ok": False, "error": str(exc)}), 500


@app.post("/api/retention/run")
def retention_run_api():
    if retention_cleanup_lock.locked():
        return jsonify({"ok": False, "error": "A video retention cleanup is already running."}), 409
    if not retention_settings()["enabled"]:
        return jsonify({"ok": False, "error": "Enable Video Retention before running cleanup."}), 400

    def worker():
        run_retention_cleanup(trigger="manual")

    threading.Thread(target=worker, name="video-retention-cleanup", daemon=True).start()
    return jsonify({"ok": True, "message": "Video retention cleanup started."})


@app.get("/api/retention/status")
def retention_status_api():
    with db() as conn:
        row = conn.execute("SELECT * FROM retention_runs ORDER BY id DESC LIMIT 1").fetchone()
    run = dict(row) if row else None
    if run:
        run["reclaimed_size"] = format_bytes(run.get("reclaimed_bytes") or 0)
    return jsonify({
        "ok": True,
        "running": retention_cleanup_lock.locked(),
        "last_run": run,
        "settings": retention_settings(),
    })


@app.route("/api/retention/protection/<video_id>", methods=["GET", "POST"])
def retention_video_protection_api(video_id):
    video_id = str(video_id or "").strip()
    if not re.fullmatch(r"[A-Za-z0-9_-]{6,20}", video_id):
        return jsonify({"ok": False, "error": "Invalid YouTube video ID."}), 400

    if request.method == "GET":
        return jsonify({"ok": True, "protected": video_id in retention_protected_video_ids()})

    payload = request.get_json(silent=True) or {}
    protected = bool(payload.get("protected", True))
    channel_id = str(payload.get("channel_id") or "").strip()
    title = str(payload.get("title") or "").strip()
    with db() as conn:
        if protected:
            conn.execute(
                """
                INSERT INTO retention_protected_videos (video_id, channel_id, title, created_at)
                VALUES (?, ?, ?, ?)
                ON CONFLICT(video_id) DO UPDATE SET
                    channel_id = excluded.channel_id,
                    title = excluded.title
                """,
                (video_id, channel_id, title, now_iso()),
            )
        else:
            conn.execute("DELETE FROM retention_protected_videos WHERE video_id = ?", (video_id,))
    return jsonify({
        "ok": True,
        "protected": protected,
        "message": "Video protected from retention cleanup." if protected else "Video will follow its channel retention policy.",
    })


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
    return redirect(url_for("index") + "#pinchflat")


@app.post("/settings/pinchflat/advanced")
def save_pinchflat_advanced_settings():
    raw = request.form.get(
        "yt_dlp_worker_concurrency",
        "2",
    ).strip()

    try:
        concurrency = int(raw)
    except (TypeError, ValueError):
        concurrency = 2

    if not 1 <= concurrency <= 16:
        flash(
            "Concurrent downloads must be between 1 and 16.",
            "error",
        )
        return redirect(
            url_for("index")
            + "#pinchflat"
        )

    try:
        result = (
            pinchflat_recreate_with_worker_concurrency(
                concurrency
            )
        )

        set_setting(
            "pinchflat_worker_concurrency",
            str(concurrency),
        )

        if result["changed"]:
            message = (
                "Pinchflat concurrent downloads changed "
                f"from {result['old']} to {result['new']}."
            )
        else:
            message = (
                "Pinchflat concurrent downloads is already "
                f"set to {concurrency}."
            )

        log_activity(
            "settings",
            "Pinchflat concurrent downloads updated",
            message,
            "success",
        )

        flash(
            message,
            "success",
        )

    except Exception as exc:
        log_activity(
            "settings",
            "Pinchflat concurrent downloads update failed",
            str(exc),
            "error",
        )

        flash(
            "Pinchflat concurrent downloads could not be changed: "
            f"{exc}",
            "error",
        )

    return redirect(
        url_for("index")
        + "#pinchflat"
    )


@app.post("/settings/pinchflat/force-index")
def save_pinchflat_force_index_settings():
    def parse_interval(name, allowed):
        raw = str(request.form.get(name, "0") or "0").strip()
        try:
            value = int(raw)
        except (TypeError, ValueError):
            value = 0
        return value if value in allowed else 0

    favourite_minutes = parse_interval(
        "pinchflat_force_index_favourite_minutes",
        PINCHFLAT_FORCE_INDEX_FAVOURITE_VALUES,
    )
    nonfavourite_minutes = parse_interval(
        "pinchflat_force_index_nonfavourite_minutes",
        PINCHFLAT_FORCE_INDEX_NONFAVOURITE_VALUES,
    )

    set_setting(
        "pinchflat_force_index_favourite_minutes",
        str(favourite_minutes),
    )
    set_setting(
        "pinchflat_force_index_nonfavourite_minutes",
        str(nonfavourite_minutes),
    )

    def interval_text(value):
        if not value:
            return "Off"
        if value < 60:
            return f"every {value} minutes"
        if value == 60:
            return "every hour"
        if value % 1440 == 0:
            days = value // 1440
            return f"every {days} day" + ("" if days == 1 else "s")
        if value % 60 == 0:
            hours = value // 60
            return f"every {hours} hours"
        return f"every {value} minutes"

    log_activity(
        "settings",
        "Scheduled Force Index updated",
        (
            f"Favourite channels: {interval_text(favourite_minutes)}. "
            f"Non-favourite channels: {interval_text(nonfavourite_minutes)}."
        ),
        "success",
    )
    flash("Scheduled Pinchflat Force Index settings saved.", "success")
    return redirect(url_for("index") + "#pinchflat")


@app.post("/settings/pinchflat/profile/create")
def create_pinchflat_profile_from_settings():
    name = request.form.get("profile_name", "").strip()
    resolution = request.form.get("preferred_resolution", "1080p").strip() or "1080p"
    if not name:
        flash("Enter a name for the new Media Profile.", "error")
        return redirect(url_for("index") + "#pinchflat")
    try:
        created, _form, _profiles = create_media_profile(
            name,
            resolution,
            set_as_default=True,
        )
        log_activity("settings", "Pinchflat Media Profile created", f"Created {created['name']}.", "success")
        flash(f"Created Media Profile {created['name']} and selected it.", "success")
    except Exception as exc:
        flash(f"Media Profile could not be created: {exc}", "error")
    return redirect(url_for("index") + "#pinchflat")


@app.post("/settings/pinchflat/profile/delete")
def delete_current_media_profile():
    profile_id = request.form.get(
        "pinchflat_media_profile_id",
        effective_media_profile_id(),
    ).strip()

    try:
        selected_name = next(
            (
                profile["name"]
                for profile in pinchflat_profiles()
                if str(profile["id"]) == str(profile_id)
            ),
            f"Media Profile {profile_id}",
        )

        remaining = delete_media_profile(profile_id)

        log_activity(
            "settings",
            "Pinchflat Media Profile deleted",
            f"Deleted {selected_name}.",
            "success",
        )

        flash(
            f"Deleted Media Profile {selected_name}. "
            f"{len(remaining)} profile(s) remain.",
            "success",
        )
    except Exception as exc:
        log_activity(
            "settings",
            "Pinchflat Media Profile deletion failed",
            str(exc),
            "error",
        )
        flash(
            f"Media Profile could not be deleted: {exc}",
            "error",
        )

    return redirect(url_for("index") + "#pinchflat")


@app.post("/settings/pinchflat/profile")
def save_current_media_profile():
    profile_id = effective_media_profile_id()
    if not profile_id:
        flash("Choose a Pinchflat Media Profile first.", "error")
        return redirect(url_for("index") + "#pinchflat")

    behaviour = request.form.get(
        "sponsorblock_behaviour",
        "remove",
    ).strip()
    if behaviour not in {"disabled", "mark", "remove"}:
        behaviour = "remove"

    extra_values = {}
    for field_name in request.form:
        if not field_name.startswith("pf_extra::"):
            continue
        original_name = field_name[len("pf_extra::"):]
        field_values = request.form.getlist(field_name)
        extra_values[original_name] = field_values[-1] if field_values else ""

    values = {
        "name": request.form.get("profile_name", "").strip(),
        "output_path_template": (
            request.form.get(
                "output_path_template",
                EMBY_OUTPUT_PATH_TEMPLATE,
            ).strip()
            or EMBY_OUTPUT_PATH_TEMPLATE
        ),
        "download_subs": request.form.get("download_subs") == "1",
        "embed_subs": request.form.get("embed_subs") == "1",
        "download_thumbnail": (
            request.form.get("download_thumbnail") == "1"
        ),
        "embed_thumbnail": (
            request.form.get("embed_thumbnail") == "1"
        ),
        "download_metadata": (
            request.form.get("download_metadata") == "1"
        ),
        "embed_metadata": (
            request.form.get("embed_metadata") == "1"
        ),
        "include_shorts": request.form.get("include_shorts") == "1",
        "include_livestreams": (
            request.form.get("include_livestreams") == "1"
        ),
        "preferred_resolution": request.form.get(
            "preferred_resolution",
            "",
        ).strip(),
        "redownload_delay_days": request.form.get(
            "redownload_delay_days",
            "",
        ).strip(),
        "download_nfo": request.form.get("download_nfo") == "1",
        "download_source_images": (
            request.form.get("download_source_images") == "1"
        ),
        "sponsorblock_behaviour": behaviour,
        "sponsorblock_categories": request.form.getlist(
            "sponsorblock_categories"
        ),
        "extra_values": extra_values,
    }

    try:
        update_media_profile_settings(profile_id, values)
        log_activity(
            "settings",
            "Pinchflat Media Profile updated",
            f"Updated Media Profile {profile_id}.",
            "success",
        )
        flash("Pinchflat Media Profile saved.", "success")
    except Exception as exc:
        log_activity(
            "settings",
            "Pinchflat Media Profile update failed",
            str(exc),
            "error",
        )
        flash(f"Pinchflat Media Profile could not be saved: {exc}", "error")

    return redirect(url_for("index") + "#pinchflat")


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
        row_dict = dict(row)
        result = apply_subscription_source_authority(
            row_dict,
            apply_settings=True,
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
        flash(
            f"Retried {row_dict['title']}. Pinchflat state: {result.get('state', 'updated')}.",
            "success",
        )
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
    ajax = is_ajax_request()
    channel_ids = request.form.getlist("channel_ids")
    action = request.form.get("bulk_action", "").strip()

    if not channel_ids:
        if ajax:
            return jsonify(
                {
                    "ok": False,
                    "error": "Select at least one source.",
                }
            ), 400

        flash(
            "Select at least one source.",
            "error",
        )
        return redirect(
            url_for("index")
            + "#subscriptions"
        )

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
    emby_library_scan_needed = False
    emby_target_library = None

    if action == "emby_refresh":
        try:
            emby_target_library = emby_detect_youtube_library()
        except Exception as exc:
            if ajax:
                return jsonify({"ok": False, "error": str(exc)}), 400
            flash(str(exc), "error")
            return redirect(url_for("index") + "#subscriptions")

    for row in rows:
        try:
            prospective = dict(row)

            if action in {"favourite", "unfavourite"}:
                set_channel_favourite_state(
                    row["channel_id"],
                    action == "favourite",
                )

            elif action in {"enable", "disable"}:
                enabled = action == "enable"

                with db() as conn:
                    conn.execute(
                        """
                        UPDATE subscriptions
                        SET download_enabled = ?,
                            source_authorised = ?,
                            needs_review = 0,
                            last_error = NULL
                        WHERE channel_id = ?
                        """,
                        (
                            1 if enabled else 0,
                            1 if enabled else 0,
                            row["channel_id"],
                        ),
                    )

                prospective["download_enabled"] = 1 if enabled else 0
                prospective["source_authorised"] = 1 if enabled else 0
                prospective["needs_review"] = 0

                with pinchflat_source_action_lock:
                    apply_subscription_source_authority(
                        prospective,
                        apply_settings=True,
                    )
            elif action == "range":
                mode = request.form.get(
                    "bulk_history_mode",
                    "default",
                ).strip()
                custom = request.form.get(
                    "bulk_custom_date",
                    "",
                ).strip()

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

                prospective["history_mode"] = mode
                prospective["history_custom_date"] = custom

                if subscription_download_enabled(prospective):
                    with pinchflat_source_action_lock:
                        apply_subscription_source_authority(
                            prospective,
                            apply_settings=True,
                        )

            elif action == "profile":
                profile_id = request.form.get(
                    "bulk_profile_id",
                    "",
                ).strip()

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

                prospective["media_profile_id"] = profile_id

                if subscription_download_enabled(prospective):
                    with pinchflat_source_action_lock:
                        apply_subscription_source_authority(
                            prospective,
                            apply_settings=True,
                        )

            elif action == "retry":
                with pinchflat_source_action_lock:
                    apply_subscription_source_authority(
                        prospective,
                        apply_settings=True,
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

            elif action in {
                "download_pending",
                "redownload_existing",
                "force_scan",
                "refresh_metadata",
                "sync_files",
            }:
                source_id = resolve_pinchflat_source_id(row)
                if not source_id:
                    raise RuntimeError("Channel is not currently a Pinchflat source.")
                with pinchflat_source_action_lock:
                    execute_pinchflat_source_action(source_id, action)

            elif action == "emby_refresh":
                if not emby_refresh_channel(
                    channel_id=row["channel_id"] or "",
                    channel_title=row["title"] or "",
                    library=emby_target_library,
                ):
                    emby_library_scan_needed = True

            elif action == "unsubscribe":
                unsubscribe_subscription(row["channel_id"])

            elif action in {"delete_local", "delete_local_pinchflat"}:
                delete_subscription_from_pinchflat_sync(
                    row["channel_id"],
                    remove_pinchflat=(action == "delete_local_pinchflat"),
                )

            elif action in {"delete_unsubscribe", "delete_unsubscribe_media"}:
                delete_and_unsubscribe_subscription(
                    row["channel_id"],
                    delete_media=(action == "delete_unsubscribe_media"),
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

    if action == "emby_refresh" and emby_library_scan_needed:
        try:
            emby_refresh_library(library=emby_target_library)
        except Exception as exc:
            errors += 1
            log_activity(
                "emby",
                "Bulk Emby refresh failed",
                str(exc),
                "error",
            )

    log_activity(
        "bulk",
        "Bulk subscription action",
        f"{action}: changed {changed}, errors {errors}.",
        "success" if errors == 0 else "warning",
    )

    message = (
        f"Bulk action completed with {errors} error(s)."
        if errors
        else f"Bulk action applied to {changed} source(s)."
    )

    updated = [
        payload
        for payload in (subscription_ajax_payload(channel_id) for channel_id in channel_ids)
        if payload
    ]
    deleted_ids = [
        channel_id
        for channel_id in channel_ids
        if action in {
            "delete_local",
            "delete_local_pinchflat",
            "delete_unsubscribe",
            "delete_unsubscribe_media",
        }
        and not subscription_ajax_payload(channel_id)
    ]

    if ajax:
        return jsonify(
            {
                "ok": errors == 0,
                "message": message,
                "changed": changed,
                "errors": errors,
                "subscriptions": updated,
                "deleted_channel_ids": deleted_ids,
            }
        )

    flash(
        message,
        "error" if errors else "success",
    )

    return redirect(
        url_for("index")
        + "#subscriptions"
    )


@app.get("/api/channels/<channel_id>/details")
def channel_details_api(channel_id):
    with db() as conn:
        row = conn.execute(
            "SELECT * FROM subscriptions WHERE channel_id = ? LIMIT 1",
            (channel_id,),
        ).fetchone()
        deleted_marker = conn.execute(
            "SELECT absence_confirmed FROM manually_deleted_channels WHERE channel_id = ? LIMIT 1",
            (channel_id,),
        ).fetchone()

    youtube_subscribed = bool(row is not None and row_value(row, "active", 0))
    if row is None and deleted_marker is not None:
        youtube_subscribed = not bool(row_value(deleted_marker, "absence_confirmed", 0))

    subscription = None
    if row is not None:
        item = subscription_view(row)
        source_id = resolve_pinchflat_source_id(item)
        profile_id = subscription_media_profile_id(item)
        profile_name = media_profile_settings(profile_id).get("name") or str(profile_id)
        disk_bytes = channel_disk_usage(item.get("title") or channel_id, storage_snapshot())
        subscription = {
            "channel_id": item.get("channel_id") or "",
            "title": item.get("title") or "YouTube channel",
            "channel_url": item.get("channel_url") or "",
            "thumbnail_url": item.get("thumbnail_url") or "",
            "active": bool(item.get("active")),
            "favourite": item.get("channel_id") in favourite_channel_ids(),
            "download_enabled": bool(item.get("download_enabled")),
            "pinchflat_added": bool(item.get("pinchflat_added")),
            "pinchflat_source_id": str(source_id or ""),
            "pinchflat_source_url": f"{PINCHFLAT_URL}/sources/{source_id}" if source_id else "",
            "ui_status": item.get("ui_status") or "",
            "cutoff": item.get("cutoff") or "",
            "history_label": item.get("history_label") or "",
            "media_profile_id": str(profile_id or ""),
            "media_profile_name": profile_name,
            "subscribed_at": item.get("subscribed_at") or "",
            "first_seen_at": item.get("first_seen_at") or "",
            "removed_at": item.get("removed_at") or "",
            "last_error": item.get("last_error") or "",
            "disk_bytes": disk_bytes,
            "disk_usage": format_bytes(disk_bytes),
        }

    video_mode = request.args.get("videos", "1").strip().lower()
    include_videos = video_mode != "0"
    include_popular = video_mode not in {"0", "recent"}
    youtube = youtube_channel_summary(
        channel_id,
        include_videos=include_videos,
        include_popular=include_popular,
    )
    if not youtube and subscription is None:
        return jsonify({"ok": False, "error": "Channel information was not found."}), 404

    return jsonify({
        "ok": True,
        "subscription": subscription,
        "subscribed": youtube_subscribed,
        "favourite": channel_id in favourite_channel_ids(),
        "youtube": youtube,
        "retention": retention_channel_summary(channel_id),
    })


@app.get("/api/subscriptions/<channel_id>/details")
def subscription_details_api(channel_id):
    return channel_details_api(channel_id)


@app.post("/api/subscriptions/<channel_id>/source-action")
def subscription_source_action_api(channel_id):
    payload = request.get_json(silent=True) or {}
    action = str(payload.get("action") or "").strip()

    friendly = {
        "download_pending": "Download Pending",
        "redownload_existing": "Re-Download Existing",
        "force_scan": "Force Scan",
        "refresh_metadata": "Refresh Media",
        "sync_files": "Sync Files on Disk",
    }

    if action not in friendly:
        return jsonify(
            {
                "ok": False,
                "error": "Unknown source action.",
            }
        ), 400

    with db() as conn:
        row = conn.execute(
            "SELECT * FROM subscriptions WHERE channel_id = ? LIMIT 1",
            (channel_id,),
        ).fetchone()

    if row is None:
        return jsonify(
            {
                "ok": False,
                "error": "Subscription was not found.",
            }
        ), 404

    item = dict(row)
    source_id = resolve_pinchflat_source_id(item)

    if not source_id:
        return jsonify(
            {
                "ok": False,
                "error": "This channel does not currently exist in Pinchflat.",
            }
        ), 409

    try:
        with pinchflat_source_action_lock:
            execute_pinchflat_source_action(
                source_id,
                action,
            )

        message = (
            f"{friendly[action]} started for "
            f"{item.get('title') or channel_id}."
        )

        log_activity(
            "pinchflat",
            friendly[action],
            message,
            "success",
            channel_id,
        )

        return jsonify(
            {
                "ok": True,
                "message": message,
            }
        )

    except Exception as exc:
        error_message = str(exc)

        log_activity(
            "pinchflat",
            f"{friendly.get(action, 'Source action')} failed",
            error_message,
            "error",
            channel_id,
        )

        return jsonify(
            {
                "ok": False,
                "error": error_message,
            }
        ), 400


def unsubscribe_subscription(channel_id):
    with db() as conn:
        row = conn.execute(
            "SELECT * FROM subscriptions WHERE channel_id = ? LIMIT 1",
            (channel_id,),
        ).fetchone()

    # A channel can still be subscribed on YouTube after the user deliberately
    # removes its local Pinchflat Sync record. Keep the global channel-image
    # unsubscribe control useful in that state too.
    if row is None:
        youtube_unsubscribe(channel_id)
        with db() as conn:
            conn.execute(
                "UPDATE manually_deleted_channels SET absence_confirmed = 1 WHERE channel_id = ?",
                (channel_id,),
            )
        message = "Unsubscribed from the channel on YouTube."
        log_activity("youtube", "YouTube subscription removed", message, "success", channel_id)
        return {
            "ok": True,
            "message": message,
            "channel_id": channel_id,
            "subscription": None,
        }

    row_dict = dict(row)
    youtube_unsubscribe(channel_id, row_value(row, "youtube_subscription_id", None))

    with db() as conn:
        conn.execute(
            """
            UPDATE subscriptions
            SET active = 0,
                removed_at = ?,
                download_enabled = 0,
                source_authorised = 0,
                last_error = NULL
            WHERE channel_id = ?
            """,
            (now_iso(), channel_id),
        )

    policy = unsubscribe_policy()
    source_id = resolve_pinchflat_source_id(row_dict)
    if policy == "disable" and source_id:
        update_pinchflat_source_settings(
            source_id,
            cutoff=subscription_cutoff(row_dict),
            download_enabled=False,
            media_profile_id=subscription_media_profile_id(row_dict),
        )
    elif policy in {"remove", "remove_delete"}:
        delete_files = policy == "remove_delete"
        output_template = media_profile_settings(subscription_media_profile_id(row_dict)).get(
            "output_path_template", EMBY_OUTPUT_PATH_TEMPLATE
        )
        source_gone = not source_id
        if source_id:
            removal_row = dict(row_dict)
            removal_row["pinchflat_source_id"] = str(source_id)
            removal_row["pinchflat_added"] = 1
            prepare_pinchflat_source_for_removal(removal_row)
            source_gone = delete_pinchflat_source(
                source_id,
                delete_files=delete_files,
                subscription=removal_row,
            )
        if delete_files:
            delete_subscription_download_folder(row_dict.get("title") or channel_id, output_template)
        if source_gone:
            clear_subscription_pinchflat_link(channel_id, source_id)
        elif source_id:
            with db() as conn:
                conn.execute(
                    """
                    UPDATE subscriptions
                    SET pinchflat_added = 1,
                        pinchflat_source_id = ?,
                        download_enabled = 0,
                        source_authorised = 0,
                        last_error = ?
                    WHERE channel_id = ?
                    """,
                    (str(source_id), "Pinchflat source removal is still in progress.", channel_id),
                )
        schedule_unsubscribe_cleanup(
            channel_id,
            row_dict.get("title") or channel_id,
            output_template,
            source_id=source_id,
            delete_files=delete_files,
            delay_seconds=300,
            checks=6,
        )

    title = row_dict.get("title") or channel_id
    message = f"Unsubscribed from {title} on YouTube."
    log_activity("youtube", "YouTube subscription removed", message, "success", channel_id)
    return {
        "ok": True,
        "message": message,
        "channel_id": channel_id,
        "subscription": subscription_ajax_payload(channel_id),
    }


def delete_and_unsubscribe_subscription(channel_id, delete_media=False):
    with db() as conn:
        row = conn.execute(
            "SELECT * FROM subscriptions WHERE channel_id = ? LIMIT 1",
            (channel_id,),
        ).fetchone()
    if row is None:
        raise RuntimeError("Subscription was not found.")

    item = dict(row)
    title = item.get("title") or channel_id
    youtube_unsubscribed = False
    source_id = None
    source_gone = True
    deleted_folder = None

    if item.get("active"):
        youtube_unsubscribe(channel_id, row_value(row, "youtube_subscription_id", None))
        youtube_unsubscribed = True

    source_id = resolve_pinchflat_source_id(item)
    profile_id = subscription_media_profile_id(item)
    output_template = media_profile_settings(profile_id).get(
        "output_path_template", EMBY_OUTPUT_PATH_TEMPLATE
    )
    source_gone = not source_id

    if source_id:
        removal_row = dict(item)
        removal_row["pinchflat_source_id"] = str(source_id)
        removal_row["pinchflat_added"] = 1
        with pinchflat_source_action_lock:
            prepare_pinchflat_source_for_removal(removal_row)
            source_gone = delete_pinchflat_source(
                source_id,
                delete_files=delete_media,
                subscription=removal_row,
            )

    if delete_media:
        deleted_folder = delete_subscription_download_folder(title, output_template)

    if not source_gone and source_id:
        schedule_unsubscribe_cleanup(
            channel_id,
            title,
            output_template,
            source_id=source_id,
            delete_files=delete_media,
            delay_seconds=300,
            checks=6,
        )

    with db() as conn:
        conn.execute(
            """
            INSERT INTO manually_deleted_channels (channel_id, title, deleted_at, absence_confirmed)
            VALUES (?, ?, ?, 0)
            ON CONFLICT(channel_id) DO UPDATE SET
                title = excluded.title,
                deleted_at = excluded.deleted_at,
                absence_confirmed = 0
            """,
            (channel_id, title, now_iso()),
        )
        conn.execute("DELETE FROM subscriptions WHERE channel_id = ?", (channel_id,))

    media_message = ""
    if delete_media:
        media_message = (
            f" Downloaded folder removed: {deleted_folder}."
            if deleted_folder
            else " Downloaded media removal was requested. No remaining channel folder was found by the app."
        )
    source_message = (
        " Pinchflat source removal is still being reconciled in the background."
        if not source_gone and source_id else ""
    )
    message = (
        f"{title} was removed from the app"
        + (" and unsubscribed from YouTube." if youtube_unsubscribed else ".")
        + source_message
        + media_message
    )
    log_activity("youtube", "Channel deleted and unsubscribed", message, "success", channel_id)
    return {
        "ok": True,
        "message": message,
        "deleted_from_app": True,
        "youtube_unsubscribed": youtube_unsubscribed,
        "pinchflat_source_removed": bool(source_gone),
        "pinchflat_source_pending": bool(source_id and not source_gone),
        "media_delete_requested": bool(delete_media),
        "media_folder_deleted": deleted_folder,
        "channel_id": channel_id,
    }


def delete_subscription_from_pinchflat_sync(channel_id, remove_pinchflat=False):
    """
    Remove a channel from this application without changing the user's
    YouTube subscription. Optionally remove the matching Pinchflat source
    while keeping downloaded media.
    """
    with db() as conn:
        row = conn.execute(
            "SELECT * FROM subscriptions WHERE channel_id = ? LIMIT 1",
            (channel_id,),
        ).fetchone()

    if row is None:
        raise RuntimeError("Channel is not currently stored in Pinchflat Sync.")

    item = dict(row)
    title = item.get("title") or channel_id
    source_id = resolve_pinchflat_source_id(item)
    source_gone = not source_id

    if remove_pinchflat and source_id:
        profile_id = subscription_media_profile_id(item)
        output_template = media_profile_settings(profile_id).get(
            "output_path_template", EMBY_OUTPUT_PATH_TEMPLATE
        )
        removal_row = dict(item)
        removal_row["pinchflat_source_id"] = str(source_id)
        removal_row["pinchflat_added"] = 1

        with pinchflat_source_action_lock:
            prepare_pinchflat_source_for_removal(removal_row)
            source_gone = delete_pinchflat_source(
                source_id,
                delete_files=False,
                subscription=removal_row,
            )

        if not source_gone:
            schedule_unsubscribe_cleanup(
                channel_id,
                title,
                output_template,
                source_id=source_id,
                delete_files=False,
                delay_seconds=300,
                checks=6,
            )

    with db() as conn:
        # Keep the channel suppressed while it remains subscribed on YouTube.
        # If it later disappears from YouTube and is genuinely re-subscribed,
        # refresh_subscriptions() will clear this marker and add it again.
        conn.execute(
            """
            INSERT INTO manually_deleted_channels (channel_id, title, deleted_at, absence_confirmed)
            VALUES (?, ?, ?, 0)
            ON CONFLICT(channel_id) DO UPDATE SET
                title = excluded.title,
                deleted_at = excluded.deleted_at,
                absence_confirmed = 0
            """,
            (channel_id, title, now_iso()),
        )
        conn.execute(
            "DELETE FROM subscriptions WHERE channel_id = ?",
            (channel_id,),
        )

    if remove_pinchflat:
        source_text = (
            " Pinchflat source removal is still being reconciled in the background."
            if source_id and not source_gone
            else " The Pinchflat source was removed." if source_id
            else " No Pinchflat source existed."
        )
    else:
        source_text = " The Pinchflat source and downloaded media were left unchanged."

    message = f"{title} was removed from Pinchflat Sync.{source_text}"
    log_activity(
        "subscriptions",
        "Channel removed from Pinchflat Sync",
        message,
        "success",
        channel_id,
    )
    return {
        "ok": True,
        "message": message,
        "deleted_from_app": True,
        "youtube_unsubscribed": False,
        "pinchflat_source_removed": bool(remove_pinchflat and source_gone),
        "pinchflat_source_pending": bool(remove_pinchflat and source_id and not source_gone),
        "media_delete_requested": False,
        "channel_id": channel_id,
    }


@app.post("/api/subscriptions/<channel_id>/delete-local")
def delete_subscription_from_pinchflat_sync_api(channel_id):
    payload = request.get_json(silent=True) or {}
    remove_pinchflat = bool(payload.get("remove_pinchflat"))
    try:
        return jsonify(
            delete_subscription_from_pinchflat_sync(
                channel_id,
                remove_pinchflat=remove_pinchflat,
            )
        )
    except Exception as exc:
        log_activity(
            "subscriptions",
            "Local channel delete failed",
            str(exc),
            "error",
            channel_id,
        )
        return jsonify({"ok": False, "error": str(exc)}), 400


@app.post("/api/subscriptions/<channel_id>/delete-unsubscribe")
def delete_and_unsubscribe_subscription_api(channel_id):
    payload = request.get_json(silent=True) or {}
    delete_media = bool(payload.get("delete_media"))
    try:
        return jsonify(delete_and_unsubscribe_subscription(channel_id, delete_media))
    except Exception as exc:
        log_activity("youtube", "Channel delete failed", str(exc), "error", channel_id)
        return jsonify({
            "ok": False,
            "error": str(exc),
            "subscription": subscription_ajax_payload(channel_id),
        }), 400


@app.post("/subscriptions/<channel_id>/unsubscribe")
def unsubscribe_from_youtube(channel_id):
    ajax = is_ajax_request()
    try:
        result = unsubscribe_subscription(channel_id)
        if ajax:
            return jsonify(result)
        flash(result["message"], "success")
    except Exception as exc:
        with db() as conn:
            conn.execute(
                "UPDATE subscriptions SET last_error = ? WHERE channel_id = ?",
                (str(exc)[:1000], channel_id),
            )
        log_activity("youtube", "YouTube unsubscribe failed", str(exc), "error", channel_id)
        if ajax:
            return jsonify({
                "ok": False,
                "error": f"Unsubscribe failed: {exc}",
                "subscription": subscription_ajax_payload(channel_id),
            }), 400
        flash(f"Unsubscribe failed: {exc}", "error")
    return redirect(url_for("index") + "#subscriptions")


@app.post("/single-download/start")
def single_download_start():
    payload = request.get_json(silent=True) or {}
    youtube_url = str(payload.get("youtube_url") or "").strip()

    try:
        video_id = youtube_video_id_from_url(youtube_url)
        if video_id:
            existing = completed_single_download_for_video(video_id)
            if existing:
                return jsonify({
                    "ok": False,
                    "already_downloaded": True,
                    "video_id": video_id,
                    "error": "This video has already been downloaded with One-time Download and the file is still present.",
                }), 409

            with db() as conn:
                active = conn.execute(
                    """
                    SELECT job_id, status
                    FROM downloads
                    WHERE source_type = 'single'
                      AND video_id = ?
                      AND status IN ('queued', 'downloading')
                    ORDER BY id DESC
                    LIMIT 1
                    """,
                    (video_id,),
                ).fetchone()
            if active:
                return jsonify({
                    "ok": True,
                    "job_id": active["job_id"],
                    "created": False,
                    "video_id": video_id,
                })

        job_id, created = enqueue_download(
            youtube_url,
            source_type="single",
            video_id=video_id or None,
        )
        return jsonify(
            {
                "ok": True,
                "job_id": job_id,
                "created": created,
                "video_id": video_id or None,
            }
        )
    except Exception as exc:
        return jsonify({"ok": False, "error": str(exc)}), 400


@app.get("/api/downloads/single-completed")
def single_download_completed_api():
    try:
        video_ids = sorted(completed_single_download_video_ids())
        return jsonify({
            "ok": True,
            "video_ids": video_ids,
            "count": len(video_ids),
        })
    except Exception as exc:
        return jsonify({"ok": False, "error": str(exc), "video_ids": []}), 500


@app.get("/api/pinchflat/download-overview")
def pinchflat_download_overview_api():
    try:
        if request.args.get("all", "0") == "1":
            limit = -1
        else:
            limit = int(
                request.args.get(
                    "limit",
                    "0",
                )
                or 0
            )

        data = pinchflat_download_overview(
            limit
        )

        return jsonify(
            {
                "ok": True,
                "database_path": str(
                    resolve_pinchflat_db_path()
                ),
                **data,
            }
        )
    except Exception as exc:
        return jsonify(
            {
                "ok": False,
                "error": str(exc),
                "active": [],
                "waiting": [],
                "summary": {
                    "active": 0,
                    "waiting": 0,
                    "tasks_active": 0,
                    "tasks_waiting": 0,
                },
                "tasks": [],
                "last_downloaded": None,
            }
        ), 503


@app.get("/api/pinchflat/task-block")
def pinchflat_task_block_status_api():
    return jsonify({
        "ok": True,
        "enabled": pinchflat_task_block_enabled(),
        "last": dict(pinchflat_task_block_last),
        "pending": pinchflat_pending_task_count(),
    })


@app.post("/api/pinchflat/task-block")
def pinchflat_task_block_api():
    payload = request.get_json(silent=True) or {}
    enabled = bool(payload.get("enabled"))
    previous = pinchflat_task_block_enabled()
    try:
        if enabled:
            set_setting("pinchflat_task_block_enabled", "1")
            result = pinchflat_delete_all_tasks()
            log_activity(
                "pinchflat",
                "Delete all Pinchflat tasks enabled",
                f"Persistent task blocking enabled. Cancelled {result.get('cancelled', 0)} and deleted {result.get('deleted', 0)} tasks immediately.",
                "warning",
            )
            return jsonify({
                "ok": True,
                "enabled": True,
                "message": (
                    f"Task blocking enabled. Cancelled {result.get('cancelled', 0)} and "
                    f"deleted {result.get('deleted', 0)} Pinchflat tasks. New tasks will be cancelled automatically."
                ),
                "result": result,
            })

        set_setting("pinchflat_task_block_enabled", "0")
        resume = pinchflat_resume_all_tasks()
        log_activity(
            "pinchflat",
            "Delete all Pinchflat tasks disabled",
            "Persistent task blocking disabled and Pinchflat queues resumed.",
            "success",
        )
        return jsonify({
            "ok": True,
            "enabled": False,
            "message": "Task blocking disabled. Pinchflat queues have resumed.",
            "result": resume,
        })
    except Exception as exc:
        set_setting("pinchflat_task_block_enabled", "1" if previous else "0")
        return jsonify({
            "ok": False,
            "enabled": previous,
            "error": str(exc),
        }), 500


@app.get("/api/pinchflat/logs")
def pinchflat_logs_api():
    try:
        tail = request.args.get(
            "tail",
            "250",
        )
        logs = pinchflat_container_logs(tail)

        return jsonify(
            {
                "ok": True,
                "container": PINCHFLAT_CONTAINER_NAME,
                "logs": logs,
            }
        )
    except Exception as exc:
        return jsonify(
            {
                "ok": False,
                "container": PINCHFLAT_CONTAINER_NAME,
                "error": str(exc),
                "logs": "",
            }
        ), 503


@app.get("/api/downloads/<job_id>")
def download_status(job_id):
    job = download_job_row(job_id)
    if not job:
        return jsonify({"ok": False, "error": "Download job not found."}), 404

    job["downloaded_text"] = format_bytes(job.get("downloaded_bytes"))
    job["total_text"] = format_bytes(job.get("total_bytes"))
    return jsonify({"ok": True, "job": job})


@app.get("/api/favourites")
def get_favourites():
    user_id = current_user_id()
    if not user_id:
        return jsonify({"ok": False, "error": "Sign in first."}), 401

    with db() as conn:
        channels = [
            dict(row)
            for row in conn.execute(
                """
                SELECT fc.*,
                       CASE WHEN s.channel_id IS NOT NULL THEN 1 ELSE 0 END AS in_app,
                       CASE
                         WHEN s.channel_id IS NOT NULL THEN COALESCE(s.active, 0)
                         WHEN md.channel_id IS NOT NULL AND COALESCE(md.absence_confirmed, 0) = 0 THEN 1
                         ELSE 0
                       END AS subscribed,
                       COALESCE(s.download_enabled, 0) AS download_enabled,
                       COALESCE(s.pinchflat_added, 0) AS pinchflat_added,
                       COALESCE(s.pinchflat_source_id, '') AS pinchflat_source_id
                FROM favourite_channels fc
                LEFT JOIN subscriptions s ON s.channel_id = fc.channel_id
                LEFT JOIN manually_deleted_channels md ON md.channel_id = fc.channel_id
                WHERE fc.user_id = ?
                ORDER BY fc.channel_title COLLATE NOCASE
                """,
                (user_id,),
            ).fetchall()
        ]
        videos = [
            dict(row)
            for row in conn.execute(
                """
                SELECT sv.*,
                       CASE WHEN EXISTS (
                           SELECT 1 FROM subscriptions s
                           WHERE s.channel_id = sv.channel_id AND s.active = 1
                       ) THEN 1 ELSE 0 END AS is_subscribed
                FROM saved_videos sv
                WHERE sv.user_id = ? AND sv.favourite = 1
                ORDER BY sv.updated_at DESC
                """,
                (user_id,),
            ).fetchall()
        ]
        lists = [
            dict(row)
            for row in conn.execute(
                """
                SELECT vl.*, COUNT(vlm.saved_video_id) AS video_count
                FROM video_lists vl
                LEFT JOIN video_list_members vlm ON vlm.list_id = vl.id
                WHERE vl.user_id = ?
                GROUP BY vl.id
                ORDER BY vl.name COLLATE NOCASE
                """,
                (user_id,),
            ).fetchall()
        ]
        members = [
            dict(row)
            for row in conn.execute(
                """
                SELECT vlm.list_id, sv.*
                FROM video_list_members vlm
                JOIN video_lists vl ON vl.id = vlm.list_id
                JOIN saved_videos sv ON sv.id = vlm.saved_video_id
                WHERE vl.user_id = ?
                ORDER BY vlm.added_at DESC
                """,
                (user_id,),
            ).fetchall()
        ]

    by_list = {}
    for row in members:
        by_list.setdefault(str(row["list_id"]), []).append(row)
    for item in lists:
        item["videos"] = by_list.get(str(item["id"]), [])

    return jsonify(
        {
            "ok": True,
            "channels": channels,
            "videos": videos,
            "lists": lists,
        }
    )


@app.post("/api/favourites/channel/toggle")
def toggle_favourite_channel():
    user_id = current_user_id()
    payload = request.get_json(silent=True) or {}
    channel_id = str(payload.get("channel_id") or "").strip()

    if not user_id or not channel_id:
        return jsonify(
            {
                "ok": False,
                "error": "Channel information is missing.",
            }
        ), 400

    with db() as conn:
        existing = conn.execute(
            "SELECT 1 FROM favourite_channels WHERE user_id = ? AND channel_id = ?",
            (user_id, channel_id),
        ).fetchone()

    favourite = not bool(existing)

    if favourite:
        # Preserve richer metadata supplied by Discover for channels which are
        # not yet present in the subscriptions table.
        with db() as conn:
            sub = conn.execute(
                "SELECT title, channel_url, thumbnail_url FROM subscriptions WHERE channel_id = ?",
                (channel_id,),
            ).fetchone()

            title = str(
                payload.get("channel_title")
                or (sub["title"] if sub else "YouTube channel")
            ).strip()
            url = str(
                payload.get("channel_url")
                or (
                    sub["channel_url"]
                    if sub
                    else f"https://www.youtube.com/channel/{channel_id}"
                )
            ).strip()
            thumb = str(
                payload.get("thumbnail_url")
                or (sub["thumbnail_url"] if sub else "")
            ).strip()

            conn.execute(
                """
                INSERT OR REPLACE INTO favourite_channels (
                    user_id, channel_id, channel_title, channel_url,
                    thumbnail_url, created_at
                ) VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    user_id,
                    channel_id,
                    title[:300],
                    url,
                    thumb,
                    now_iso(),
                ),
            )
    else:
        set_channel_favourite_state(
            channel_id,
            False,
            user_id=user_id,
        )

    return jsonify(
        {
            "ok": True,
            "favourite": favourite,
            "channel_id": channel_id,
        }
    )


@app.post("/api/favourites/video/toggle")
def toggle_favourite_video():
    user_id = current_user_id()
    payload = request.get_json(silent=True) or {}
    if not user_id:
        return jsonify({"ok": False, "error": "Sign in first."}), 401

    item = normalise_saved_video(payload)
    with db() as conn:
        existing = conn.execute(
            "SELECT * FROM saved_videos WHERE user_id = ? AND video_id = ?",
            (user_id, item["video_id"]),
        ).fetchone()
    new_state = not bool(existing and existing["favourite"])
    saved = upsert_saved_video(user_id, item, favourite=new_state)
    return jsonify({"ok": True, "favourite": bool(saved["favourite"]), "video_id": item["video_id"]})


@app.post("/api/favourites/lists/create")
def create_favourite_list():
    user_id = current_user_id()
    payload = request.get_json(silent=True) or {}
    name = str(payload.get("name") or "").strip()
    if not user_id or not name:
        return jsonify({"ok": False, "error": "Enter a list name."}), 400
    if len(name) > 80:
        return jsonify({"ok": False, "error": "List names are limited to 80 characters."}), 400
    try:
        with db() as conn:
            cur = conn.execute(
                "INSERT INTO video_lists (user_id, name, created_at) VALUES (?, ?, ?)",
                (user_id, name, now_iso()),
            )
            list_id = cur.lastrowid
    except sqlite3.IntegrityError:
        return jsonify({"ok": False, "error": "A list with that name already exists."}), 400
    return jsonify({"ok": True, "list": {"id": list_id, "name": name, "video_count": 0, "videos": []}})


@app.post("/api/favourites/lists/delete")
def delete_favourite_list():
    user_id = current_user_id()
    payload = request.get_json(silent=True) or {}
    try:
        list_id = int(payload.get("list_id"))
    except (TypeError, ValueError):
        return jsonify({"ok": False, "error": "Invalid list."}), 400
    with db() as conn:
        owned = conn.execute(
            "SELECT id FROM video_lists WHERE id = ? AND user_id = ?",
            (list_id, user_id),
        ).fetchone()
        if not owned:
            return jsonify({"ok": False, "error": "List not found."}), 404
        conn.execute("DELETE FROM video_list_members WHERE list_id = ?", (list_id,))
        conn.execute("DELETE FROM video_lists WHERE id = ?", (list_id,))
    return jsonify({"ok": True})


@app.post("/api/favourites/lists/add")
def add_video_to_favourite_list():
    user_id = current_user_id()
    payload = request.get_json(silent=True) or {}
    try:
        list_id = int(payload.get("list_id"))
    except (TypeError, ValueError):
        return jsonify({"ok": False, "error": "Choose a list."}), 400
    with db() as conn:
        owned = conn.execute(
            "SELECT id FROM video_lists WHERE id = ? AND user_id = ?",
            (list_id, user_id),
        ).fetchone()
    if not owned:
        return jsonify({"ok": False, "error": "List not found."}), 404
    saved = upsert_saved_video(user_id, payload, favourite=None)
    with db() as conn:
        conn.execute(
            "INSERT OR IGNORE INTO video_list_members (list_id, saved_video_id, added_at) VALUES (?, ?, ?)",
            (list_id, saved["id"], now_iso()),
        )
    return jsonify({"ok": True})


@app.post("/api/favourites/lists/remove")
def remove_video_from_favourite_list():
    user_id = current_user_id()
    payload = request.get_json(silent=True) or {}
    try:
        list_id = int(payload.get("list_id"))
    except (TypeError, ValueError):
        return jsonify({"ok": False, "error": "Invalid list."}), 400
    video_id = str(payload.get("video_id") or "").strip()
    with db() as conn:
        row = conn.execute(
            """
            SELECT sv.id
            FROM saved_videos sv
            JOIN video_lists vl ON vl.user_id = sv.user_id
            WHERE sv.user_id = ? AND sv.video_id = ? AND vl.id = ?
            """,
            (user_id, video_id, list_id),
        ).fetchone()
        if row:
            conn.execute(
                "DELETE FROM video_list_members WHERE list_id = ? AND saved_video_id = ?",
                (list_id, row["id"]),
            )
    return jsonify({"ok": True})


@app.post("/api/favourites/video/download")
def download_favourite_video():
    user_id = current_user_id()
    payload = request.get_json(silent=True) or {}
    video_id = str(payload.get("video_id") or "").strip()
    with db() as conn:
        row = conn.execute(
            "SELECT * FROM saved_videos WHERE user_id = ? AND video_id = ?",
            (user_id, video_id),
        ).fetchone()
    if not row:
        return jsonify({"ok": False, "error": "Saved video not found."}), 404
    job_id, created = enqueue_download(
        row["video_url"], source_type="favourite", video_id=row["video_id"],
        title=row["title"], channel_title=row["channel_title"],
    )
    return jsonify({"ok": True, "job_id": job_id, "queued": created})


@app.post("/api/favourites/lists/download")
def download_favourite_list():
    user_id = current_user_id()
    payload = request.get_json(silent=True) or {}
    try:
        list_id = int(payload.get("list_id"))
    except (TypeError, ValueError):
        return jsonify({"ok": False, "error": "Invalid list."}), 400
    with db() as conn:
        list_row = conn.execute(
            "SELECT * FROM video_lists WHERE id = ? AND user_id = ?",
            (list_id, user_id),
        ).fetchone()
        videos = conn.execute(
            """
            SELECT sv.* FROM video_list_members vlm
            JOIN saved_videos sv ON sv.id = vlm.saved_video_id
            WHERE vlm.list_id = ? AND sv.user_id = ?
            ORDER BY vlm.added_at ASC
            """,
            (list_id, user_id),
        ).fetchall()
    if not list_row:
        return jsonify({"ok": False, "error": "List not found."}), 404
    queued = 0
    skipped = 0
    for row in videos:
        _job_id, created = enqueue_download(
            row["video_url"], source_type=f"favourite_list:{list_row['name']}",
            video_id=row["video_id"], title=row["title"], channel_title=row["channel_title"],
        )
        queued += 1 if created else 0
        skipped += 0 if created else 1
    return jsonify({"ok": True, "queued": queued, "skipped": skipped})


@app.post("/api/youtube/subscribe")
def subscribe_to_youtube_channel():
    payload = request.get_json(silent=True) or {}
    channel_id = str(payload.get("channel_id") or "").strip()
    if not channel_id:
        return jsonify({"ok": False, "error": "Channel ID is missing."}), 400
    try:
        with db() as conn:
            existing = conn.execute(
                "SELECT active FROM subscriptions WHERE channel_id = ?",
                (channel_id,),
            ).fetchone()
        if not existing or not bool(existing["active"]):
            youtube_subscribe(channel_id)
        refresh_subscriptions()
        return jsonify({"ok": True, "already_subscribed": bool(existing and existing["active"])})
    except Exception as exc:
        return jsonify({"ok": False, "error": str(exc)}), 400


@app.get("/api/latest-subscriptions")
def latest_subscription_videos():
    refresh = request.args.get("refresh", "0") == "1"

    try:
        result = youtube_latest_subscription_videos(
            limit=36,
            force=refresh,
        )
        return jsonify({"ok": True, **result})
    except Exception as exc:
        return jsonify({"ok": False, "error": str(exc)}), 400


@app.post("/api/youtube/video/like")
def like_youtube_video():
    payload = request.get_json(silent=True) or {}
    video_id = str(payload.get("video_id") or "").strip()

    if not video_id:
        return jsonify(
            {"ok": False, "error": "A YouTube video ID is required."}
        ), 400

    try:
        creds = load_credentials()
        if not creds:
            raise RuntimeError("Google account is not connected.")

        if not google_write_scope_ready(creds):
            raise RuntimeError(
                "Google is connected without YouTube write access. "
                "Reconnect Google to enable liking videos."
            )

        youtube_api_request(
            creds,
            "POST",
            "videos/rate",
            "videos.rate",
            50,
            params={
                "id": video_id,
                "rating": "like",
            },
        )

        item = {
            "video_id": video_id,
            "title": str(payload.get("title") or "YouTube video"),
            "channel_id": str(payload.get("channel_id") or ""),
            "channel_title": str(payload.get("channel_title") or "YouTube"),
        }
        record_discovery_like(item)

        with YOUTUBE_LIKED_VIDEOS_LOCK:
            YOUTUBE_LIKED_VIDEOS_CACHE.update(
                {
                    "expires_at": 0.0,
                    "results": [],
                    "retrieved_at": "",
                }
            )
        with YOUTUBE_DISLIKED_VIDEOS_LOCK:
            YOUTUBE_DISLIKED_VIDEOS_CACHE.update(
                {
                    "expires_at": 0.0,
                    "results": [],
                    "retrieved_at": "",
                }
            )

        log_activity(
            "youtube",
            "YouTube video liked",
            (
                f"Liked {item['title']} from "
                f"{item['channel_title']} on YouTube."
            ),
            "success",
            item["channel_id"] or None,
        )

        return jsonify(
            {
                "ok": True,
                "video_id": video_id,
                "liked": True,
            }
        )

    except Exception as exc:
        return jsonify(
            {"ok": False, "error": str(exc)}
        ), 400


@app.get("/api/youtube/video-metadata/<video_id>")
def youtube_video_metadata_api(video_id):
    try:
        return jsonify(
            {
                "ok": True,
                "video": youtube_video_metadata(
                    video_id
                ),
            }
        )
    except Exception as exc:
        return jsonify(
            {
                "ok": False,
                "error": str(exc),
            }
        ), 400


@app.get("/api/discover")
def discover_videos():
    kind = request.args.get("kind", "videos").strip().lower()
    refresh = request.args.get("refresh", "0") == "1"

    if kind not in {
        "downloaded",
        "liked",
        "disliked",
        "videos",
        "shorts",
        "top100",
    }:
        kind = "downloaded"

    try:
        if kind == "downloaded":
            stats = api_usage_stats()
            return jsonify(
                {
                    "ok": True,
                    "results": pinchflat_recent_downloaded_videos(
                        100
                    ),
                    "source": "Pinchflat",
                    "search_remaining": stats["search_remaining"],
                }
            )

        if kind == "liked":
            result = youtube_liked_videos(
                force=refresh
            )
            stats = api_usage_stats()

            return jsonify(
                {
                    "ok": True,
                    **result,
                    "search_remaining": (
                        stats["search_remaining"]
                    ),
                }
            )

        if kind == "disliked":
            result = youtube_disliked_videos(
                force=refresh
            )
            stats = api_usage_stats()

            return jsonify(
                {
                    "ok": True,
                    **result,
                    "search_remaining": (
                        stats["search_remaining"]
                    ),
                }
            )

        if kind == "top100":
            result = youtube_top100_channels(force=refresh)
            result["results"] = annotate_favourites(result.get("results", []))
            stats = api_usage_stats()
            return jsonify(
                {
                    "ok": True,
                    **result,
                    "search_remaining": stats["search_remaining"],
                }
            )

        result = youtube_discovery_results(
            kind=kind,
            limit=24 if kind == "shorts" else 150,
        )
        result["results"] = annotate_favourites(result.get("results", []))
        return jsonify({"ok": True, **result})
    except Exception as exc:
        return jsonify({"ok": False, "error": str(exc)}), 400


@app.post("/settings/apis")
def save_api_settings():
    server_url = str(request.form.get("emby_server_url") or "").strip().rstrip("/")
    api_key = str(request.form.get("emby_api_key") or "").strip()
    auto_refresh = request.form.get("emby_auto_refresh_after_download") == "1"
    clear_key = request.form.get("emby_clear_api_key") == "1"

    set_setting("emby_server_url", server_url)
    if clear_key:
        set_setting("emby_api_key", "")
    elif api_key:
        set_setting("emby_api_key", api_key)

    set_setting(
        "emby_auto_refresh_after_download",
        "1" if auto_refresh else "0",
    )

    # Seed the automatic-refresh marker when Emby is first configured. This
    # means the monitor reacts to the next completed download rather than
    # treating content which was already present as a new event.
    if auto_refresh and not get_setting("emby_last_refresh_media_id", "").strip():
        try:
            overview = pinchflat_download_overview(queue_limit=0)
            latest = overview.get("last_downloaded") or {}
            media_id = str(latest.get("media_item_id") or "").strip()
            if media_id:
                set_setting("emby_last_refresh_media_id", media_id)
        except Exception:
            pass

    log_activity(
        "settings",
        "Emby API settings updated",
        (
            f"Server: {server_url or 'not configured'}. "
            f"Automatic refresh: {'enabled' if auto_refresh else 'disabled'}."
        ),
        "info",
    )
    flash("Emby API settings saved.", "success")
    return redirect(url_for("index") + "#emby")


@app.get("/api/emby/test")
def emby_test_api():
    try:
        info = emby_test_connection()
        library = info.get("youtube_library") or {}
        library_note = (
            f" · Pinchflat library: {library.get('name')}"
            if library.get("name")
            else ""
        )
        single_library = {}
        single_error = ""
        playlist_library = {}
        playlist_error = ""
        try:
            single_library = emby_detect_download_library(
                get_setting("single_download_folder", "Single Downloads")
            )
        except Exception as exc:
            single_error = str(exc)
        try:
            playlist_library = emby_detect_download_library(
                get_setting("emby_download_folder", "Emby Download")
            )
        except Exception as exc:
            playlist_error = str(exc)

        return jsonify(
            {
                "ok": True,
                "message": (
                    f"Connected to {info['server_name']}"
                    + (f" · Emby {info['version']}" if info.get("version") else "")
                    + library_note
                ),
                "server": info,
                "youtube_library": library,
                "youtube_library_error": info.get("youtube_library_error") or "",
                "single_download_library": single_library,
                "single_download_library_error": single_error,
                "emby_download_library": playlist_library,
                "emby_download_library_error": playlist_error,
            }
        )
    except Exception as exc:
        return jsonify(
            {
                "ok": False,
                "error": str(exc),
            }
        ), 400


@app.post("/api/emby/refresh")
def emby_refresh_api():
    payload = request.get_json(silent=True) or {}
    channel_id = str(payload.get("channel_id") or "").strip()
    channel_title = str(payload.get("channel_title") or "").strip()
    target = str(payload.get("target") or "pinchflat").strip().lower()

    try:
        if target == "single":
            result = emby_refresh_download_library(
                get_setting("single_download_folder", "Single Downloads"),
                "One-time Download",
            )
        elif target == "emby_download":
            result = emby_refresh_download_library(
                get_setting("emby_download_folder", "Emby Download"),
                "Emby Download",
            )
        else:
            result = emby_refresh_library(
                channel_id=channel_id,
                channel_title=channel_title,
            )
        if result.get("scope") == "channel":
            message = f"Emby scan started for {result.get('channel') or 'the channel'}. Metadata refresh will follow."
        else:
            library = result.get("library") or {}
            message = f"Emby scan started for {library.get('name') or 'the selected YouTube library'}. Metadata refresh will follow."
        return jsonify(
            {
                "ok": True,
                "message": message,
                "scope": result.get("scope"),
                "library": result.get("library") or {},
            }
        )
    except Exception as exc:
        return jsonify(
            {
                "ok": False,
                "error": str(exc),
            }
        ), 400


@app.post("/settings/youtube")
def save_youtube_settings():
    try:
        quota = int(request.form.get("youtube_daily_quota", "10000"))
    except ValueError:
        quota = 10000

    quota = min(max(quota, 100), 100000000)
    set_setting("youtube_daily_quota", str(quota))

    log_activity(
        "settings",
        "YouTube settings updated",
        f"Daily API quota estimate set to {quota}.",
        "info",
    )
    flash("YouTube settings saved.", "success")
    return redirect(url_for("index") + "#youtube")


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
    return jsonify({"status": "ok", "version": VERSION})


init_db()
init_v3_db()
start_download_worker()
start_scan_worker()
threading.Thread(target=_v3_import_existing_library, name="v3-library-import", daemon=True).start()

scheduler = BackgroundScheduler(
    timezone=os.getenv("TZ", "Europe/London")
)
scheduler.add_job(
    youtube_sync_once,
    "interval",
    minutes=current_youtube_sync_interval(),
    id="youtube-subscription-sync",
    max_instances=1,
)
scheduler.add_job(
    pinchflat_sync_once,
    "interval",
    minutes=current_pinchflat_sync_interval(),
    id="pinchflat-source-sync",
    max_instances=1,
)
scheduler.add_job(
    sync_emby_download_playlist,
    "interval",
    minutes=current_emby_poll_interval(),
    id="emby-download-sync",
    max_instances=1,
)
scheduler.add_job(
    process_deferred_unsubscribe_cleanups,
    "interval",
    minutes=1,
    id="unsubscribe-cleanup",
    max_instances=1,
)
scheduler.add_job(
    emby_auto_refresh_new_downloads,
    "interval",
    minutes=1,
    id="emby-library-refresh-monitor",
    max_instances=1,
)
scheduler.add_job(
    scheduled_pinchflat_force_index,
    "interval",
    minutes=1,
    id="pinchflat-scheduled-force-index",
    max_instances=1,
    coalesce=True,
)
scheduler.add_job(
    scheduled_retention_cleanup,
    "interval",
    hours=1,
    id="video-retention-cleanup",
    max_instances=1,
    coalesce=True,
)
scheduler.start()
