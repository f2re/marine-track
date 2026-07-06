from marine_track.models import Sensor
from marine_track.telegram_bot import bbox_geojson, parse_hours, parse_sensor
from marine_track.telegram_config import parse_admin_ids


def test_id_list_parser():
    assert parse_admin_ids("123, 456;789 bad") == {123, 456, 789}


def test_sensor_aliases():
    assert parse_sensor("s1", Sensor.AUTO) == Sensor.SENTINEL1
    assert parse_sensor("s2", Sensor.AUTO) == Sensor.SENTINEL2
    assert parse_sensor(None, Sensor.AUTO) == Sensor.AUTO


def test_hours_parser():
    assert parse_hours("72", 24) == 72
    assert parse_hours(None, 24) == 24


def test_bbox_payload():
    payload = bbox_geojson(36.5, 43.8, 38.5, 45.0)
    feature = payload["features"][0]
    coords = feature["geometry"]["coordinates"][0]
    assert coords[0] == [36.5, 43.8]
    assert coords[-1] == [36.5, 43.8]
