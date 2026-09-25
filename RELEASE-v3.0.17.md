# v3.0.17

- Move watched controls from Diagnostics to Settings > Downloader > Watched. Keep request history and errors in Diagnostics Activity.
- Verify a signed-in YouTube session before enabling automatic marking and before each watched request. Detect expired cookies locally, display session warnings and pause waiting requests when authentication cannot be confirmed.
- Add a Check cookie session button. New cookie files clear stale session results. A valid file alone does not establish an active session.
- Add a confirmed one-time batch to mark all eligible downloaded YouTube videos as watched. Skip duplicate video IDs, missing files, non-YouTube downloads and requests already queued or sent.
- Add an Emby user selector and actions to match one selected video or all Emby-played downloads. Match by YouTube provider ID or the ID in the filename, never by title. Do not change Emby played flags or remove YouTube watch history.
- Add cancellation for waiting bulk and Emby requests. Preserve completed downloads when watched requests fail.
- Restore stable Docker publication to latest and 3.0.17.

## Install

Upload the full source ZIP, or overlay the changed-files ZIP onto v3.0.17-beta.1. Preserve deployment-specific paths and environment values. Include the updated .github/workflows files. Push to main, or manually run the publication workflow on the branch containing these files.

This release publishes both `ghcr.io/ashcooperuk/youtube-subscription-downloader:latest` and `ghcr.io/ashcooperuk/youtube-subscription-downloader:3.0.17`. Change the existing ZimaOS app image from the beta tag to either of these, then pull and recreate the container with the same mounts. Check the displayed app version.

## Watched controls

Open Settings > Downloader > Watched. The beta's automatic preference and request history carry forward. A new installation starts with automatic marking off.

Upload signed-in YouTube cookies in the Downloader cookie section, then press Check cookie session. Only an explicit signed-in response from YouTube counts as active. Expired, rejected or unverified sessions display a message in Watched. Queued requests pause until a fresh cookie upload or successful session check. A request which already failed does not retry automatically.

Automatic marking applies after future successful YouTube downloads and media processing. It does not wait for local playback. Turning it off cancels waiting automatic requests. A running request will finish. Google OAuth access does not replace the cookie session.

The account in the cookies receives the history updates, even if the Google OAuth account differs. Request sent reports the request outcome, not independently verified YouTube history.

## One-time marking

Choose a downloaded video for an individual request, or press Mark all downloaded videos as watched. Confirm the displayed count to queue the one-time batch. Bulk selection covers all eligible completed files, not just the 500 most recent downloads shown in the individual selector. Includes YouTube one-time downloads. Skips duplicate video IDs and requests already queued or sent.

Requests run sequentially in the background. Leave YTSD running. Large libraries take time because each request checks the cookie session first. Cancel waiting bulk requests stops waiting bulk/Emby requests but does not undo history or stop a request already running.

## Match Emby played status

Configure the existing Emby server URL and API key under Settings > Emby. Under Downloader > Watched, press Load Emby users and explicitly choose whose played status to use.

Use Match selected video with Emby for the selected download, or Match all Emby-played videos for a one-time scan. Review and confirm the count before queueing. The app reads all pages of Emby's played-video results and checks each video's Played flag. A timeout or failed lookup queues no partial result.

Matching requires a YouTube provider ID or a filename ending in [YouTube video ID] before the extension. This works across different Docker mount roots. Titles alone never count as matches. Downloads with custom filenames and no YouTube provider ID will not match.

Only downloaded YouTube files marked played by the chosen Emby user qualify. This is one-way marking on YouTube, not a two-way watched/unwatched sync. It does not update Emby or remove watch history. Automatic post-download marking is independent: keep it off if you only want Emby-played videos marked.

## Validation

127 offline regression tests passed, including cookie expiry, explicit session verification, batch deduplication/cancellation, Emby pagination and played-only matching. Desktop/mobile browser checks cover the moved controls, session messages, manual/bulk actions and Emby matching with fixtures. No live account mutations occurred during development. The preceding beta's watched requests were confirmed by the user against their YouTube account; the new checks and Emby integration still need validation on the deployed services.
