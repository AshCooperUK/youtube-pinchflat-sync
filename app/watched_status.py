"""YouTube watched requests. Never infer account history from HTTP success."""
import http.cookiejar
import json
import re
import time
import requests
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path


def cookie_session_file_status(cookie_path):
    try:
        jar = http.cookiejar.MozillaCookieJar(str(cookie_path))
        jar.load(ignore_discard=True, ignore_expires=True)
        tokens = [c for c in jar if c.domain.lstrip('.') == 'youtube.com' and c.name in
                  {'SID','SAPISID','__Secure-1PAPISID','__Secure-3PAPISID'}]
        if not tokens:
            return 'auth_required', 'Signed-in YouTube cookies are missing. Upload a fresh cookie file in Downloader.'
        if not any(c.expires is None or c.expires > time.time() for c in tokens):
            return 'auth_expired', 'Your YouTube cookies have expired. Upload fresh signed-in cookies in Downloader. Watched requests are paused.'
        return 'unchecked', 'Cookie file available. The signed-in session will be checked before each watched request.'
    except (OSError, ValueError, http.cookiejar.LoadError):
        return 'auth_required', 'YouTube cookies are missing or invalid. Upload fresh signed-in cookies in Downloader.'


def check_cookie_session(cookie_path):
    state,message = cookie_session_file_status(cookie_path)
    if state != 'unchecked':
        return state,message
    try:
        jar = http.cookiejar.MozillaCookieJar(str(cookie_path))
        jar.load(ignore_discard=True, ignore_expires=False)
        with requests.Session() as session:
            session.cookies.update(jar)
            response = session.get('https://www.youtube.com/feed/history', timeout=(5,15),
                headers={'User-Agent':'Mozilla/5.0','Accept-Language':'en-GB,en;q=0.9'})
            response.raise_for_status()
        # Only explicit server confirmation counts as an active signed-in session.
        states = []
        for match in re.finditer(r'ytcfg\.set\(\s*', response.text):
            try:
                config,_ = json.JSONDecoder().raw_decode(response.text[match.end():])
                if isinstance(config,dict) and isinstance(config.get('LOGGED_IN'),bool):
                    states.append(config['LOGGED_IN'])
            except ValueError:
                continue
        if False in states:
            return 'auth_expired', 'YouTube rejected the saved session. Upload fresh signed-in cookies in Downloader. No watched request was sent.'
        if True in states:
            return 'active', 'YouTube confirmed an active signed-in cookie session.'
        return 'auth_unverified', 'Unable to confirm a signed-in YouTube session. Check cookies, consent and network access. No watched request was sent.'
    except requests.RequestException:
        return 'auth_unverified', 'YouTube session check failed. Check network access and try again. No watched request was sent.'


def send_watched_request(video_id, cookie_path):
    # Work on a private cookie copy so yt-dlp cannot rewrite the downloader's jar.
    with tempfile.TemporaryDirectory(prefix='ytsd-watched-') as directory:
        cookies = Path(directory) / 'cookies.txt'
        shutil.copyfile(cookie_path, cookies)
        cookies.chmod(0o600)
        state,message = check_cookie_session(cookies)
        if state != 'active':
            return state,message
        command = [sys.executable, '-m', 'yt_dlp', '--ignore-config', '--simulate',
                   '--mark-watched', '--no-playlist', '--no-progress', '--no-colors',
                   '--socket-timeout', '15', '--retries', '0', '--extractor-retries', '0',
                   '--cookies', str(cookies), 'https://www.youtube.com/watch?v=' + video_id]
        try:
            result = subprocess.run(command, capture_output=True, text=True, timeout=90)
        except subprocess.TimeoutExpired:
            return 'failed', 'Timed out after 90 seconds. YouTube completion is unverified. No automatic retry.'
        except OSError:
            return 'failed', 'Could not start yt-dlp. YouTube completion is unverified.'
    # Do not persist raw extractor output: it can contain account/session information.
    output = (result.stdout or '') + '\n' + (result.stderr or '')
    lowered = output.lower()
    if 'unable to mark' in lowered:
        return 'failed', 'yt-dlp could not send the watched request. Check cookie expiry and network/DNS access. YouTube completion is unverified.'
    if result.returncode:
        return 'failed', 'yt-dlp exited with an error. Check the saved cookies and video availability. YouTube completion is unverified.'
    if 'marking fully watched' not in lowered:
        return 'unverified', 'yt-dlp did not report a fully-watched request. Check the saved YouTube account cookies. Completion is unverified.'
    if 'warning:' in lowered:
        return 'unverified', 'yt-dlp reported a fully-watched request with warnings. Check YouTube using the cookie account. Completion is unverified.'
    return 'sent', 'Watched request sent without a reported error. Open YouTube using the cookie account and check the full progress bar. Completion is unverified.'
