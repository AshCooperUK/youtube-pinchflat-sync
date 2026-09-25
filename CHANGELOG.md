# YTSD release history

This history restores the release notes from the repository's older READMEs, deployment metadata and release commits, checked against the available development conversations. Personal deployment examples have been replaced with generic values. Historical entries describe behaviour at the time. V3 uses the native downloader and supersedes the older Pinchflat instructions.

The earliest archived release is **v1.1.0**. No separate v1.0.0 release notes were available, so no features or release dates have been invented for that version. Versions documented inside another release's README are retained even where no separate Git tag exists.

## v3.0.15

- Add a top-centre Subscribe/Subscribed control beside the existing channel-image actions across subscription rows, channel/player popups and shared channel widgets.
- Add an explicit unsubscribe dialog with choices to keep files, delete subscription files, remove the YTSD channel record while retaining files, or remove the record and subscription media together. These choices override the automatic unsubscribe policy. Separate one-time downloads remain unchanged.
- Add a plus button beside the Subscriptions tile minimise control. Accept YouTube channel URLs, @handles and channel IDs, with targeted API calls rather than a full subscription refresh.
- Restore explicitly re-added channels even when an earlier local removal suppressed them. Cancel pending cleanup on re-subscribe and honour the new-channel download policy.
- Keep the new controls administrator-only, require Google write access and CSRF protection, and retain foreground focus for nested popup choices.

## v3.0.14

- Add Latest download: newest first and oldest first to the subscription filter popup.
- Sort channels using the latest successful video download still present on disk. Ignore queued, processing, failed and cancelled jobs, audio-only files, sidecars and missing files. Channels without dated downloads appear last within each favourites group.
- Preserve the saved sort preference and favourites-first setting. Refresh channel ordering from the existing dashboard download-status poll.
- Apply the same download-date sort in Upload Guide without additional YouTube API requests.

## v3.0.13

- Keep Guide refreshing other channels when one uploads playlist is missing or inaccessible. Cache the affected channel's error and retry it after 24 hours, refreshing its playlist metadata first.
- Recover invalid pagination tokens per channel with a ten-minute retry. Preserve account-wide quota and authentication backoffs.
- Display persistent channel errors and retry times in Guide rows and Settings > Guide, with an affected-channel summary below the timeline.
- Distinguish the actual retry time from the next daily scheduled refresh.
- Automatically clear legacy global playlist-error pauses during the database upgrade. Cached uploads and download preferences are preserved.

## v3.0.12

- Show all active YouTube subscriptions in Guide, including channels without download monitoring, with favourites first.
- Add searchable Guide channel visibility switches, Show all / Hide all, and a separate programme-thumbnail background switch in Settings > Guide. Preserve the expected-upload prediction toggle. New subscriptions appear by default. Guide switches do not change downloads.
- Keep Guide browsing on the server catalogue. Hidden channels pause indexing, channel descriptions/images use a seven-day refresh cache, and recent-upload checks retain the daily schedule and API allowance.
- Fix channel action menus appearing behind modal channel/player views. Menus open in the active dialog and browser top layer, receive focus and return focus to their trigger when dismissed. Escape closes the menu before the channel dialog.
- Add hand cursors to Guide links and controls. Increase Guide avatars to 76px, matching featured-channel cards elsewhere in the app.
- Request browser fullscreen with navigation controls hidden. Restore the layout on fullscreen exit. Retain a labelled in-page fallback when fullscreen is unavailable.
- Support horizontal trackpad scrolling, Shift+wheel, touch swipes and focused-grid arrow keys. Day moves by one hour, Week by one day and Month by one calendar month. Preserve vertical channel scrolling.
- Move Previous/Next into full-height rails beside the listings. Keep Today beside the date, add short transitions and honour reduced-motion preferences.
- Hide Minimise on the standalone Guide page while retaining the dashboard tile control.

## v3.0.11

- Move Scan schedule from Downloader to Automation, preserving existing favourite/other intervals and legacy save URLs.
- Explain scheduled deep scans versus the manual YTSD Sync & Scan action and the separate recent-upload scan.
- Fix the native downloader scheduler job ID used when saving Automation intervals and displaying its next run. Previously, interval changes could silently fail to take effect until restart.
- Include all v3.0.10 fixes for guide layout, inline Favourites, provider metadata, Emby refresh and Shorts/force scanning.

## v3.0.10

- Fix clipped Upload Guide Day cards. Programme titles, info/play controls and durations stay inside each card at desktop and mobile sizes. Keep the release-time bars and match the Week/Month card styling.
- Centre the Single Download icon in Latest Downloaded.
- Show Favourite Channels and Favourite Videos inside the existing Discover popup. Keep the shared channel and video popups for individual entries.
- Hide YouTube-only actions on downloaded videos from other providers. Show their programme/provider name without a disabled YouTube channel button or an invented view count.
- Save source descriptions, programme titles, season/episode numbers, durations, thumbnails and release dates for one-time downloads. Use these saved details in the existing media player without a YouTube lookup.
- Write provider-aware movie or episode NFOs. Recognised TV episodes use their real programme name, season and episode number. BBC combined titles have a specific fallback when the extractor omits separate episode fields.
- Organise recognised one-time TV episodes under Programme/Season N with SxxExx filenames when the default output template is selected. Keep custom output templates in use.
- Repair existing registered non-YouTube downloads automatically from saved local metadata. Keep video bytes, subtitles and watched/rating NFO fields. Refuse destination collisions and report each result in Activity. Add Repair one-time metadata in Settings > Downloader for a manual retry.
- Fix targeted Emby library detection for separate one-time libraries and new folders under mapped library roots. Notify Emby after completion without waiting for a full filesystem inventory.
- Make Force Scan check recent uploads before deep history and artwork preparation. Eligible jobs enter the worker queue immediately. Log the scan result and exclusions with video thumbnails and links.
- Identify Shorts through YouTube channel-tab membership, including watch URLs with no Shorts flag. Cache the result locally and recheck exclusions before media transfer. Defer unverified entries instead of downloading an unknown type. Keep short regular videos eligible.
- Use the configured timezone for download cutoffs and exact publication times. Keep scanner and download workers running after an individual job error. Report suppressed scans instead of claiming they started.

## v3.0.9

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

## v3.0.8

- Click any subscription column heading to sort in both directions: Channel, Enabled, Range, Media Profile, Cut-off, Disk usage, Error and Save / Actions.
- Remember sorting across refreshes. Keep the sort dropdown and heading arrows in sync, with keyboard controls and accessible direction announcements.
- Compare resolution and disk usage numerically, cut-off dates chronologically, and Range in preset order. Save / Actions groups unsaved changes. Honour the existing favourites-first preference.
- Share ordering and direction with Upload Guide. The guide always pins favourites and uses saved channel settings, so unsaved dashboard edits remain local to the dashboard.
- Open Activity thumbnails and video titles in the existing media-player popup. Open Activity channel names in the existing channel popup, including after automatic refresh.
- Recover missing Activity context from exact video IDs, saved job records and local saved-video metadata. Persist channel names for future logs, including one-time downloads and failures.
- Restore the documented v1/v2 release archive and add Cloudflare-first installation instructions with generic setup screenshots and YAML examples.

## v3.0.7

Built on the completed v3.0.6 work. The public GitHub baseline checked for this package was v3.0.5, commit `d0c7fdaa3c2da0d8e43039ef9b9e48fdbd49a662`. Both ZIPs include the v3.0.6 fixes, so upgrading from either version retains completed-only Latest Downloaded, Current Downloads progress and illustrated Activity logs.

### YouTube release dates in Emby

- Video NFOs now contain `premiered`, `releasedate` and `year`. Subscription episodes also contain `aired`. One-time videos receive a video-specific movie NFO beside the media file.
- Prefer the public YouTube `videos.snippet.publishedAt` timestamp cached by the guide. When unavailable, use yt-dlp release/upload timestamps or a known upload date. Never use filesystem timestamps or import/completion time as a release date.
- Keep full timezone-aware publication timestamps in the catalogue and download records. NFO calendar dates follow the configured guide timezone, default Europe/London. Date-only source records remain date-only.
- Existing media receives corrected dates as API metadata arrives. Settings > Downloader > Repair Emby release dates performs an explicit local repair using known API metadata, info JSON or saved publication dates. Import / rescan existing media also runs this repair.
- Repair changes NFO metadata without re-downloading or converting videos. Preserve watched counts, ratings, existing title edits, date-added fields and filename-based season/episode numbers. NFO writes are atomic, readable by Emby and preserve existing file permissions where available.
- Results appear in Settings > Diagnostics > Activity. A repair failure concerning a video carries the existing video/job identity and thumbnail.
- This updates each video's release date. Emby's separate Date Added value continues to describe library import. Channel/series creation dates are not invented from the newest download.

### Upload Guide

- Add Guide navigation and a durable `/guide` page within the existing app shell. Keep the approved navy panels, selected-programme detail area, compact channel grid, blue selection, green downloaded indicators and mobile channel/card layout.
- Show active subscriptions with downloads enabled, including channels with no local files or uploads in the visible period. Use current-user favourites first, then the same selected channel/profile/status/newest/storage comparator as the main subscriptions table. Include real channel descriptions and API avatars with a placeholder fallback.
- Clicking or keyboard-activating a published video opens the existing player immediately. Hover/focus updates the upper detail area. Channel names and avatars open the existing channel popup. Preserve guide position, filters, date, selected programme and focus across popup use and normal refresh.
- Week defaults to two days before today through four days ahead. Day includes the entire local day through six-hour windows, with known durations drawn to scale and separate lanes for multiple uploads. Month groups dated cards in weekly buckets. Header dates drill into smaller ranges. GMT/BST days use their actual 23/25-hour boundaries.
- Include All uploads, Published, Expected, search, Previous, Today, Next and Day/Week/Month controls. Genuine YouTube scheduled events are labelled Scheduled, independently from published videos. Dense groups expand without hiding the remaining uploads. Additional channel/event pages load on demand.
- Search channel names, descriptions and known video titles. Cancel stale requests and prevent older responses from replacing newer views. Reflect favourite/enabled changes without a reload.
- Downloaded badges use the completed-video inventory and verify the file still exists. Queued, failed, partial and deleted media never qualify. Retention removes local badges without erasing YouTube catalogue history.

### Persistent catalogue and API use

- Idempotent SQLite migration adds separate channel/video catalogue tables, per-channel cursors and coverage, persistent backoff and worker leases. Existing downloader/favourite records retain their roles.
- Catalogue history is independent of download ranges. Default metadata coverage is All available. Index recent uploads first, then resume older playlist pages in background batches. Show coverage honestly until pagination finishes.
- Use the existing server-side OAuth refresh and quota-counting wrapper. Batch channel and video requests, follow playlist pagination beyond the first 50, and omit `maxResults` with the `videos.list` ID filter.
- Preserve publication, scheduled start, actual start/end, first-seen and metadata-check timestamps separately. Never use playlist insertion time as publication time. Short duration alone does not classify a video as a Short.
- A single background worker checks for work every 30 seconds, with at most ten API calls per batch. Default guide allowance is 1,000 calls daily, counted alongside the app's existing API statistics. Recent uploads refresh approximately every two hours, scheduled/live entries approximately every 15 minutes, and channel metadata at least weekly. Manual Refresh requests fresh channel metadata and recent uploads without starting downloads.
- Historical metadata is refreshed after 25 days. Unrefreshed copies expire at 30 days and coverage resets for re-indexing. Quota/authentication failures pause with persistent backoff and retain still-valid cached records. Detailed failures go to Activity without credentials or request headers.
- Guide settings provide timezone, All available / Past year history and the daily guide API allowance. These controls do not change downloader settings. Read endpoints require an authenticated session. Metadata refresh and guide configuration require administrator access and CSRF protection.

### Forecasting dependency from the handover

The handover explicitly requires verification of the project's accepted YouTube API terms before activating upload predictions derived from API timestamps. No evidence of project permission was supplied in the repository or handover.

The guide therefore ships with a separate inactive prediction provider and the Expected control explains the dependency. No fabricated schedules, programme titles, thumbnails, video IDs or confidence scores ship. Forecast pattern detection/calibration is deferred until this dependency is resolved. Published history, announced schedules and existing popups work independently.

References checked on 20 September 2026: [YouTube Developer Policies, III.E.4 and III.L](https://developers.google.com/youtube/terms/developer-policies), [derived-metrics terms](https://developers.google.com/youtube/terms/derived-metrics-policy), [video timestamps](https://developers.google.com/youtube/v3/docs/videos), [playlist pagination](https://developers.google.com/youtube/v3/docs/playlistItems/list), [video batches](https://developers.google.com/youtube/v3/docs/videos/list) and [Emby NFO refresh discussion](https://emby.media/community/topic/134463-how-to-apply-nfo-file-changes/).

### Upgrade

1. Extract the full ZIP or the changed-files ZIP and upload the contents to the existing GitHub repository, preserving folders and `.github/workflows`. The changed-files archive supports the checked v3.0.5 baseline and v3.0.6.
2. Build/pull image version 3.0.7 and recreate the container with the existing `/data` and `/downloads` mounts. The database migration runs automatically.
3. Open Guide. Cached uploads appear as background indexing progresses. Google must be connected for catalogue updates. Full historical indexing takes multiple batches depending on channel size and the daily allowance.
4. For existing Emby videos, run Settings > Downloader > Repair Emby release dates. Check Diagnostics > Activity, then refresh the affected metadata in Emby with NFO reading enabled. Use Emby's release-date field for YouTube chronology. Files without a known publication date wait for metadata rather than receiving an invented date.

### Validation

58 Python regression tests pass, including the earlier real FFmpeg/subtitle-failure tests. New checks cover a zero-file library, historical videos beyond Today cutoffs, 120-video pagination with resumed backfill, timestamp persistence, per-user favourites, sorting/search, GMT/BST boundaries, scheduled/Short states, completed-only badges, local deletion, quota backoff, metadata expiry/renewal, invalid pagination tokens, persistent worker deduplication, authenticated/CSRF access, selection persistence, dense event pagination and Emby NFO repair.

Chromium checks compare the approved reference with desktop, Day, Month and mobile views. Checks cover remote and downloaded playback in the same popup, existing channel details, focus restoration, favourite changes, morning/evening windows, search/refresh persistence, stale-response handling, all shared sort modes and metadata refresh without media jobs. The existing completed-only dashboard and illustrated Activity checks also pass. Python compilation, JavaScript syntax, Jinja parsing, duplicate HTML IDs and YAML parsing pass.

Validation uses deterministic local API/media fixtures plus real FFmpeg. Live Google credentials, the NAS and the deployed Emby server are not available in this workspace. GitHub Actions performs the Compose validation and container build after upload.

[Release details](RELEASE-v3.0.7.md).

## v3.0.6

Based on GitHub v3.0.5 at `d0c7fdaa3c2da0d8e43039ef9b9e48fdbd49a662`. Includes all previous fixes.

### Latest Downloaded

- Shows the newest successfully completed video file still on disk. Pending jobs, downloads, FFmpeg processing, skipped videos and failures never replace the last successful video.
- Shows the video thumbnail, title and channel. Removes status messages, error details and progress indicators from this tile.
- Keeps the previous successful video visible until another video completes. If no completed video exists, shows the empty state.
- Uses the same completed-only rule for the alternate latest-video display when the main summary tile is disabled.

### Current Downloads

- Keeps active worker messages, percentages and FFmpeg/metadata phases beside their video thumbnails.
- Retains waiting jobs and one-time downloads when their popup is closed.
- Removes the Recent results list from Current Downloads. Completed, failed and skipped job events appear in Settings → Diagnostics → Activity.

### Activity

- Saves video ID, video title and download job ID with video activity entries. Thumbnail links remain available if the job record is later removed.
- Adds a thumbnail, video title and YouTube link to video-related queue, progress, completion, failure, subtitle, metadata, conversion, Emby refresh and like events.
- Records phase changes once. Percentage updates within an unchanged phase do not generate another log entry.
- Adds thumbnails to the existing direct-download history display.
- Refreshes Activity on opening Diagnostics, then every ten seconds while the tab is visible. Includes a manual Refresh activity button.
- Keeps log text escaped, restricts the Activity endpoint to administrators and supplies an image fallback when YouTube does not serve a thumbnail.
- Preserves existing logs during the automatic database upgrade. Older entries gain thumbnails when a video URL, yt-dlp error ID, media filename or unambiguous saved video title identifies the video. Ambiguous old entries retain their original text without assigning an unrelated thumbnail.

### Upgrade from v3.0.5

1. Extract the full ZIP or the changed-files ZIP. Upload the extracted files to GitHub with their folder structure, including `.github/workflows`.
2. Build and pull the updated image, then recreate the container using the existing `/data` and `/downloads` mounts.
3. Confirm the dashboard shows v3.0.6. The database upgrade runs automatically. This release needs no media rescan.
4. Open Settings → Diagnostics → Activity for video failures and processing history.

Download ranges, Shorts filtering, retention protection, import enabling, metadata repair and filename handling retain their existing behaviour.

### Validation

All 41 Python regression tests passed. Coverage includes completed-only selection, failure reporting, per-phase logging, one-time download URLs, stored thumbnail identity, legacy log matching, database upgrades and administrator access. Earlier media, FFmpeg, subtitle, import and filename checks also pass.

Chromium checks passed at 1600 px and 390 px. Checks covered the last successful video staying visible, absence of status text in Latest Downloaded, active FFmpeg progress, illustrated failures in Activity, automatic refresh, escaped log text, thumbnail fallback and responsive layout. No JavaScript errors or horizontal page/dialog overflow appeared. Python compilation, Jinja parsing, duplicate HTML ID checks and YAML parsing passed.

Validation used local download fixtures and real FFmpeg. Live YouTube, NAS and Emby checks remain deployment checks. GitHub Actions validates Compose and builds the Docker image.

[Release details](RELEASE-v3.0.6.md).

## v3.0.5

Includes the v3.0.4 fixes. The full package and cumulative changed-files package both upgrade GitHub v3.0.3 at `2938997827cdf38a1f1ffb8820888366912587f5`, or the previously supplied v3.0.4 package.

### Shorts and download results

- Subscription filtering uses yt-dlp's YouTube `media_type` classification as well as explicit Shorts URLs. Shorts arriving through ordinary `/watch?v=` links are excluded when the Shorts switch is off. Normal videos are not excluded merely because they are short in length.
- The filter runs before video and subtitle transfers, including for jobs queued before the upgrade. An already running transfer is not interrupted by changing the switch.
- Excluded jobs are recorded as **Skipped**, with the reason visible in Current Downloads. They are not repeatedly queued while the relevant switch remains off. Turning Shorts back on makes those videos eligible on a later scan, subject to the selected download range. The same behaviour applies to excluded livestreams.
- Explicit one-time downloads retain their own settings.
- Expert JSON cannot override the managed media filter or hide job failures with `ignoreerrors`.
- Current Downloads shows the first five waiting jobs and provides the existing queue button for the full list. A collapsible Recent results list shows up to eight completions, failures, skips or cancellations from the last 24 hours. Imported historical media does not fill this list.
- Sync banners now say how many jobs were **added during that scan**, and report the state of those specific jobs at scan completion. A job may already have completed, failed or been skipped by the time the page reloads. The live active/waiting counts continue to come from the download database.
- Failures from newly added jobs count towards the sync error total. A sync with errors no longer displays a green success banner. Routine sync no longer erases video errors and reports them as successful source repairs.

### Existing library import

- Settings → Downloader → Import / rescan existing media enables matched current subscriptions after importing. This also covers files already in the database and repeated imports.
- Matching uses available channel IDs, channel NFO, saved channel folders and unambiguous channel names. Conflicting names or an unknown explicit channel ID do not enable another channel by mistake. Existing subscriptions are matched locally; the import does not subscribe to channels on YouTube or restore removed subscriptions.
- Existing download ranges, media profiles and retention settings are preserved. Newly enabled channels participate in subsequent scheduled or manual scans.
- Automatic startup inventory checks do not re-enable channels the user has disabled. Subtitle/artwork files alone do not count as imported media.
- The import completion banner states how many channels were enabled. Channel artwork and NFO repair continues in the background; its results appear in Activity.

### Subscription search and sorting

- Search covers Channel, Range, Media Profile, Cutoff, Disk usage and Error. For example, `720`, `this month`, `7.2 GB` and `private` match their respective columns. Multiple search words may match across columns.
- Only the selected range and profile are searched, rather than every option in their dropdowns. The search also works for viewer accounts.
- Media Profile sorting groups 720p, 1080p, 4K and audio profiles in that order, with channel names breaking ties. The existing favourite pinning preference still applies.
- Search, status filter and sorting remain saved in the browser.

### Upgrade

1. Extract either ZIP and upload the extracted files to GitHub, preserving their folders. Include `app/downloader_media.py`, the tests and `.github/workflows` updates. Do not upload the ZIP as a replacement for the source files.
2. Let GitHub build the image, then pull it and recreate the container with the existing `/data` and `/downloads` mounts. Check the dashboard shows **v3.0.5**.
3. Run **Import / rescan existing media** to enable matched channels and repair their artwork/NFO using the saved Media & Emby switches. Folder repairs wait for active channel downloads to finish.
4. Run **YTSD Sync & Scan**. Watch Current Downloads for waiting jobs and recent outcomes. Shorts already downloaded by an older release are left in place.

The package includes v3.0.4's optional subtitle failure handling, accurate FFmpeg/metadata phases, early channel artwork, episode NFO, portable Unicode filenames and channel folder repair. See [v3.0.4 details](RELEASE-v3.0.4.md).

### Validation

All 33 Python regression tests passed with yt-dlp 2026.08.19 and real FFmpeg. New coverage includes the real yt-dlp processing path rejecting a watch-link Short before any transfer, exclusion/re-enable behaviour, manual and automatic import behaviour, existing-file matching, ambiguous channel names and scan outcomes for jobs that already finished or failed. Earlier metadata, filesystem and caption-failure regressions also pass.

Chromium checks passed at 1600 px and 390 px: all six searchable columns, selected-profile matching, read-only cells, profile ordering, saved filters, waiting jobs and recent result reasons. No JavaScript errors or page-width overflow were found. Python compilation, Jinja parsing, duplicate HTML ID checks and YAML parsing passed.

Live YouTube downloads, the NAS share and Emby were not available locally. Docker image build and Compose validation remain in the GitHub Actions workflow. The screenshots cannot establish the exact historical outcome of the two jobs on the user's server; the new messages and results list make subsequent outcomes visible.

[Release details](RELEASE-v3.0.5.md).

## v3.0.4

Based on GitHub `main` at `2938997827cdf38a1f1ffb8820888366912587f5` (v3.0.3).

### Download and metadata fixes

- Subtitle downloads no longer trigger a false FFmpeg status or replace the video's progress with a caption file's size. Finishing one media stream also does not claim FFmpeg has started. The actual postprocessor hooks report merging, embedding and conversion.
- Unavailable optional subtitles no longer stop the video download. Available tracks still download and embed. The dashboard and Activity log show which languages failed. Video download errors remain fatal and visible.
- Channel scans prepare `tvshow.nfo`, `fanart.jpg`, `poster.jpg` and `banner.jpg` before downloading videos, using the saved Media & Emby switches. Workers also prepare missing channel files when resuming queued work.
- Existing channel artwork is reused during later downloads. This removes the repeated network fetch and image generation after every video. Import / rescan explicitly refreshes artwork.
- Episode NFO files are written beside completed subscription media when Emby NFO is enabled. They contain the original title, channel, publication date and YouTube ID.
- Metadata writing has its own visible status. Latest Downloaded also shows the most recent failure, including its error, until a later completion or active processing job replaces it.
- Library imports exclude temporary media streams and conversion files.

### Channel folders and filenames

- New output uses Windows-compatible path components. Unicode letters and symbols remain supported. Invalid punctuation becomes a hyphen. Trailing spaces and dots are removed, reserved device names receive a prefix, and names have byte limits.
- The original titles remain in the app and metadata. Video filenames retain the YouTube ID with the standard templates.
- Subscription downloads use a saved directory selected from the subscription's channel identity. They no longer switch directories according to the video's uploader field. Different channels with conflicting names receive distinct folder names.
- Known existing channel folders with unsafe names are renamed and download records are updated. The repair preserves the contents, refuses destination conflicts, skips busy folders, and does not merge or overwrite another folder. A recorded literal DOS-style alias is renamed using the channel title.
- Folder repair also covers subtitle-only directories whose names match a known subscription. Unidentified aliases without a matching channel record or name need manual identification. Existing individual media filenames remain unchanged.

Samba's `mangled names` setting explains how Windows clients receive aliases such as `AAYEKP~7` for names containing illegal NTFS characters: <https://www.samba.org/samba/docs/current/man-html/smb.conf.5.html#MANGLEDNAMES>. The screenshot alone does not establish the original Linux folder name.

### Upgrade from v3.0.3

1. Extract the full ZIP or the smaller changed-files ZIP and upload the extracted files to GitHub, preserving the directory structure. Include the new `app/downloader_media.py` file and the changed `.github/workflows` files.
2. Wait for the image build, pull the updated image and recreate the container using the existing `/data` and `/downloads` mounts. Check the dashboard shows v3.0.4.
3. Once current downloads finish, open Settings → Downloader → Existing library → Import / rescan existing media. This imports completed media, repairs known channel folder names and rebuilds artwork and NFO files using your saved switches. The Activity log reports repair results.
4. Run a normal channel scan for GSH Electrical and Autoalex Cars to retry failed or missing videos. A forced re-download is unnecessary for files already recorded as complete.
5. Refresh the relevant Emby library after folder repair.

Download ranges and retention protection keep their existing behaviour. This release does not delete older media because its download range changes.

### Validation

All 24 regression tests passed with yt-dlp 2026.08.19. The suite reproduced the old subtitle-only failure with a local HTTP server returning HTTP 429 for one caption. The fixed worker downloaded the video, embedded the available caption through FFmpeg, and wrote JSON, episode NFO and channel artwork. Tests also cover folder repair, conflicts, active downloads, Unicode, reserved names, length limits, metadata reuse, video totals and temporary-file exclusion.

Chromium checks passed at 1600 px and 390 px: visible caption messages, visible failure details, correct metadata status, two-line error text, no horizontal overflow and no JavaScript errors. Python compilation, Jinja parsing, HTML ID checks and YAML parsing passed.

Live YouTube authentication, the NAS SMB share, Emby and the Docker image build were not available in the local test environment. GSH Electrical's original failure requires its historical download log for exact confirmation.

Run the regression suite with `python -m unittest discover -s tests -v` after installing application dependencies and FFmpeg.

[Release details](RELEASE-v3.0.4.md).

## v3.0.3

Based on GitHub `main` at `2f391048b935a2170933486bb28f853bac4d506e` (v3.0.2).

### Fixes

- Restores the missing `_v3_subscription_info_date` function. In v3.0.2, this caused a downloaded video to enter the failed state before completion and channel metadata were recorded.
- Keeps jobs visible during merging, embedding and FFmpeg compatibility conversion. Latest Downloaded now shows the processing job, its current phase and progress. The completed-video count increases after processing finishes.
- Makes Discover → Downloaded use the native download database. A second, older function had overridden the native reader and still requested the removed Pinchflat database.
- Resolves final output files using the exact YouTube ID. The old bracketed glob matched unrelated filenames. Sidecars and temporary stream files no longer qualify as final media.
- Writes subscription artwork at the channel root. `fanart.jpg` and `poster.jpg` use the channel avatar, with the channel banner as fallback. `banner.jpg` uses the banner, with the avatar as fallback. The full avatar remains visible in fanart and poster images. Subscription artwork never falls back to a video thumbnail.
- A failed banner request no longer prevents avatar artwork from being written. Saved subscription avatars provide a fallback when channel metadata is unavailable. `tvshow.nfo` follows the Emby NFO setting.
- Applies media switches to the native yt-dlp configuration without overriding the chosen values. Embedding and SponsorBlock now install the required Python API postprocessors. Compatibility conversion preserves subtitle tracks, chapter metadata and attached cover art.
- Counts unique completed video files still present on disk. The Downloads tile and its displayed video size exclude audio files, JSON, NFO, images, subtitles, incomplete transfers and temporary conversion files. Other storage views still report their existing total disk usage.

### Interface changes

- Smaller summary cards with responsive column widths.
- YouTube refresh logo below the Google Cloud link in the Google card.
- YTSD Sync & Scan icon in the Downloader card. Both actions retain administrator access and CSRF protection.
- Current Downloads replaces Subscription Downloads. Closing the One-time Download popup returns its active job to Current Downloads. Reopening the popup resumes status polling.
- Discover → Latest Subscriptions shows recent videos and Shorts from subscribed channels.
- The homepage subscription feed starts disabled. This preference changes once during the upgrade. Re-enabling the homepage feed in Dashboard settings remains supported and persists across restarts.
- Compact Media & Emby switches. Subtitle languages appear above SponsorBlock, followed by switches for the SponsorBlock categories.

### Apply this release

1. Extract either ZIP. Upload the extracted files to the repository, retaining their relative paths. Include `.github/workflows` when uploading the full release.
2. Let the container workflow publish v3.0.3. Pull the updated image and recreate the application container, retaining the existing `/data` and `/downloads` mounts.
3. Check the dashboard shows v3.0.3.
4. Open Settings → Downloader → Existing library → Import / rescan existing media. This imports older files missed by the completion fault and rebuilds channel artwork and NFO using the saved media settings. Artwork repair runs in the background. The Activity panel records completion and any channel-specific errors.
5. Refresh the relevant Emby library after artwork repair completes.

The full ZIP contains the complete source. The changed-files ZIP applies to the v3.0.2 commit above. Neither package contains a user database, OAuth tokens, cookies, media downloads or compiled Python caches. Existing container paths and account settings remain in use.

### Validation

All 11 regression tests passed. They cover the download-to-processing-to-completed hand-off, the missing date function through the real worker path, native Discover responses, video-only totals and sizes, duplicate paths, absent files, temporary files, exact video-ID matching, artwork fallbacks, saved settings, feed migration and real FFmpeg conversion to H.264/AAC with subtitle preservation. Chromium checks passed at 1600 px and 390 px: 152 px desktop summary cards, both Discover tabs, all 16 switches, settings persistence, popup-to-dashboard progress transfer, no horizontal mobile overflow and no JavaScript errors. Browser checks use a local fixture rather than a connected YouTube or Emby account. Live account downloading and the Docker image build require the deployment environment.

Run the backend regression suite with:

```bash
python -m unittest discover -s tests -v
```

[Release details](RELEASE-v3.0.3.md).

## v3.0.2

- Rescan the entire existing media library using info JSON, NFO and YouTube IDs in filenames to import earlier downloads into native history.
- Keep completed media totals and recent-download data available to the dashboard.
- Continue the native downloader, metadata and interface improvements from v3.0.1.

[Release source](https://github.com/AshCooperUK/youtube-pinchflat-sync/commit/2f391048b935a2170933486bb28f853bac4d506e).

## v3.0.1

- Cache settings and use SQLite WAL to reduce dashboard delays and database contention.
- Preload dashboard data, combine summary requests and keep download counts and latest completed media current.
- Add live progress and immediate favourite feedback. Streamline downloader settings and summary tiles.
- Improve existing-library imports, download metadata and YouTube channel artwork.
- Include hidden project files in downloadable source packages and add branch validation and container release metadata.

[Release merge](https://github.com/AshCooperUK/youtube-pinchflat-sync/commit/efedc70).

## v3.0.0

- Replace Pinchflat with native yt-dlp subscription scanning, a persistent SQLite download queue and controlled background workers.
- Remove the Pinchflat container, API, database and Docker socket requirements while retaining the existing application data for upgrades.
- Add validated private YouTube cookie uploads, anonymous-first requests and authenticated retries, error classification and managed expert downloader options.
- Preserve subscriptions, media profiles, Google OAuth, users, security, favourites, Discover, one-time downloads, Emby Download automation and retention.
- Add native scheduled scans with staggered work, direct-play media conversion, Emby metadata/artwork controls and native channel actions.
- Manual sync scans enabled channels. Retention records prevent deleted videos from being queued again. Explicit re-download replaces existing media.
- Add native application, cookie, deployment and container-build validation.

[Release merge](https://github.com/AshCooperUK/youtube-pinchflat-sync/commit/7f877ba).

## v2.15.0.6

- Fixes the One-time Download popup appearing stuck at 0% while yt-dlp is still preparing the YouTube request.
- Adds explicit Queued, Preparing, Downloading, Processing and Converting for Emby stages.
- Uses an indeterminate progress bar until yt-dlp exposes a real total, then switches to measured percentage progress.
- Persists the active output filename from yt-dlp and uses file growth as a fallback for transferred bytes and speed when hook updates are sparse.
- Keeps the v2.15.0.5 persistent Delete all tasks toggle for Pinchflat Oban work.

[Archived release documentation](https://github.com/AshCooperUK/youtube-pinchflat-sync/blob/183214b9109ebeca095227d750ecba2cb1b07da3/README.md).

## v2.15.0.5

- Fixes One-time Download status so the popup shows clear preparation, YouTube download, post-processing and H.264/AAC compatibility-conversion phases instead of appearing stuck at 0%.
- Keeps live byte, speed and ETA updates from yt-dlp and adds conversion progress while ffmpeg prepares the Emby / Smart TV file.
- Adds a persistent Delete all tasks toggle to the Pinchflat tasks tile. Enabling it pauses Pinchflat Oban queues, cancels executing jobs, deletes queued non-completed jobs and continues removing newly created tasks until switched off.
- Switching Delete all tasks off resumes the Pinchflat queues.

[Archived release documentation](https://github.com/AshCooperUK/youtube-pinchflat-sync/blob/5cf4471b5046a94333e8bdae98de43768a1f0e25/README.md).

## v2.15.0.4

- Added an Emby / Smart TV compatibility profile to Settings > Downloads > One-time Download.
- One-time video downloads now prefer H.264/AVC video and AAC audio in MP4 for better Direct Play compatibility on Emby clients such as LG Smart TVs.
- If YouTube does not offer a compatible stream combination, the app converts only the completed One-time Download before the targeted Emby scan. Pinchflat and Emby Download playlist jobs are unchanged.

[Archived release documentation](https://github.com/AshCooperUK/youtube-pinchflat-sync/blob/cb98a106c3fd285cb78a405a2d1367de77dcbf0d/README.md).

## v2.15.0.3

- Adds a membership-error counter to the Pinchflat tasks tile.
- Counts non-completed Pinchflat media-download jobs whose stored yt-dlp error contains “Join this channel”, identifying members-only YouTube failures.
- Keeps membership errors separate from active/waiting non-download task counts and hides the line when the count is zero.

[Archived release documentation](https://github.com/AshCooperUK/youtube-pinchflat-sync/blob/cb98a106c3fd285cb78a405a2d1367de77dcbf0d/README.md).

## v2.15.0.2

- Fixed the Settings sidebar being clipped when the modal is shorter than the full navigation.
- The left Settings navigation and right settings panel now scroll independently.
- Added a bounded mobile Settings navigation area so all sections remain reachable on smaller screens.

- Adds a Pinchflat active tasks status tile for background Oban work such as source indexing and metadata jobs. Media-download jobs are excluded because they already appear in Pinchflat Downloads.
- Adds the Pinchflat active tasks tile to Settings → Dashboard so it can be shown, hidden and reordered with the other status tiles.
- Adds best-effort live download speed to active Pinchflat downloads. The app uses yt-dlp progress output when Pinchflat exposes it and otherwise estimates transfer rate from the growing media file.
- Keeps the active-task tile refreshed even when the full Pinchflat Downloads dashboard section is disabled.

[Archived release documentation](https://github.com/AshCooperUK/youtube-pinchflat-sync/blob/55e6f7989f8cb5854666c37f7214b4556cf253ba/README.md).

## v2.15.0.0

- Adds Settings → Video Retention with a master switch and separate policies for favourite and non-favourite channels.
- Retention age is based on the original YouTube upload date rather than the local file creation date.
- Adds a configurable minimum number of newest videos to keep per channel and a grace period for newly downloaded historical media.
- Adds per-channel retention overrides with channel search and a one-click return to the inherited group policy.
- Adds Cleanup Preview showing eligible videos, reclaimable storage, affected channels and protected media before anything is deleted.
- Adds manual Run cleanup now plus scheduled Daily, Every 3 days or Weekly cleanup.
- Protects favourite videos when enabled and always excludes One-time Downloads from automatic retention cleanup.
- Adds a purple retention shield around channel artwork. Pressing it opens that channel's retention policy directly.
- Adds an individual video protection shield to the media player, Channel video tiles, Discover, Random Shorts and Favourite Video tiles.
- Adds retention information to Channel details, including policy source, minimum kept, stored media, eligible media and reclaimable space.
- Uses Pinchflat's media deletion path with prevent-download state so retention cleanup does not immediately download removed videos again.
- Respects Pinchflat's native Prevent Automatic Deletion flag.
- Refreshes the detected Emby YouTube library after a retention cleanup removes media.
- Video Retention defaults to Off after upgrade, so no files are deleted until the feature is explicitly enabled.
- Reorganises Settings into a grouped sidebar: General, Dashboard, YouTube, Pinchflat, Emby, Downloads, Video Retention, Favourites, Automation, Security and Diagnostics.
- Reorders Dashboard settings to match the physical top-to-bottom dashboard layout and adds clear descriptions beside each setting.
- Consolidates the old API, Logs and Advanced settings areas into the relevant YouTube, Emby, Pinchflat and Diagnostics sections.
- Removes the old editable Download Paths settings card. Pinchflat subscription paths now remain owned by the selected Media Profile, One-time Download owns its own path, and Emby Download owns its playlist path under Automation.
- Clarifies One-time Download settings and confirms every Single Download action uses the saved resolution, audio-only format, folder, filename template and metadata options.
- Fixes One-time Download Emby refresh so the app detects and scans the Emby library or folder associated with the configured Single Downloads path instead of always scanning the main Pinchflat YouTube library.
- Applies the same targeted Emby library detection to the Emby Download playlist folder.
- Adds separate Emby status rows and manual scan buttons for Pinchflat downloads, One-time Downloads and Emby Download.

[Archived release documentation](https://github.com/AshCooperUK/youtube-pinchflat-sync/blob/6b7aacd3b66fe38e1ed8425751af5d4eb0e472a4/README.md).

## v2.14.0.12

- Redesigns Discover → Random Shorts to use the same visual language as the main media player.
- Replaces the old large Shorts text buttons with the shared icon action dock for favourite, subscribe, like, one-time download and YouTube.
- Adds a matching channel information card with global channel image controls, banner and public channel statistics.
- Adds a compact video overview for views, likes, comments, date, duration and category.
- Makes Short descriptions use the same clickable-link handling as the main media player.
- Adds repository screenshots under `docs/screenshots` so GitHub displays app previews directly from the README after the files are pushed.

[Archived release documentation](https://github.com/AshCooperUK/youtube-pinchflat-sync/blob/04c2472a02f298fe7c25852e85273d6409596027/README.md).

## v2.14.0.11

- One-time Download controls now detect completed direct downloads which still exist on disk.
- Download icons are disabled and greyed out for videos already present from One-time Download.
- The state is shared across Channel videos, Discover, Favourites and the media player.
- Manual Single Download requests also refuse to duplicate a completed video while its file remains present.
- Removing the downloaded file makes the video eligible for One-time Download again after the next status lookup/page load.


Settings notification correction.

- Keeps Settings save notifications above the open Settings dialog instead of hiding them behind the modal.
- Stops persistent dashboard warnings from being mistaken for the result of a Settings save.
- Successful Settings saves now show the normal green success notification. Genuine save failures remain red.

[Archived release documentation](https://github.com/AshCooperUK/youtube-pinchflat-sync/blob/19005251159b05785a6188e6a41480f0b7944906/README.md).

## v2.14.0.10

Settings notification correction.

- Keeps Settings save notifications above the open Settings dialog instead of hiding them behind the modal.
- Stops persistent dashboard warnings from being mistaken for the result of a Settings save.
- Successful Settings saves now show the normal green success notification. Genuine save failures remain red.

[Archived release documentation](https://github.com/AshCooperUK/youtube-pinchflat-sync/blob/04c2472a02f298fe7c25852e85273d6409596027/README.md).

## v2.14.0.9

Scheduled Pinchflat indexing update.

- Adds Settings → Pinchflat → Scheduled Force Index.
- Gives favourite and non-favourite channels independent Force Index intervals.
- Defaults both schedules to Off so existing installs do not create extra YouTube traffic until enabled.
- Applies the schedule only to active, download-enabled subscriptions which currently have a linked Pinchflat source.
- Spreads each full source pass across the chosen interval and processes sources sequentially instead of sending one large burst to Pinchflat.
- Caps scheduled work per minute and spaces actions to reduce the chance of contributing to YouTube HTTP 429 rate limiting.
- Stores the last scheduled Force Index result per channel so restarts continue from the least recently scanned sources.

[Archived release documentation](https://github.com/AshCooperUK/youtube-pinchflat-sync/blob/19005251159b05785a6188e6a41480f0b7944906/README.md).

## v2.14.0.8

- Makes web addresses and email addresses in media-player video descriptions clickable and opens web links in a new tab.
- Applies the same link handling to the channel description shown inside the media player.

Channel video icon consistency update.

- Replaces the plain down-arrow button on Popular and Latest videos in the Channel popup with the same one-time download SVG icon used by the media player.
- Keeps the existing one-time download behaviour unchanged.

[Archived release documentation](https://github.com/AshCooperUK/youtube-pinchflat-sync/blob/19005251159b05785a6188e6a41480f0b7944906/README.md).

## v2.14.0.7

Channel video icon consistency update.

- Replaces the plain down-arrow button on Popular and Latest videos in the Channel popup with the same one-time download SVG icon used by the media player.
- Keeps the existing one-time download behaviour unchanged.

[Archived release documentation](https://github.com/AshCooperUK/youtube-pinchflat-sync/blob/955e643c28e96cb8c0ae81f0cecfcc82bdfbb6ab/README.md).

## v2.14.0.6

Settings and dashboard layout usability update.

- Saves normal Settings forms asynchronously so the Settings dialog stays open instead of closing, reloading the dashboard and reopening.
- Keeps the active Settings tab and scroll position while saving.
- Applies dashboard-affecting changes with one clean refresh when Settings is closed, rather than after every Save action.
- Clears one-time Settings URL hashes after opening so a later page refresh does not unexpectedly reopen Settings.
- Uses a consistent 18px gap between all enabled dashboard sections regardless of custom order or disabled sections.

[Archived release documentation](https://github.com/AshCooperUK/youtube-pinchflat-sync/blob/04ff9c0caa38cdd0348ef476b88a600382426063/README.md).

## v2.14.0.5

Channel navigation and control consistency update.

- Makes web addresses and email addresses in Channel About text clickable. Web links open in a new tab.
- Adds a one-time download icon directly over Popular and Latest video thumbnails in the Channel popup.
- Adds global Page View controls for channel-image actions across Subscriptions, Discover, Favourites, Channel details, Featured Channels and the media player.
- Adds individual visibility switches for Favourite, download enable/disable, Force Scan and remove/delete channel controls.
- Adds clearer HTTP 429 guidance beside Pinchflat's concurrent-download setting.

[Archived release documentation](https://github.com/AshCooperUK/youtube-pinchflat-sync/blob/0b93457bebc3bdbf17e152c114b7b0c95c547070/README.md).

## v2.14.0.4

Media player visual redesign.

- Rebuilds the shared media-player popup with a cleaner visual layout and a wider player area.
- Replaces the large text-heavy action buttons with compact icon actions for video favourite, YouTube subscribe, YouTube like, one-time download and Open on YouTube.
- Keeps channel favourite, download enable/disable, Force Scan and remove controls on the channel artwork instead of duplicating those actions as large buttons.
- Adds the YouTube channel banner to the media-player channel card when available.
- Increases the channel artwork size and groups channel statistics into a more compact visual card.
- Reorganises video data into an icon-led overview, technical details and a separate About this video section.
- Keeps channel names and the About channel card linked to the full in-app Channel details popup.

[Archived release documentation](https://github.com/AshCooperUK/youtube-pinchflat-sync/blob/91c06f3228c6b31fb69ad9dc782d2f6a2296aeba/README.md).

## v2.14.0.3

Emby scan and metadata sequencing update.

- Every Emby channel or YouTube-library scan now queues a second metadata pass after a short delay so newly indexed media and NFO files are available first.
- The second pass uses Emby's FullRefresh / Replace all metadata mode while keeping existing images and video preview thumbnails.
- Single Download now scans the detected Emby YouTube library after a successful download and automatically follows with the delayed metadata refresh.
- Emby refreshes remain scoped to the detected YouTube library or matching channel folder. Other Emby libraries are not scanned.

[Archived release documentation](https://github.com/AshCooperUK/youtube-pinchflat-sync/blob/02ab6e4f03acf4be5ecd08d56c1fc9d47fcf5549/README.md).

## v2.14.0.2

- Adds a consistent channel removal icon to channel artwork, with choices matching the Actions menu for YouTube, Pinchflat Sync, Pinchflat and media cleanup.
- Redesigns the Favourites popup around compact channel/video tiles and the same channel-image controls used elsewhere in the app.
- Adds Discover > Disliked Videos using the connected YouTube account's rating data.

Dashboard layout and built-in function reference update.

- Keeps normal vertical spacing between Pinchflat Downloads and Subscriptions when Latest from your subscriptions is disabled.
- Hides the duplicate Last downloaded row inside Pinchflat Downloads when the dedicated Latest download status tile is enabled.
- Removes the subscription helper sentence under the Subscriptions heading.
- Adds a footer link to the GitHub repository.
- Adds a Debug & function reference popup from the bug icon in the bottom-left footer, with searchable descriptions of user-facing controls and the service each action talks to.

- Automatically resolves the host directory mounted at `/downloads` from Docker instead of asking you to duplicate the YouTube library path in Settings.
- Matches that host bind to Emby's Virtual Folders, including a different in-container path used by a local Emby container.
- Supports an Emby library rooted at the YouTube directory itself or a subfolder such as `YouTube/shows`.
- Channel-level Refresh Emby first refreshes the matching channel item recursively.
- If a new channel folder has not been indexed yet, only the detected Emby YouTube library is refreshed. Other Emby libraries are not scanned.
- Settings → Emby → Emby now reports the automatically detected YouTube library when Test connection is used.
- Settings → Emby → Emby Scan Library Files now scans only the detected YouTube library.
- Automatic refresh after a completed Pinchflat download and Bulk Refresh Emby use the same targeted library logic.
- Reworks Discover video controls into a consistent icon system.
- Discover → Downloaded shows Favourite, Refresh in Emby and YouTube subscription state/actions.
- Discover → Liked Videos and Random Videos show Favourite, one-time Download and Subscribe actions.
- Discover → Top 100 also exposes subscription state/action alongside the existing channel controls.
- Filled Favourite and subscribed-state icons remain visible so the current state is clear without hovering.
- Random Videos now returns up to 150 normal videos per batch instead of 100 while continuing to reject Shorts and clips of roughly three minutes or less.
- Channel names in Discover open the in-app Channel details view rather than leaving the application.
- Extends the same Channel-details behaviour to additional visible channel names, including Shorts, favourite-video cards, Pinchflat activity and media-player headings.
- Keeps the v2.13.0c fast dashboard startup and immediate subscription Enabled toggle behaviour.

[Archived release documentation](https://github.com/AshCooperUK/youtube-pinchflat-sync/blob/6b7aacd3b66fe38e1ed8425751af5d4eb0e472a4/README.md).

## v2.14.0.1

Dashboard layout and built-in function reference update.

- Keeps normal vertical spacing between Pinchflat Downloads and Subscriptions when Latest from your subscriptions is disabled.
- Hides the duplicate Last downloaded row inside Pinchflat Downloads when the dedicated Latest download status tile is enabled.
- Removes the subscription helper sentence under the Subscriptions heading.
- Adds a footer link to the GitHub repository.
- Adds a Debug & function reference popup from the bug icon in the bottom-left footer, with searchable descriptions of user-facing controls and the service each action talks to.

- Automatically resolves the host directory mounted at `/downloads` from Docker instead of asking you to duplicate the YouTube library path in Settings.
- Matches that host bind to Emby's Virtual Folders, including a different in-container path used by a local Emby container.
- Supports an Emby library rooted at the YouTube directory itself or a subfolder such as `YouTube/shows`.
- Channel-level Refresh Emby first refreshes the matching channel item recursively.
- If a new channel folder has not been indexed yet, only the detected Emby YouTube library is refreshed. Other Emby libraries are not scanned.
- Settings → API → Emby now reports the automatically detected YouTube library when Test connection is used.
- Settings → API → Emby Scan Library Files now scans only the detected YouTube library.
- Automatic refresh after a completed Pinchflat download and Bulk Refresh Emby use the same targeted library logic.
- Reworks Discover video controls into a consistent icon system.
- Discover → Downloaded shows Favourite, Refresh in Emby and YouTube subscription state/actions.
- Discover → Liked Videos and Random Videos show Favourite, one-time Download and Subscribe actions.
- Discover → Top 100 also exposes subscription state/action alongside the existing channel controls.
- Filled Favourite and subscribed-state icons remain visible so the current state is clear without hovering.
- Random Videos now returns up to 150 normal videos per batch instead of 100 while continuing to reject Shorts and clips of roughly three minutes or less.
- Channel names in Discover open the in-app Channel details view rather than leaving the application.
- Extends the same Channel-details behaviour to additional visible channel names, including Shorts, favourite-video cards, Pinchflat activity and media-player headings.
- Keeps the v2.13.0c fast dashboard startup and immediate subscription Enabled toggle behaviour.

[Archived release documentation](https://github.com/AshCooperUK/youtube-pinchflat-sync/blob/7314dedfa7fc6adc4e58a62eced639acab895473/README.md).

## v2.14.0.0

Emby library targeting and Discover interaction update.

- Automatically resolves the host directory mounted at `/downloads` from Docker instead of asking you to duplicate the YouTube library path in Settings.
- Matches that host bind to Emby's Virtual Folders, including a different in-container path used by a local Emby container.
- Supports an Emby library rooted at the YouTube directory itself or a subfolder such as `YouTube/shows`.
- Channel-level Refresh Emby first refreshes the matching channel item recursively.
- If a new channel folder has not been indexed yet, only the detected Emby YouTube library is refreshed. Other Emby libraries are not scanned.
- Settings → API → Emby now reports the automatically detected YouTube library when Test connection is used.
- Settings → API → Emby Scan Library Files now scans only the detected YouTube library.
- Automatic refresh after a completed Pinchflat download and Bulk Refresh Emby use the same targeted library logic.
- Reworks Discover video controls into a consistent icon system.
- Discover → Downloaded shows Favourite, Refresh in Emby and YouTube subscription state/actions.
- Discover → Liked Videos and Random Videos show Favourite, one-time Download and Subscribe actions.
- Discover → Top 100 also exposes subscription state/action alongside the existing channel controls.
- Filled Favourite and subscribed-state icons remain visible so the current state is clear without hovering.
- Random Videos now returns up to 150 normal videos per batch instead of 100 while continuing to reject Shorts and clips of roughly three minutes or less.
- Channel names in Discover open the in-app Channel details view rather than leaving the application.
- Extends the same Channel-details behaviour to additional visible channel names, including Shorts, favourite-video cards, Pinchflat activity and media-player headings.
- Keeps the v2.13.0c fast dashboard startup and immediate subscription Enabled toggle behaviour.

[Archived release documentation](https://github.com/AshCooperUK/youtube-pinchflat-sync/blob/779ce5569d8e2d83b8e0301a315e2a5589bd5b5c/README.md).

## v2.13.0c

- Speeds dashboard startup and applies the subscription Enabled toggle immediately.
- Retains the compact Actions menu, Emby refresh integration, featured channels and channel insights from v2.13.0b.

These changes are recorded in the following v2.14.0.0 release notes. The v2.13.0c commit retained the earlier v2.13.0b README heading.

[Archived release documentation](https://github.com/AshCooperUK/youtube-pinchflat-sync/blob/1d659f3474af5b71d2377e19551f98c618137f26/README.md).

## v2.13.0b

Channel-actions correction, Emby integration and Channel UI refinement.

- Restores a compact per-channel Actions menu. Clicking a channel name opens Channel insights, while Actions opens management commands beside the row.
- Mirrors every per-channel Actions command in Subscription tools bulk actions, including Pinchflat actions, Emby refresh, unsubscribe and destructive removal options.
- Adds Settings → API → Emby with Server URL, API key, automatic post-download refresh, connection test and an Emby Scan Library Files control.
- Adds automatic Emby library scans after newly completed Pinchflat downloads are detected.
- Adds Refresh Emby to individual channel Actions and bulk actions.
- Adds YouTube Featured channels to Channel insights using YouTube channel sections where available.
- Moves Channel videos and About directly below the Channel identity header.
- Replaces the text-heavy YouTube and Pinchflat header buttons with compact service-logo controls.
- Adds visual status overlays to the channel image for Favourite, Downloads enabled and Force Scan.
- Groups Channel statistics into clearer overview, recent performance, channel details and Pinchflat sections while keeping the existing information.
- Removes the explanatory daily-snapshot text from the growth-history panel.
- Makes Favourite, Downloads enabled and Force Scan overlays interactive wherever channel artwork is shown in the main channel interfaces.
- Moves About and channel tags into the Channel identity panel, uses a YouTube service icon and keeps long descriptions naturally expanding without an inner scrollbar.
- Adds filesystem capacity and a usage progress indicator to Settings → Downloads.
- Adds a Favourites overview with live counters and image-only favourite-channel tiles.

[Archived release documentation](https://github.com/AshCooperUK/youtube-pinchflat-sync/blob/1d659f3474af5b71d2377e19551f98c618137f26/README.md).

## v2.13.0

Channel insights, richer media details and bulk Pinchflat management.

- Adds Pinchflat source actions and destructive channel actions to Subscription tools bulk actions.
- Makes linked channel names open the in-app Channel view instead of leaving the dashboard.
- Expands Channel with the current handle, channel age, compact subscriber counts, country, category, public statistics, recent-upload averages, topics, keywords and source details.
- Adds local daily channel-stat snapshots and an interactive Views, Subscribers and Videos history graph. Historical points build from this release onwards.
- Adds Popular and Latest video panels to Channel. Popular video lookups are cached to reduce YouTube API use.
- Adds a configurable Latest download dashboard status tile. Clicking the tile opens the shared media player.
- Expands the media player with richer video statistics, language, privacy, licensing, format details and a matching channel information panel.
- Keeps explicit Open YouTube controls available where you want to leave the app.

[Archived release documentation](https://github.com/AshCooperUK/youtube-pinchflat-sync/blob/ebc7aff4ab1c4d7dbef2e6cc04c962ccf08bc8bb/README.md).

## v2.12.4

Dashboard usability and persistent-login update.

- Adds a Google Cloud Console shortcut to the Google status tile using the Google Cloud logo and the same tile spacing as the Pinchflat shortcut.
- Keeps authenticated sessions across browser restarts with a configurable remembered-login period under Settings → Security.
- Keeps the existing inactivity timeout and account lockout controls separate from the remembered-login period.
- Makes pinned favourite subscriptions obey the selected subscription sort order instead of remaining alphabetically ordered.
- Improves the Subscription tools popup with labelled View subscriptions and Bulk actions sections.
- Adds clear descriptions for filtering, sorting and bulk-action controls.
- Only shows the bulk Apply button after a bulk action has been selected.

[Archived release documentation](https://github.com/AshCooperUK/youtube-pinchflat-sync/blob/6505f66a1f642b26b480df47b4337dec8304bb0b/README.md).

## v2.12.3

Pinchflat source-action reliability update.

- Fixes the unreliable source-action discovery used by Force Scan, Download Pending, Re-Download Existing, Refresh Metadata and Sync Files on Disk.
- Stops trying to identify source actions by scraping visible button/form text from the Pinchflat source page.
- Calls Pinchflat's documented SourceController routes directly:
  - `/sources/:source_id/force_download_pending`
  - `/sources/:source_id/force_redownload`
  - `/sources/:source_id/force_index`
  - `/sources/:source_id/force_metadata_refresh`
  - `/sources/:source_id/sync_files_on_disk`
- Loads the Pinchflat source page first to establish the Phoenix session and obtain its CSRF token.
- Posts only the CSRF token to the forced-action route instead of accidentally sending unrelated source-edit form fields.
- Treats Pinchflat's normal 302/303 redirect after queueing an action as success.
- Force Scan remains the friendly app name for Pinchflat's `force_index` action.
- HTTP 500 errors now include useful Pinchflat response text and a short tail of recent Pinchflat Docker logs where available.
- Failed source actions are written to Settings → Logs → Activity with the detailed Pinchflat error.

[Archived release documentation](https://github.com/AshCooperUK/youtube-pinchflat-sync/blob/e86207304de18033971ec70d26d2c77f102d0f38/README.md).

## v2.12.2

Subscription search placement update.

- Moves the channel search box out of the Subscription tools popup and into the top-right of the Subscriptions card.
- Places Search immediately before the blue visible-count badge, tools button and minimise button.
- Search remains available even while the Subscriptions section is minimised.
- Search remains live and debounced, with no submit button and no page reload.
- Keeps status filtering, sorting, selection and bulk controls inside Subscription tools.
- Adds responsive sizing so the search field fills the available width on smaller screens.

[Archived release documentation](https://github.com/AshCooperUK/youtube-pinchflat-sync/blob/3ce200908a173af1e4e6a691b3185a5516a786d5/README.md).

## v2.12.1

Destructive channel removal fix.

- Fixes `Delete Channel & Unsubscribe` and `Delete Channel & Unsubscribe & Remove Media` leaving an inactive `No longer subscribed` row in the main Subscriptions list.
- A destructive Delete Channel action now removes the subscription row from the app database after the YouTube unsubscribe and Pinchflat removal request has been made.
- The row disappears from the current page immediately without a full page reload.
- The subscription count and dashboard counters update in place.
- Adds a short-lived manual-delete tombstone so a stale YouTube subscriptions response cannot immediately recreate a channel just deleted by the user.
- Once a later YouTube refresh has observed the channel absent, a genuine future re-subscribe is allowed and the channel is imported normally again.
- Pinchflat cleanup jobs continue even after the app subscription row has been removed.
- `Delete Channel & Unsubscribe & Remove Media` still asks Pinchflat to remove media and also removes the matching channel folder from the configured downloads tree when present.
- The success message now reports whether Pinchflat removal is still being reconciled in the background and whether the app found and removed a remaining channel folder.
- The confirmation button now changes to `Removing…` / `Removing media…` and disables both confirmation buttons while the operation runs.
- Prevents accidental double-clicks while a destructive channel removal is in progress.
- Failed removal now logs a clear activity error and keeps the channel management popup available for retry.

[Archived release documentation](https://github.com/AshCooperUK/youtube-pinchflat-sync/blob/369732e6c7bb32beda7804fdab8bb866725a1f20/README.md).

## v2.12.0

Subscription workflow and source-management update.

- Keeps the page anchored to the same subscription after Save and favourite changes.
- Serialises per-channel Save requests so several Pinchflat source updates do not collide.
- Adds a short queue between subscription saves and shows Queued / Saving states.
- Debounces subscription searching by 450 ms so filtering waits for typing to pause.
- Moves subscription search, filtering, sorting, selection and bulk controls into a new Subscription tools popup beside the count badge.
- Per-channel Save changes is only visible after that row has unsaved changes.
- Adds Save selected changes to Bulk actions only when selected rows contain unsaved changes.
- Adds Make favourite and Remove favourite to Bulk actions.
- Adds a per-channel Actions popup with local subscription data, Pinchflat source information and live YouTube channel statistics.
- Adds Pinchflat actions: Download Pending, Re-Download Existing, Force Scan, Refresh Metadata and Sync Files on Disk.
- Source action discovery follows Pinchflat's own visible form/button labels instead of depending on one fixed internal route.
- Adds Unsubscribe, Delete Channel & Unsubscribe, and Delete Channel & Unsubscribe & Remove Media actions.
- Destructive delete actions use a separate confirmation popup.
- Favourite changes now update every visible Discover tile from that channel immediately without a page refresh.
- Discover clears stale tiles when loading a different category, so videos from the previous category are no longer shown underneath the loading message.

[Archived release documentation](https://github.com/AshCooperUK/youtube-pinchflat-sync/blob/24c51e76f822b34d016cfce178191fb4205d010d/README.md).

## v2.11.0

Pinchflat concurrent download control.

- Adds `Settings → Pinchflat → Advanced Pinchflat`.
- Adds a Concurrent downloads selector for Pinchflat's `YT_DLP_WORKER_CONCURRENCY`.
- Supports 1, 2, 3, 4, 5, 6, 8, 10, 12 and 16 concurrent yt-dlp workers.
- Displays the value currently applied to the running Pinchflat Docker container.
- Applying a different value safely recreates the Pinchflat container because Docker environment variables cannot be modified in place.
- Preserves the Pinchflat image, environment, bind mounts, ports, restart policy, labels, resource settings and network aliases.
- Keeps the original container as a temporary rollback copy until the replacement starts successfully.
- Automatically restores the original Pinchflat container if recreation or startup fails.
- Pinchflat configuration and downloaded media remain in their existing bind-mounted directories.
- Fresh installs explicitly set the Pinchflat default worker concurrency to 2 in the bundled Compose configuration.

[Archived release documentation](https://github.com/AshCooperUK/youtube-pinchflat-sync/blob/0ee02f439b7594b9051a1054876c559970866259/README.md).

## v2.10.1

Dismissible page messages.

- Adds a close button to the right-hand side of server-generated success and error messages.
- The close button follows the existing dark UI style.
- Messages fade away cleanly when dismissed.
- Extra right-hand padding prevents message text from overlapping the close button.

[Archived release documentation](https://github.com/AshCooperUK/youtube-pinchflat-sync/blob/1dce17ecaec2ebc57a16f8bdacc79265f6a6bfe6/README.md).

## v2.10.0

YouTube Liked Videos in Discover.

- Adds `Discover → Liked Videos`.
- Reads every video currently marked Like on the connected YouTube account using `videos.list?myRating=like`.
- Liked Videos use the same clean 16:9 tile layout as Downloaded and Random Videos.
- The list follows YouTube pagination until all liked videos have been retrieved.
- Liked-video results are cached for 10 minutes to reduce YouTube API calls on large libraries.
- Pressing Discover Refresh while on Liked Videos forces a fresh read from YouTube.
- Fetching Liked Videos uses normal YouTube Data API quota units but does not use the app's expensive `search.list` discovery allowance.
- Channel avatars are loaded for liked videos so the in-app media player receives the same rich channel presentation as Random Videos.
- Adds a circular download icon beside the favourite-channel heart on Liked Videos tiles.
- The download icon opens the existing Single Download popup with the YouTube URL already filled in.
- Pressing the tile download icon never starts or queues a download automatically. The user must press Download in the Single Download popup.
- Clicking the heart continues to favourite the channel, matching the existing Discover tile behaviour.
- Liked Videos stay synchronised with favourite-channel and favourite-video state changes made elsewhere in the app.
- Liking a YouTube video from inside the app invalidates the Liked Videos cache so a later refresh includes the new like.
- Also cleans the duplicated Discover tile click branch left from the earlier Downloaded metadata update.

[Archived release documentation](https://github.com/AshCooperUK/youtube-pinchflat-sync/blob/1dce17ecaec2ebc57a16f8bdacc79265f6a6bfe6/README.md).

## v2.9.1

Discover Downloaded live-refresh fix.

- Fixes switching from Random Videos back to Downloaded leaving the Random Videos tiles visible until Refresh was pressed.
- Changing Discover tabs now immediately renders the cached content for the selected tab.
- Switching back to Downloaded silently checks Pinchflat for newly completed downloads.
- While Discover is open on Downloaded, the app checks for new completed Pinchflat downloads every four seconds.
- The background check keeps the existing tiles visible while it runs, so the grid does not flash or disappear.
- Downloaded redraws only when the latest-100 result has changed.
- If the main Pinchflat Downloads poll spots a different Last downloaded video, an open Downloaded view refreshes immediately.
- Automatic Downloaded refreshes read Pinchflat only and use no YouTube search quota.
- Closing Discover or pressing Escape stops the Downloaded background timer.

[Archived release documentation](https://github.com/AshCooperUK/youtube-pinchflat-sync/blob/5dcdf13fb31d57c5cfb6291e17a875b89a0b53bc/README.md).

## v2.9.0

Page View customisation and Pinchflat queue refresh fix.

- Adds `Settings → Page View`.
- Each major dashboard section can be enabled or completely disabled.
- Disabled Pinchflat Downloads does not start its four-second background poll.
- Disabled Latest from subscriptions does not make its background YouTube latest-video request.
- Disabled Subscriptions does not build the full channel-management table or calculate per-channel disk usage during the page request.
- Adds default minimise/restore settings for Pinchflat Downloads, Latest from subscriptions and Subscriptions.
- Adds individual visibility controls for the Google, Pinchflat, Subscriptions, Downloads and Errors status tiles.
- Adds visibility controls for every top-page button except Settings.
- Adds native drag-and-drop ordering for the main dashboard sections.
- Adds native drag-and-drop ordering for the five status tiles.
- Settings always remains visible so Page View can always be changed.
- The page applies saved section and status-tile order on every load.
- Fixes the Pinchflat Download Queue flicker introduced in v2.8.0. The four-second dashboard poll no longer redraws or clears the queue popup.
- The queue keeps its existing contents visible during its independent ten-second refresh.
- Makes the displayed YouTube channel name clickable in Current downloads, Last downloaded and Pinchflat Queue rows.
- Channel links open the source YouTube channel in a new tab.
- Cleans up the duplicated Discover tile click branch from v2.8.0.
- Downloaded Discover tiles now also use the metadata-enriched media player when opened with the keyboard.

[Archived release documentation](https://github.com/AshCooperUK/youtube-pinchflat-sync/blob/5dcdf13fb31d57c5cfb6291e17a875b89a0b53bc/README.md).

## v2.8.0

Dashboard loading, Discover history, queue and subscription AJAX update.

- Adds `Downloaded` as the first and default Discover view.
- Downloaded shows the 100 most recent completed Pinchflat downloads using the same video-tile style as Random Videos.
- Clicking a Downloaded tile opens the existing in-app media player.
- Adds a cached YouTube metadata lookup so videos opened from Pinchflat gain the proper channel logo, description, view count, publication age, favourite state and subscription state.
- The metadata lookup also improves Current downloads, Last downloaded and Pinchflat Queue playback.
- Adds minimise/restore to the Subscriptions section using the same window-style control as the other dashboard sections.
- Replaces the `N shown` text beside subscription sorting with a compact blue count badge in the Subscriptions header.
- Pinchflat Downloads, Subscriptions and Latest from your subscriptions now start minimised on every fresh page load.
- Latest from your subscriptions always starts minimised and its YouTube requests are deliberately started after the rest of the dashboard has loaded.
- The Pinchflat dashboard poll now fetches active jobs and queue counts without returning waiting queue rows.
- Opening the Pinchflat Queue fetches the complete waiting queue instead of only the first 100 jobs.
- The complete queue refreshes every 10 seconds while its popup is open.
- Per-channel Save now uses AJAX and does not reload the page.
- Saving a channel preserves scroll position, filters, sorting, Pinchflat Downloads and Latest video state.
- Save buttons show `Saving…` then `Saved ✓`.
- Enable/disable, range and Media Profile changes are reflected in the affected row without a page refresh.
- Bulk subscription actions now use AJAX and update only the affected rows.
- Unsubscribe now uses AJAX, updates/removes the affected row and leaves the rest of the dashboard untouched.
- Subscription, enabled/disabled/pending and error summary counters update in place after AJAX changes.

[Archived release documentation](https://github.com/AshCooperUK/youtube-pinchflat-sync/blob/4bd27f3eda0f3ec52019b9bcd9356173573eb548/README.md).

## v2.7.4

Pinchflat download spacing and queue-navigation fix.

- Fixes the thumbnail/text overlap in the Last downloaded row.
- Current downloads, Last downloaded and Queue rows now use a consistent 128px thumbnail column with 18px spacing.
- Prevents media text from overflowing into the thumbnail column.
- Opening a video from the Pinchflat Download Queue now remembers the queue as the parent window.
- Closing the media player returns to the Pinchflat Download Queue rather than closing everything.
- Restores the queue's previous scroll position when returning from the media player.
- Closing the media player with Escape or by clicking its backdrop follows the same queue-return behaviour.
- Videos opened from Current downloads or Last downloaded still close normally.

[Archived release documentation](https://github.com/AshCooperUK/youtube-pinchflat-sync/blob/9ca1817b11124a48d7626bbf364346bf8dbdab5e/README.md).

## v2.7.3

Pinchflat download dashboard media links and queue cleanup.

- Makes the Last downloaded thumbnail and title clickable.
- Clicking Last downloaded opens the existing in-app YouTube video popup rather than the downloaded local file.
- Adds YouTube thumbnails to every currently downloading Pinchflat media item.
- Makes current-download thumbnails and titles open the same in-app YouTube video popup.
- Removes the Pinchflat download progress bars because Pinchflat currently starts yt-dlp without usable progress output.
- Stops parsing Pinchflat logs for percentage data every four seconds.
- Hides retryable Pinchflat media jobs from the user-facing waiting queue and queue badge.
- Removes the Retries summary tile from the Pinchflat Download Queue.
- Replaces the queue table with larger media rows matching the current/last-downloaded presentation.
- Waiting queue thumbnails and titles open the existing in-app YouTube video popup.
- Removes `Waiting Pinchflat media download jobs. This view is read-only.` from the queue popup.
- Keeps scheduled and genuinely waiting jobs visible while retryable/private/member-only failures stay out of the queue presentation.

[Archived release documentation](https://github.com/AshCooperUK/youtube-pinchflat-sync/blob/90970008be63fafdf44dc9798d339cc2093f96bd/README.md).

## v2.7.2

Pinchflat queue schema compatibility fix.

- Fixes `no such column: updated_at` from the Pinchflat downloads dashboard.
- The Oban queue query now builds its sort expression only from columns present in the installed Pinchflat database.
- Supports Oban schemas with or without `scheduled_at`, `inserted_at`, `attempted_at` or `updated_at`.
- Removes the hard dependency on the Oban `updated_at` column.
- Queue summary counts are now calculated with dedicated COUNT queries rather than from the first page of queue rows.
- Waiting, Active and Retries therefore remain accurate when more than 100 jobs are queued.
- The queue popup now displays the real API error instead of remaining stuck on `Loading queue...` with zero counters when an error occurs.
- Adds the detected Oban column list to the internal API response for easier future schema diagnostics.

[Archived release documentation](https://github.com/AshCooperUK/youtube-pinchflat-sync/blob/67ca9cd6eebdaa3d7c8291a3190da399e56b7047/README.md).

## v2.7.1

Pinchflat database path compatibility fix.

- Fixes `Pinchflat database is unavailable` in the v2.7 download dashboard.
- Uses `/pinchflat-config/db/pinchflat.db` for current Pinchflat installs.
- Falls back automatically to `/pinchflat-config/pinchflat.db` for older layouts.
- Still honours an explicit `PINCHFLAT_DB_PATH` environment variable when the configured file exists.
- Re-checks the database location on every read, so no clean reinstall is required.
- Updates the supplied Docker compose files to the current Pinchflat database location.
- The existing Pinchflat config mount remains unchanged.

[Archived release documentation](https://github.com/AshCooperUK/youtube-pinchflat-sync/blob/39e618128153d567f15a4b79b01f9364839cd218/README.md).

## v2.7.0

Live Pinchflat download dashboard and waiting queue.

- Adds a full-width `Pinchflat downloads` dashboard tile below the summary tiles and above `Latest from your subscriptions`.
- Reads Pinchflat media-download jobs directly from the mounted Pinchflat SQLite database in read-only mode.
- Tracks Pinchflat's `Pinchflat.Downloading.MediaDownloadWorker` Oban jobs rather than unrelated Pinchflat background work.
- Shows every currently active media download with title, source/channel, attempt number, start time and elapsed time.
- Adds a live progress bar. Pinchflat normally runs yt-dlp with `--no-progress`, so the bar becomes an honest indeterminate downloading animation when Pinchflat does not expose a numeric percentage.
- If a Pinchflat build emits standard yt-dlp progress output, the dashboard automatically shows percentage, total size, speed and ETA.
- Shows the most recently downloaded Pinchflat media item underneath the active jobs, including title, channel, completion time, file size and YouTube thumbnail when the database contains a usable YouTube ID.
- Adds compact Queue, Refresh and Minimise controls matching the style used by Latest from your subscriptions.
- The Queue control shows a live waiting-job count badge.
- Adds a `Pinchflat Download Queue` popup showing waiting count, active count and retry count.
- Queue rows show position, video title, source/channel, queued time, attempt and current queue state.
- The queue is deliberately read-only in this release.
- The dashboard refreshes automatically every four seconds while the browser tab is visible.
- Minimise state is remembered in the browser.
- No Pinchflat database writes are performed by the download dashboard.

[Archived release documentation](https://github.com/AshCooperUK/youtube-pinchflat-sync/blob/c678b4cb6b0957ab764139ac25088e2cc8c61a17/README.md).

## v2.6.5

Pinchflat log viewer fix.

- Fixes `name 'urlencode' is not defined` when loading Pinchflat Docker logs.
- Adds the missing `urlencode` import used to build the Docker logs API query string.
- Removes the `Check the Docker socket mount and Pinchflat container name.` footer from the log viewer.
- The real Docker or Pinchflat error remains displayed inside the log box if log retrieval genuinely fails.

[Archived release documentation](https://github.com/AshCooperUK/youtube-pinchflat-sync/blob/3e657076b9bab953097d652fb48873182db989b5/README.md).

## v2.6.4

Settings form consistency and Pinchflat container logs.

- Adds a dedicated Pinchflat Logs tile under Settings > Logs.
- Pinchflat logs are read directly from the configured Docker container through the existing Docker socket integration.
- The log tile supports 100, 250, 500 or 1,000 recent lines and a manual Refresh logs control.
- Pinchflat Docker logs are restricted to administrator accounts.
- Adds Docker stdout/stderr multiplexed-stream decoding so the log viewer displays clean text.
- Fixes the global checkbox height inherited from normal text fields.
- Checkboxes and radio buttons now use a consistent 18px control aligned vertically with their labels.
- Checkbox rows throughout Settings use a consistent flex layout and 42px row height.
- Normal Settings buttons, text inputs and dropdowns now share the same 42px control height.
- Reworks Settings tabs into an even grid so the tab buttons line up consistently.
- Reworks the Media Profile preset row so Apply Preset no longer stretches across the whole panel.
- Aligns Media Profile selector, New Profile and Delete Profile controls.
- Keeps multi-line text areas intentionally taller while matching the same border, focus and typography treatment.

[Archived release documentation](https://github.com/AshCooperUK/youtube-pinchflat-sync/blob/23de543aea643f350a6fecec01c5e150de305f22/README.md).

## v2.6.3

YouTube statistics cleanup.

- Removes all creator statistics relating to the authenticated user's own YouTube channel.
- Removes own-channel subscriber count.
- Removes own-channel upload count.
- Removes own-channel view count.
- Removes the own-channel account summary/header from Settings > YouTube.
- Stops calling `channels.list?mine=true` solely for statistics.
- Keeps useful account/library information: YouTube subscriptions, liked videos and playlists.
- Keeps YouTube API quota usage and remaining discovery-search allowance.
- Personal watch-history totals and total watch time remain omitted because the YouTube Data API does not expose them.

[Archived release documentation](https://github.com/AshCooperUK/youtube-pinchflat-sync/blob/36e82bd6a7ff47cbf1b822be540331586fe20a63/README.md).

## v2.6.2

UI consistency, favourites refresh and YouTube statistics.

- Playback Download actions now open the Single Download window with the current video URL filled in. They no longer start the download automatically.
- Removes the arrow icon from the main Single Download button.
- Removes the Single Download shortcut from the Downloads dashboard tile.
- Uses the requested Pinchflat CasaOS icon at the top-right of the Pinchflat dashboard tile.
- Replaces the Latest Videos text controls with compact Windows-style refresh and minimise controls.
- Minimise collapses the Latest section into a compact header and changes to a restore control.
- Favourite channel cards are larger and centred. YouTube and Subscribe sit side-by-side only when Subscribe is required.
- Favourite video cards are wider and use a Play, Download, Save to list and Remove favourite layout.
- Favourite video Download opens the configured Single Download window.
- Removes the obsolete Emby scheduling note from Settings > YouTube.
- Adds a YouTube account statistics dashboard for subscriptions, liked videos, own-channel subscribers, public uploads, channel views, playlists, API use and discovery allowance.
- Clearly reports that personal watch-history totals and total watch time are not exposed by the YouTube Data API.
- Standardises normal buttons, inputs and dropdowns around a common 42px Bootstrap-style control height with consistent focus states.

[Archived release documentation](https://github.com/AshCooperUK/youtube-pinchflat-sync/blob/36e82bd6a7ff47cbf1b822be540331586fe20a63/README.md).

## v2.6.1

Media Profile manager and one-time-download UI refresh.

- Adds `Single Download` to the main top menu.
- Keeps the Downloads tile quick-download icon.
- Removes the duplicate Single Download launcher from Settings > Downloads. Settings now only controls one-time-download defaults.
- Adds `One-time download` to the in-app video player action panel.
- Adds `Download` to Random Shorts. Both routes use the same configured one-time-download backend and progress dialog.
- Keeps download controls outside the YouTube iframe so YouTube's own player buttons are never covered.
- Rebuilds Settings > Pinchflat as a cleaner Media Profile Manager.
- Adds profile selection, create and delete controls at the top of the manager.
- Adds guarded Media Profile deletion. The last profile cannot be deleted, and profiles used by enabled app-managed Pinchflat sources are protected.
- Moves Pinchflat statistics to the bottom of the Media Profile Manager.
- Reorganises profile settings into General, Subtitles, Thumbnails, Metadata, Release Formats, Quality, Media Center, SponsorBlock and Advanced sections.
- Dynamically detected fields from the installed Pinchflat release are grouped into the most relevant section when possible.
- Adds local starting presets for Default, Media Center / Emby, Music and Archiving. Presets only populate the editor and require Save Profile before anything is written to Pinchflat.
- Adds an Output Template Help popup with Liquid syntax, yt-dlp syntax, media-centre aliases, custom aliases and common template variables.
- Adds explanatory text beside the main Pinchflat profile options.

[Archived release documentation](https://github.com/AshCooperUK/youtube-pinchflat-sync/blob/d59fa775441979f9f8e5109d011f90746e71c3b0/README.md).

## v2.6.0

Interface, source-control and settings refresh.

- Renames the main interface to `Pinchflat Sync` and removes the old subtitle.
- Renames the main sync action to `Pinchflat Sync`.
- Moves `Refresh YouTube` beside it and gives both primary-action styling.
- Replaces the top `Open Pinchflat` button with a clickable Pinchflat icon beside the Online state.
- Moves Single Download into the Downloads dashboard tile.
- Adds a minimise control to Latest from your subscriptions.
- Moves custom favourite video lists into Settings > Favourites.
- Moves Activity into Settings > Logs alongside recent downloads and sync runs.
- Retires the old Approve and Unapprove workflow. The Enabled toggle is now the sole authority for Pinchflat source membership.
- Existing databases are migrated automatically so legacy review state no longer blocks source reconciliation.
- Makes Save and Unsubscribe source-row actions compact and equal in size.
- Standardises normal and compact button dimensions across the interface.
- Expands Settings > Pinchflat into a Media Profile manager with profile creation, editing and dynamically detected Pinchflat profile fields.
- Adds profile-name editing and support for Pinchflat text, select, checkbox and textarea fields not already represented by friendly controls.
- Adds Settings > Downloads > One-time download with video/quality mode, audio format, NFO control, download folder and a yt-dlp output template.
- Keeps One-time Download settings independent from the normal subscription and Emby Download paths.
- Adds Subscribe controls to the shared in-app video popup and Random Shorts. Existing subscriptions show as Subscribed.
- Keeps the app on the v2 release line.

[Archived release documentation](https://github.com/AshCooperUK/youtube-pinchflat-sync/blob/c4b21eed3ec871987fd56ed5fff2646ffd641b49/README.md).

## v2.5.1

Random Videos / Shorts separation and Shorts layout fix.

- Random Videos now exclude Shorts and other very short clips.
- Normal discovery searches use YouTube's `medium` and `long` duration classes.
- A second safety check removes any Random Video result at three minutes or less.
- Random Shorts continue to use YouTube's `short` duration search.
- The Random Shorts popup now uses a smaller portrait player so the complete interface fits inside the modal.
- Random Shorts mode disables the outer modal scrollbar.
- The Shorts description no longer has its own scrollbar.
- Long Short descriptions are clipped inside a fixed-height description area instead of creating nested scrolling.
- Buttons are slightly more compact in Shorts mode.
- On smaller displays the Shorts player reduces further to keep the complete layout visible.
- Random Videos, Top 100 and other Discover pages keep their normal scrolling behaviour.

[Archived release documentation](https://github.com/AshCooperUK/youtube-pinchflat-sync/blob/e6f97abdabb45f2b9070eaaeac6977d4641d5612/README.md).

## v2.5.0

Random Videos / For You redesign.

- Expands Random Videos to a target of up to 100 video tiles.
- YouTube Data API does not expose the signed-in YouTube Home recommendation feed, so the app builds its own For You-style feed.
- The first search batches use subscriptions, favourite channels and videos liked through this app as personal interest signals.
- If personalised results do not fill 100 positions, additional English/UK discovery searches fill the remaining tiles.
- Current subscribed channels remain excluded from Discover so the page continues to help find other creators.
- Uses several relevance, date and view-count search batches to improve variety.
- Random Video cards are now clean 16:9 thumbnail-only tiles.
- Channel avatars, channel names and action buttons are removed from the normal tile layout.
- Hovering a tile reveals the video title, channel, views and publication age.
- Duration remains visible in the bottom-right corner.
- A small Favourite Channel heart appears over the thumbnail on hover and remains visible when favourited.
- Favourite Video and Like on YouTube buttons are removed from the Random Videos grid.
- Clicking a Random Video opens the existing in-app playback popup.
- Channel avatar data is still retained in the background for Favourite Channel and the playback popup.
- Random Shorts and Top 100 retain their existing layouts.

[Archived release documentation](https://github.com/AshCooperUK/youtube-pinchflat-sync/blob/901378d09c2b1563274e0404fbcd8be8c131a3af/README.md).

## v2.4.0

Home-page Shorts shelf.

- Adds a `Shorts from your subscriptions` shelf inside `Latest from your subscriptions`.
- On a desktop four-column layout the Shorts shelf appears after the first eight normal videos, giving exactly two video rows before Shorts.
- The insertion point adapts to the responsive layout, so Shorts still appear after two rows on three-column, two-column and one-column screens.
- Shows up to eight of the newest detected Shorts from active subscribed channels.
- Normal latest videos and Shorts are separated, so a detected Short is not duplicated in the standard video grid.
- Shorts detection uses videos up to 60 seconds, plus videos up to three minutes when the creator explicitly uses `#shorts`.
- The app enriches up to 150 recent subscription-feed candidates in batches of 50 to find enough normal videos and Shorts.
- Clicking a home-page Short opens the existing in-app video popup.
- The popup automatically changes to a portrait 9:16 player layout for Shorts.
- The heart on each Short favourites the channel, matching the rest of the home page.
- The popup keeps Favourite Video, Favourite Channel, Like on YouTube and Open on YouTube.
- The Shorts shelf automatically moves to remain after two rows when the browser width changes.

[Archived release documentation](https://github.com/AshCooperUK/youtube-pinchflat-sync/blob/6e5bdc6fa9710bc13242b870ea20ed128a0e14f5/README.md).

## v2.3.4

Random Shorts empty-player regression fix.

- Fixes the black Random Shorts panel introduced after personalised Discover searches were added.
- Personalised Shorts searches previously used subscribed channel names too narrowly. Because Discover excludes channels you already subscribe to, a valid search could be filtered down to zero videos.
- Shorts searches now keep the user's personal interest seeds and add a broader English interest branch in the same search.
- If YouTube still returns no suitable Shorts, the player now shows a clear `No Shorts found` message instead of an empty black rectangle.
- The Shorts player host is rebuilt safely when the YouTube iframe has been destroyed or replaced.
- If YouTube reports an individual Short as unplayable, the app automatically advances to another Short in the batch.
- The v2.3.3 YouTube Like CSRF fix remains included.
- The v2.3.2 popup layout and v2.3.1 embedded-player referrer fixes remain included.

[Archived release documentation](https://github.com/AshCooperUK/youtube-pinchflat-sync/blob/6eb0f7825ee873d84673f9eea4ff0124898cc37f/README.md).

## v2.3.3

YouTube Like CSRF fix.

- Fixes `Unexpected token '<' ... is not valid JSON` when pressing `Like on YouTube`.
- The Like button previously posted JSON without the application's required CSRF header.
- Flask rejected the request with an HTML 400 page before the YouTube Like endpoint ran.
- `Like on YouTube` now uses the existing CSRF-aware `apiPost()` helper.
- The fix applies to Random Videos, Random Shorts and the Latest from your subscriptions popup.
- No database migration or clean installation is required.

[Archived release documentation](https://github.com/AshCooperUK/youtube-pinchflat-sync/blob/647a237c47e52246b6b14be0bff3eec6527826ab/README.md).

## v2.3.2

Latest-video popup interface refresh.

- Changes the popup header title to the YouTube channel name.
- Changes the header subtitle to the selected video title.
- Adds the channel avatar to the right-hand information panel.
- Keeps the channel name and view/publish statistics together in a compact channel summary.
- Rebuilds the action area as a two-column equal-size button grid.
- `Favourite video`, `Favourite channel`, `Like on YouTube`, and `Open on YouTube` now share the same height and width.
- Moves the video description into its own clearly labelled section below the actions.
- Improves mobile layout by changing the action grid to one column on narrow screens.
- Retains the v2.3.1 YouTube embedded-player referrer fix.

[Archived release documentation](https://github.com/AshCooperUK/youtube-pinchflat-sync/blob/58aa6ba120be6c6200f1b9f0820acc19cd05c6d2/README.md).

## v2.3.1

YouTube embedded-player identity fix.

- Fixes YouTube player `Error 153` in the Latest from your subscriptions popup.
- The app previously sent `Referrer-Policy: same-origin`, which stripped the HTTP Referer when the browser loaded `youtube-nocookie.com`.
- The global referrer policy is now `strict-origin-when-cross-origin`.
- The latest-video iframe explicitly uses `referrerpolicy="strict-origin-when-cross-origin"`.
- The embedded player URL includes both `origin` and `widget_referrer`.
- The Shorts player now also supplies `widget_referrer`.
- Privacy-enhanced `youtube-nocookie.com` playback remains enabled.
- No database migration or clean installation is required.

[Archived release documentation](https://github.com/AshCooperUK/youtube-pinchflat-sync/blob/bff338f4358f79ab7a4ac6748fd9468680e45614/README.md).

## v2.3.0

Expanded latest-subscriptions player.

- Increases `Latest from your subscriptions` from 12 to 36 videos.
- There is still no date window. The app combines current subscription channel feeds and displays the newest 36 videos overall.
- Clicking a video thumbnail or title now opens an in-app playback popup instead of immediately opening YouTube.
- The popup uses YouTube's privacy-enhanced embedded player and starts the selected video automatically.
- The popup includes `Favourite Video`, `Favourite Channel`, `Like on YouTube`, and `Open on YouTube`.
- Favourite state remains synchronised with the main subscription list, Discover and Favourites.
- The popup shows the video title, channel, views, publication age and full YouTube description.
- Closing the popup clears the embedded player so playback stops immediately.
- Channel avatar and channel name on the main latest-video tiles still open the YouTube channel directly.
- The final metadata enrichment remains a single `videos.list` request by limiting candidate enrichment to 50 video IDs.

[Archived release documentation](https://github.com/AshCooperUK/youtube-pinchflat-sync/blob/b0d97c511c7c277a3a4dd7fd78fa1b3e59161296/README.md).

## v2.2.2

Personalised Discover and YouTube Like controls.

- Moves the Random Shorts title, channel name and description below the action buttons so `Next Short` no longer shifts position when the text changes.
- Removes `Save to list` from Random Videos and Random Shorts.
- Keeps custom video lists available from the Favourites area.
- Adds `Like on YouTube` to Random Videos and Random Shorts.
- The Like button calls YouTube `videos.rate` with `rating=like`, so the rating is written to the connected YouTube account.
- A successful YouTube Like is also stored as a local Discover interest hint.
- Random Shorts and Random Videos now build their search query from the user's own interests rather than only generic discovery terms.
- Explicitly liked Discover videos carry the strongest weighting.
- Favourite channels carry the next strongest weighting.
- Current active YouTube subscriptions provide the broader interest pool.
- Up to three interest seeds are combined for each discovery batch.
- Random Shorts still exclude channels already present in the current subscription list, keeping Discover focused on finding other creators.
- The Shorts panel shows which subscription/favourite interests influenced the current batch.

[Archived release documentation](https://github.com/AshCooperUK/youtube-pinchflat-sync/blob/913eb10056c9afb033dee3a3b14f68563875ced2/README.md).

## v2.2.1

Latest subscriptions feed fix.

- Replaces the deprecated YouTube `activities.list?home=true` approach used in v2.2.0.
- There is no date or time window.
- The app reads the recent public upload feed for every active subscribed YouTube channel.
- It combines all feed entries, sorts them by publication timestamp and selects the 12 newest videos overall.
- Channel feeds are fetched concurrently and cached for ten minutes.
- The final 12 candidates are enriched with `videos.list` for accurate title, thumbnail, duration and view count.
- Only one low-cost `videos.list` API request is needed after the channel feeds are gathered.
- Results remain filtered against the app's current active subscription database.
- The heart on each tile still favourites the channel, not the video.
- `Refresh videos` forces a fresh scan of the subscribed channel feeds.

[Archived release documentation](https://github.com/AshCooperUK/youtube-pinchflat-sync/blob/7729d45d0e62b06a1b541baf80ae679f9a88e3fa/README.md).

## v2.2.0

Latest subscription videos dashboard.

- Adds a new `Latest from your subscriptions` section between the dashboard status cards and the Subscriptions table.
- Shows up to 12 of the newest YouTube uploads returned for channels which are currently active subscriptions in the app.
- Uses YouTube's authorised activity feed, then filters every result against the app's subscription database so recommendations and non-subscribed channels are excluded.
- Video details include thumbnail, duration, title, channel avatar, channel name, view count and relative publish time.
- Clicking the video thumbnail or title opens the video on YouTube.
- Clicking the channel avatar or channel name opens the YouTube channel.
- Each video thumbnail has a heart in the top-right corner.
- The heart favourites the channel, not the video.
- Favourite hearts stay synchronised with the main subscription list and Favourites popup.
- Results are cached for five minutes to keep YouTube API usage low.
- Adds a `Refresh videos` button for an immediate refresh.
- The layout uses four columns on large screens, three on smaller desktops, two on tablets and one on narrow screens.

[Archived release documentation](https://github.com/AshCooperUK/youtube-pinchflat-sync/blob/a6f0faadf16db00a57efbf24514a7a5fc44c878b/README.md).

## v2.1.1

Random Shorts description display.

- Adds the YouTube Short description beside the embedded Shorts player.
- Uses the full description returned by the existing `videos.list` request, so no additional YouTube API request is required.
- Preserves description line breaks and links as text.
- Long descriptions use a compact scrollable panel so the Shorts popup stays within the screen.
- If a Short has no description, the panel displays `No description provided for this Short.`

[Archived release documentation](https://github.com/AshCooperUK/youtube-pinchflat-sync/blob/2154ab6efe7c43b8d58485d04f880ed5713c6828/README.md).

## v2.1.0

Favourites and custom video lists.

- Adds a Favourites button beside Discover.
- Favourite Channels, Favourite Videos and My Lists are stored per signed-in app user in SQLite.
- Adds a heart control to every subscribed channel image.
- Adds channel hearts to Random Videos, Random Shorts and Top 100.
- Adds video hearts to Random Videos and Random Shorts.
- Favourite channels which are not currently subscribed show a Subscribe button.
- Adds custom named video lists. A saved video can belong to multiple lists.
- Adds Save to list actions from Discover, Random Shorts and Favourite Videos.
- Adds Download List, which queues every video in a custom list through the existing download engine.
- Adds individual Download buttons for Favourite Videos.
- Adds a Favourites filter to the main subscription list.
- Adds a General setting to pin favourite subscribed channels to the top of the channel list.
- Existing Google, Pinchflat, discovery, download and authentication behaviour remains unchanged.

[Archived release documentation](https://github.com/AshCooperUK/youtube-pinchflat-sync/blob/12d528e8612170c85769cb15368325f409bf3023/README.md).

## v2.0.2

English-first Discover and Top 100 channel images.

- Random Videos and Random Shorts remain restricted to the GB content region with `relevanceLanguage=en`.
- Discovery now also checks `videos.list` language metadata. Videos explicitly marked with a non-English default language are excluded.
- When YouTube does not provide language metadata, titles using predominantly non-Latin scripts are excluded as a fallback.
- Top 100 now filters Wikipedia's global Top 100 table using its explicit `Primary language` column and keeps entries containing English.
- Top 100 channel icons are loaded from the live YouTube channel resource.
- `/channel/`, `/@handle`, and `/user/` Top 100 links are resolved through `channels.list`.
- Top 100 channel details are cached with the existing six-hour Top 100 cache.
- Top 100 tiles display the channel avatar, English-language label and country.
- The Top 100 panel description now makes clear it is the English-language subset of the current global Top 100 ranking.

[Archived release documentation](https://github.com/AshCooperUK/youtube-pinchflat-sync/blob/12d528e8612170c85769cb15368325f409bf3023/README.md).

## v2.0.1

Discover and unsubscribe fixes.

- Restores the per-channel YouTube Unsubscribe route accidentally omitted from v2.0.0.
- Unsubscribe again calls the YouTube subscriptions API and applies the configured Pinchflat keep, disable, remove, or remove-and-delete policy.
- Adds a Top 100 section to YouTube Discover.
- Top 100 uses Wikipedia's current public list of the most-subscribed YouTube channels and caches the result for six hours.
- Top 100 does not consume YouTube Data API search quota.
- Fixes Random Shorts rendering by allowing the YouTube iframe API and player in the Content Security Policy.
- Random Shorts now use the privacy-enhanced YouTube player host.
- The Shorts player is reduced to a 330px-wide portrait player so it fits inside the popup.
- Shorts start muted for reliable browser autoplay and include a Sound on / Mute button.
- Automatic next-Short playback remains available.

[Archived release documentation](https://github.com/AshCooperUK/youtube-pinchflat-sync/blob/13378edd9c30c0faf5c688e04b35692a956ade34/README.md).

## v2.0.0

Major discovery, automation and media-management release.

- Adds a Discover button beside Log out. The popup has Random Videos and Random Shorts views.
- Random Videos shows channel-avatar tiles from channels you are not currently subscribed to. Clicking a tile opens the selected video on YouTube.
- Random Shorts uses an embedded YouTube player and automatically advances to the next result when a Short finishes.
- Discovery excludes currently subscribed channel IDs and tracks the YouTube `search.list` daily search bucket separately.
- Splits automation into three independent schedules: YouTube subscription refresh, Pinchflat source reconciliation and Emby Download playlist checks.
- Adds Unapprove per channel and as a bulk action. Unapproving disables the channel, revokes source authorisation and removes the Pinchflat source while keeping downloaded media.
- Direct Single Download and Emby Download folders now receive Emby-friendly `banner.jpg`, `fanart.jpg`, `poster.jpg` and `tvshow.nfo` metadata inside each channel folder.
- Automatically creates standard Pinchflat Media Profiles for YouTube 1080p, YouTube 720p, YouTube Audio Only and YouTube 4K alongside YouTube Sync.
- Standard profiles use SponsorBlock Remove Segments with the Sponsor category by default.
- Existing Media Profile bulk selection now exposes the additional standard profiles automatically.
- Adds a real `.ico` favicon to every web page.
- Keeps cutoff dates on one line in the subscription table.
- Fixes the Settings popup to use one internal scrollbar rather than nested scrollbars.
- Removes the Add pending button from the main subscription toolbar. Authorised sources are handled by the normal Pinchflat sync.
- Restores and formalises the Single Download JSON endpoints used by the progress-bar popup.

[Archived release documentation](https://github.com/AshCooperUK/youtube-pinchflat-sync/blob/302572c8a6898f6b702334d288284751f569418d/README.md).

## v1.9.4

Verification marker parsing fix.

- Fixes the false `Pinchflat direct deletion did not return verification markers` error.
- v1.9.3 successfully deleted the Pinchflat source, but the Python regex looked for a literal `\d` instead of digits.
- Valid output such as `MATCH_COUNT=1 REMAINING_COUNT=0` is now parsed correctly.
- The same correction is applied to `SOURCE_COUNT`.
- After a successful delete, the app now proceeds normally and shows `Not in Pinchflat` instead of leaving a false error.
- Direct deletion through the running Pinchflat release remains unchanged.
- Docker power control and explicit source authorisation remain unchanged.

[Archived release documentation](https://github.com/AshCooperUK/youtube-pinchflat-sync/blob/5b597203df27b4569c78e483fe0fb4227944963a/README.md).

## v1.9.3

Running-Pinchflat RPC deletion fix.

- Fixes `could not lookup Ecto repo Pinchflat.Repo because it was not started`.
- v1.9.2 used `bin/pinchflat eval` for direct source deletion and verification.
- An Elixir release `eval` command runs in a separate VM without starting the release applications, so `Pinchflat.Repo` is unavailable there.
- Direct deletion and source verification now use `bin/pinchflat rpc`.
- `rpc` executes inside the already-running Pinchflat release, where `Pinchflat.Repo`, Oban and the application supervision tree are active.
- Source deletion still uses `Pinchflat.Sources.delete_source/2`.
- The app still verifies the live Pinchflat source list before changing the channel to `Not in Pinchflat`.
- Existing downloaded files remain when a channel is disabled.
- Docker power control and explicit source authorisation are unchanged.

[Archived release documentation](https://github.com/AshCooperUK/youtube-pinchflat-sync/blob/357124585f47483947962b881d06f3b93a4d1a0a/README.md).

## v1.9.2

Verified direct source deletion release.

- Fixes the app showing `Not in Pinchflat` while the source still exists in Pinchflat.
- Fixes a v1.9.0/v1.9.1 verification bug where an unavailable read-only Pinchflat SQLite database could be mistaken for successful deletion.
- Source deletion now locates the source inside the live Pinchflat application by YouTube channel identity.
- YouTube channel ID is authoritative. Numeric Pinchflat source ID is only used when channel identity is unavailable.
- The app calls `Pinchflat.Sources.delete_source/2` directly.
- Pinchflat removes associated source tasks, media records and the source record through its own application code.
- The app performs a second live source-list check after deletion.
- `Not in Pinchflat` is shown only after Pinchflat reports zero matching sources.
- Existing downloaded files remain when a channel is disabled.
- Docker power control and explicit source authorisation remain unchanged.

[Archived release documentation](https://github.com/AshCooperUK/youtube-pinchflat-sync/blob/4f3a10f8bcd67c3672ff7174ec185ba591b34728/README.md).

## v1.9.1

Safe source-authorisation and first-import release.

- Stops stale Enabled/Pending state from an older `/data` directory recreating Pinchflat sources after a reinstall.
- Adds explicit source authorisation. Pinchflat source creation requires both Enabled and an authorised Save/Approve action.
- Save with Enabled on authorises and creates or repairs the source.
- Save with Enabled off revokes authorisation and removes the source.
- Approve + Save enables and authorises the source.
- Automatic retry and Add pending cannot create unauthorised sources.
- A truly new database treats the first Google import as a baseline. Existing subscriptions start disabled and waiting for approval.
- Future newly subscribed channels still follow the configured new-subscription policy.
- Existing rows already linked to Pinchflat remain authorised. Stale Enabled/Pending rows without a Pinchflat link reset to Disabled.
- Status text now distinguishes `Pending Pinchflat creation` from `Save to add to Pinchflat`.

[Archived release documentation](https://github.com/AshCooperUK/youtube-pinchflat-sync/blob/e3c49b4a85ea2a8f951134e6281af195266d0628/README.md).

## v1.9.0

Direct Pinchflat control release.

- Fixes Pinchflat sources getting stuck on `Removing from Pinchflat`.
- The sync app now mounts the Docker Engine socket and controls its own Pinchflat container.
- Source removal now uses `Pinchflat.Sources.delete_source/2` inside the Pinchflat container as the primary deletion path.
- This removes the source synchronously through Pinchflat's own application code rather than relying on the web form or queued SourceDeletionWorker.
- Pinchflat's own source deletion removes associated source tasks before removing the source, which stops pending source work.
- Existing downloaded files are kept when a channel is simply disabled.
- The YouTube unsubscribe policy still controls whether downloaded files are retained or deleted.
- Adds an Enabled / Disabled power switch to the Pinchflat dashboard card.
- The switch starts and stops the `pinchflat` Docker container.
- Background source reconciliation pauses while Pinchflat is intentionally stopped.
- Full YouTube refresh and Emby Download processing continue while Pinchflat is stopped.
- Adds the `/var/run/docker.sock` mount, `PINCHFLAT_CONTAINER_NAME` and `DOCKER_SOCKET_PATH` settings.

This release needs the ZimaOS application to be recreated or updated from the new YAML so the Docker socket mount is applied.

[Archived release documentation](https://github.com/AshCooperUK/youtube-pinchflat-sync/blob/b593d0075c5958ce6a1a4444368c99e1b35fa05e/README.md).

## v1.8.8

Pinchflat source deletion transport fix.

- Fixes disabled sources remaining in Pinchflat after the app says `Removing from Pinchflat`.
- Uses Pinchflat's real HTTP `DELETE /sources/:id` route rather than replaying the HTML form with `POST + _method=delete`.
- Keeps Pinchflat's CSRF token and `delete_files` parameter when issuing the DELETE request.
- Prevents an in-progress source deletion from being immediately handled by Automatic Retry in the same sync.
- Source-authority and unsubscribe reconciliation continue checking deletion every five minutes.
- Once Pinchflat removes the source, the app clears the stored Pinchflat source link and shows `Not in Pinchflat`.

[Archived release documentation](https://github.com/AshCooperUK/youtube-pinchflat-sync/blob/b593d0075c5958ce6a1a4444368c99e1b35fa05e/README.md).

## v1.8.7

Authoritative Enabled toggle release.

- The per-channel Enabled toggle now controls whether the channel exists in Pinchflat.
- Enabled and approved means the source must exist in Pinchflat.
- Disabled means the Pinchflat source is removed while existing downloaded files are kept.
- Waiting for approval also means no Pinchflat source is created.
- Saving a disabled channel never creates or repairs a Pinchflat source.
- Saving an enabled channel creates a missing source or updates the existing source.
- The background pending importer imports enabled sources only.
- Automatic retry follows the Enabled state and never re-adds disabled sources.
- Bulk Enable, Disable, Approve, Retry, Range and Media Profile actions use the same source-authority rules.
- A five-minute reconciliation job gradually removes legacy disabled sources which older releases had already added to Pinchflat.
- Legacy reconciliation is limited to 25 Pinchflat source changes per pass.
- The subscription table shows `Not in Pinchflat` for disabled channels and `Removing from Pinchflat` while asynchronous deletion completes.
- Disabling a source removes only the Pinchflat source. Existing downloaded files remain. File deletion remains controlled by the separate YouTube unsubscribe policy.

[Archived release documentation](https://github.com/AshCooperUK/youtube-pinchflat-sync/blob/81ad54ca9246fe3f0403d1662523e17adce458a2/README.md).

## v1.8.6

Authoritative Pinchflat source removal release.

- Unsubscribing from YouTube now keeps the Pinchflat source link until Pinchflat has really removed the source.
- Before deletion, the app disables Download Media on the source so Pinchflat dequeues pending download tasks.
- The app then starts Pinchflat's normal asynchronous source deletion.
- Source deletion is verified rather than treating Pinchflat's initial redirect as completion.
- Removed subscriptions are reconciled with Pinchflat every five minutes until the source disappears.
- Follow-up cleanup continues removing files which reappear after an already-running download completes.
- Adds a read-only Pinchflat database mount so the app can recover orphaned source IDs left by older releases.
- Older orphaned Pinchflat sources are matched by YouTube channel ID and removed automatically when the selected unsubscribe policy removes sources.
- The app does not write directly to Pinchflat's database.

[Archived release documentation](https://github.com/AshCooperUK/youtube-pinchflat-sync/blob/4352bf432860242f5e3f510be0deeaf95a913c75/README.md).

## v1.8.5

Canonical URL and fresh-install Google OAuth fix.

- `APP_URL` in Docker/ZimaOS YAML is authoritative when supplied.
- The deployment uses the public URL configured in YAML, for example `https://youtube.example.com`.
- Google OAuth therefore uses `https://youtube.example.com/oauth/google/callback` even if the ZimaOS tile initially opens `http://server.example:8787`.
- Adds `CANONICAL_REDIRECT=true`. Opening the local ZimaOS tile redirects the browser to `APP_URL`.
- `/health` remains local for ZimaOS and Docker checks.
- The Public dashboard URL field becomes read-only while YAML manages it.
- HTTPS canonical deployments use Secure session cookies.
- `APP_URL` and `CANONICAL_REDIRECT` are exposed in ZimaOS environment metadata.

For another server, edit `APP_URL` in the YAML before deployment.

[Archived release documentation](https://github.com/AshCooperUK/youtube-pinchflat-sync/blob/8cf47405dfcbeda7002a0ef7dff23e698292aa9a/README.md).

## v1.8.4

YouTube subscription refresh accuracy fix.

- Fixes false-positive `YouTube subscription restored` activity entries.
- The refresh no longer marks every subscription inactive before processing the current YouTube list.
- A channel is treated as genuinely re-subscribed only when it was already inactive and has a recorded `removed_at` timestamp.
- Normal existing subscriptions remain active without generating restoration activity.
- Genuine unsubscribe then re-subscribe recovery remains unchanged, including stale Pinchflat source repair and cancellation of delayed cleanup jobs.

[Archived release documentation](https://github.com/AshCooperUK/youtube-pinchflat-sync/blob/8cf47405dfcbeda7002a0ef7dff23e698292aa9a/README.md).

## v1.8.3

Subscription row editor usability release.

- Simplifies each subscription row into one staged editor.
- Enabled is now a proper toggle and no longer saves immediately.
- Range changes no longer save immediately.
- Media Profile changes no longer save immediately.
- Review sources have an Approve button. Approval is staged locally in the browser and automatically turns Enabled on.
- Nothing in a source row is written until the far-right Save button is clicked.
- A single Save updates Enabled, approval state, range and Media Profile together.
- Approving and saving a review source creates it in Pinchflat immediately.
- Stale Pinchflat source links are repaired during the same Save operation.
- Changed rows get a small amber marker and the button changes to `Save changes` until saved.
- Retry is no longer a separate row action. Saving the row retries the Pinchflat update with the current choices.

[Archived release documentation](https://github.com/AshCooperUK/youtube-pinchflat-sync/blob/8cf47405dfcbeda7002a0ef7dff23e698292aa9a/README.md).

## v1.8.2

Re-subscribe recovery release.

- Channels which were previously removed can now be subscribed to again cleanly.
- Re-subscribing cancels any outstanding delayed file-cleanup job for that channel.
- The app checks whether the previously stored Pinchflat source ID still exists.
- A stale Pinchflat source ID is cleared automatically rather than producing `/sources/<id>/edit` 404 errors.
- The next full sync recreates a fresh Pinchflat source when the old source was deleted.
- The per-channel Retry button also detects a stale source ID and recreates the source immediately.
- Automatic retry has the same stale-source recovery behaviour.
- Re-subscribed channels follow the current New Subscription Behaviour setting.

[Archived release documentation](https://github.com/AshCooperUK/youtube-pinchflat-sync/blob/c2e912e71ce5fc177dd11218e53b2adac9d99052/README.md).

## v1.8.1

Unsubscribe cleanup and media-path maintenance release.

- Restores the default subscription output template to:
  `/shows/{{ source_custom_name }}/{{ season_by_year__episode_by_date_and_index }} - {{ title }}.{{ ext }}`
- Automatically migrates the exact v1.7/v1.8 generated template without `/shows/` to the corrected template. Custom templates are left unchanged.
- When the unsubscribe policy is `Remove Pinchflat source and delete downloaded files`, the app first disables downloading on the Pinchflat source so no new media is queued.
- It then asks Pinchflat to delete the source and its files.
- The local channel folder is removed immediately after source deletion.
- A persistent cleanup queue rechecks the channel after five minutes, then every five minutes for 30 minutes.
- Follow-up cleanup survives an app restart because cleanup jobs are stored in SQLite.
- The extra cleanup window works around Pinchflat's known orphaned-download behaviour when a source is deleted while jobs are already queued.

[Archived release documentation](https://github.com/AshCooperUK/youtube-pinchflat-sync/blob/eb27f46868260c58a0f0788da337f2adc779e738/README.md).

## v1.8.0

Workflow and settings usability update.

- Adds an unsubscribe policy which removes the Pinchflat source and deletes its downloaded media.
- After Pinchflat media deletion, the app also removes any remaining channel folder under the selected subscription path.
- Adds Pinchflat statistics to Settings > Pinchflat and removes the duplicate Open Pinchflat button from that tab.
- The Media Profile save button now names the selected profile.
- Adds editable download paths for subscription auto-downloads, Emby Download and Single Download.
- Moves Emby Download scheduling from YouTube to Automation.
- Replaces raw schedule minute boxes with friendly schedule dropdowns.
- Shows next subscription and Emby Download run times.
- Removes the user/account badge from the main header.
- The logout button now reads `Log out username`.
- YouTube settings now focus on Google OAuth and API quota configuration.

[Archived release documentation](https://github.com/AshCooperUK/youtube-pinchflat-sync/blob/75ac4cf5106d8f6e1f7d9b2a525c8902431d5ac4/README.md).

## v1.7.1

Pinchflat settings display and UI maintenance release.

- Fixes Pinchflat toggle values not appearing enabled after reopening Settings.
- Pinchflat uses Alpine-powered hidden toggle inputs rather than ordinary HTML checkboxes. The app now reads Pinchflat's actual `enabled: true/false` state from the edit form.
- Subtitle, thumbnail, metadata, NFO and Series Images toggles now reflect the values already saved in Pinchflat.
- Simplifies Output path template to one normal text input.
- Changes the default media-centre path to:
  `{{ source_custom_name }}/{{ season_by_year__episode_by_date_and_index }} - {{ title }}.{{ ext }}`
- Removes the extra output-template helper button and duplicate template display.
- Makes Enable/Disable and Delete user buttons the same width.
- Existing Pinchflat profile settings remain authoritative. The app reads the current profile each time Settings opens.

[Archived release documentation](https://github.com/AshCooperUK/youtube-pinchflat-sync/blob/61139ef1fd35795f487bf8c8dbbeedbfd22dedf6/README.md).

## v1.7.0

Pinchflat profile management and user administration update.

- Administrators can permanently delete other users from Settings > Security.
- The current Pinchflat Media Profile can now be edited directly from Settings > Pinchflat.
- Adds an editable Emby output path template.
- Adds subtitle, thumbnail and metadata download/embed controls.
- Adds Shorts and livestream include toggles.
- Adds preferred resolution and redownload delay controls.
- Adds NFO and Series Images controls.
- Adds SponsorBlock behaviour and category controls.
- Newly auto-created `YouTube Sync` profiles default to the Emby media-centre template, Shorts excluded, livestreams included, NFO enabled and Series Images enabled.
- Fixes the Settings dialog occasionally closing the first time the Pinchflat tab is selected.
- Returning from a Pinchflat or Security settings save reopens the correct Settings tab.

[Archived release documentation](https://github.com/AshCooperUK/youtube-pinchflat-sync/blob/885bd8d33e0442b8630cc27d7e7dec9633608f3e/README.md).

## v1.6.0

Native authentication and security release.

- First-run administrator setup.
- Username and password login before the dashboard loads.
- Passwords use Argon2id hashing.
- Optional TOTP two-factor authentication for Microsoft Authenticator, Google Authenticator, Authy and compatible apps.
- Ten one-time recovery codes when 2FA is enabled or regenerated.
- Administrator and Viewer roles. Viewer accounts have read-only dashboard access.
- User management under Settings → Security.
- Password changes invalidate other active sessions.
- Log out all devices.
- Failed-login throttling and temporary account lockout.
- Configurable inactivity session timeout.
- Login and security activity history including IP address.
- CSRF protection for all browser POST actions.
- Security response headers on every response.
- The public `/health` endpoint exposes only status and version.
- Standalone account recovery utility at `app/manage_user.py` for password resets, account unlocks and emergency 2FA removal.
- All v1.5.2 channel artwork, Emby Download, single downloads, quota statistics and storage reporting are retained.

### First start after upgrading

Existing v1.5.x installations have no local dashboard users. The first request to the dashboard is redirected to `/setup`, where you create the first Administrator account. Existing YouTube, Pinchflat and subscription data remains in place.

For a WAN-facing installation, enable authenticator 2FA on the administrator account from Settings → Security.

### Emergency account recovery

From inside the running container:

```bash
docker exec -it youtube-pinchflat-sync python /app/manage_user.py list
docker exec -it youtube-pinchflat-sync python /app/manage_user.py reset-password USERNAME
docker exec -it youtube-pinchflat-sync python /app/manage_user.py unlock USERNAME
docker exec -it youtube-pinchflat-sync python /app/manage_user.py disable-2fa USERNAME
```

[Archived release documentation](https://github.com/AshCooperUK/youtube-pinchflat-sync/blob/82b6a2d462396a096ba12725311acf7a2daddffe/README.md).

## v1.5.2

Channel artwork update.

- Shows the YouTube channel image above the channel name in the subscriptions table.
- Stores the thumbnail URL returned by the YouTube subscriptions API.
- Uses the highest available subscription thumbnail.
- Existing installations gain the new database field automatically.
- If a channel has no image, or the remote image fails to load, the app uses its own built-in YouTube Pinchflat Sync icon.
- Channel names remain shortened in the table, while hovering shows the full name.
- Run Refresh YouTube once after upgrading to populate images for existing subscriptions.

[Archived release documentation](https://github.com/AshCooperUK/youtube-pinchflat-sync/blob/e8caf95ab840d9b2633e6c3a4422f063182c2f75/README.md).

## v1.5.1

Maintenance release fixing the v1.5.0 startup failure.

- Fixes the missing `current_emby_poll_interval()` function which prevented Gunicorn from booting.
- Adds a persistent 5-minute default for the `Emby Download` playlist polling interval.
- Passes the polling interval into the Settings interface.
- Saves changes to the polling interval correctly.
- Reschedules the background playlist job immediately after changing the interval.

[Archived release documentation](https://github.com/AshCooperUK/youtube-pinchflat-sync/blob/ad8c79a7e2bcf14f291a0d2f4428f0548aefa517/README.md).

## v1.5.0

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

[Archived release documentation](https://github.com/AshCooperUK/youtube-pinchflat-sync/blob/4adf3a992c42849d54b2abe23912b8f793063d36/README.md).

## v1.4.0

Version 1.4.0 is the UI and automation release.

### New dashboard

The main page now focuses on:

- Google status
- Pinchflat status
- Active subscriptions
- Enabled and disabled downloads
- Pending sources
- Errors
- Subscription management

Configuration no longer fills the main page.

Use the `Settings` button to open a tabbed settings popup.

Use the `Activity` button to view recent sync activity and sync runs.

### New subscription behaviour

The default is now:

`Automatically enable and download`

When the scheduled sync finds a brand-new YouTube subscription it:

1. Adds the channel to the local database.
2. Enables downloads.
3. Creates the Pinchflat source.
4. Uses the configured default download range.
5. Uses the configured default Pinchflat Media Profile.

The Settings > General tab also offers:

- Automatically enable and download
- Add to Pinchflat with downloads disabled
- Wait for approval before adding

### YouTube unsubscribe behaviour

When a channel disappears from your YouTube subscriptions, choose one of:

- Keep Pinchflat source
- Disable downloads in Pinchflat
- Remove Pinchflat source while keeping downloaded files

Removed YouTube subscriptions stay in the local history and are hidden from the normal active view. Use the `Removed` filter to see them.

### Subscription filters and sorting

The source table now has:

- Channel search
- All active filter
- Enabled filter
- Disabled filter
- Pending filter
- Needs review filter
- Error filter
- Removed filter
- A to Z sorting
- Status sorting
- Newest-first sorting

The browser remembers search, filter and sorting choices.

### Bulk actions

Select several channels and apply:

- Enable downloads
- Disable downloads
- Approve review sources
- Set download range
- Set Pinchflat Media Profile
- Retry errors

A confirmation box appears before a bulk change is applied.

### Media Profiles

Pinchflat Media Profiles are loaded into dropdowns.

You can choose:

- A default Media Profile in Settings > Pinchflat
- A different Media Profile for an individual YouTube source
- A Media Profile for several selected sources using the bulk controls

On a fresh Pinchflat installation the app can automatically create a `YouTube Sync` Media Profile.

### Automatic retries

Failed Pinchflat source updates are retried during scheduled syncs.

The dashboard keeps the last error and retry count until the update succeeds.

### Activity history

The Activity popup keeps recent events such as:

- New YouTube subscriptions
- Removed YouTube subscriptions
- Pinchflat source imports
- Automatic retries
- Settings changes
- Synchronisation results

### Download ranges

The existing per-source ranges remain:

- Default
- Today
- This week
- This month
- Last 6 months
- Last year
- Last 2 to 10 years
- Original YouTube subscription date
- Custom date

The default download history lives under Settings > Downloads.

### Settings tabs

The Settings popup contains:

- General
- YouTube
- Pinchflat
- Downloads
- Automation
- Advanced

The Google OAuth credential form stays hidden while Google is connected.

### Pinchflat onboarding

When the app creates a Pinchflat source, it completes Pinchflat onboarding automatically so Pinchflat opens on the normal dashboard.

[Archived release documentation](https://github.com/AshCooperUK/youtube-pinchflat-sync/blob/d9fcc37b041c4db0e87415e7c536eb440dbc0851/README.md).

## v1.3.1

This maintenance release fixes editing existing Pinchflat sources:

- The app now selects Pinchflat's actual Source edit form.
- It ignores the global `/search` form on Pinchflat pages.
- Per-source download-range changes now post back to the Source route.
- Per-source Enabled/Disabled changes use the same corrected edit form.
- Pinchflat HTTP 500 update errors now show the target route for easier diagnosis.

[Archived release documentation](https://github.com/AshCooperUK/youtube-pinchflat-sync/blob/3254bd2ddaea701893c6cef6ce55fac7b3c01db4/README.md).

## v1.3.0

This version adds:

- New YouTube subscriptions default to downloads disabled.
- Pinchflat sources are created with `Download Media` off unless you enable them.
- Disabled sources remain available for indexing and review without downloading media.
- Each source has its own Enabled/Disabled control.
- Multi-select checkboxes let you enable or disable several sources together.
- Download date ranges stay separate from the enabled state.
- Fresh Pinchflat installs automatically receive a `YouTube Sync` Media Profile.
- Automatic profile creation uses Pinchflat's own New Media Profile form and current defaults.
- The Pinchflat onboarding screen is completed automatically.
- Existing Pinchflat sources from earlier app versions retain their enabled state during database migration.

[Archived release documentation](https://github.com/AshCooperUK/youtube-pinchflat-sync/blob/63361da542f8edbf817145589dabeae60cdc870f/README.md).

## v1.2.1

- Each YouTube subscription has its own download-range dropdown.
- Choices include Default, Today, This week, This month, Last 6 months, Last year, 2 to 10 years, original subscription date and a custom date.
- A source row shows the exact Pinchflat cutoff date before it is added.
- `Refresh YouTube subscriptions` discovers subscriptions without adding them to Pinchflat. This gives you time to choose per-source ranges.
- `Add pending to Pinchflat` creates pending sources using their individual ranges.
- `Full sync now` retains the original automatic behaviour.
- The scheduled sync still runs every `SYNC_INTERVAL_MINUTES`.
- The OAuth configuration section is hidden after Google connects. Disconnect Google to show it again.
- Existing v1.1 SQLite databases are upgraded automatically.
- The app checks that the configured Pinchflat Media Profile exists before creating a source.
- Pinchflat source creation now starts from Pinchflat's live HTML form values, reducing breakage when Pinchflat changes form fields.
- After the first successful source is added, the app marks Pinchflat onboarding complete using `?onboarding=0`.
- The Open Pinchflat button opens the normal Pinchflat dashboard once a valid Media Profile exists.
- Pinchflat HTTP 500 errors now include a clearer source-creation message in the dashboard.

[Archived release documentation](https://github.com/AshCooperUK/youtube-pinchflat-sync/blob/63361da542f8edbf817145589dabeae60cdc870f/README.md).

## v1.2.0

- Each YouTube subscription has its own download-range dropdown.
- Choices include Default, Today, This week, This month, Last 6 months, Last year, 2 to 10 years, original subscription date and a custom date.
- A source row shows the exact Pinchflat cutoff date before it is added.
- `Refresh YouTube subscriptions` discovers subscriptions without adding them to Pinchflat. This gives you time to choose per-source ranges.
- `Add pending to Pinchflat` creates pending sources using their individual ranges.
- `Full sync now` retains the original automatic behaviour.
- The scheduled sync still runs every `SYNC_INTERVAL_MINUTES`.
- The OAuth configuration section is hidden after Google connects. Disconnect Google to show it again.
- Existing v1.1 SQLite databases are upgraded automatically.

[Archived release documentation](https://github.com/AshCooperUK/youtube-pinchflat-sync/blob/502a624c26e95c9fe7f046189a85cd0340e0f67f/README.md).

## v1.1.0

This version adds:

- ZimaOS/CasaOS `x-casaos` metadata so the app appears as a dashboard tile.
- A repository layout which works as a ZimaOS custom App Store source.
- GitHub Actions publishing to GitHub Container Registry.
- Dashboard configuration for Google OAuth.
- Download history presets which map to Pinchflat's `download_cutoff_date`.
- Persistent settings in SQLite.

[Archived release documentation](https://github.com/AshCooperUK/youtube-pinchflat-sync/blob/63fabba3842f1202dbc905faa3f9f2177140719b/README.md).
