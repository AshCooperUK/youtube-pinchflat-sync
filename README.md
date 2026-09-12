# YouTube Pinchflat Sync

A small Docker dashboard which reads the subscriptions from your Google/YouTube account and automatically creates Pinchflat sources.

## Version 1.1.0

This version adds:

- ZimaOS/CasaOS `x-casaos` metadata so the app appears as a dashboard tile.
- A repository layout which works as a ZimaOS custom App Store source.
- GitHub Actions publishing to GitHub Container Registry.
- Dashboard configuration for Google OAuth.
- Download history presets which map to Pinchflat's `download_cutoff_date`.
- Persistent settings in SQLite.

## Download history choices

The dashboard offers:

- Today
- This week
- This month
- Last 6 months
- Last year
- 1 to 10 years back
- Custom start date
- Original YouTube subscription date

Pinchflat uses a lower cutoff date. A year range therefore means "N years ago through today". It is not an upper-bounded historic window.

The selected cutoff applies when the sync service creates a new Pinchflat source. Existing Pinchflat sources keep the cutoff already stored in Pinchflat.

## Recommended GitHub repository

Create this public repository:

`https://github.com/AshCooperUK/youtube-pinchflat-sync`

Upload the contents of this package to the repository root and push to `main`.

The included GitHub Actions workflow builds:

`ghcr.io/ashcooperuk/youtube-pinchflat-sync:latest`

and:

`ghcr.io/ashcooperuk/youtube-pinchflat-sync:1.1.0`

After the first workflow completes, open the package in GitHub and make the container package Public so ZimaOS can pull it without a registry login.

## ZimaOS App Store source

Once the repository exists, add this source to ZimaOS:

`https://github.com/AshCooperUK/youtube-pinchflat-sync/archive/refs/heads/main.zip`

The app manifest is:

`Apps/YouTubePinchflatSync/docker-compose.yml`

The same YAML is also available at the repository root as `compose.yaml`.

## Existing BUTANE data

The supplied YAML uses:

- Sync data: `/media/NVME-Storage/AppData/youtube-pinchflat-sync/data`
- Pinchflat config: `/media/NVME-Storage/AppData/pinchflat`
- Pinchflat downloads: `/media/Storage/Media/YouTube`

Keeping these paths means your current database, Google token and Pinchflat configuration remain in place when you move from the locally built stack to the GitHub image.

## Moving the current install to ZimaOS

Stop the current stack without deleting data:

```bash
cd /media/NVME-Storage/youtube-pinchflat-sync
sudo docker compose down
```

Push this repository to GitHub and wait for the container workflow to finish.

Install the app from the ZimaOS YAML/App Store entry.

Open:

`http://butane.grovefarm:8787`

Then open Configuration and set:

- Public dashboard URL: `https://youtube.ashjohn.uk`
- Google OAuth Client ID
- Google OAuth Client Secret
- Pinchflat Media Profile ID

For Google, keep this authorised redirect URI:

`https://youtube.ashjohn.uk/oauth/google/callback`

## Cloudflare

The Cloudflare Tunnel public hostname remains:

`https://youtube.ashjohn.uk`

with the local service:

`http://butane.grovefarm:8787`

## Development

Copy `.env.example` to `.env`, then use:

```bash
sudo docker compose -f docker-compose.dev.yml up -d --build
```
