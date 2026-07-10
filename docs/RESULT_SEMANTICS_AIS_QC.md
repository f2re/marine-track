# Result semantics and AIS QC

Marine Track exports georeferenced **vessel candidates**, not confirmed vessels. `ranking_score`
is an ordering/filtering score and is not a probability. Own-system operational speed remains
`speed.value_knots = null` until a separately validated estimator is available.

Deep-water Kelvin wavelength output is stored only in `research_proxies.kelvin_speed`; its
assumptions and quality score are explicit. AIS SOG/COG is stored only in `references.ais`, never
copied into own speed or heading, and is explicitly marked `not_ground_truth`.

AIS references use a maximum interpolation-gap gate, nearest/second-nearest ambiguity margin and
deterministic one-to-one MMSI assignment. Configure these with
`MARINE_TRACK_AIS_MAX_INTERPOLATION_GAP_MIN` and `MARINE_TRACK_AIS_AMBIGUITY_MARGIN_M`.

A local `runtime_state.json` (mode 0600) keeps the private raster path required by calibration.
It is not sent by Telegram. Public `report.json` stays redacted and points to this state only by a
relative reference.
