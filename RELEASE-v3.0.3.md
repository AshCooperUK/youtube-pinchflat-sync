# YouTube Subscription Downloader v3.0.3

Based on GitHub `main` at `2f391048b935a2170933486bb28f853bac4d506e` (v3.0.2).

## Fixes

- Restores the missing `_v3_subscription_info_date` function. In v3.0.2, this caused a downloaded video to enter the failed state before completion and channel metadata were recorded.
- Keeps jobs visible during merging, embedding and FFmpeg compatibility conversion. Latest Downloaded now shows the processing job, its current phase and progress. The completed-video count increases after processing finishes.
- Makes Discover → Downloaded use the native download database. A second, older function had overridden the native reader and still requested the removed Pinchflat database.
- Resolves final output files using the exact YouTube ID. The old bracketed glob matched unrelated filenames. Sidecars and temporary stream files no longer qualify as final media.
- Writes subscription artwork at the channel root. `fanart.jpg` and `poster.jpg` use the channel avatar, with the channel banner as fallback. `banner.jpg` uses the banner, with the avatar as fallback. The full avatar remains visible in fanart and poster images. Subscription artwork never falls back to a video thumbnail.
- A failed banner request no longer prevents avatar artwork from being written. Saved subscription avatars provide a fallback when channel metadata is unavailable. `tvshow.nfo` follows the Emby NFO setting.
- Applies media switches to the native yt-dlp configuration without overriding the chosen values. Embedding and SponsorBlock now install the required Python API postprocessors. Compatibility conversion preserves subtitle tracks, chapter metadata and attached cover art.
- Counts unique completed video files still present on disk. The Downloads tile and its displayed video size exclude audio files, JSON, NFO, images, subtitles, incomplete transfers and temporary conversion files. Other storage views still report their existing total disk usage.

## Interface changes

- Smaller summary cards with responsive column widths.
- YouTube refresh logo below the Google Cloud link in the Google card.
- YTSD Sync & Scan icon in the Downloader card. Both actions retain administrator access and CSRF protection.
- Current Downloads replaces Subscription Downloads. Closing the One-time Download popup returns its active job to Current Downloads. Reopening the popup resumes status polling.
- Discover → Latest Subscriptions shows recent videos and Shorts from subscribed channels.
- The homepage subscription feed starts disabled. This preference changes once during the upgrade. Re-enabling the homepage feed in Dashboard settings remains supported and persists across restarts.
- Compact Media & Emby switches. Subtitle languages appear above SponsorBlock, followed by switches for the SponsorBlock categories.

## Apply this release

1. Extract either ZIP. Upload the extracted files to the repository, retaining their relative paths. Include `.github/workflows` when uploading the full release.
2. Let the container workflow publish v3.0.3. Pull the updated image and recreate the application container, retaining the existing `/data` and `/downloads` mounts.
3. Check the dashboard shows v3.0.3.
4. Open Settings → Downloader → Existing library → Import / rescan existing media. This imports older files missed by the completion fault and rebuilds channel artwork and NFO using the saved media settings. Artwork repair runs in the background. The Activity panel records completion and any channel-specific errors.
5. Refresh the relevant Emby library after artwork repair completes.

The full ZIP contains the complete source. The changed-files ZIP applies to the v3.0.2 commit above. Neither package contains a user database, OAuth tokens, cookies, media downloads or compiled Python caches. Existing container paths and account settings remain in use.

## Validation

All 11 regression tests passed. They cover the download-to-processing-to-completed hand-off, the missing date function through the real worker path, native Discover responses, video-only totals and sizes, duplicate paths, absent files, temporary files, exact video-ID matching, artwork fallbacks, saved settings, feed migration and real FFmpeg conversion to H.264/AAC with subtitle preservation. Chromium checks passed at 1600 px and 390 px: 152 px desktop summary cards, both Discover tabs, all 16 switches, settings persistence, popup-to-dashboard progress transfer, no horizontal mobile overflow and no JavaScript errors. Browser checks use a local fixture rather than a connected YouTube or Emby account. Live account downloading and the Docker image build require the deployment environment.

Run the backend regression suite with:

```bash
python -m unittest discover -s tests -v
```
