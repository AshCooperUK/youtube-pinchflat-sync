# v3.0.18

- Remove the deferred Android TV and LG webOS server integrations, pairing page and associated tests from the release.
- Keep Settings > Downloader > Watched, active cookie checks, automatic post-download marking, one-time bulk marking and Emby played matching.
- Publish Docker tags latest and 3.0.18.

## Upgrade from a mixed TV/webOS checkout

This is a complete source release. ZIP extraction over existing files does not remove obsolete files.

In your GitHub Desktop repository folder, replace the app and tests folders with the folders from this ZIP. These are source folders, not your Docker /data or /downloads volumes. Preserve any deployment data if you placed it inside your source checkout. Copy the remaining release files, including .github/workflows. Keep your existing .git folder and deployment-specific environment values and volume paths.

Remove the obsolete TV-only files README.txt, CHANGELOG.txt and TV-TEST-RESULTS.txt if present. This release replaces RELEASE-v3.0.18.md with these notes. No PowerShell helper is required.

Review the changes in GitHub Desktop, commit and push. Wait for Validate V3 and Build and publish Docker image to succeed. Then update the existing ZimaOS app using ghcr.io/ashcooperuk/youtube-subscription-downloader:3.0.18 and the same data and media mounts.

No database reset or media deletion is required. The package contains no APK, IPK, TV API modules or TV pairing page. Existing installed client apps are not uninstalled by a server upgrade.

For watched controls and Emby matching instructions, see RELEASE-v3.0.17.md.

## Validation

All 127 core regression tests passed locally. TV/webOS tests are removed with their deferred features. No live account mutations were performed. Docker publication and deployment happen after you push this release.
