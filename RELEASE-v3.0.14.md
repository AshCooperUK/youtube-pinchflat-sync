# YTSD v3.0.14: sort channels by latest downloaded episode

- Add Latest download: newest first and oldest first to the subscription filter popup.
- Sort channels using the latest successful video download still present on disk. Ignore queued, processing, failed and cancelled jobs, audio-only files, sidecars and missing files. Channels without dated downloads appear last within each favourites group.
- Preserve the saved sort preference and favourites-first setting. Refresh channel ordering from the existing dashboard download-status poll.
- Apply the same download-date sort in Upload Guide without additional YouTube API requests.

## Using the new options

Open the Subscriptions filter popup, then choose either Latest download: newest first or Latest download: oldest first under Sort results by. Both compare each channel's most recent completed download, using its download completion date rather than its YouTube publication date. Equal dates sort by channel name, then channel ID.

The favourites-first preference still takes priority. Disable Keep favourite channels at the top in Settings if you want one date order across all channels. Channels without a dated video download appear last in each group. Existing media imports use the completion timestamp recorded during import. Files without a known completion date remain undated.

The existing dashboard status poll refreshes the timestamps and reorders rows when this sort is selected. If the relevant dashboard polling tiles are disabled, reload the page to update the dates. Removing the latest video falls back to the channel's next most recent remaining video.

## Updating

Overlay the changed-files ZIP onto v3.0.13, or use the full-source ZIP. Preserve your deployment-specific YAML values and existing data/download mounts. Upload to GitHub, wait for the container build, then pull and recreate the app container.

## Validation

105 automated tests passed. New tests cover completed-file eligibility, removed-file fallback, missing dates, timezone ordering, channel identity, both sort directions, stable ties, browser/Guide sort parity and timestamp delivery through the dashboard and API. No live YouTube API calls are required for this feature.

Browser checks passed for both directions, saved selection after reload, live timestamp updates and the mobile filter popup. No JavaScript errors occurred.
