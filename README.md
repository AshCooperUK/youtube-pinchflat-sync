# YouTube Pinchflat Sync

A Docker dashboard for ZimaOS which reads your YouTube subscriptions, creates and manages Pinchflat sources, and adds direct-download automation for an Emby YouTube library.

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
