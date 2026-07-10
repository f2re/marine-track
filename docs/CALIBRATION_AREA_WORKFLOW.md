# Calibration area and scene acquisition workflow

Calibration does not learn from an empty output directory. Candidate calibration reads
`detections/*/report.json`; phase 2 creates independent tiles from the same reports and their
private `runtime_state.json`. The Telegram administrator workflow therefore prepares source data
before asking for labels:

```text
Calibration
  -> choose water area
  -> choose Sentinel-1 / Sentinel-2 / auto
  -> choose 24 h / 3 d / 7 d / 14 d / 30 d
  -> search detection-capable scenes
  -> choose one scene or batch up to three
  -> materialize and run detection
  -> generate candidate tasks and independent phase 2 tiles
  -> label candidates or tiles
```

## Area sources

The Telegram UI offers three source types:

1. `Default AOI` from `MARINE_TRACK_DEFAULT_AOI`.
2. Bboxes saved by `/detectbbox` or `/bboxdates`.
3. A built-in catalog of compact operational sectors.

Catalog sectors are deliberately small interactive AOIs. They are not legal, navigation,
hydrographic or exclusive-economic-zone boundaries. Large named seas are represented by several
sectors so that search, COG materialization and detection remain bounded.

## Built-in catalog

### Europe and Mediterranean

Black Sea west/centre/east; Sea of Azov and Kerch Strait; Sea of Marmara and Bosporus; Aegean
north/south; Adriatic north/south; Ionian; Tyrrhenian; Ligurian; western Mediterranean; Alboran and
Gibraltar; Levantine Sea; Baltic south/centre; Gulf of Finland; North Sea south/north; English
Channel; Bay of Biscay; Norwegian Sea; southern Barents Sea.

### Middle East and Africa

Gulf of Suez; Red Sea north/centre/south; Bab-el-Mandeb; Gulf of Aden; Persian Gulf west/east;
Strait of Hormuz; Gulf of Oman; Arabian Sea off Oman and Somalia; Mozambique Channel north/south;
Gulf of Guinea; Cape of Good Hope approaches.

### Asia-Pacific

Bay of Bengal; Andaman Sea; Malacca and Singapore straits; Gulf of Thailand; South China Sea
north/centre/south; Taiwan Strait; East China Sea; Yellow Sea; Bohai Gulf; Sea of Japan; Sea of
Okhotsk; Philippine Sea; Java Sea; Makassar Strait; Banda Sea; Arafura Sea; Timor Sea; Coral Sea;
Tasman Sea; southern Bering Sea.

### Americas

Gulf of Mexico west/east; Florida Strait; Caribbean west/east; Bahamas passages; Caribbean and
Pacific approaches to the Panama Canal; southern and northern California approaches; Gulf of
California; New York and Chesapeake approaches; Gulf of St. Lawrence; Labrador Sea; Hudson Bay;
Santos approaches; outer Rio de la Plata; Valparaiso approaches; Callao approaches.

### Polar and open ocean

Greenland Sea; Denmark Strait; Drake Passage; Magellan Strait; North Atlantic near the Azores;
North Pacific near Hawaii; Indian Ocean south of Sri Lanka; Cape Horn approaches; southern Indian
Ocean sector.

The canonical list, identifiers and bboxes are defined in
`src/marine_track/calibration_areas.py`. Telegram exposes category pages and an `All sectors` page.

## Sensor and period

Sentinel-1 is the recommended first source because SAR acquisition is independent of cloud cover.
Sentinel-2 should be labelled and evaluated as a separate optical applicability profile. `auto`
tries the configured sensor order.

Short periods are appropriate for frequently covered sectors. A 14- or 30-day interval is more
robust for sparse coverage or provider outages.

## Search sessions and access control

Search results are stored under:

```text
MARINE_TRACK_OUTPUT_DIR/calibration/area_search/sessions/<session_id>.json
```

The session is mode `0600`, written atomically and bound to both Telegram `user_id` and `chat_id`.
Scene tokens remain scoped by the existing scene registry. A different user or chat cannot execute
a saved calibration session.

## Zero-candidate scenes

A successful scene with zero current detector candidates is still useful. The workflow generates
independent phase 2 tiles from the raster, allowing the administrator to identify missed vessels
and true empty-water negatives. Candidate calibration is offered only when at least one candidate
was produced; phase 2 remains available in all successful runs.
