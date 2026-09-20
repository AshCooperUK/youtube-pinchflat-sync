# YouTube Subscription Downloader v3.0.4

Based on GitHub `main` at `2938997827cdf38a1f1ffb8820888366912587f5` (v3.0.3).

## Download and metadata fixes

- Subtitle downloads no longer trigger a false FFmpeg status or replace the video's progress with a caption file's size. Finishing one media stream also does not claim FFmpeg has started. The actual postprocessor hooks report merging, embedding and conversion.
- Unavailable optional subtitles no longer stop the video download. Available tracks still download and embed. The dashboard and Activity log show which languages failed. Video download errors remain fatal and visible.
- Channel scans prepare `tvshow.nfo`, `fanart.jpg`, `poster.jpg` and `banner.jpg` before downloading videos, using the saved Media & Emby switches. Workers also prepare missing channel files when resuming queued work.
- Existing channel artwork is reused during later downloads. This removes the repeated network fetch and image generation after every video. Import / rescan explicitly refreshes artwork.
- Episode NFO files are written beside completed subscription media when Emby NFO is enabled. They contain the original title, channel, publication date and YouTube ID.
- Metadata writing has its own visible status. Latest Downloaded also shows the most recent failure, including its error, until a later completion or active processing job replaces it.
- Library imports exclude temporary media streams and conversion files.

## Channel folders and filenames

- New output uses Windows-compatible path components. Unicode letters and symbols remain supported. Invalid punctuation becomes a hyphen. Trailing spaces and dots are removed, reserved device names receive a prefix, and names have byte limits.
- The original titles remain in the app and metadata. Video filenames retain the YouTube ID with the standard templates.
- Subscription downloads use a saved directory selected from the subscription's channel identity. They no longer switch directories according to the video's uploader field. Different channels with conflicting names receive distinct folder names.
- Known existing channel folders with unsafe names are renamed and download records are updated. The repair preserves the contents, refuses destination conflicts, skips busy folders, and does not merge or overwrite another folder. A recorded literal DOS-style alias is renamed using the channel title.
- Folder repair also covers subtitle-only directories whose names match a known subscription. Unidentified aliases without a matching channel record or name need manual identification. Existing individual media filenames remain unchanged.

Samba's `mangled names` setting explains how Windows clients receive aliases such as `AAYEKP~7` for names containing illegal NTFS characters: <https://www.samba.org/samba/docs/current/man-html/smb.conf.5.html#MANGLEDNAMES>. The screenshot alone does not establish the original Linux folder name.

## Upgrade from v3.0.3

1. Extract the full ZIP or the smaller changed-files ZIP and upload the extracted files to GitHub, preserving the directory structure. Include the new `app/downloader_media.py` file and the changed `.github/workflows` files.
2. Wait for the image build, pull the updated image and recreate the container using the existing `/data` and `/downloads` mounts. Check the dashboard shows v3.0.4.
3. Once current downloads finish, open Settings → Downloader → Existing library → Import / rescan existing media. This imports completed media, repairs known channel folder names and rebuilds artwork and NFO files using your saved switches. The Activity log reports repair results.
4. Run a normal channel scan for GSH Electrical and Autoalex Cars to retry failed or missing videos. A forced re-download is unnecessary for files already recorded as complete.
5. Refresh the relevant Emby library after folder repair.

Download ranges and retention protection keep their existing behaviour. This release does not delete older media because its download range changes.

## Validation

All 24 regression tests passed with yt-dlp 2026.08.19. The suite reproduced the old subtitle-only failure with a local HTTP server returning HTTP 429 for one caption. The fixed worker downloaded the video, embedded the available caption through FFmpeg, and wrote JSON, episode NFO and channel artwork. Tests also cover folder repair, conflicts, active downloads, Unicode, reserved names, length limits, metadata reuse, video totals and temporary-file exclusion.

Chromium checks passed at 1600 px and 390 px: visible caption messages, visible failure details, correct metadata status, two-line error text, no horizontal overflow and no JavaScript errors. Python compilation, Jinja parsing, HTML ID checks and YAML parsing passed.

Live YouTube authentication, the NAS SMB share, Emby and the Docker image build were not available in the local test environment. GSH Electrical's original failure requires its historical download log for exact confirmation.

Run the regression suite with `python -m unittest discover -s tests -v` after installing application dependencies and FFmpeg.
