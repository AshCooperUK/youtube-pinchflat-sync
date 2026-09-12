import json
import os
import secrets
import sqlite3
import threading
import time
from datetime import date, datetime, timezone
from pathlib import Path

import requests
from apscheduler.schedulers.background import BackgroundScheduler
from bs4 import BeautifulSoup
from dateutil.relativedelta import relativedelta
from flask import Flask, flash, jsonify, redirect, render_template, request, session, url_for
from google.auth.transport.requests import Request as GoogleRequest
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import Flow
from werkzeug.middleware.proxy_fix import ProxyFix

VERSION = "1.2.0"

DATA_DIR = Path(os.getenv("DATA_DIR", "/data"))
DATA_DIR.mkdir(parents=True, exist_ok=True)
DB_PATH = DATA_DIR / "sync.db"
TOKEN_PATH = DATA_DIR / "google-token.json"
SECRET_PATH = DATA_DIR / "flask-secret.txt"

YOUTUBE_SCOPE = os.getenv(
    "YOUTUBE_SCOPE",
    "https://www.googleapis.com/auth/youtube.readonly",
)

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

        # v1.2 migration. Existing databases are upgraded in place.
        ensure_column(conn, "subscriptions", "history_mode", "TEXT")
        ensure_column(conn, "subscriptions", "history_custom_date", "TEXT")
        ensure_column(conn, "subscriptions", "pinchflat_source_id", "TEXT")

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
    creds = Credentials.from_authorized_user_info(
        data,
        scopes=[YOUTUBE_SCOPE],
    )

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

        response = requests.get(
            "https://www.googleapis.com/youtube/v3/subscriptions",
            headers=headers,
            params=params,
            timeout=30,
        )
        response.raise_for_status()
        payload = response.json()

        for item in payload.get("items", []):
            snippet = item["snippet"]
            channel_id = snippet["resourceId"]["channelId"]

            items.append(
                {
                    "channel_id": channel_id,
                    "title": snippet.get("title", channel_id),
                    "channel_url": (
                        f"https://www.youtube.com/channel/{channel_id}"
                    ),
                    "subscribed_at": snippet.get("publishedAt"),
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

    with db() as conn:
        conn.execute("UPDATE subscriptions SET active = 0")

        for sub in subs:
            conn.execute(
                """
                INSERT INTO subscriptions (
                    channel_id,
                    title,
                    channel_url,
                    subscribed_at,
                    first_seen_at,
                    active,
                    history_mode
                )
                VALUES (?, ?, ?, ?, ?, 1, 'default')
                ON CONFLICT(channel_id) DO UPDATE SET
                    title = excluded.title,
                    channel_url = excluded.channel_url,
                    subscribed_at = excluded.subscribed_at,
                    active = 1
                """,
                (
                    sub["channel_id"],
                    sub["title"],
                    sub["channel_url"],
                    sub["subscribed_at"],
                    first_seen,
                ),
            )

    return len(subs)


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


def add_pinchflat_source(sub):
    session_obj = pinchflat_session()

    form_page = session_obj.get(
        f"{PINCHFLAT_URL}/sources/new",
        timeout=30,
    )
    form_page.raise_for_status()

    soup = BeautifulSoup(form_page.text, "html.parser")
    csrf = soup.find("input", {"name": "_csrf_token"})

    if not csrf or not csrf.get("value"):
        raise RuntimeError(
            "Pinchflat CSRF token was not found. "
            "Check the Pinchflat URL and authentication."
        )

    cutoff = subscription_cutoff(sub)

    payload = {
        "_csrf_token": csrf["value"],
        "source[original_url]": row_value(sub, "channel_url", ""),
        "source[custom_name]": row_value(sub, "title", ""),
        "source[media_profile_id]": effective_media_profile_id(),
        "source[download_media]": "true",
        "source[fast_index]": "false",
        "source[index_frequency_minutes]": "1440",
        "source[download_cutoff_date]": cutoff,
        "source[retention_period_days]": "",
        "source[title_filter_regex]": "",
        "source[output_path_template_override]": "",
        "source[min_duration_seconds]": "",
        "source[max_duration_seconds]": "",
        "source[cookie_behaviour]": "disabled",
    }

    if DRY_RUN:
        return "dry-run"

    response = session_obj.post(
        f"{PINCHFLAT_URL}/sources",
        data=payload,
        timeout=180,
        allow_redirects=False,
    )

    if response.status_code in (301, 302, 303):
        location = response.headers.get("Location", "")
        match = __import__("re").search(r"/sources/([^/?#]+)", location)
        source_id = match.group(1) if match else None
        return "created", source_id

    if response.status_code == 200:
        error_soup = BeautifulSoup(
            response.text,
            "html.parser",
        )
        text = " ".join(error_soup.stripped_strings)

        if "already been taken" in text.lower():
            return "exists", None

        raise RuntimeError(
            "Pinchflat rejected the source. "
            "Open Pinchflat and check its logs."
        )

    response.raise_for_status()
    return "created", None


def update_pinchflat_source_cutoff(source_id, cutoff):
    """Update the download cutoff on an existing Pinchflat source via its HTML edit form."""
    session_obj = pinchflat_session()
    edit_url = f"{PINCHFLAT_URL}/sources/{source_id}/edit"
    response = session_obj.get(edit_url, timeout=30)
    response.raise_for_status()

    soup = BeautifulSoup(response.text, "html.parser")
    form = soup.find("form")
    if not form:
        raise RuntimeError("Pinchflat edit form was not found.")

    payload = {}

    for field in form.find_all(["input", "select", "textarea"]):
        name = field.get("name")
        if not name:
            continue

        if field.name == "input":
            field_type = (field.get("type") or "text").lower()
            if field_type in ("submit", "button", "file"):
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

    payload["source[download_cutoff_date]"] = cutoff

    action = form.get("action") or f"/sources/{source_id}"
    if action.startswith("http://") or action.startswith("https://"):
        target = action
    else:
        target = f"{PINCHFLAT_URL}{action}"

    update_response = session_obj.post(
        target,
        data=payload,
        timeout=180,
        allow_redirects=False,
    )

    if update_response.status_code in (301, 302, 303):
        return True

    if update_response.status_code == 200:
        text = " ".join(BeautifulSoup(update_response.text, "html.parser").stripped_strings)
        raise RuntimeError(
            "Pinchflat did not accept the updated cutoff. "
            f"Response: {text[:300]}"
        )

    update_response.raise_for_status()
    return True


def add_pending_sources():
    with db() as conn:
        pending = conn.execute(
            """
            SELECT *
            FROM subscriptions
            WHERE active = 1 AND pinchflat_added = 0
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
                        last_error = NULL
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
                    SET last_error = ?
                    WHERE channel_id = ?
                    """,
                    (
                        str(exc)[:1000],
                        sub["channel_id"],
                    ),
                )

        if ADD_DELAY_SECONDS > 0:
            time.sleep(ADD_DELAY_SECONDS)

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

        total = refresh_subscriptions()
        result = add_pending_sources()

        status = (
            "ok"
            if result["errors"] == 0
            else "completed_with_errors"
        )

        message = (
            f"Found {total} subscriptions. "
            f"Added {result['added']} Pinchflat sources. "
            f"Errors: {result['errors']}."
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
                    total,
                    result["added"],
                    result["errors"],
                    message,
                    run_id,
                ),
            )

        return {
            "status": status,
            "total": total,
            "added": result["added"],
            "errors": result["errors"],
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

    return item


@app.route("/")
def index():
    google_connected = False

    if google_configured():
        try:
            creds = load_credentials()
            google_connected = bool(creds and creds.valid)
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

    subs = [subscription_view(row) for row in rows]
    defaults = default_history_settings()

    return render_template(
        "index.html",
        version=VERSION,
        google_configured=google_configured(),
        google_connected=google_connected,
        callback_uri=google_redirect_uri(),
        app_url=effective_app_url(),
        media_profile_id=effective_media_profile_id(),
        pinchflat_online=pinchflat_health(),
        pinchflat_public_url=PINCHFLAT_PUBLIC_URL,
        subs=subs,
        last_run=last_run,
        dry_run=DRY_RUN,
        interval=SYNC_INTERVAL_MINUTES,
        default_history_mode=defaults["mode"],
        default_history_years=defaults["years"],
        default_history_custom_date=defaults["custom_date"],
        default_history_cutoff=resolve_history_cutoff(),
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
            SELECT pinchflat_added, pinchflat_source_id, subscribed_at
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
            update_pinchflat_source_cutoff(
                row["pinchflat_source_id"],
                cutoff,
            )
            flash(
                f"Source download range saved and Pinchflat cutoff updated to {cutoff}.",
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
        include_granted_scopes="true",
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

    flash(
        "Google account connected.",
        "success",
    )
    return redirect(url_for("index"))


@app.post("/oauth/google/disconnect")
def google_disconnect():
    if TOKEN_PATH.exists():
        TOKEN_PATH.unlink()

    flash(
        "Google account disconnected.",
        "success",
    )
    return redirect(url_for("index"))


@app.post("/refresh-subscriptions")
def refresh_only():
    try:
        total = refresh_subscriptions()
        flash(
            f"Refreshed {total} YouTube subscriptions. "
            "Choose per-source ranges before adding pending sources if required.",
            "success",
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
            "default_cutoff": resolve_history_cutoff(),
        }
    )


init_db()

scheduler = BackgroundScheduler(
    timezone=os.getenv("TZ", "Europe/London")
)
scheduler.add_job(
    sync_once,
    "interval",
    minutes=SYNC_INTERVAL_MINUTES,
    id="subscription-sync",
    max_instances=1,
)
scheduler.start()
