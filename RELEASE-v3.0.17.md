# YTSD 3.0.17

Adds read-only TV API version 1 for YTSD TV 0.1.0-beta.1.

- Paged completed-video catalogue and channel list, including YouTube and external one-time downloads.
- Existing account favourites, metadata, local artwork and external subtitle tracks.
- Existing session authentication, two-factor sign-in and authenticated media range streaming.
- No database migrations, download administration or changes to existing web and phone routes.
- TV playback progress and watched status live on the TV, separately for each server and account.

The TV app requires this server version. Older web and phone clients continue using their existing routes.

Upgrade the application files using your normal container build process. Preserve your current environment, Compose settings, data and media mounts. Build and recreate the container with the existing volumes. The release does not require a clean installation.

TV GET routes: /api/tv/session, /api/tv/library, /api/tv/channels, /api/tv/videos/<job_id>, /api/tv/artwork/<job_id>, /api/tv/subtitles/<job_id>/<index>.

The catalogue checks completed state, file existence, non-zero size, containment beneath the media root and supported video extensions. It omits AVI, audio-only profiles, temporary files and sidecars. Codec support still depends on the playback device. No transcoding is introduced.

Validation: automated TV API and existing-server regression tests accompany this release. See the TV release test report for client tests and physical-device checks.
