YouTube Subscription Downloader 3.0.17

Complete application source based on 3.0.16 with read-only TV API version 1.
YTSD TV 0.1.0-beta.1 requires this server version.

Existing installations

Preserve the existing environment, Compose settings, data and media volumes.
Replace the application source, rebuild the Docker image, then recreate the
container with the existing mounts. Include the new app/tv_api.py module.
Confirm the dashboard reports 3.0.17. No database migration is required.
The included Compose file is a generic example for a separate installation.

Changes

app/tv_api.py adds a paged completed-video catalogue, channel grouping, account
favourites, metadata, artwork and subtitle discovery/streaming. Existing session
login, two-factor authentication and /downloads/<job_id>/media remain authoritative.
TV watch history stays on the device. The API supplies no administration actions.
The existing web and phone routes retain their behaviour.
Setup and Emby address placeholders use generic examples.

Build an image from the source root:

docker build -t ytsd:3.0.17 ./app

Run tests with Python 3.12 or 3.13:

python -m pip install -r app/requirements.txt pytest
python -m pytest -q tests

See RELEASE-v3.0.17.md and tests/test_tv_api.py for the TV contract and tests.
