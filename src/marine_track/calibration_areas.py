from __future__ import annotations

from dataclasses import dataclass
from typing import Final

AREA_PAGE_SIZE: Final = 6


@dataclass(frozen=True)
class CalibrationAreaGroup:
    id: str
    name: str
    emoji: str


@dataclass(frozen=True)
class CalibrationArea:
    """Operational calibration sector, not a legal or hydrographic boundary."""

    id: str
    group_id: str
    name: str
    west: float
    south: float
    east: float
    north: float
    kind: str = "open_sea"
    default_hours: int = 168

    @property
    def bbox(self) -> tuple[float, float, float, float]:
        return self.west, self.south, self.east, self.north

    def geojson(self) -> dict[str, object]:
        coordinates = [
            [self.west, self.south],
            [self.east, self.south],
            [self.east, self.north],
            [self.west, self.north],
            [self.west, self.south],
        ]
        return {
            "type": "FeatureCollection",
            "features": [
                {
                    "type": "Feature",
                    "properties": {
                        "name": self.name,
                        "calibration_area_id": self.id,
                        "sector_kind": self.kind,
                        "boundary_type": "operational_bbox",
                    },
                    "geometry": {"type": "Polygon", "coordinates": [coordinates]},
                }
            ],
        }


AREA_GROUPS: Final[tuple[CalibrationAreaGroup, ...]] = (
    CalibrationAreaGroup("eu", "Европа и Средиземноморье", "🌍"),
    CalibrationAreaGroup("mea", "Ближний Восток и Африка", "🌍"),
    CalibrationAreaGroup("ap", "Азия и Тихий океан", "🌏"),
    CalibrationAreaGroup("am", "Северная и Южная Америка", "🌎"),
    CalibrationAreaGroup("po", "Полярные и океанские сектора", "🧭"),
)


def _a(
    area_id: str,
    group_id: str,
    name: str,
    bbox: tuple[float, float, float, float],
    kind: str = "open_sea",
    hours: int = 168,
) -> CalibrationArea:
    return CalibrationArea(area_id, group_id, name, *bbox, kind=kind, default_hours=hours)


# Each box is deliberately compact enough for an interactive calibration run.
# The catalog covers major operational waters and approaches; it is not a list of
# official maritime boundaries and is not intended for navigation or jurisdiction.
CALIBRATION_AREAS: Final[tuple[CalibrationArea, ...]] = (
    # Europe and Mediterranean.
    _a("bs_w", "eu", "Чёрное море · запад", (28.5, 42.0, 30.5, 43.0)),
    _a("bs_c", "eu", "Чёрное море · центр", (31.5, 43.0, 33.5, 44.0)),
    _a("bs_e", "eu", "Чёрное море · восток", (36.0, 43.0, 38.0, 44.0)),
    _a("az_k", "eu", "Азовское море и Керченский пролив", (35.0, 44.6, 37.0, 45.6), "strait"),
    _a("mar_b", "eu", "Мраморное море и Босфор", (27.5, 40.3, 29.5, 41.3), "strait"),
    _a("aeg_n", "eu", "Эгейское море · север", (24.0, 39.0, 26.0, 40.0)),
    _a("aeg_s", "eu", "Эгейское море · юг", (24.0, 36.0, 26.0, 37.0)),
    _a("adr_n", "eu", "Адриатическое море · север", (12.5, 44.0, 14.5, 45.0)),
    _a("adr_s", "eu", "Адриатическое море · юг", (17.0, 40.5, 19.0, 41.5)),
    _a("ion", "eu", "Ионическое море", (18.0, 38.0, 20.0, 39.0)),
    _a("tyr", "eu", "Тирренское море", (11.0, 39.0, 13.0, 40.0)),
    _a("lig", "eu", "Лигурийское море", (8.0, 42.5, 10.0, 43.5)),
    _a("med_w", "eu", "Средиземное море · запад", (1.0, 38.0, 3.0, 39.0)),
    _a("alb_g", "eu", "Альборанское море и Гибралтар", (-5.5, 35.0, -3.5, 36.0), "strait"),
    _a("lev", "eu", "Левантийское море", (33.0, 33.0, 35.0, 34.0)),
    _a("bal_s", "eu", "Балтийское море · юг", (13.0, 54.0, 15.0, 55.0)),
    _a("bal_c", "eu", "Балтийское море · центр", (18.0, 57.0, 20.0, 58.0)),
    _a("g_fin", "eu", "Финский залив", (24.0, 59.0, 26.0, 60.0), "gulf"),
    _a("nsea_s", "eu", "Северное море · юг", (2.0, 52.0, 4.0, 53.0)),
    _a("nsea_n", "eu", "Северное море · север", (1.0, 58.0, 3.0, 59.0)),
    _a("chan", "eu", "Ла-Манш", (-1.0, 49.5, 1.0, 50.5), "strait"),
    _a("bisc", "eu", "Бискайский залив", (-4.0, 45.0, -2.0, 46.0), "gulf"),
    _a("nor", "eu", "Норвежское море", (4.0, 64.0, 7.0, 65.0)),
    _a("bar_s", "eu", "Баренцево море · юг", (33.0, 70.0, 36.0, 71.0)),
    # Middle East and Africa.
    _a("suez", "mea", "Суэцкий залив", (32.5, 28.0, 34.0, 29.0), "gulf"),
    _a("red_n", "mea", "Красное море · север", (34.0, 27.0, 36.0, 28.0)),
    _a("red_c", "mea", "Красное море · центр", (38.0, 20.0, 40.0, 21.0)),
    _a("red_s", "mea", "Красное море · юг", (42.0, 14.0, 44.0, 15.0)),
    _a("bab", "mea", "Баб-эль-Мандебский пролив", (42.5, 12.0, 44.0, 13.0), "strait"),
    _a("aden", "mea", "Аденский залив", (44.0, 11.5, 46.0, 12.5), "gulf"),
    _a("pg_w", "mea", "Персидский залив · запад", (49.0, 27.0, 51.0, 28.0), "gulf"),
    _a("pg_e", "mea", "Персидский залив · восток", (53.0, 25.5, 55.0, 26.5), "gulf"),
    _a("horm", "mea", "Ормузский пролив", (55.0, 25.5, 57.0, 26.5), "strait"),
    _a("oman", "mea", "Оманский залив", (57.0, 24.0, 59.0, 25.0), "gulf"),
    _a("arab_w", "mea", "Аравийское море · Оман", (60.0, 20.0, 62.0, 21.0)),
    _a("som", "mea", "Аравийское море · Сомали", (50.0, 8.0, 52.0, 9.0)),
    _a("moz_n", "mea", "Мозамбикский пролив · север", (42.0, -16.0, 44.0, -15.0), "strait"),
    _a("moz_s", "mea", "Мозамбикский пролив · юг", (38.0, -25.0, 40.0, -24.0), "strait"),
    _a("guinea", "mea", "Гвинейский залив", (1.0, 4.0, 3.0, 5.0), "gulf"),
    _a("cape", "mea", "Подходы к мысу Доброй Надежды", (17.0, -35.0, 19.0, -34.0), "approach"),
    # Asia-Pacific.
    _a("bob", "ap", "Бенгальский залив", (88.0, 19.0, 90.0, 20.0), "gulf"),
    _a("and", "ap", "Андаманское море", (96.0, 8.0, 98.0, 9.0)),
    _a("mal", "ap", "Малаккский пролив", (101.0, 2.0, 103.0, 3.0), "strait"),
    _a("sing", "ap", "Сингапурский пролив", (103.0, 1.0, 104.0, 2.0), "strait"),
    _a("thai", "ap", "Сиамский залив", (100.0, 9.0, 102.0, 10.0), "gulf"),
    _a("scs_n", "ap", "Южно-Китайское море · север", (114.0, 18.0, 116.0, 19.0)),
    _a("scs_c", "ap", "Южно-Китайское море · центр", (112.0, 11.0, 114.0, 12.0)),
    _a("scs_s", "ap", "Южно-Китайское море · юг", (108.0, 5.0, 110.0, 6.0)),
    _a("tai", "ap", "Тайваньский пролив", (118.5, 23.0, 120.5, 24.0), "strait"),
    _a("ecs", "ap", "Восточно-Китайское море", (124.0, 29.0, 126.0, 30.0)),
    _a("yel", "ap", "Жёлтое море", (123.0, 35.0, 125.0, 36.0)),
    _a("boh", "ap", "Бохайский залив", (118.5, 38.0, 120.5, 39.0), "gulf"),
    _a("jap", "ap", "Японское море", (130.0, 37.0, 132.0, 38.0)),
    _a("okh", "ap", "Охотское море", (145.0, 47.0, 147.0, 48.0)),
    _a("phil", "ap", "Филиппинское море", (127.0, 14.0, 129.0, 15.0)),
    _a("java", "ap", "Яванское море", (108.0, -6.0, 110.0, -5.0)),
    _a("mak", "ap", "Макасарский пролив", (117.0, -1.0, 119.0, 0.0), "strait"),
    _a("banda", "ap", "Море Банда", (128.0, -6.0, 130.0, -5.0)),
    _a("araf", "ap", "Арафурское море", (135.0, -10.0, 137.0, -9.0)),
    _a("tim", "ap", "Тиморское море", (124.0, -12.0, 126.0, -11.0)),
    _a("coral", "ap", "Коралловое море", (150.0, -20.0, 152.0, -19.0)),
    _a("tasm", "ap", "Тасманово море", (166.0, -38.0, 168.0, -37.0)),
    _a("ber", "ap", "Берингово море · юг", (-173.0, 55.0, -171.0, 56.0)),
    # Americas.
    _a("gom_w", "am", "Мексиканский залив · запад", (-96.0, 25.0, -94.0, 26.0), "gulf"),
    _a("gom_e", "am", "Мексиканский залив · восток", (-88.0, 27.0, -86.0, 28.0), "gulf"),
    _a("flor", "am", "Флоридский пролив", (-82.0, 24.0, -80.0, 25.0), "strait"),
    _a("car_w", "am", "Карибское море · запад", (-82.0, 17.0, -80.0, 18.0)),
    _a("car_e", "am", "Карибское море · восток", (-68.0, 15.0, -66.0, 16.0)),
    _a("bah", "am", "Багамские проливы", (-78.0, 24.0, -76.0, 25.0), "strait"),
    _a("pan_c", "am", "Карибские подходы к Панамскому каналу", (-80.5, 9.0, -78.5, 10.0), "approach"),
    _a("pan_p", "am", "Тихоокеанские подходы к Панамскому каналу", (-80.0, 7.5, -78.0, 8.5), "approach"),
    _a("cal_s", "am", "Калифорнийское побережье · юг", (-122.0, 34.0, -120.0, 35.0), "approach"),
    _a("cal_n", "am", "Калифорнийское побережье · север", (-125.0, 38.0, -123.0, 39.0), "approach"),
    _a("gcal", "am", "Калифорнийский залив", (-111.0, 25.0, -109.0, 26.0), "gulf"),
    _a("ny", "am", "Подходы к Нью-Йорку", (-75.0, 39.5, -73.0, 40.5), "approach"),
    _a("ches", "am", "Подходы к Чесапикскому заливу", (-76.0, 36.5, -74.0, 37.5), "approach"),
    _a("stl", "am", "Залив Святого Лаврентия", (-62.0, 47.0, -60.0, 48.0), "gulf"),
    _a("lab", "am", "Лабрадорское море", (-55.0, 55.0, -53.0, 56.0)),
    _a("hud", "am", "Гудзонов залив", (-83.0, 58.0, -81.0, 59.0), "gulf"),
    _a("san", "am", "Подходы к порту Сантус", (-47.0, -25.0, -45.0, -24.0), "approach"),
    _a("rdp", "am", "Ла-Плата · внешние подходы", (-57.0, -36.0, -55.0, -35.0), "approach"),
    _a("val", "am", "Подходы к Вальпараисо", (-73.0, -34.0, -71.0, -33.0), "approach"),
    _a("calo", "am", "Подходы к Кальяо", (-78.0, -13.0, -76.0, -12.0), "approach"),
    # Polar and open-ocean calibration sectors.
    _a("green", "po", "Гренландское море", (-5.0, 72.0, -2.0, 73.0)),
    _a("den", "po", "Датский пролив", (-28.0, 65.0, -25.0, 66.0), "strait"),
    _a("drake", "po", "Пролив Дрейка", (-59.0, -58.0, -56.0, -57.0), "strait"),
    _a("mag", "po", "Магелланов пролив", (-73.0, -53.0, -71.0, -52.0), "strait"),
    _a("azores", "po", "Северная Атлантика · Азорские острова", (-29.0, 37.0, -27.0, 38.0)),
    _a("haw", "po", "Северный Тихий океан · Гавайи", (-159.0, 20.0, -157.0, 21.0)),
    _a("sri", "po", "Индийский океан · юг Шри-Ланки", (80.0, 5.0, 82.0, 6.0)),
    _a("cap_h", "po", "Подходы к мысу Горн", (-69.0, -57.0, -66.0, -56.0), "approach"),
    _a("so_ind", "po", "Южный Индийский океан", (70.0, -45.0, 73.0, -44.0)),
)

_AREA_BY_ID: Final = {area.id: area for area in CALIBRATION_AREAS}
_GROUP_BY_ID: Final = {group.id: group for group in AREA_GROUPS}


def get_calibration_area(area_id: str) -> CalibrationArea | None:
    return _AREA_BY_ID.get(area_id)


def get_area_group(group_id: str) -> CalibrationAreaGroup | None:
    return _GROUP_BY_ID.get(group_id)


def areas_for_group(group_id: str) -> list[CalibrationArea]:
    return [area for area in CALIBRATION_AREAS if area.group_id == group_id]


def paginate_areas(areas: list[CalibrationArea], page: int) -> tuple[list[CalibrationArea], int, int]:
    page_count = max(1, (len(areas) + AREA_PAGE_SIZE - 1) // AREA_PAGE_SIZE)
    normalized_page = min(max(int(page), 0), page_count - 1)
    start = normalized_page * AREA_PAGE_SIZE
    return areas[start : start + AREA_PAGE_SIZE], normalized_page, page_count


def validate_catalog() -> list[str]:
    errors: list[str] = []
    seen: set[str] = set()
    group_ids = set(_GROUP_BY_ID)
    for area in CALIBRATION_AREAS:
        if area.id in seen:
            errors.append(f"duplicate area id: {area.id}")
        seen.add(area.id)
        if area.group_id not in group_ids:
            errors.append(f"unknown group for {area.id}: {area.group_id}")
        if not (-180.0 <= area.west < area.east <= 180.0):
            errors.append(f"invalid longitude bounds: {area.id}")
        if not (-90.0 <= area.south < area.north <= 90.0):
            errors.append(f"invalid latitude bounds: {area.id}")
        if area.east - area.west > 4.0 or area.north - area.south > 2.0:
            errors.append(f"sector is too large for interactive calibration: {area.id}")
    return errors


CATALOG_ERRORS: Final = validate_catalog()
if CATALOG_ERRORS:  # pragma: no cover - import-time invariant
    raise RuntimeError("Invalid calibration area catalog: " + "; ".join(CATALOG_ERRORS))
