# YouTube Subscription Downloader v3.0.5

Includes the v3.0.4 fixes. The full package and cumulative changed-files package both upgrade GitHub v3.0.3 at `2938997827cdf38a1f1ffb8820888366912587f5`, or the previously supplied v3.0.4 package.

## Shorts and download results

- Subscription filtering uses yt-dlp's YouTube `media_type` classification as well as explicit Shorts URLs. Shorts arriving through ordinary `/watch?v=` links are excluded when the Shorts switch is off. Normal videos are not excluded merely because they are short in length.
- The filter runs before video and subtitle transfers, including for jobs queued before the upgrade. An already running transfer is not interrupted by changing the switch.
- Excluded jobs are recorded as **Skipped**, with the reason visible in Current Downloads. They are not repeatedly queued while the relevant switch remains off. Turning Shorts back on makes those videos eligible on a later scan, subject to the selected download range. The same behaviour applies to excluded livestreams.
- Explicit one-time downloads retain their own settings.
- Expert JSON cannot override the managed media filter or hide job failures with `ignoreerrors`.
- Current Downloads shows the first five waiting jobs and provides the existing queue button for the full list. A collapsible Recent results list shows up to eight completions, failures, skips or cancellations from the last 24 hours. Imported historical media does not fill this list.
- Sync banners now say how many jobs were **added during that scan**, and report the state of those specific jobs at scan completion. A job may already have completed, failed or been skipped by the time the page reloads. The live active/waiting counts continue to come from the download database.
- Failures from newly added jobs count towards the sync error total. A sync with errors no longer displays a green success banner. Routine sync no longer erases video errors and reports them as successful source repairs.

## Existing library import

- Settings → Downloader → Import / rescan existing media enables matched current subscriptions after importing. This also covers files already in the database and repeated imports.
- Matching uses available channel IDs, channel NFO, saved channel folders and unambiguous channel names. Conflicting names or an unknown explicit channel ID do not enable another channel by mistake. Existing subscriptions are matched locally; the import does not subscribe to channels on YouTube or restore removed subscriptions.
- Existing download ranges, media profiles and retention settings are preserved. Newly enabled channels participate in subsequent scheduled or manual scans.
- Automatic startup inventory checks do not re-enable channels the user has disabled. Subtitle/artwork files alone do not count as imported media.
- The import completion banner states how many channels were enabled. Channel artwork and NFO repair continues in the background; its results appear in Activity.

## Subscription search and sorting

- Search covers Channel, Range, Media Profile, Cutoff, Disk usage and Error. For example, `720`, `this month`, `7.2 GB` and `private` match their respective columns. Multiple search words may match across columns.
- Only the selected range and profile are searched, rather than every option in their dropdowns. The search also works for viewer accounts.
- Media Profile sorting groups 720p, 1080p, 4K and audio profiles in that order, with channel names breaking ties. The existing favourite pinning preference still applies.
- Search, status filter and sorting remain saved in the browser.

## Upgrade

1. Extract either ZIP and upload the extracted files to GitHub, preserving their folders. Include `app/downloader_media.py`, the tests and `.github/workflows` updates. Do not upload the ZIP as a replacement for the source files.
2. Let GitHub build the image, then pull it and recreate the container with the existing `/data` and `/downloads` mounts. Check the dashboard shows **v3.0.5**.
3. Run **Import / rescan existing media** to enable matched channels and repair their artwork/NFO using the saved Media & Emby switches. Folder repairs wait for active channel downloads to finish.
4. Run **YTSD Sync & Scan**. Watch Current Downloads for waiting jobs and recent outcomes. Shorts already downloaded by an older release are left in place.

The package includes v3.0.4's optional subtitle failure handling, accurate FFmpeg/metadata phases, early channel artwork, episode NFO, portable Unicode filenames and channel folder repair. See [v3.0.4 details](RELEASE-v3.0.4.md).

## Validation

All 33 Python regression tests passed with yt-dlp 2026.08.19 and real FFmpeg. New coverage includes the real yt-dlp processing path rejecting a watch-link Short before any transfer, exclusion/re-enable behaviour, manual and automatic import behaviour, existing-file matching, ambiguous channel names and scan outcomes for jobs that already finished or failed. Earlier metadata, filesystem and caption-failure regressions also pass.

Chromium checks passed at 1600 px and 390 px: all six searchable columns, selected-profile matching, read-only cells, profile ordering, saved filters, waiting jobs and recent result reasons. No JavaScript errors or page-width overflow were found. Python compilation, Jinja parsing, duplicate HTML ID checks and YAML parsing passed.

Live YouTube downloads, the NAS share and Emby were not available locally. Docker image build and Compose validation remain in the GitHub Actions workflow. The screenshots cannot establish the exact historical outcome of the two jobs on the user's server; the new messages and results list make subsequent outcomes visible.
