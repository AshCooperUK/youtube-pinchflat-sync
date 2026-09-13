# YouTube Pinchflat Sync

## Version 1.3.1

This maintenance release fixes editing existing Pinchflat sources:

- The app now selects Pinchflat's actual Source edit form.
- It ignores the global `/search` form on Pinchflat pages.
- Per-source download-range changes now post back to the Source route.
- Per-source Enabled/Disabled changes use the same corrected edit form.
- Pinchflat HTTP 500 update errors now show the target route for easier diagnosis.

## Version 1.3.0

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

## Recommended first-use flow

1. Connect Google.
2. Refresh YouTube subscriptions.
3. Tick the channels you want and select `Enable selected`.
4. Choose any per-source download ranges.
5. Select `Add pending to Pinchflat`.

Channels you do not enable are still added to Pinchflat with media downloading disabled.

Version 1.2.1 improves Pinchflat setup detection and onboarding handling.

## v1.2.1 changes

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

## Important behaviour

Per-source ranges are applied when the sync service creates a Pinchflat source.

For sources created by v1.2.1, the app stores the Pinchflat source ID. Changing the dropdown later also updates the existing Pinchflat download cutoff through Pinchflat's edit form.

Older sources without a stored source ID keep their existing Pinchflat cutoff until changed directly in Pinchflat.

## Google OAuth

For the existing deployment:

`https://youtube.ashjohn.uk/oauth/google/callback`

## Container

`ghcr.io/ashcooperuk/youtube-pinchflat-sync:latest`
