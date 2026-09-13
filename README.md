# YouTube Pinchflat Sync

A Docker dashboard for ZimaOS which reads your YouTube subscriptions, creates and manages Pinchflat sources, and adds direct-download automation for an Emby YouTube library.

## Version 1.5.1

Maintenance release fixing the v1.5.0 startup failure.

- Fixes the missing `current_emby_poll_interval()` function which prevented Gunicorn from booting.
- Adds a persistent 5-minute default for the `Emby Download` playlist polling interval.
- Passes the polling interval into the Settings interface.
- Saves changes to the polling interval correctly.
- Reschedules the background playlist job immediately after changing the interval.

## Version 1.5.0

Version 1.5.0 adds:

- Private YouTube playlist automation using the exact playlist name `Emby Download`.
- Automatic creation of `Emby Download` after Google is connected with write access.
- Playlist polling every 5 minutes by default.
- Videos added to `Emby Download` are queued for direct download automatically.
- Playlist items can be removed from `Emby Download` after a successful download.
- A `Single Download` popup for one YouTube video URL.
- Live download percentage, speed, ETA and transferred size.
- Direct downloads use yt-dlp and FFmpeg inside the sync container.
- YouTube unsubscribe buttons with confirmation.
- Google OAuth write scope for supported YouTube write operations.
- Estimated YouTube Data API quota usage in Settings → Advanced.
- Total YouTube library disk usage on the dashboard.
- Estimated disk usage per channel in the subscription table.
- Disk usage sorting.
- Long channel names are shortened visually and show the full title on hover.
- Consistent dashboard button sizes.
- Per-channel Range and Save controls sit on one row.
- Existing v1.4 automation remains, including automatic downloads for new subscriptions, unsubscribe policies, retries, bulk actions and selectable Pinchflat Media Profiles.

## Google OAuth change

v1.5.0 uses:

`https://www.googleapis.com/auth/youtube`

Existing installations which were connected with `youtube.readonly` need to reconnect Google once.

The callback remains:

`https://youtube.ashjohn.uk/oauth/google/callback`

## Emby Download

The app creates a private YouTube playlist named:

`Emby Download`

Add a YouTube video to this playlist from the normal YouTube website or mobile app. The app checks the playlist on its own schedule and queues unseen videos for download.

The default direct-download path is:

`/downloads/Emby Download/<channel>/<video title> [video id].mp4`

With the supplied ZimaOS Compose file, `/downloads` maps to:

`/media/Storage/Media/YouTube`

The playlist item is removed after a successful download by default. This is configurable under Settings → YouTube.

## Single Download

Select `Single Download` on the main dashboard, paste a YouTube video URL and start the job.

The default path is:

`/downloads/Single Downloads/<channel>/<video title> [video id].mp4`

The popup displays download progress, speed, ETA and transferred size.

## YouTube unsubscribe

The subscription table contains an `Unsubscribe` action.

This removes the subscription from the authenticated YouTube account after a confirmation prompt. Existing media files remain untouched. The app then applies the configured local unsubscribe policy for the Pinchflat source.

## API quota statistics

Settings → Advanced shows the quota cost tracked by this application.

The value is an application-side estimate based on the documented costs of the YouTube Data API calls made by this service. The Google Cloud Console remains authoritative for project quota.

## Storage statistics

The sync container has access to the same `/downloads` directory as Pinchflat.

The dashboard reports total disk usage and scans folder names to estimate usage per channel. Per-channel values work best when the Pinchflat output template includes the source/channel name as a folder.

## Installation

The production image is:

`ghcr.io/ashcooperuk/youtube-pinchflat-sync:latest`

The ZimaOS application manifest is:

`Apps/YouTubePinchflatSync/docker-compose.yml`

The root `compose.yaml` contains the same deployment.

Persistent paths:

- `/media/NVME-Storage/AppData/youtube-pinchflat-sync/data`
- `/media/NVME-Storage/AppData/pinchflat`
- `/media/Storage/Media/YouTube`

## Updating with GitHub Desktop

1. Extract the release ZIP over your local `youtube-pinchflat-sync` repository.
2. Open GitHub Desktop.
3. Commit with `Release v1.5.0`.
4. Push `main`.
5. Wait for GitHub Actions to publish the new container.
6. Recreate or update the ZimaOS application.

GitHub Actions publishes:

- `ghcr.io/ashcooperuk/youtube-pinchflat-sync:latest`
- `ghcr.io/ashcooperuk/youtube-pinchflat-sync:1.5.0`
