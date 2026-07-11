# Sentinel-1 provider canary and administrator self-test

The canary is an explicitly invoked operational check. It is not executed during service startup or deployment, so provider quotas and raster downloads are not consumed without an administrator action.

## Modes

### `asset`

The default mode performs:

1. selection or derivation of a compact AOI;
2. Sentinel-1 detection-capable provider search using the normal fallback order;
3. typed processing-asset selection;
4. runtime URL signing or transient OAuth header acquisition;
5. a small TIFF HTTP range-read probe.

It does not materialize the full raster and does not run detection.

### `detection`

This mode requires a separate confirmation in Telegram. It performs the asset canary and then:

1. registers exactly one scene in an isolated user/chat-scoped canary registry;
2. materializes and crops the compact AOI;
3. runs the operational Sentinel-1 preprocessing and CFAR pipeline;
4. produces zero image crops and records only a compact result summary in the canary report.

Wake/Hough/Kelvin research enrichment is explicitly forced off, even when it is enabled for another research workflow. The result verifies integration, not scientific detection accuracy.

## AOI contract

`MARINE_TRACK_CANARY_AOI` may point to a dedicated compact GeoJSON. When it is empty, the application intersects an 8 km local square with `MARINE_TRACK_DEFAULT_AOI`. The default maximum canary area is 100 km². All AOIs still pass the normal GeoJSON and resource-limit validation.

```dotenv
MARINE_TRACK_CANARY_AOI=
MARINE_TRACK_CANARY_SIDE_KM=8
MARINE_TRACK_CANARY_MAX_AREA_KM2=100
MARINE_TRACK_CANARY_LOOKBACK_HOURS=168
MARINE_TRACK_CANARY_MAX_RESULTS=5
```

## CLI

```bash
marine-track provider-canary --mode asset
marine-track provider-canary --mode detection
```

The command prints the redacted JSON report and returns a non-zero exit code when the canary fails. CLI detection uses an isolated local scope unless explicit owner IDs are supplied.

## Telegram

The administrator can use `/selftest` or the `🩺 Self-test` button. The full detection test is never started by opening the menu: Telegram first displays a quota/download warning and requires a second confirmation.

## Reports

Reports are written atomically with mode `0600`:

```text
MARINE_TRACK_OUTPUT_DIR/selftest/latest.json
MARINE_TRACK_OUTPUT_DIR/selftest/runs/<canary-id>/report.json
```

Reports contain stage status and duration, AOI metrics/hash, provider and scene metadata, typed asset characteristics, access mode, range-probe result and an optional detection summary. They do not contain authorization headers, access tokens, passwords, signed query parameters or absolute local paths.
