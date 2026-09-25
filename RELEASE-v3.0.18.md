# YTSD 3.0.18

Adds read-only LG webOS TV support and reconciles the two earlier 3.0.17 builds.

The v3.0.17 upload replaced the watched-status implementation from 3.0.17-beta.1
while leaving its regression tests. This release restores the matching main
application code, background queue and dashboard controls from commit 62753b0.
The experimental automatic watched request remains opt-in and separate from TV
playback. Existing download completion remains authoritative.

The webOS app uses browser-approved TV codes through `/tv-link`. The existing
website login and two-factor flow authorise read-only TV credentials. The new
`/api/webos` namespace accepts TV bearer credentials, with per-file signed URLs
for native media playback, artwork and subtitles. Access checks include account
status, session version, device expiry and explicit revocation. Native seeking
uses the existing conditional file-serving behaviour. SRT sidecars convert to
WebVTT for the TV's native subtitle player.

New pairing/device tables are created automatically in the existing database.
Existing web, phone and Android TV routes retain their authentication behaviour.
No TV watch history sync is added. Playback progress stays on each client.

Preserve your current environment, Compose files and volume mounts. Rebuild the
image with the complete application directory. The changed-files package leaves
deployment configuration out. The full source package provides generic examples.

Validation: 136 server tests passed, including all watched-status and TV tests.
Physical LG installation, decoding and remote controls need hardware testing.
