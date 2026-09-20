# YouTube Subscription Downloader

A self-hosted Docker web application for managing YouTube subscriptions and downloading them directly with yt-dlp.

Version: **3.0.6**

V3 removes Pinchflat completely. The application now owns channel scanning, the persistent download queue, yt-dlp workers, authentication, download history, Emby integration and retention itself.

## What V3 includes

- Google OAuth subscription import and refresh
- Per-channel download enable/disable
- Per-channel history ranges
- Native yt-dlp subscription downloads
- Persistent download and scan queues
- One-time URL downloads with live progress
- H.264 + AAC + MP4 Direct Play compatibility conversion for One-time and subscription downloads
- Emby Download playlist automation
- Targeted Emby library and metadata refreshes
- Favourite channels and favourite videos
- Discover, liked/disliked videos, random videos and Shorts
- Channel details, YouTube statistics and local growth history
- Video retention policies and per-channel overrides
- User accounts, 2FA and session controls
- In-app YouTube cookies.txt upload for account-required downloads
- Anonymous-first downloads with authenticated retry
- Error classification for membership, age restrictions, authentication, private/unavailable videos and rate limiting
- Optional expert yt-dlp JSON options

## V3 architecture

```text
YouTube / Google OAuth
        |
        v
YouTube Subscription Downloader
        |
        +-- subscription scanner
        +-- persistent SQLite queue
        +-- yt-dlp workers
        +-- FFmpeg post-processing
        +-- artwork / NFO / metadata
        +-- retention
        +-- Emby refresh
        |
        v
/media/Storage/Media/YouTube
```

There is no Pinchflat container, Pinchflat SQLite database, Oban queue or Pinchflat API dependency.

## Upgrade from V2

V3 deliberately keeps the existing host data directory:

```text
/media/NVME-Storage/AppData/youtube-pinchflat-sync/data
```

This preserves the existing application database, users, Google OAuth token, favourites and settings during the upgrade.

The old Pinchflat config mount and Docker socket mount are no longer required.

V3.0.2 and later can rescan the complete existing `/downloads/shows` media library, using `.info.json`, NFO and filename YouTube IDs where available, so older downloads can be imported into the native history without being downloaded again.

Before upgrading, keep a backup of the existing application data directory and YouTube media library.

## YouTube authentication

Settings → Downloader → YouTube Authentication provides an upload box for a Mozilla/Netscape-format `cookies.txt` file.

The file is validated and stored privately at:

```text
/data/auth/youtube-cookies.txt
```

The cookie contents are never displayed by the web interface.

Downloads use anonymous yt-dlp first. If YouTube reports an account/sign-in restriction, V3 can retry using the configured cookies. Members-only content still requires the uploaded account to have the relevant membership.

Current yt-dlp guidance recommends using cookies only where necessary and keeping request rates conservative. PO Token handling is available as an expert option, although provider plugins are preferable to manually maintained tokens.

## Docker

The production image is:

```text
ghcr.io/ashcooperuk/youtube-subscription-downloader:latest
```

The application listens on port `8787`.

Main mounts:

```text
/data       Application database, OAuth, authentication and settings
/downloads  YouTube media library
```

The public URL can remain:

```text
https://youtube.ashjohn.uk
```

## Default downloader safety

V3 defaults to:

- 1 concurrent yt-dlp download worker
- lightweight channel-feed scans
- 4 RSS scan workers
- queued deep scans rather than simultaneous forced indexing
- duplicate checks by YouTube video ID

This is intentionally different from the old Pinchflat Force Index model which could accumulate a large persisted indexing backlog.

## Development

Build locally:

```bash
docker compose -f docker-compose.dev.yml up -d --build
```

Health endpoint:

```text
/health
```

## Release

V3.0.6 keeps Latest Downloaded on the last successful video without status text, shows active worker progress in Current Downloads, and adds video thumbnails and automatic refresh to Diagnostics Activity. Includes all earlier fixes. See [release details](RELEASE-v3.0.6.md).
