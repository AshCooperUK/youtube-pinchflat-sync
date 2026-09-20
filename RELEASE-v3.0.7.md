# YouTube Subscription Downloader v3.0.7

Built on the completed v3.0.6 work. The public GitHub baseline checked for this package was v3.0.5, commit `d0c7fdaa3c2da0d8e43039ef9b9e48fdbd49a662`. Both ZIPs include the v3.0.6 fixes, so upgrading from either version retains completed-only Latest Downloaded, Current Downloads progress and illustrated Activity logs.

## YouTube release dates in Emby

- Video NFOs now contain `premiered`, `releasedate` and `year`. Subscription episodes also contain `aired`. One-time videos receive a video-specific movie NFO beside the media file.
- Prefer the public YouTube `videos.snippet.publishedAt` timestamp cached by the guide. When unavailable, use yt-dlp release/upload timestamps or a known upload date. Never use filesystem timestamps or import/completion time as a release date.
- Keep full timezone-aware publication timestamps in the catalogue and download records. NFO calendar dates follow the configured guide timezone, default Europe/London. Date-only source records remain date-only.
- Existing media receives corrected dates as API metadata arrives. Settings > Downloader > Repair Emby release dates performs an explicit local repair using known API metadata, info JSON or saved publication dates. Import / rescan existing media also runs this repair.
- Repair changes NFO metadata without re-downloading or converting videos. Preserve watched counts, ratings, existing title edits, date-added fields and filename-based season/episode numbers. NFO writes are atomic, readable by Emby and preserve existing file permissions where available.
- Results appear in Settings > Diagnostics > Activity. A repair failure concerning a video carries the existing video/job identity and thumbnail.
- This updates each video's release date. Emby's separate Date Added value continues to describe library import. Channel/series creation dates are not invented from the newest download.

## Upload Guide

- Add Guide navigation and a durable `/guide` page within the existing app shell. Keep the approved navy panels, selected-programme detail area, compact channel grid, blue selection, green downloaded indicators and mobile channel/card layout.
- Show active subscriptions with downloads enabled, including channels with no local files or uploads in the visible period. Use current-user favourites first, then the same selected channel/profile/status/newest/storage comparator as the main subscriptions table. Include real channel descriptions and API avatars with a placeholder fallback.
- Clicking or keyboard-activating a published video opens the existing player immediately. Hover/focus updates the upper detail area. Channel names and avatars open the existing channel popup. Preserve guide position, filters, date, selected programme and focus across popup use and normal refresh.
- Week defaults to two days before today through four days ahead. Day includes the entire local day through six-hour windows, with known durations drawn to scale and separate lanes for multiple uploads. Month groups dated cards in weekly buckets. Header dates drill into smaller ranges. GMT/BST days use their actual 23/25-hour boundaries.
- Include All uploads, Published, Expected, search, Previous, Today, Next and Day/Week/Month controls. Genuine YouTube scheduled events are labelled Scheduled, independently from published videos. Dense groups expand without hiding the remaining uploads. Additional channel/event pages load on demand.
- Search channel names, descriptions and known video titles. Cancel stale requests and prevent older responses from replacing newer views. Reflect favourite/enabled changes without a reload.
- Downloaded badges use the completed-video inventory and verify the file still exists. Queued, failed, partial and deleted media never qualify. Retention removes local badges without erasing YouTube catalogue history.

## Persistent catalogue and API use

- Idempotent SQLite migration adds separate channel/video catalogue tables, per-channel cursors and coverage, persistent backoff and worker leases. Existing downloader/favourite records retain their roles.
- Catalogue history is independent of download ranges. Default metadata coverage is All available. Index recent uploads first, then resume older playlist pages in background batches. Show coverage honestly until pagination finishes.
- Use the existing server-side OAuth refresh and quota-counting wrapper. Batch channel and video requests, follow playlist pagination beyond the first 50, and omit `maxResults` with the `videos.list` ID filter.
- Preserve publication, scheduled start, actual start/end, first-seen and metadata-check timestamps separately. Never use playlist insertion time as publication time. Short duration alone does not classify a video as a Short.
- A single background worker checks for work every 30 seconds, with at most ten API calls per batch. Default guide allowance is 1,000 calls daily, counted alongside the app's existing API statistics. Recent uploads refresh approximately every two hours, scheduled/live entries approximately every 15 minutes, and channel metadata at least weekly. Manual Refresh requests fresh channel metadata and recent uploads without starting downloads.
- Historical metadata is refreshed after 25 days. Unrefreshed copies expire at 30 days and coverage resets for re-indexing. Quota/authentication failures pause with persistent backoff and retain still-valid cached records. Detailed failures go to Activity without credentials or request headers.
- Guide settings provide timezone, All available / Past year history and the daily guide API allowance. These controls do not change downloader settings. Read endpoints require an authenticated session. Metadata refresh and guide configuration require administrator access and CSRF protection.

## Forecasting dependency from the handover

The handover explicitly requires verification of the project's accepted YouTube API terms before activating upload predictions derived from API timestamps. No evidence of project permission was supplied in the repository or handover.

The guide therefore ships with a separate inactive prediction provider and the Expected control explains the dependency. No fabricated schedules, programme titles, thumbnails, video IDs or confidence scores ship. Forecast pattern detection/calibration is deferred until this dependency is resolved. Published history, announced schedules and existing popups work independently.

References checked on 20 September 2026: [YouTube Developer Policies, III.E.4 and III.L](https://developers.google.com/youtube/terms/developer-policies), [derived-metrics terms](https://developers.google.com/youtube/terms/derived-metrics-policy), [video timestamps](https://developers.google.com/youtube/v3/docs/videos), [playlist pagination](https://developers.google.com/youtube/v3/docs/playlistItems/list), [video batches](https://developers.google.com/youtube/v3/docs/videos/list) and [Emby NFO refresh discussion](https://emby.media/community/topic/134463-how-to-apply-nfo-file-changes/).

## Upgrade

1. Extract the full ZIP or the changed-files ZIP and upload the contents to the existing GitHub repository, preserving folders and `.github/workflows`. The changed-files archive supports the checked v3.0.5 baseline and v3.0.6.
2. Build/pull image version 3.0.7 and recreate the container with the existing `/data` and `/downloads` mounts. The database migration runs automatically.
3. Open Guide. Cached uploads appear as background indexing progresses. Google must be connected for catalogue updates. Full historical indexing takes multiple batches depending on channel size and the daily allowance.
4. For existing Emby videos, run Settings > Downloader > Repair Emby release dates. Check Diagnostics > Activity, then refresh the affected metadata in Emby with NFO reading enabled. Use Emby's release-date field for YouTube chronology. Files without a known publication date wait for metadata rather than receiving an invented date.

## Validation

58 Python regression tests pass, including the earlier real FFmpeg/subtitle-failure tests. New checks cover a zero-file library, historical videos beyond Today cutoffs, 120-video pagination with resumed backfill, timestamp persistence, per-user favourites, sorting/search, GMT/BST boundaries, scheduled/Short states, completed-only badges, local deletion, quota backoff, metadata expiry/renewal, invalid pagination tokens, persistent worker deduplication, authenticated/CSRF access, selection persistence, dense event pagination and Emby NFO repair.

Chromium checks compare the approved reference with desktop, Day, Month and mobile views. Checks cover remote and downloaded playback in the same popup, existing channel details, focus restoration, favourite changes, morning/evening windows, search/refresh persistence, stale-response handling, all shared sort modes and metadata refresh without media jobs. The existing completed-only dashboard and illustrated Activity checks also pass. Python compilation, JavaScript syntax, Jinja parsing, duplicate HTML IDs and YAML parsing pass.

Validation uses deterministic local API/media fixtures plus real FFmpeg. Live Google credentials, the NAS and the deployed Emby server are not available in this workspace. GitHub Actions performs the Compose validation and container build after upload.
