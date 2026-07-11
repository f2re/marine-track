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

`/etc/marine-track/marine-track.env` is the only production environment file used
by deploy, runtime checks and systemd. `/opt/marine_track/.env` is a legacy source
only. Install and deploy reconcile non-empty legacy values into empty canonical
values, preserve already configured canonical values, add new template keys without
duplicates and normalize the result to LF with exactly one trailing newline.

Initial preparation:

```bash
sudo ./install_telegram_bot.sh --prepare-only
sudoedit /etc/marine-track/marine-track.env
sudo ./deploy_telegram_bot.sh
```

The required Telegram settings are:

```dotenv
TELEGRAM_BOT_TOKEN=<new token from BotFather>
TELEGRAM_ADMIN_IDS=<numeric Telegram user id>
MARINE_TRACK_ALLOW_PUBLIC_BOT=0
```

Empty detection override variables in the template are intentional and mean “use
`config/processing.yaml`”. They are not numeric configuration errors.

A deploy holds `/run/lock/marine-track-deploy.lock`, safely parses the canonical
environment file without executing it as shell code, copies the source into a
staging release, builds a non-editable virtual environment, runs compile,
`runtime_check.py`, smoke check and offline health check, makes the release
read-only, switches `current` atomically, restarts systemd and executes an online
Telegram `getMe` health gate. Failure after the switch restores `previous` and
restarts the former release.

Each attempt uses an immutable directory named `<code-version>-<UTC timestamp>`; therefore a retry of
the same commit never collides with a failed earlier attempt. `release.json` records non-secret
release metadata, while `release.env` supplies `MARINE_TRACK_CODE_VERSION` and
`MARINE_TRACK_RELEASE_ID` to systemd after the shared environment file. Inactive failed attempts are
kept only until normal release retention removes them. Operators can correlate a failed attempt with
journal output by its release id without exposing credentials.

Use the health command independently:

```bash
/opt/marine_track/current/.venv/bin/marine-track-health \
  --base-dir /opt/marine_track/current \
  --env-file /etc/marine-track/marine-track.env \
  --telegram --json
```

To inspect the active configuration without printing secrets:

```bash
sudo grep -E '^(MARINE_TRACK_ENV_FILE|MARINE_TRACK_OUTPUT_DIR|MARINE_TRACK_CACHE_DIR|TELEGRAM_ADMIN_IDS|MARINE_TRACK_ALLOW_PUBLIC_BOT)=' \
  /etc/marine-track/marine-track.env
sudo systemctl status marine-track.service --no-pager
sudo journalctl -u marine-track.service -n 100 --no-pager
```

`degraded` is non-fatal and normally means that no scene registry or calibrated
profile exists yet. `failed` exits non-zero and blocks deploy/start. Set
`MARINE_TRACK_HEALTH_MIN_FREE_MB` to the required free-space floor and
`MARINE_TRACK_KEEP_RELEASES` to the number of non-current/non-previous releases
to retain.
