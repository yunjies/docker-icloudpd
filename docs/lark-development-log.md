# Lark Integration Development Log

## Summary

This branch adds Feishu/Lark notification support and Feishu/Lark DM remote control to the Docker wrapper layer. It does not modify the upstream `icloudpd` Python package.

The implementation is split into two small Python helpers:

- `lark_send.py`: sends Lark text messages through the Lark OpenAPI.
- `lark_control.py`: receives Lark event callbacks and translates valid DM commands into the existing `sync-icloud.sh` remote-control flow.

## Implemented Behavior

### Notifications

`notification_type=lark` is supported by `sync-icloud.sh`.

Required config:

```ini
notification_type=lark
lark_app_id=
lark_app_secret=
lark_receive_id=
lark_receive_id_type=open_id
```

The sender caches `tenant_access_token` under `/tmp/icloudpd/lark_tenant_access_token.json`.

### Remote Control

`lark_control_enabled=true` starts an HTTP event receiver from `launcher.sh`.

Default endpoint:

```text
0.0.0.0:8088/lark/events
```

Supported commands match the existing Telegram behavior:

```text
<user>          # immediate sync, ignored with a reply if sync is already running
<user> auth     # remote re-authentication
<user> 123456   # MFA code
<user> a        # SMS device option
```

The receiver validates `lark_verification_token`, supports Lark `im.message.receive_v1`, and ignores non-control messages.

### User Feedback

The Lark controller replies directly to DM commands:

- accepted control commands
- unknown command formats
- ignored sync requests when iCloudPD is already syncing

This avoids silent failures from the user's perspective.

## NAS Deployment Notes

The working Unraid compose project is:

```text
/boot/config/plugins/compose.manager/projects/iCloud/docker-compose.yml
```

Current published callback mapping:

```text
public/OpenWrt -> 192.168.1.217:18088 -> container:8088
```

The external Lark callback URL should route to:

```text
/lark/events
```

The container image used during validation:

```text
yunjies/icloudpd:lark
```

The local NAS build directory used during development:

```text
/mnt/user/appdata/codex-build/docker-icloudpd
```

## Issues Found And Fixed

### Docker `COPY --chmod` Compatibility

Unraid's Docker version did not reliably apply executable permissions from `COPY --chmod`. The Dockerfiles now explicitly run:

```dockerfile
RUN chmod +x /usr/local/bin/*.sh /usr/local/bin/*.py
```

### Port Conflict

NAS port `8088` was already used by `metatube-server`, so iCloudPD publishes:

```text
18088:8088
```

### Wrong Lark Event Type

Initial Lark testing only delivered `im.message.message_read_v1`, which contains no message text. Remote control requires:

```text
im.message.receive_v1
```

### App-Scoped `open_id`

Lark returned `open_id cross app` when the receiver ID did not belong to the current app. The fix was to use the app-scoped sender `open_id` from `im.message.receive_v1`.

### Auth Flow Interruptions

Early versions interrupted every `icloudpd` process after receiving a command. This killed the `--auth-only` re-authentication process after an MFA code was sent.

The current behavior is:

- interrupt normal sync/check jobs for `<user>` and `<user> auth`
- never interrupt `--auth-only`
- never interrupt auth when receiving MFA codes or SMS device choices

## Security Notes

Do not commit these values:

- `lark_app_secret`
- `lark_verification_token`
- user-specific `open_id` values if the repository is public
- Apple ID credentials or cookie files

The repository contains templates and code only. Runtime secrets should stay in `/config/icloudpd.conf`, compose environment variables, or the Unraid compose project.

## Verification Performed

- Python syntax check:

```bash
python -m py_compile lark_control.py lark_send.py
```

- Lark challenge endpoint validated through the public callback path.
- Lark startup notification sent successfully.
- Lark DM message received as `im.message.receive_v1`.
- Lark DM command reached the container and was translated into remote-control behavior.

## Remaining Operational Notes

The container health may remain `unhealthy` if the iCloud cookie is expired or missing. That is independent of the Lark transport and should be handled through normal iCloudPD initialization or re-authentication.

For Docker Hub publishing, the NAS must be logged in:

```bash
docker login -u yunjies
docker push yunjies/icloudpd:lark
```
