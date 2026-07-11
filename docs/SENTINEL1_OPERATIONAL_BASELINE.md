# Sentinel-1 operational baseline

Marine Track treats Sentinel-1 as the only operational single-raster detection path.
Sentinel-2 single-band detection and wake/Kelvin enrichment are disabled unless an
operator explicitly enables their research flags.

## Radiometric contract

The selected typed `SceneAsset`, its STAC metadata, GeoTIFF band tags, scale and
offset are resolved into a `SensorPreprocessingPlan` before detection.

- Provider-declared sigma0/gamma0/RTC linear assets are converted with
  `10 * log10(power)` and labelled `provider_declared_calibrated_backscatter`.
- Provider-declared dB assets remain in dB, but are only called calibrated when the
  asset semantics explicitly identify sigma0/gamma0/RTC.
- Amplitude/DN inputs are converted with `20 * log10(amplitude)` and labelled
  `relative_uncalibrated_amplitude`.
- Unknown radiometry is converted only to a relative dB domain and carries warnings;
  the report never claims absolute calibration.

Calibration and thermal-noise sidecars are recorded as metadata but are not silently
applied. A raw GRD measurement is therefore not presented as calibrated sigma0 unless
the provider asset already declares that domain.

## Speckle filtering and masks

The default nodata-aware Lee filter is applied in the native linear domain before dB
conversion when the input domain is amplitude or power. For already logarithmic
inputs it is applied in dB and the preprocessing plan records a warning. Source masks,
AOI masks, NaN and nodata remain excluded from local statistics and detection.

Materialization is protected by a per-cache-target inter-process lock. A corrupt
non-empty cache entry is removed and rebuilt once under the lock; concurrent workers
do not download the same target simultaneously.

## Operational and research gates

```dotenv
MARINE_TRACK_S1_SPECKLE_FILTER=lee
MARINE_TRACK_S1_LEE_WINDOW_PX=5
MARINE_TRACK_RASTER_LOCK_TIMEOUT_S=300
MARINE_TRACK_ENABLE_SENTINEL2_SINGLE_BAND_EXPERIMENTAL=0
MARINE_TRACK_ENABLE_WAKE_RESEARCH=0
```

Sentinel-2 operational detection requires a co-registered B02/B03/B04/B08 stack plus
SCL, cloud and water masks. Until that pipeline is implemented, the Telegram
calibration UI marks Sentinel-2 unavailable. Enabling the single-band flag changes it
to an explicitly labelled research path; it does not make it operational.

Wake-axis and Kelvin wavelength enrichment are also research-only. When disabled,
no Kelvin proxy is calculated and operational speed remains `not_estimated`.

## Provenance

`report.json` schema 4 and private `runtime_state.json` schema 2 include the resolved
preprocessing plan, radiometric domain, calibration status, polarization/band,
filter configuration and warnings. Candidate metadata carries the same plan so that
calibration profiles can be separated by sensor and radiometric regime.
