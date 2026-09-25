# v3.0.17-beta.1

Experimental YouTube watched-status requests. This release does not confirm changes to account history. Verify the result in YouTube after a single-video test.

## Changes

- Add an administrator-only YouTube watched-status test under Settings > Diagnostics, using an existing completed YouTube download and the saved cookie account.
- Add an automatic post-download option, switched off by default. Queue requests only after successful media processing. Imports and non-YouTube downloads do not trigger requests.
- Persist requests separately from downloads, with duplicate suppression, a 90-second timeout and no automatic retries. Disabling automation cancels waiting automatic requests. Interrupted requests remain unverified after restart.
- Report sent, failed or unverified request results without claiming YouTube stored 100% watched progress. Preserve download success when watched requests fail.
- Use a private temporary cookie copy and keep raw extractor output out of Activity. Retain video/channel links in Activity.
- Publish only the 3.0.17-beta.1 container tag. The beta workflow does not replace latest. Supplied deployment YAML selects the beta tag.

## Install the beta

1. Upload the full source ZIP to your repository, or overlay the changed-files ZIP onto v3.0.16. Preserve your deployment-specific paths and environment values.
2. Let the container publication workflow finish. This workflow publishes only `ghcr.io/ashcooperuk/youtube-subscription-downloader:3.0.17-beta.1`.
3. In ZimaOS, edit the existing app image to `ghcr.io/ashcooperuk/youtube-subscription-downloader:3.0.17-beta.1`, then pull and recreate the container using the existing data and downloads mounts. An update of `latest` will not install this beta.
4. Check the displayed app version is `3.0.17-beta.1`. The database migration adds a separate request table. Existing download records and media remain unchanged.

## One-video test

1. Keep the automatic watched option off.
2. Use saved signed-in YouTube cookies under Settings > Downloader. The cookie account receives the request, which might differ from the Google OAuth account. Google OAuth credentials alone do not authorise this feature.
3. Open Settings > Diagnostics > YouTube watched status.
4. Choose a completed video from the selector. This lists eligible files within the latest 500 completed downloads.
5. Press Send test request once. The worker checks the queue every five seconds and allows at most 90 seconds per attempt.
6. Read the result below the selector. Request sent means yt-dlp reported a fully-watched request without an error. Completion remains unverified. Failed or unverified attempts do not retry automatically.
7. Open YouTube using the cookie account, refresh watch history and inspect the video's watched progress. Check the area where you normally see unwatched videos too. YouTube controls its own recommendations and filtering.
8. If the account result meets your needs, enable Mark as watched on YouTube after successful download. This applies only to future successful downloads and does not process the existing library.

Use All activity in Diagnostics for queued/sent records. Errors and warnings includes failed/unverified attempts. Video entries retain thumbnails and popup links where available. The results panel shows the latest 20 requests.

The request uses yt-dlp simulation. It does not download another copy or launch a background player. Raw output and cookies are not stored in Activity. This beta uses fixed yt-dlp request options rather than custom download options.

## Turn off or roll back

Switch off the automatic option to cancel waiting automatic requests. Manual requests remain queued and any running request will finish. Changing this setting does not undo YouTube history changes.

To return to the stable server, set the existing container image to `ghcr.io/ashcooperuk/youtube-subscription-downloader:3.0.16`, pull and recreate it with the same mounts. The added table is compatible with the previous release. Restore the v3.0.16 publication workflow when returning the repository to stable development.

## Validation

118 offline regression tests passed. Coverage includes permission/CSRF checks, eligibility, missing cookies, deduplication, opt-in, cancellation, subprocess timeout, result classification and separation from download status. Browser checks cover desktop/mobile controls and manual queuing. No requests were sent to a real YouTube account during validation. The account-side outcome requires your test.
