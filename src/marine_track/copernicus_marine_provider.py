from __future__ import annotations

import os
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path


@dataclass(frozen=True)
class MarineSubsetRequest:
    dataset_id: str
    variables: list[str]
    west: float
    south: float
    east: float
    north: float
    start: datetime
    end: datetime
    output_dir: Path


class CopernicusMarineProvider:
    """Real Copernicus Marine Toolbox wrapper.

    The provider delegates actual data access to the official `copernicusmarine`
    Python package. Credentials are optional when the user's local toolbox is already
    logged in; otherwise set COPERNICUSMARINE_SERVICE_USERNAME/PASSWORD.
    """

    name = "copernicus_marine"

    def subset(self, request: MarineSubsetRequest) -> list[Path]:
        try:
            import copernicusmarine
        except ImportError as exc:  # pragma: no cover - environment dependent
            raise RuntimeError("copernicusmarine is not installed") from exc

        request.output_dir.mkdir(parents=True, exist_ok=True)
        before = set(request.output_dir.glob("*"))
        kwargs = {
            "dataset_id": request.dataset_id,
            "variables": request.variables,
            "minimum_longitude": request.west,
            "maximum_longitude": request.east,
            "minimum_latitude": request.south,
            "maximum_latitude": request.north,
            "start_datetime": request.start.isoformat(),
            "end_datetime": request.end.isoformat(),
            "output_directory": str(request.output_dir),
            "force_download": True,
        }
        username = os.getenv("COPERNICUSMARINE_SERVICE_USERNAME")
        password = os.getenv("COPERNICUSMARINE_SERVICE_PASSWORD")
        if username and password:
            kwargs["username"] = username
            kwargs["password"] = password
        result = copernicusmarine.subset(**kwargs)
        after = set(request.output_dir.glob("*"))
        created = sorted(path for path in after.difference(before) if path.is_file())
        if created:
            return created
        if isinstance(result, list):
            return [Path(str(item)) for item in result if Path(str(item)).exists()]
        if result is not None and Path(str(result)).exists():
            return [Path(str(result))]
        return []
