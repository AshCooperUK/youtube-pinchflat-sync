# YouTube Subscription Downloader v3.0.12

This release improves Guide navigation, channel selection and nested channel menus.

## Changes

- Show all active YouTube subscriptions in Guide, including channels without download monitoring, with favourites first.
- Add searchable Guide channel visibility switches, Show all / Hide all, and a separate programme-thumbnail background switch in Settings > Guide. Preserve the expected-upload prediction toggle. New subscriptions appear by default. Guide switches do not change downloads.
- Keep Guide browsing on the server catalogue. Hidden channels pause indexing, channel descriptions/images use a seven-day refresh cache, and recent-upload checks retain the daily schedule and API allowance.
- Fix channel action menus appearing behind modal channel/player views. Menus open in the active dialog and browser top layer, receive focus and return focus to their trigger when dismissed. Escape closes the menu before the channel dialog.
- Add hand cursors to Guide links and controls. Increase Guide avatars to 76px, matching featured-channel cards elsewhere in the app.
- Request browser fullscreen with navigation controls hidden. Restore the layout on fullscreen exit. Retain a labelled in-page fallback when fullscreen is unavailable.
- Support horizontal trackpad scrolling, Shift+wheel, touch swipes and focused-grid arrow keys. Day moves by one hour, Week by one day and Month by one calendar month. Preserve vertical channel scrolling.
- Move Previous/Next into full-height rails beside the listings. Keep Today beside the date, add short transitions and honour reduced-motion preferences.
- Hide Minimise on the standalone Guide page while retaining the dashboard tile control.

## Upgrade from v3.0.11

Extract the changed-files ZIP over v3.0.11 or use the full-source ZIP. Preserve deployment-specific YAML values and existing data/media mounts. Upload the extracted files with their folder structure, build the v3.0.12 image and recreate the container. The app creates the Guide visibility table automatically. Existing download settings and media paths stay unchanged.

All active subscriptions appear by default. Their saved uploads appear as indexing progresses. Open Settings > Guide to hide channels, switch predictions or thumbnail backgrounds, or adjust the existing metadata allowance and daily update time. Thumbnail backgrounds default off, and the existing prediction preference is preserved. Guide visibility settings apply to the installation, while favourite ordering follows the signed-in user.

## Navigation

Use the side rails, horizontal trackpad gestures or Shift+mouse-wheel. A leftward scroll moves earlier and a rightward scroll moves later. On touchscreens, swipe the timeline left to reveal later dates and right for earlier dates. Vertical scrolling continues to move through channels. Day advances by an hour, Week by a day and Month by a calendar month. The date picker and Today remain available.

Fullscreen uses the browser Fullscreen API with navigationUI set to hide. Supported desktop browsers hide their toolbars and the normal taskbar view. Browser/operating-system overlays, permissions and mobile support remain outside the app's control. Escape or Restore exits fullscreen. If the browser refuses the request, the app expands within the page and explains the fallback. See [browser fullscreen behaviour](https://developer.mozilla.org/en-US/docs/Web/API/Element/requestFullscreen).

## API usage

Guide page loads, timeline changes, predictions and the Guide video-info panel read SQLite and do not request YouTube Data API metadata. Existing player/channel detail popups still use their own detail-fetch behaviour. Thumbnails load from the saved image URLs. Background indexing uses channels, playlistItems and videos list requests, with channel/video batches where supported, checkpointed history and the existing daily cap. New channels need initial indexing and large libraries can take several days under a small allowance. No search.list calls are added. See [YouTube quota costs](https://developers.google.com/youtube/v3/determine_quota_cost).

## Validation

96 automated tests passed, including independent Guide visibility, download-setting preservation, new-channel defaults, cached reads, settings permissions and daily refresh caching. Browser checks cover nested menu focus, confirmation layering, fullscreen entry/exit, day/week/month movement, thumbnail settings, standalone/dashboard controls and mobile layout. Live YouTube account indexing and physical operating-system taskbar behaviour were not tested in this environment.
