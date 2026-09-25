YouTube Subscription Downloader 3.0.18

Complete server source with Android TV API v1 and LG webOS API v1.
The webOS 0.1.0 beta needs this server build or a later compatible version.

This release reconciles the earlier 3.0.17 and 3.0.17-beta.1 work. It restores
the experimental watched-status function, routes and dashboard controls while
retaining the Android TV catalogue. The matching test_v317 regression tests pass.

New webOS support uses /tv-link for browser-approved pairing and /api/webos for
read-only client access. Per-file media grants support native playback, artwork,
subtitles and seeking. WebVTT and SRT sidecars work with the webOS client. The
server stores hashed device credentials and checks account status and session
version. Sign-out and browser revocation remove access. Watch progress remains
on each TV. Android/web cookie authentication and existing media routes remain.

Existing installations

Preserve your Compose file, environment, data mount and media mount. Use the
changed-files archive to update an existing checkout, or replace the complete
app source from this archive. Rebuild the Docker image and recreate your existing
container with the same volumes. Check the dashboard reports 3.0.18. New watched
request and webOS pairing/device tables are created automatically. No data reset
or manual migration is required. Automatic watched requests remain opt-in.

The deployment YAML files here are generic examples. Retain your existing
configuration when upgrading. Do not replace production mounts with example paths.
The release has not been pushed, published or deployed on your behalf.

Build an image from the source root:

docker build -t ytsd:3.0.18 ./app

Run the same tests as GitHub validation with Python 3.12 or 3.13:

python -m pip install -r app/requirements.txt
python -m unittest discover -s tests -v

136 server tests passed. See RELEASE-v3.0.18.md for the changes. Install the
separate webOS IPK through LG Developer Mode. Physical LG testing is outstanding.
