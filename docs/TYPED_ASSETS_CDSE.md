# Typed assets and CDSE materialization

`Scene.asset_records` is the canonical provider/materializer contract. The legacy
`Scene.assets: {key: href}` mapping remains serialized and readable for existing
registries and Telegram UI, while every legacy string is automatically promoted
to a `SceneAsset` at model validation time.

A typed asset records media type, roles, band/polarization, units, nodata,
scale/offset, storage/auth mode, alternate HTTPS/S3 references and sidecars.
Secrets are never stored in the scene or report. OAuth bearer headers and
Planetary Computer signatures are resolved immediately before probe/download.

The default CDSE STAC endpoint is `https://stac.dataspace.copernicus.eu/v1/`
with `sentinel-1-grd` and `sentinel-2-l2a`. Environment variables may override
all three values. For CDSE assets the materializer prefers an HTTPS alternate
over S3, obtains a transient OIDC token and sends it for the range-read canary,
GDAL/rasterio crop and download.

Before a remote asset reaches detection, the materializer requests the first
bytes with `Range: bytes=0-N` and verifies TIFF magic or TIFF media type. HTTP
401/403, non-raster responses and inaccessible storage fail before the expensive
detection stage. Configure probe limits with:

```dotenv
MARINE_TRACK_ASSET_PROBE_TIMEOUT_S=30
MARINE_TRACK_ASSET_PROBE_BYTES=4096
```

The asset manifest and reproducibility report contain only sanitized URLs and
typed domain metadata; bearer values and signed query strings are not persisted.
