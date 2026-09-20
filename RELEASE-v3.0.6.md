# YouTube Subscription Downloader v3.0.6

Based on GitHub v3.0.5 at `d0c7fdaa3c2da0d8e43039ef9b9e48fdbd49a662`. Includes all previous fixes.

## Latest Downloaded

- Shows the newest successfully completed video file still on disk. Pending jobs, downloads, FFmpeg processing, skipped videos and failures never replace the last successful video.
- Shows the video thumbnail, title and channel. Removes status messages, error details and progress indicators from this tile.
- Keeps the previous successful video visible until another video completes. If no completed video exists, shows the empty state.
- Uses the same completed-only rule for the alternate latest-video display when the main summary tile is disabled.

## Current Downloads

- Keeps active worker messages, percentages and FFmpeg/metadata phases beside their video thumbnails.
- Retains waiting jobs and one-time downloads when their popup is closed.
- Removes the Recent results list from Current Downloads. Completed, failed and skipped job events appear in Settings → Diagnostics → Activity.

## Activity

- Saves video ID, video title and download job ID with video activity entries. Thumbnail links remain available if the job record is later removed.
- Adds a thumbnail, video title and YouTube link to video-related queue, progress, completion, failure, subtitle, metadata, conversion, Emby refresh and like events.
- Records phase changes once. Percentage updates within an unchanged phase do not generate another log entry.
- Adds thumbnails to the existing direct-download history display.
- Refreshes Activity on opening Diagnostics, then every ten seconds while the tab is visible. Includes a manual Refresh activity button.
- Keeps log text escaped, restricts the Activity endpoint to administrators and supplies an image fallback when YouTube does not serve a thumbnail.
- Preserves existing logs during the automatic database upgrade. Older entries gain thumbnails when a video URL, yt-dlp error ID, media filename or unambiguous saved video title identifies the video. Ambiguous old entries retain their original text without assigning an unrelated thumbnail.

## Upgrade from v3.0.5

1. Extract the full ZIP or the changed-files ZIP. Upload the extracted files to GitHub with their folder structure, including `.github/workflows`.
2. Build and pull the updated image, then recreate the container using the existing `/data` and `/downloads` mounts.
3. Confirm the dashboard shows v3.0.6. The database upgrade runs automatically. This release needs no media rescan.
4. Open Settings → Diagnostics → Activity for video failures and processing history.

Download ranges, Shorts filtering, retention protection, import enabling, metadata repair and filename handling retain their existing behaviour.

## Validation

All 41 Python regression tests passed. Coverage includes completed-only selection, failure reporting, per-phase logging, one-time download URLs, stored thumbnail identity, legacy log matching, database upgrades and administrator access. Earlier media, FFmpeg, subtitle, import and filename checks also pass.

Chromium checks passed at 1600 px and 390 px. Checks covered the last successful video staying visible, absence of status text in Latest Downloaded, active FFmpeg progress, illustrated failures in Activity, automatic refresh, escaped log text, thumbnail fallback and responsive layout. No JavaScript errors or horizontal page/dialog overflow appeared. Python compilation, Jinja parsing, duplicate HTML ID checks and YAML parsing passed.

Validation used local download fixtures and real FFmpeg. Live YouTube, NAS and Emby checks remain deployment checks. GitHub Actions validates Compose and builds the Docker image.
