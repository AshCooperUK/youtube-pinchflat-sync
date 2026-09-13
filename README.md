# YouTube Pinchflat Sync

A Docker dashboard for ZimaOS which reads the subscriptions from your Google/YouTube account and manages matching Pinchflat sources.

## Version 1.4.0

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

## Google OAuth

For the current Ash setup:

`https://youtube.ashjohn.uk/oauth/google/callback`

The Google OAuth scope is:

`https://www.googleapis.com/auth/youtube.readonly`

## Storage paths

The supplied ZimaOS YAML uses:

- Sync data: `/media/NVME-Storage/AppData/youtube-pinchflat-sync/data`
- Pinchflat config: `/media/NVME-Storage/AppData/pinchflat`
- Pinchflat downloads: `/media/Storage/Media/YouTube`

Upgrades preserve the SQLite database and OAuth token when those paths remain unchanged.

## Publishing with GitHub Desktop

Extract a release ZIP over your local clone of:

`AshCooperUK/youtube-pinchflat-sync`

Then use GitHub Desktop:

1. Review the changed files.
2. Enter a summary such as `Release v1.4.0`.
3. Select `Commit to main`.
4. Select `Push origin`.
5. Wait for GitHub Actions to finish.

The included workflow publishes:

`ghcr.io/ashcooperuk/youtube-pinchflat-sync:latest`

and:

`ghcr.io/ashcooperuk/youtube-pinchflat-sync:1.4.0`

## ZimaOS

The ZimaOS compose definition is available at:

`compose.yaml`

and:

`Apps/YouTubePinchflatSync/docker-compose.yml`

The dashboard listens on port `8787`.

Pinchflat listens on port `8945`.
