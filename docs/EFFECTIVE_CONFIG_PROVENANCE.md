# Effective processing configuration and reproducibility

`config/processing.yaml` is now the shared baseline for CLI and Telegram detection. Optional
`MARINE_TRACK_DETECTION_*` values override YAML; explicit CLI/function arguments override both.
The resolved values are validated and hashed before detection.

Every `report.json` contains schema v2, the exact effective detector parameters, config hash,
code/package/Python version, sensor/product/asset identity, redacted asset URL, auth mode,
raster dimensions/CRS/transform/pixel size and AOI hash. Absolute paths and URL query credentials
are removed recursively before atomic JSON write.

Use `marine-track effective-config --sensor sentinel1` to inspect the active values. Deployment
preflight rejects missing or invalid processing config. Set `MARINE_TRACK_CODE_VERSION` to an
immutable release SHA when `.git` is absent from the production release directory.
