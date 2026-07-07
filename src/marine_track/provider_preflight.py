from __future__ import annotations

import argparse
import importlib.util
import os
import sys
from dataclasses import dataclass
from pathlib import Path

VALID_PROVIDER_PROFILES = {"all", "scene", "aux", "core"}


@dataclass(frozen=True)
class ProviderCheck:
    name: str
    kind: str
    modules: tuple[str, ...]
    env_groups: tuple[tuple[str, ...], ...] = ()


CHECKS = (
    ProviderCheck("asf", "scene", ("asf_search",), (("EARTHDATA_USERNAME", "EARTHDATA_TOKEN"),)),
    ProviderCheck("copernicus_cdse", "scene", ("pystac_client",), (("CDSE_ACCESS_TOKEN", "CDSE_USERNAME"),)),
    ProviderCheck("planetary_computer", "scene", ("pystac_client", "planetary_computer")),
    ProviderCheck("earthsearch", "scene", ("pystac_client",)),
    ProviderCheck("sentinelhub", "scene", ("sentinelhub",), (("SENTINELHUB_ACCESS_TOKEN", "SENTINELHUB_CLIENT_ID"),)),
    ProviderCheck("copernicus_marine", "aux", ("copernicusmarine",), (("COPERNICUSMARINE_SERVICE_USERNAME",),)),
    ProviderCheck("local_ais", "aux", ("pandas",), (("MARINE_TRACK_AIS_CSV",),)),
    ProviderCheck("noaa_marinecadastre", "aux", ("pandas",), (("NOAA_MARINECADASTRE_BASE_URL",),)),
)


def load_dotenv(path: Path) -> None:
    if not path.is_file():
        return
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


def provider_profile() -> str:
    value = os.getenv("MARINE_TRACK_PROVIDER_PROFILE", "all").strip().lower()
    if value not in VALID_PROVIDER_PROFILES:
        raise ValueError(f"invalid MARINE_TRACK_PROVIDER_PROFILE={value!r}; use all, scene, aux, core")
    return value


def check_enabled(profile: str, kind: str) -> bool:
    return profile == "all" or (profile == "scene" and kind == "scene") or (profile == "aux" and kind == "aux")


def run_preflight() -> int:
    profile = provider_profile()
    failures = 0
    print(f"Provider preflight: profile={profile}")
    for check in CHECKS:
        if not check_enabled(profile, check.kind):
            print(f"- {check.name}: skipped ({check.kind})")
            continue
        issues: list[str] = []
        for module in check.modules:
            if importlib.util.find_spec(module) is None:
                issues.append(f"missing module {module}")
        for group in check.env_groups:
            if not any(os.getenv(item, "").strip() for item in group):
                issues.append("optional credentials/env not set: " + " or ".join(group))
        has_missing_module = any(issue.startswith("missing module") for issue in issues)
        if has_missing_module:
            failures += 1
        status = "fail" if has_missing_module else "warn" if issues else "ok"
        print(f"- {check.name}: {status}")
        for issue in issues:
            print(f"  - {issue}")
    return 1 if failures else 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Marine Track provider readiness preflight")
    parser.add_argument("--env-file", default=".env", help="Env file to read before checks")
    args = parser.parse_args(argv)
    load_dotenv(Path(args.env_file))
    try:
        return run_preflight()
    except Exception as exc:
        print(f"Provider preflight failed: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
