# v3.0.16

- Remove the dashboard Errors tile and its display/order settings, including saved settings from earlier versions.
- Move error review to Settings > Diagnostics. Errors and warnings includes retained Activity history and failures stored against downloads, channels, scans, guide refreshes, sync, retention and cleanup jobs.
- Add paging for older errors and activity. Preserve video thumbnails and channel/player popup links where identifiers are available.
- Change + Add YouTube channel to Add to YTSD. Adding a channel enables download monitoring without subscribing the connected YouTube account. Existing active channels retain their download preference.
- Keep local channels through YouTube subscription refreshes. The separate Subscribe control still changes the YouTube account explicitly.

## Upgrade

Overlay the full ZIP, or use the changed-files ZIP over v3.0.15. Preserve deployment-specific YAML and environment values. Rebuild/publish the container and recreate it with the existing data and media mounts. Database changes are applied automatically.

Local channel lookup uses Google read access; adding locally does not require YouTube write access. New local channels use the configured default download range/profile.

Diagnostics can show retained records, not previously deleted logs. Current errors and their historical events can both appear. These changes do not clear stored failures.

## Validation

Automated regression tests cover local additions, refresh preservation, error aggregation and pagination. Browser checks cover the shared channel controls, popup focus, mobile add dialog and Diagnostics. Live Google account mutations and production downloads were not performed.
