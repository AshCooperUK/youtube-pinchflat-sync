# YTSD v3.0.13 — Guide playlist recovery

- Keep Guide refreshing other channels when one uploads playlist is missing or inaccessible. Cache the affected channel's error and retry it after 24 hours, refreshing its playlist metadata first.
- Recover invalid pagination tokens per channel with a ten-minute retry. Preserve account-wide quota and authentication backoffs.
- Display persistent channel errors and retry times in Guide rows and Settings > Guide, with an affected-channel summary below the timeline.
- Distinguish the actual retry time from the next daily scheduled refresh.
- Automatically clear legacy global playlist-error pauses during the database upgrade. Cached uploads and download preferences are preserved.

## Updating

Use the full-source ZIP, or overlay the changed-files ZIP onto v3.0.12. Preserve your deployment-specific YAML values and existing data/download mounts. Upload to GitHub, wait for the container build, then pull and recreate the container in ZimaOS. Restarting an existing container alone does not select a newer image.

The migration removes the old global playlist-error pause automatically. The background Guide worker resumes indexing. If YouTube still cannot supply a channel's uploads playlist, that channel gets a visible error and a 24-hour cooldown while other channels continue. Manual refresh respects cooldowns and API quota backoffs. No database reset or cache deletion is needed.

## Validation

101 automated tests passed, including five new regression tests for missing and inaccessible playlists, continued recent/backfill indexing, persistent cooldowns, repaired playlist IDs, quota/authentication backoff and legacy database migration. JavaScript syntax validation passed. Requests were simulated; live YouTube account behaviour was not tested.
