# YouTube Pinchflat Sync

A Docker dashboard for ZimaOS which reads your YouTube subscriptions, creates and manages Pinchflat sources, and adds direct-download automation for an Emby YouTube library.

## Version 2.8.0

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


## Version 2.7.4

Pinchflat download spacing and queue-navigation fix.

- Fixes the thumbnail/text overlap in the Last downloaded row.
- Current downloads, Last downloaded and Queue rows now use a consistent 128px thumbnail column with 18px spacing.
- Prevents media text from overflowing into the thumbnail column.
- Opening a video from the Pinchflat Download Queue now remembers the queue as the parent window.
- Closing the media player returns to the Pinchflat Download Queue rather than closing everything.
- Restores the queue's previous scroll position when returning from the media player.
- Closing the media player with Escape or by clicking its backdrop follows the same queue-return behaviour.
- Videos opened from Current downloads or Last downloaded still close normally.


## Version 2.7.3

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


## Version 2.7.2

Pinchflat queue schema compatibility fix.

- Fixes `no such column: updated_at` from the Pinchflat downloads dashboard.
- The Oban queue query now builds its sort expression only from columns present in the installed Pinchflat database.
- Supports Oban schemas with or without `scheduled_at`, `inserted_at`, `attempted_at` or `updated_at`.
- Removes the hard dependency on the Oban `updated_at` column.
- Queue summary counts are now calculated with dedicated COUNT queries rather than from the first page of queue rows.
- Waiting, Active and Retries therefore remain accurate when more than 100 jobs are queued.
- The queue popup now displays the real API error instead of remaining stuck on `Loading queue...` with zero counters when an error occurs.
- Adds the detected Oban column list to the internal API response for easier future schema diagnostics.


## Version 2.7.1

Pinchflat database path compatibility fix.

- Fixes `Pinchflat database is unavailable` in the v2.7 download dashboard.
- Uses `/pinchflat-config/db/pinchflat.db` for current Pinchflat installs.
- Falls back automatically to `/pinchflat-config/pinchflat.db` for older layouts.
- Still honours an explicit `PINCHFLAT_DB_PATH` environment variable when the configured file exists.
- Re-checks the database location on every read, so no clean reinstall is required.
- Updates the supplied Docker compose files to the current Pinchflat database location.
- The existing Pinchflat config mount remains unchanged.


## Version 2.7.0

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


## Version 2.6.5

Pinchflat log viewer fix.

- Fixes `name 'urlencode' is not defined` when loading Pinchflat Docker logs.
- Adds the missing `urlencode` import used to build the Docker logs API query string.
- Removes the `Check the Docker socket mount and Pinchflat container name.` footer from the log viewer.
- The real Docker or Pinchflat error remains displayed inside the log box if log retrieval genuinely fails.


## Version 2.6.4

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


## Version 2.6.3

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


## Version 2.6.2

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


## Version 2.6.1

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

## Version 2.6.0

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

## Version 2.5.1

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

## Version 2.5.0

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

## Version 2.4.0

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

## Version 2.3.4

Random Shorts empty-player regression fix.

- Fixes the black Random Shorts panel introduced after personalised Discover searches were added.
- Personalised Shorts searches previously used subscribed channel names too narrowly. Because Discover excludes channels you already subscribe to, a valid search could be filtered down to zero videos.
- Shorts searches now keep the user's personal interest seeds and add a broader English interest branch in the same search.
- If YouTube still returns no suitable Shorts, the player now shows a clear `No Shorts found` message instead of an empty black rectangle.
- The Shorts player host is rebuilt safely when the YouTube iframe has been destroyed or replaced.
- If YouTube reports an individual Short as unplayable, the app automatically advances to another Short in the batch.
- The v2.3.3 YouTube Like CSRF fix remains included.
- The v2.3.2 popup layout and v2.3.1 embedded-player referrer fixes remain included.

## Version 2.3.3

YouTube Like CSRF fix.

- Fixes `Unexpected token '<' ... is not valid JSON` when pressing `Like on YouTube`.
- The Like button previously posted JSON without the application's required CSRF header.
- Flask rejected the request with an HTML 400 page before the YouTube Like endpoint ran.
- `Like on YouTube` now uses the existing CSRF-aware `apiPost()` helper.
- The fix applies to Random Videos, Random Shorts and the Latest from your subscriptions popup.
- No database migration or clean installation is required.

## Version 2.3.2

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

## Version 2.3.1

YouTube embedded-player identity fix.

- Fixes YouTube player `Error 153` in the Latest from your subscriptions popup.
- The app previously sent `Referrer-Policy: same-origin`, which stripped the HTTP Referer when the browser loaded `youtube-nocookie.com`.
- The global referrer policy is now `strict-origin-when-cross-origin`.
- The latest-video iframe explicitly uses `referrerpolicy="strict-origin-when-cross-origin"`.
- The embedded player URL includes both `origin` and `widget_referrer`.
- The Shorts player now also supplies `widget_referrer`.
- Privacy-enhanced `youtube-nocookie.com` playback remains enabled.
- No database migration or clean installation is required.

## Version 2.3.0

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

## Version 2.2.2

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

## Version 2.2.1

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

## Version 2.2.0

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

## Version 2.1.1

Random Shorts description display.

- Adds the YouTube Short description beside the embedded Shorts player.
- Uses the full description returned by the existing `videos.list` request, so no additional YouTube API request is required.
- Preserves description line breaks and links as text.
- Long descriptions use a compact scrollable panel so the Shorts popup stays within the screen.
- If a Short has no description, the panel displays `No description provided for this Short.`

## Version 2.1.0

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

## Version 2.0.2

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

## Version 2.0.1

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

## Version 2.0.0

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

## Version 1.9.4

Verification marker parsing fix.

- Fixes the false `Pinchflat direct deletion did not return verification markers` error.
- v1.9.3 successfully deleted the Pinchflat source, but the Python regex looked for a literal `\d` instead of digits.
- Valid output such as `MATCH_COUNT=1 REMAINING_COUNT=0` is now parsed correctly.
- The same correction is applied to `SOURCE_COUNT`.
- After a successful delete, the app now proceeds normally and shows `Not in Pinchflat` instead of leaving a false error.
- Direct deletion through the running Pinchflat release remains unchanged.
- Docker power control and explicit source authorisation remain unchanged.

## Version 1.9.3

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

## Version 1.9.2

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

## Version 1.9.1

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

## Version 1.9.0

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

## Version 1.8.8

Pinchflat source deletion transport fix.

- Fixes disabled sources remaining in Pinchflat after the app says `Removing from Pinchflat`.
- Uses Pinchflat's real HTTP `DELETE /sources/:id` route rather than replaying the HTML form with `POST + _method=delete`.
- Keeps Pinchflat's CSRF token and `delete_files` parameter when issuing the DELETE request.
- Prevents an in-progress source deletion from being immediately handled by Automatic Retry in the same sync.
- Source-authority and unsubscribe reconciliation continue checking deletion every five minutes.
- Once Pinchflat removes the source, the app clears the stored Pinchflat source link and shows `Not in Pinchflat`.

## Version 1.8.7

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

## Version 1.8.6

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

## Version 1.8.5

Canonical URL and fresh-install Google OAuth fix.

- `APP_URL` in Docker/ZimaOS YAML is authoritative when supplied.
- This deployment defaults to `https://youtube.ashjohn.uk`.
- Google OAuth therefore uses `https://youtube.ashjohn.uk/oauth/google/callback` even if the ZimaOS tile initially opens `http://butane.grovefarm:8787`.
- Adds `CANONICAL_REDIRECT=true`. Opening the local ZimaOS tile redirects the browser to `APP_URL`.
- `/health` remains local for ZimaOS and Docker checks.
- The Public dashboard URL field becomes read-only while YAML manages it.
- HTTPS canonical deployments use Secure session cookies.
- `APP_URL` and `CANONICAL_REDIRECT` are exposed in ZimaOS environment metadata.

For another server, edit `APP_URL` in the YAML before deployment.

## Version 1.8.4

YouTube subscription refresh accuracy fix.

- Fixes false-positive `YouTube subscription restored` activity entries.
- The refresh no longer marks every subscription inactive before processing the current YouTube list.
- A channel is treated as genuinely re-subscribed only when it was already inactive and has a recorded `removed_at` timestamp.
- Normal existing subscriptions remain active without generating restoration activity.
- Genuine unsubscribe then re-subscribe recovery remains unchanged, including stale Pinchflat source repair and cancellation of delayed cleanup jobs.

## Version 1.8.3

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

## Version 1.8.2

Re-subscribe recovery release.

- Channels which were previously removed can now be subscribed to again cleanly.
- Re-subscribing cancels any outstanding delayed file-cleanup job for that channel.
- The app checks whether the previously stored Pinchflat source ID still exists.
- A stale Pinchflat source ID is cleared automatically rather than producing `/sources/<id>/edit` 404 errors.
- The next full sync recreates a fresh Pinchflat source when the old source was deleted.
- The per-channel Retry button also detects a stale source ID and recreates the source immediately.
- Automatic retry has the same stale-source recovery behaviour.
- Re-subscribed channels follow the current New Subscription Behaviour setting.

## Version 1.8.1

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

## Version 1.8.0

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

## Version 1.7.1

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

## Version 1.7.0

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

## Version 1.6.0

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

## Version 1.5.2

Channel artwork update.

- Shows the YouTube channel image above the channel name in the subscriptions table.
- Stores the thumbnail URL returned by the YouTube subscriptions API.
- Uses the highest available subscription thumbnail.
- Existing installations gain the new database field automatically.
- If a channel has no image, or the remote image fails to load, the app uses its own built-in YouTube Pinchflat Sync icon.
- Channel names remain shortened in the table, while hovering shows the full name.
- Run Refresh YouTube once after upgrading to populate images for existing subscriptions.

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
