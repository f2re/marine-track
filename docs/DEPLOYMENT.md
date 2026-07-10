# Atomic production deployment

The production layout separates immutable releases from mutable runtime state:

```text
/opt/marine_track/releases/<release-id>/   root-owned code and venv
/opt/marine_track/current -> releases/...  atomic active symlink
/opt/marine_track/previous -> releases/... rollback target
/etc/marine-track/marine-track.env          root:marine-track 0640
/var/lib/marine-track/output/               service-owned state/output
/var/cache/marine-track/                    service-owned provider/raster cache
/var/log/marine-track/                      service-owned logs
```

Initial preparation:

```bash
sudo ./install_telegram_bot.sh --prepare-only
sudoedit /etc/marine-track/marine-track.env
sudo ./deploy_telegram_bot.sh
```

A deploy holds `/run/lock/marine-track-deploy.lock`, copies the source into a
staging release, builds a non-editable virtual environment, runs compile,
`runtime_check.py`, smoke check and offline health check, makes the release
read-only, switches `current` atomically, restarts systemd and executes an online
Telegram `getMe` health gate. Failure after the switch restores `previous` and
restarts the former release.

Use the health command independently:

```bash
/opt/marine_track/current/.venv/bin/marine-track-health   --base-dir /opt/marine_track/current   --env-file /etc/marine-track/marine-track.env   --telegram --json
```

`degraded` is non-fatal and normally means that no scene registry or calibrated
profile exists yet. `failed` exits non-zero and blocks deploy/start. Set
`MARINE_TRACK_HEALTH_MIN_FREE_MB` to the required free-space floor and
`MARINE_TRACK_KEEP_RELEASES` to the number of non-current/non-previous releases
to retain.
