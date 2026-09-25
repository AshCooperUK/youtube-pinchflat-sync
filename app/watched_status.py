"""Experimental YouTube watched requests. Never infer account history from HTTP success."""
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path


def send_watched_request(video_id, cookie_path):
    # Work on a private cookie copy so yt-dlp cannot rewrite the downloader's jar.
    with tempfile.TemporaryDirectory(prefix='ytsd-watched-') as directory:
        cookies = Path(directory) / 'cookies.txt'
        shutil.copyfile(cookie_path, cookies)
        cookies.chmod(0o600)
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
