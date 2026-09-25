# YTSD v3.0.15: channel subscription controls

- Add a top-centre Subscribe/Subscribed control beside the existing channel-image actions across subscription rows, channel/player popups and shared channel widgets.
- Add an explicit unsubscribe dialog with choices to keep files, delete subscription files, remove the YTSD channel record while retaining files, or remove the record and subscription media together. These choices override the automatic unsubscribe policy. Separate one-time downloads remain unchanged.
- Add a plus button beside the Subscriptions tile minimise control. Accept YouTube channel URLs, @handles and channel IDs, with targeted API calls rather than a full subscription refresh.
- Restore explicitly re-added channels even when an earlier local removal suppressed them. Cancel pending cleanup on re-subscribe and honour the new-channel download policy.
- Keep the new controls administrator-only, require Google write access and CSRF protection, and retain foreground focus for nested popup choices.

## Using the controls

The red tick at the top centre of a channel image means subscribed. Select it to choose an unsubscribe action. A plus in the same position subscribes the channel. The existing green tick still controls download monitoring independently.

All four choices unsubscribe from YouTube and stop new subscription monitoring. The choices state whether they keep or delete the local channel record and subscription files. Confirm selected action applies the selected option. Closing the dialog makes no changes. Removing only a local YTSD record without unsubscribing remains available through the existing trash menu.

Media removal targets the resolved subscription folder, including its artwork and sidecar files. Separate one-time downloads remain unchanged. If a download is active for that channel, file removal asks you to wait until it finishes. Pending subscription jobs are cancelled when the removal succeeds. Job claiming and removal share a lock so a queued worker cannot start writing during deletion.

The tile's plus button accepts https://www.youtube.com/@handle, @handle, /channel/ URLs, /user/ URLs and UC channel IDs. For old /c/ vanity links, use the channel's current @handle instead. Newly added channels follow the configured new-channel download policy. Adding reloads the dashboard so the new row appears immediately. Your current search/status filter still applies.

## Updating

Overlay the changed-files ZIP onto v3.0.14, or use the full-source ZIP. Preserve your deployment-specific YAML settings and data/download mounts. Upload to GitHub, wait for the container build, then pull and recreate the app container.

## Validation

110 automated tests passed, including removal outcomes, file preservation, active-download protection, failed API calls, invalid URLs, read-only access, duplicate subscriptions and restoring suppressed records. Live YouTube subscription changes were simulated.

Browser checks passed for subscribed/unsubscribed state, the selected removal payload, nested popup focus and stacking, shared avatar controls, and mobile channel addition with error recovery.
