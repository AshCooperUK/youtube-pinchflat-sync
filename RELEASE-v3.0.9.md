# YTSD v3.0.9

The guide now loads all enabled channels and uploads from its server catalogue, with daily updates and a simpler menu. Upload estimates are enabled following the project owner's confirmation to activate them; they are YTSD estimates and do not represent YouTube announcements or approval.

## Changes

- Enable upload estimates from saved channel history, with labelled time windows, supporting observation counts and qualitative confidence. Keep genuine YouTube announcements separate. Predictions never create video IDs or download jobs.
- Validate daily, weekday, fortnightly and calendar-month patterns against later historical observations. Separate known content types and suppress sparse, irregular, stale or changed schedules. Show estimates only within the next 14 days.
- Show all enabled guide channels and all uploads in the selected period. Remove More channels and collapsed +N uploads controls. Include the initial catalogue in the page response and read further navigation from SQLite.
- Index automatically after Google is connected and channels are enabled. Refresh channel metadata and recent uploads daily at a configurable time (default 04:00, Europe/London). Preserve checkpoints, a daily API allowance, retries and historical metadata renewal across restarts.
- Move guide controls to Settings > Guide. Cache video views, likes and comments alongside publication data. Guide browsing and its info popup do not call the YouTube Data API.
- Replace hover details with click-to-open video info, plus a separate play icon for the existing player. Channel names and avatars use the shared channel popup, including inside guide details. Preserve the existing site-wide popup links.
- Add a dashboard Guide tile with minimise, full-screen maximise, visibility, auto-load and position settings under Settings > Dashboard.
- Move Single Download to a download icon in Latest Downloaded. Simplify the URL popup and accept supported HTTP/HTTPS sites through yt-dlp without a YouTube-only hostname restriction.
- Keep non-YouTube provider identities, thumbnails and NFO labels separate. Add a short source identifier to non-YouTube filenames to avoid collisions between generic extractor IDs. Reuse the media popup for authenticated local playback of completed files; support seeking and never serve partial files or paths outside the media root. Keep YouTube cookie retries scoped to YouTube.
- Move Favourites into Discover. Place Settings immediately before Log out and remove the account name from that button. Use a hamburger menu on mobile and tablets.
- Preserve completed-only Latest Downloaded, active processing in Current Downloads, Activity thumbnails/popups, sortable subscriptions, Shorts exclusions, retention protection and Emby release dates.

## Refresh behaviour

On startup, the worker resumes any incomplete catalogue. New enabled channels are picked up automatically. Google must be connected before metadata can be fetched. Settings > Guide defaults to a daily 04:00 refresh in Europe/London; both the time and timezone are editable. Manual Refresh requests metadata only.

Recent uploads and channel metadata refresh on the daily schedule. Older records are renewed before their 30-day expiry. The worker checks for pending work every 30 seconds, limits each batch to ten API calls and defaults to a daily guide allowance of 1,000 calls. Background indexing can span multiple batches or days for a large library. Page loads, date navigation, search and guide-info popups read the saved catalogue. Playing videos and opening the full channel popup retain their existing streaming/detail behaviour.

Predictions use exact cached publication times, separate known Shorts/livestream/unknown types and assume the configured guide timezone. Pattern selection uses an older training window and a later holdout. Estimates show evidence and confidence; irregular channels may have none. No numeric probability or invented video title/thumbnail is displayed. Published or announced events suppress corresponding estimates. Changing the prediction or timezone setting takes effect on the next worker batch.

## Upgrade from v3.0.8

1. Overlay the changed-files ZIP on v3.0.8, or use the full-source ZIP. Keep your deployment-specific YAML values, application data and media mounts.
2. Upload the source to your GitHub repository and let its container workflow build v3.0.9. Pull the image and recreate the container.
3. Database columns and guide settings migrate automatically. Review Settings > Guide and Settings > Dashboard. Initial indexing continues automatically; a manual sync is not required for the guide.

The release does not rename or delete existing media. Download ranges, retention settings and per-video protection remain unchanged.

## Validation

78 automated regression tests cover the native downloader, metadata, inventory, retention exclusions, Activity, sorting, guide cache and scheduling, prediction suppression and calendar patterns, authentication and URL handling. A real generic HTTP video was downloaded using yt-dlp, completed through the existing worker, and served with an authenticated range request for playback.

Browser checks cover all 32 enabled test channels, dense upload days, click-only info, video and channel popups, full-screen/minimise, prediction blocks, guide/dashboard settings, Favourites, local media playback and mobile/tablet navigation without page errors. The earlier sorting and Activity popup checks also pass.

No live YouTube account, production library or Emby server was used. Third-party website availability and access requirements depend on yt-dlp and the source site.
