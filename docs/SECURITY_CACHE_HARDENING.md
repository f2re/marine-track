# Telegram access, scene token scope and search cache contract

## Access policy

Operational Telegram commands are fail-closed. A user is authorized only when their numeric ID
is present in `TELEGRAM_ADMIN_IDS` or `MARINE_TRACK_ALLOW_PUBLIC_BOT=1` is explicitly set.

`/start`, `/help`, `/status` and `/whoami` remain available for enrollment and diagnostics.
Detection, scene browsing, saved AOIs, output settings and calibration remain protected.

`runtime_check.py` rejects deployment when both the allowlist is empty and public mode is not
explicitly enabled. Invalid IDs and invalid boolean values are configuration errors.

## Scene registry isolation

Every registry record stores `owner_user_id` and `owner_chat_id`. The token hash includes both
values. Preview, pagination and detection resolve a token only for the matching Telegram user and
chat. Old unscoped records are intentionally invalid; repeat `/dates`, `/bboxdates` or
`/detectbbox` after deployment. Registry writes are atomic and guarded by an in-process lock.

## Search cache v2

The cache key includes AOI hash, sensor, absolute UTC start/end, result limit, purpose and required
capability. Catalog search uses `catalog/any_scene`; detection search uses
`detection/processable_geotiff_cog`. Equal-duration windows at different times and catalog versus
detection flows cannot reuse each other's entries.
