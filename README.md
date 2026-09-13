# YouTube Pinchflat Sync

Version 1.2.0 adds per-source Pinchflat download cutoffs.

## v1.2.0 changes

- Each YouTube subscription has its own download-range dropdown.
- Choices include Default, Today, This week, This month, Last 6 months, Last year, 2 to 10 years, original subscription date and a custom date.
- A source row shows the exact Pinchflat cutoff date before it is added.
- `Refresh YouTube subscriptions` discovers subscriptions without adding them to Pinchflat. This gives you time to choose per-source ranges.
- `Add pending to Pinchflat` creates pending sources using their individual ranges.
- `Full sync now` retains the original automatic behaviour.
- The scheduled sync still runs every `SYNC_INTERVAL_MINUTES`.
- The OAuth configuration section is hidden after Google connects. Disconnect Google to show it again.
- Existing v1.1 SQLite databases are upgraded automatically.

## Important behaviour

Per-source ranges are applied when the sync service creates a Pinchflat source.

For sources created by v1.2.0, the app stores the Pinchflat source ID. Changing the dropdown later also updates the existing Pinchflat download cutoff through Pinchflat's edit form.

Older sources without a stored source ID keep their existing Pinchflat cutoff until changed directly in Pinchflat.

## Recommended first-use flow

1. Connect Google.
2. Select `Refresh YouTube subscriptions`.
3. Choose a range for any channels which need an override.
4. Select `Add pending to Pinchflat`.

Channels left on `Default` use the dashboard's default download history.

## Google OAuth

For the existing deployment:

`https://youtube.ashjohn.uk/oauth/google/callback`

## Container

`ghcr.io/ashcooperuk/youtube-pinchflat-sync:latest`
