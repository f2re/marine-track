# Sentinel-1 provider canary and administrator self-test

Marine Track includes an explicit operational canary for the live path:

```text
compact AOI
  -> detection-capable Sentinel-1 search
  -> typed processing asset selection
  -> runtime URL signing or OAuth bearer acquisition
  -> TIFF range-read probe
  -> optional confirmed compact detection run
```

The canary never runs automatically during installation, deployment, restart or health checks. This
avoids unrequested provider quota, network traffic and raster downloads.

## Modes

`asset` is the default and low-cost mode. It searches for a processable Sentinel-1 scene and reads a
small byte range from the selected GeoTIFF/COG. It does not materialize the full raster.

`detection` is an explicitly confirmed end-to-end mode. It registers a user/chat-scoped scene token,
materializes one compact AOI crop and runs candidate detection. Wake/Kelvin research is forcibly
disabled for the canary. The command requires non-zero owner user and chat identifiers.

## CLI

```bash
marine-track provider-canary --mode asset
```

For a confirmed compact detection run:

```bash
marine-track provider-canary \
  --mode detection \
  --owner-user-id 123456789 \
  --owner-chat-id 123456789 \
  --confirm-detection
```

The command prints a redacted JSON report and exits non-zero when any stage fails.

## Telegram

Administrators can use `/selftest` or the `🩺 Самопроверка` menu button. The interface separates:

1. provider/asset range-read validation;
2. a second confirmation screen for the quota-using compact detection test.

The resulting redacted JSON report is sent to the administrator. Non-administrators cannot run the
self-test even when public bot access is enabled.

## AOI configuration

The canary uses `MARINE_TRACK_CANARY_AOI` when configured. Otherwise it derives a small polygon from
the representative point of `MARINE_TRACK_DEFAULT_AOI` and intersects it with that AOI. It does not
search the whole default area.

```dotenv
MARINE_TRACK_CANARY_AOI=
MARINE_TRACK_CANARY_LOOKBACK_HOURS=336
MARINE_TRACK_CANARY_MAX_RESULTS=3
MARINE_TRACK_CANARY_SPAN_DEG=0.10
```

The span is constrained to `0.02..0.25` degrees and the final polygon is checked by the normal AOI
resource-limit contract before provider search.

## Report security

Reports are written beneath:

```text
MARINE_TRACK_OUTPUT_DIR/selftest/<run-id>/report.json
```

with mode `0600`. They include stage status and duration, provider, scene/product identifier, typed
asset semantics, range-read status and optional candidate count. They do not contain:

- bearer tokens or client secrets;
- signed URL query strings;
- authorization headers;
- passwords;
- absolute server paths.

The private compact AOI and provider search artifacts stay under the self-test run directory. A
failed run still writes a report with a sanitized exception type and message.
