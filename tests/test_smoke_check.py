from marine_track.smoke_check import run_smoke_check


def test_smoke_check_reads_env_and_creates_runtime_dirs(tmp_path, monkeypatch):
    for key in (
        "TELEGRAM_BOT_TOKEN",
        "BOT_TOKEN",
        "MARINE_TRACK_DEFAULT_AOI",
        "MARINE_TRACK_OUTPUT_DIR",
        "MARINE_TRACK_CACHE_DIR",
        "MARINE_TRACK_PROVIDER_PROFILE",
    ):
        monkeypatch.delenv(key, raising=False)

    aoi = tmp_path / "data" / "aoi" / "example.geojson"
    aoi.parent.mkdir(parents=True)
    aoi.write_text('{"type":"FeatureCollection","features":[]}', encoding="utf-8")
    env_file = tmp_path / ".env"
    env_file.write_text(
        "\n".join(
            [
                "TELEGRAM_BOT_TOKEN=test-token",
                "MARINE_TRACK_DEFAULT_AOI=data/aoi/example.geojson",
                "MARINE_TRACK_OUTPUT_DIR=runs/telegram",
                "MARINE_TRACK_CACHE_DIR=runs/cache",
                "MARINE_TRACK_PROVIDER_PROFILE=core",
            ]
        ),
        encoding="utf-8",
    )

    errors = run_smoke_check(tmp_path, env_file)

    assert errors == []
    assert (tmp_path / "runs" / "telegram").is_dir()
    assert (tmp_path / "runs" / "cache").is_dir()
