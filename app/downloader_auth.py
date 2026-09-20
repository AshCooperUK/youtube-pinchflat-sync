import json
import os
from pathlib import Path

import yt_dlp

AUTH_RETRY_MARKERS = (
    "sign in to confirm your age",
    "sign in to confirm you're not a bot",
    "sign in to confirm you’re not a bot",
    "this video is available to this channel's members",
    "join this channel",
    "members-only",
    "members only",
    "private video",
    "login required",
    "authentication required",
    "confirm your age",
)

ERROR_MARKERS = (
    ("membership_required", ("join this channel", "members-only", "members only", "channel's members")),
    ("age_restricted", ("confirm your age", "age-restricted", "age restricted")),
    ("rate_limited", ("http error 429", "too many requests", "not a bot")),
    ("private", ("private video", "video is private")),
    ("authentication_required", ("sign in", "login required", "authentication required")),
    ("unavailable", ("video unavailable", "this video is unavailable", "content isn't available", "content is not available")),
)


def validate_netscape_cookie_text(text):
    if not isinstance(text, str):
        raise ValueError("Cookie file must be text.")
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    lines = text.split("\n")
    first = next((line.strip() for line in lines if line.strip()), "")
    if first not in {"# HTTP Cookie File", "# Netscape HTTP Cookie File"}:
        raise ValueError(
            "Cookies must be exported in Mozilla/Netscape cookies.txt format."
        )

    cookie_rows = 0
    youtube_rows = 0
    google_rows = 0
    for raw in lines:
        line = raw.strip("\n")
        if not line:
            continue
        # Netscape cookie exports encode HttpOnly cookies as
        # "#HttpOnly_.example.com<TAB>...". They are cookie records, not
        # comments, and YouTube account cookies commonly use this form.
        if line.startswith("#HttpOnly_"):
            line = line[len("#HttpOnly_"):]
        elif line.lstrip().startswith("#"):
            continue
        fields = line.split("\t")
        if len(fields) < 7:
            raise ValueError("Cookie file contains a row which is not Netscape format.")
        domain = fields[0].lstrip(".").casefold()
        cookie_rows += 1
        if domain == "youtube.com" or domain.endswith(".youtube.com"):
            youtube_rows += 1
        if domain == "google.com" or domain.endswith(".google.com"):
            google_rows += 1

    if cookie_rows == 0:
        raise ValueError("Cookie file does not contain any cookies.")
    if youtube_rows == 0:
        raise ValueError("Cookie file does not contain any YouTube cookies.")

    normalised = "\n".join(lines).rstrip("\n") + "\n"
    return normalised, {
        "cookies": cookie_rows,
        "youtube_cookies": youtube_rows,
        "google_cookies": google_rows,
    }


def cookie_file_status(path):
    path = Path(path)
    if not path.exists() or not path.is_file():
        return {
            "configured": False,
            "valid": False,
            "size": 0,
            "youtube_cookies": 0,
            "google_cookies": 0,
            "error": "",
        }
    try:
        text = path.read_text(encoding="utf-8")
        _normalised, stats = validate_netscape_cookie_text(text)
        return {
            "configured": True,
            "valid": True,
            "size": path.stat().st_size,
            **stats,
            "error": "",
        }
    except Exception as exc:
        return {
            "configured": True,
            "valid": False,
            "size": path.stat().st_size if path.exists() else 0,
            "youtube_cookies": 0,
            "google_cookies": 0,
            "error": str(exc),
        }


def save_cookie_upload(file_storage, destination, max_bytes=5 * 1024 * 1024):
    if file_storage is None:
        raise ValueError("Choose a cookies.txt file to upload.")
    raw = file_storage.read(max_bytes + 1)
    if len(raw) > max_bytes:
        raise ValueError("Cookie file is larger than 5 MB.")
    try:
        text = raw.decode("utf-8-sig")
    except UnicodeDecodeError as exc:
        raise ValueError("Cookie file must be UTF-8 text.") from exc

    normalised, stats = validate_netscape_cookie_text(text)
    destination = Path(destination)
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = destination.with_suffix(destination.suffix + ".upload")
    temporary.write_text(normalised, encoding="utf-8", newline="\n")
    try:
        temporary.chmod(0o600)
    except OSError:
        pass
    os.replace(temporary, destination)
    try:
        destination.chmod(0o600)
    except OSError:
        pass
    return stats


def classify_yt_dlp_error(error):
    message = str(error or "")
    lowered = message.casefold()
    for code, markers in ERROR_MARKERS:
        if any(marker in lowered for marker in markers):
            return code
    return "download_error"


def should_retry_with_cookies(error):
    lowered = str(error or "").casefold()
    return any(marker in lowered for marker in AUTH_RETRY_MARKERS)


def parse_custom_yt_dlp_options(raw):
    raw = str(raw or "").strip()
    if not raw:
        return {}
    try:
        value = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise ValueError("Custom yt-dlp options must be valid JSON.") from exc
    if not isinstance(value, dict):
        raise ValueError("Custom yt-dlp options must be a JSON object.")

    blocked = {
        "outtmpl",
        "progress_hooks",
        "postprocessor_hooks",
        "cookiefile",
        "cookiesfrombrowser",
        "paths",
        "windowsfilenames",
        "restrictfilenames",
    }
    return {key: val for key, val in value.items() if key not in blocked}


def authenticated_ydl_options(base_options, cookie_path=None, po_token="", custom_options=None):
    options = dict(base_options or {})
    if cookie_path:
        path = Path(cookie_path)
        if path.exists() and path.is_file():
            options["cookiefile"] = str(path)

    token = str(po_token or "").strip()
    if token:
        # Manual GVS tokens remain available as an expert fallback. Current
        # yt-dlp guidance recommends a PO Token Provider plugin for reliable
        # automatic token generation, so this field is deliberately optional.
        extractor_args = dict(options.get("extractor_args") or {})
        youtube_args = dict(extractor_args.get("youtube") or {})
        youtube_args["player_client"] = ["default", "mweb"]
        youtube_args["po_token"] = [f"mweb.gvs+{token}"]
        extractor_args["youtube"] = youtube_args
        options["extractor_args"] = extractor_args

    options.update(custom_options or {})
    return options


def test_cookie_authentication(cookie_path, po_token="", custom_options=None):
    status = cookie_file_status(cookie_path)
    if not status["configured"]:
        raise RuntimeError("No YouTube cookie file is configured.")
    if not status["valid"]:
        raise RuntimeError(status["error"] or "The cookie file is invalid.")

    options = authenticated_ydl_options(
        {
            "quiet": True,
            "no_warnings": True,
            "skip_download": True,
            "extract_flat": True,
            "playlistend": 1,
            "socket_timeout": 20,
        },
        cookie_path=cookie_path,
        po_token=po_token,
        custom_options=custom_options,
    )
    # Watch Later is private and therefore a useful lightweight authentication
    # probe. We only request one flat entry and never download media.
    with yt_dlp.YoutubeDL(options) as ydl:
        info = ydl.extract_info(
            "https://www.youtube.com/playlist?list=WL",
            download=False,
        )
    return {
        "ok": bool(info),
        "title": str((info or {}).get("title") or "Watch Later"),
        "entries": len((info or {}).get("entries") or []),
    }
