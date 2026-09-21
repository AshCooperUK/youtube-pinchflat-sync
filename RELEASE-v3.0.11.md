# YouTube Subscription Downloader v3.0.11

- Move Scan schedule from Downloader to Automation, preserving existing favourite/other intervals and legacy save URLs.
- Explain scheduled deep scans versus the manual YTSD Sync & Scan action and the separate recent-upload scan.
- Fix the native downloader scheduler job ID used when saving Automation intervals and displaying its next run. Previously, interval changes could silently fail to take effect until restart.
- Include all v3.0.10 fixes for guide layout, inline Favourites, provider metadata, Emby refresh and Shorts/force scanning.

## Upgrade

Extract the full-source ZIP, or overlay the changed-files ZIP on v3.0.9 or v3.0.10. Preserve application-data/media mounts and deployment-specific YAML values. Upload the extracted files with their folder structure, build the v3.0.11 container, and recreate it. Existing scan intervals are preserved. See RELEASE-v3.0.10.md for source metadata repair behaviour included in this release.

## Which scan runs?

- **Automation > Scan schedule:** staggered deep scans of enabled favourite/other channels, with separate intervals. Uses the same queue and download workers as a channel Force Scan. Respects download ranges, profiles, exclusions and scan suppression.
- **Automation > Recent upload scan:** checks recent uploads across enabled channels at its own interval.
- **YTSD icon:** refreshes YouTube subscriptions, reconciles/registers enabled channels, checks recent uploads, retries monitoring updates and checks the Emby Download playlist immediately. It is not identical to the deep-scan schedule.

No schedule requires an open dashboard. Deep scans are spread across the interval rather than all starting at once.

## Validation

90 existing regression tests and 3 Automation regression tests passed. Checks cover preserved intervals, legacy save routes, form placement and rescheduling the actual native job. Desktop/mobile browser checks cover the moved schedule and the v3.0.10 UI fixes. Live BBC and Emby access remain untested; provider transfers use local media and Emby responses are mocked.
