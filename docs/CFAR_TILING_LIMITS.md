# CFAR, tiled inference and resource limits

The operational detector reads a bounded scene-wide sample to establish one 2/98 percentile
normalization domain, then processes the raster in overlapping windows. It does not load the
full-resolution band into memory. The overview renderer also requests a bounded rasterio
`out_shape`, so result rendering cannot undo the memory bound.

Local CFAR uses an outer training window minus the complete inner guard region. The guard
region includes the cell under test. Per-candidate provenance records the usable training
count, training fraction, local mean/std, threshold and incomplete-support flag. Tile overlap
must be at least twice the outer-window radius because ownership boundaries lie near the
midpoint of an overlap.

Candidate ownership partitions the full raster in global pixel coordinates. This removes
duplicate emissions from overlapping tiles while retaining deterministic IDs and global
bounding boxes.

The fail-closed defaults are:

```dotenv
MARINE_TRACK_MAX_AOI_AREA_KM2=25000
MARINE_TRACK_MAX_AOI_VERTICES=5000
MARINE_TRACK_MAX_RASTER_PIXELS=2000000000
MARINE_TRACK_MAX_TILES=20000
MARINE_TRACK_MAX_CANDIDATES=10000
MARINE_TRACK_DETECTION_TILE_SIZE_PX=1024
MARINE_TRACK_DETECTION_TILE_OVERLAP_PX=128
MARINE_TRACK_CFAR_MIN_TRAINING_FRACTION=0.5
MARINE_TRACK_NORMALIZATION_SAMPLE_PIXELS=1000000
```

The baseline values come from `resource_limits` and sensor preprocessing sections in
`config/processing.yaml`. Non-empty environment variables override the YAML values. The same
resolution contract is used by pre-provider AOI validation, tiled detector execution and the
effective configuration recorded in `report.json`; malformed present configuration fails closed.

AOIs are interpreted as WGS84 polygonal GeoJSON. Out-of-range coordinates, invalid topology,
excessive vertices and excessive geodesic area are rejected before provider search. Raster
pixel/tile limits are checked immediately after opening the materialized crop and before tiled
detection. These limits are operational safety controls, not scientific tuning parameters.
