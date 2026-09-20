# YTSD v3.0.8

Subscriptions now sort from every column heading in both directions. The sort dropdown, remembered choice and Upload Guide stay aligned. Resolution and storage use numeric order, Cut-off uses date order, and Range follows the preset list. Save / Actions brings unsaved changes first. Favourites remain pinned when the existing dashboard preference is enabled.

Settings → Diagnostics → Activity opens video thumbnails and titles in the existing media player and channel names in the existing Channel view. Both the initial page and refreshed logs use the same popup behaviour. Channel context is recovered from local records where possible and saved with new events so completed, failed and one-time jobs retain their links.

The README starts installation with the Cloudflare domain and tunnel, then the public URL in YAML, Docker launch and Google OAuth. Setup images use generic values. CHANGELOG.md restores the available release notes from v1.1.0 onwards. The earliest archive contains no separate v1.0.0 notes.

## Upgrade

Upload the complete source ZIP, or overlay the changed-files ZIP on v3.0.7. Keep existing application data and media mounts. Check APP_URL in the YAML still matches your own public HTTPS hostname before recreating the container. The Activity database column is added automatically without removing old entries.

No live YouTube account or Emby server was used for validation. Automated fixtures exercise download and metadata regressions, Activity context, sorting, existing popup behaviour and responsive layout. Existing Upload Guide forecasts remain inactive pending the permission required by its handover.
