# YouTube Subscription Downloader v3.0.10

This release fixes the Upload Guide Day layout, Discover navigation, one-time source metadata and channel scan behaviour.

## Changes

- Fix clipped Upload Guide Day cards. Programme titles, info/play controls and durations stay inside each card at desktop and mobile sizes. Keep the release-time bars and match the Week/Month card styling.
- Centre the Single Download icon in Latest Downloaded.
- Show Favourite Channels and Favourite Videos inside the existing Discover popup. Keep the shared channel and video popups for individual entries.
- Hide YouTube-only actions on downloaded videos from other providers. Show their programme/provider name without a disabled YouTube channel button or an invented view count.
- Save source descriptions, programme titles, season/episode numbers, durations, thumbnails and release dates for one-time downloads. Use these saved details in the existing media player without a YouTube lookup.
- Write provider-aware movie or episode NFOs. Recognised TV episodes use their real programme name, season and episode number. BBC combined titles have a specific fallback when the extractor omits separate episode fields.
- Organise recognised one-time TV episodes under Programme/Season N with SxxExx filenames when the default output template is selected. Keep custom output templates in use.
- Repair existing registered non-YouTube downloads automatically from saved local metadata. Keep video bytes, subtitles and watched/rating NFO fields. Refuse destination collisions and report each result in Activity. Add Repair one-time metadata in Settings > Downloader for a manual retry.
- Fix targeted Emby library detection for separate one-time libraries and new folders under mapped library roots. Notify Emby after completion without waiting for a full filesystem inventory.
- Make Force Scan check recent uploads before deep history and artwork preparation. Eligible jobs enter the worker queue immediately. Log the scan result and exclusions with video thumbnails and links.
- Identify Shorts through YouTube channel-tab membership, including watch URLs with no Shorts flag. Cache the result locally and recheck exclusions before media transfer. Defer unverified entries instead of downloading an unknown type. Keep short regular videos eligible.
- Use the configured timezone for download cutoffs and exact publication times. Keep scanner and download workers running after an individual job error. Report suppressed scans instead of claiming they started.

## Upgrade from v3.0.9

1. Extract the changed-files ZIP over v3.0.9, or use the full-source ZIP. Preserve the existing application-data and media mounts and your deployment-specific YAML values.
2. Upload the extracted source to GitHub with its folder structure, including `.github/workflows` and the new `app/source_metadata.py`. Allow the container workflow to build v3.0.10, then pull and recreate the container.
3. Database columns and the video-type cache are created automatically. Existing registered non-YouTube one-time downloads are checked for saved `.info.json` metadata at startup. Progress appears in Settings > Diagnostics > Activity.

## Existing BBC and other one-time downloads

The repair reads the original source sidecar. It restores the programme/episode information, plot, duration and release date. If a recognised TV episode uses the default output template, its media and matching sidecars move into `Single Downloads/Programme/Season N/SxxExx - Title [id] [source-id].ext`. The database path changes with the move. Video content is not re-encoded or downloaded again. Existing destination files are never overwritten. Custom output templates keep their current paths.

NFO writing follows the Single Download NFO setting. Existing watched state, ratings and unrelated NFO fields are preserved. A targeted Emby scan and metadata refresh follow a successful repair. Use Settings > Downloader > Repair one-time metadata to retry. Missing source sidecars or source metadata are reported in Activity; unavailable episode details are not invented.

New standalone videos receive a movie NFO beside the file. Recognised episodes receive an episode NFO and programme `tvshow.nfo`. Their original source dates remain separate from the local download date. Emby TV libraries should include the folder containing the programme folders, following [Emby's TV naming guidance](https://emby.media/support/articles/TV-Naming.html).

## Force Scan and Shorts

Force Scan starts a background channel scan and checks recent uploads first. Eligible jobs are passed to the existing download workers as soon as they are found, without waiting for deep history to finish or requiring YTSD refresh. Waiting scans and active transfers retain their existing dashboard indicators. Activity records the result, excluded videos and failures.

RSS and individual video metadata do not always identify Shorts. YTSD checks membership of the channel's Videos, Shorts and Streams tabs through yt-dlp and caches each type for up to 30 days. These checks do not use YouTube Data API quota. A short runtime alone does not make a video a Short. An unverified type is deferred or skipped with an Activity reason and is checked again by a later scan. Explicit one-time downloads continue to honour the requested URL independently of subscription filters.

## Validation

90 automated regression tests passed. Coverage includes a real local HTTP transfer through yt-dlp using BBC-shaped extractor metadata, provider NFO creation, metadata repair and collision handling, original media-byte preservation, playback metadata, authenticated media access, Emby library selection and completion notification, scan dispatch, Shorts rejection before transfer, and timezone boundaries.

Browser checks passed for desktop and mobile layouts, Day controls, the centred download icon, inline Favourites, non-YouTube actions, provider details in the player, existing channel/video popups, guide maximise/minimise and tablet navigation. Previous subscription sorting and Activity checks are retained in the automated suite.

BBC service access and a live Emby server were not available in this test environment. The provider transfer used a local test video, and Emby responses were mocked. The source website and installed yt-dlp extractor still determine available metadata and download access.
