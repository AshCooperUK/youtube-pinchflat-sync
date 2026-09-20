"""Publication dates for Emby. Never derive release dates from file/import times."""
from datetime import date, datetime, timezone
from pathlib import Path
import os
import re
import stat
import tempfile
import xml.etree.ElementTree as ET
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError


def exact_timestamp(value):
    text = str(value or '').strip()
    if 'T' not in text and ' ' not in text:
        return None
    try:
        result = datetime.fromisoformat(text.replace('Z', '+00:00'))
        if result.tzinfo is None:
            return None
        return result.astimezone(timezone.utc).isoformat()
    except (ValueError, TypeError, OverflowError):
        return None


def publication_value(info, fallback=''):
    info = info or {}
    for value in (info.get('youtube_published_at'), info.get('published_at')):
        if exact_timestamp(value):
            return exact_timestamp(value)
    for key in ('release_timestamp', 'timestamp'):
        try:
            if info.get(key) is not None:
                return datetime.fromtimestamp(float(info[key]), timezone.utc).isoformat()
        except (ValueError, TypeError, OSError, OverflowError):
            pass
    if exact_timestamp(fallback):
        return exact_timestamp(fallback)
    for value in (info.get('upload_date'), info.get('release_date'), info.get('published_at'), fallback):
        text = str(value or '').strip()
        if re.fullmatch(r'\d{8}', text):
            text = f'{text[:4]}-{text[4:6]}-{text[6:8]}'
        try:
            return date.fromisoformat(text).isoformat()
        except ValueError:
            pass
    return ''


def publication_date(value, tz_name='Europe/London'):
    exact = exact_timestamp(value)
    if exact:
        try:
            zone = ZoneInfo(tz_name)
        except (ValueError, ZoneInfoNotFoundError):
            zone = ZoneInfo('Europe/London')
        return datetime.fromisoformat(exact).astimezone(zone).date()
    try:
        return date.fromisoformat(str(value or ''))
    except ValueError:
        return None


def xml_text(value):
    return re.sub(r'[\x00-\x08\x0b\x0c\x0e-\x1f\ud800-\udfff\ufffe\uffff]', '', str(value or ''))


def atomic_xml(root, path):
    ET.indent(root, space='  ')
    content = ET.tostring(root, encoding='utf-8', xml_declaration=True)
    if path.is_file() and path.read_bytes() == content:
        return False
    previous = path.stat() if path.is_file() else None
    fd, temporary = tempfile.mkstemp(prefix='.ytsd-nfo-', dir=path.parent)
    try:
        # mkstemp defaults to 0600. New NFOs must be readable by Emby's account.
        os.fchmod(fd, stat.S_IMODE(previous.st_mode) if previous else 0o644)
        if previous:
            try:
                os.fchown(fd, previous.st_uid, previous.st_gid)
            except (AttributeError, PermissionError):
                pass
        with os.fdopen(fd, 'wb') as stream:
            stream.write(content)
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)
    return True


def write_video_nfo(info, output_path, episode=True, tz_name='Europe/London'):
    path = Path(output_path).with_suffix('.nfo')
    root = ET.parse(path).getroot() if path.is_file() else ET.Element('episodedetails' if episode else 'movie')
    # Preserve ratings, watched state, user edits and all unrelated NFO fields.
    def put(key, value, replace=True):
        node = root.find(key)
        if node is None:
            node = ET.SubElement(root, key)
        if replace or not node.text:
            node.text = xml_text(value)
    put('title', info.get('title') or Path(output_path).stem, False)
    put('plot', info.get('description') or '', False)
    if episode:
        put('showtitle', info.get('channel') or info.get('uploader') or 'YouTube', False)
    released = publication_date(publication_value(info), tz_name)
    if released:
        for key in ('premiered', 'releasedate') + (('aired',) if episode else ()):
            put(key, released.isoformat())
        put('year', str(released.year))
        if episode:
            # Filename-based episode numbering remains unchanged on repair.
            match = re.match(r's(\d+)E(\d+)', Path(output_path).stem, re.I)
            put('season', match[1] if match else str(released.year), False)
            put('episode', match[2] if match else released.strftime('%m%d') + '00', False)
    video_id = str(info.get('id') or info.get('video_id') or '')
    if re.fullmatch(r'[A-Za-z0-9_-]{11}', video_id):
        node = root.find("uniqueid[@type='youtube']")
        if node is None:
            node = ET.SubElement(root, 'uniqueid', {'type': 'youtube', 'default': 'true'})
        node.text = video_id
    return atomic_xml(root, path)
