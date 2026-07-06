from __future__ import annotations

import importlib.util
import os
from dataclasses import dataclass


@dataclass(frozen=True)
class ProviderCheck:
    name: str
    kind: str
    modules: tuple[str, ...]
    required_env_any: tuple[tuple[str, ...], ...] = ()
    required_env_all: tuple[str, ...] = ()


CHECKS = (
    ProviderCheck(
        name="asf",
        kind="scene",
        modules=("asf_search",),
        required_env_any=(("EARTHDATA_USERNAME", "EARTHDATA_TOKEN"),),
    ),
    ProviderCheck(
        name="copernicus_cdse",
        kind="scene",
        modules=("pystac_client",),
        required_env_any=(("CDSE_ACCESS_TOKEN", "CDSE_USERNAME"),),
    ),
    ProviderCheck(
        name="planetary_computer",
        kind="scene",
        modules=("pystac_client", "planetary_computer"),
    ),
    ProviderCheck(
        name="earthsearch",
        kind="scene",
        modules=("pystac_client",),
    ),
    ProviderCheck(
        name="sentinelhub",
        kind="scene",
        modules=("sentinelhub",),
        required_env_any=(("SENTINELHUB_ACCESS_TOKEN", "SENTINELHUB_CLIENT_ID"),),
    ),
    ProviderCheck(
        name="copernicus_marine",
        kind="aux",
        modules=("copernicusmarine",),
        required_env_any=(("COPERNICUSMARINE_SERVICE_USERNAME",),),
    ),
    ProviderCheck(
        name="local_ais",
        kind="aux",
        modules=("pandas",),
        required_env_any=(("MARINE_TRACK_AIS_CSV",),),
    ),
    ProviderCheck(
        name="noaa_marinecadastre",
        kind="aux",
        modules=("pandas",),
        required_env_any=(("NOAA_MARINECADASTRE_BASE_URL",),),
    ),
)


def load_dotenv(path: str = ".env") -> None:
    if not os.path.isfile(path):
        return
    with open(path, encoding="utf-8") as file_obj:
        for raw_line in file_obj:
            line = raw_line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, value = line.split("=", 1)
            os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


def provider_profile() -> str:
    value = os.getenv("MARINE_TRACK_PROVIDER_PROFILE", "all").strip().lower()
    if value == "none":
        return "core"
    return value if value in {"all", "scene", "aux", "core"} else "all"


def enabled_kind(kind: str, profile: str) -> bool:
    if profile == "all":
        return True
    if profile == "scene":
        return kind == "scene"
    if profile == "aux":
        return kind == "aux"
    return False


def module_available(name: str) -> bool:
    return importlib.util.find_spec(name) is not None


def env_any_satisfied(group: tuple[str, ...]) -> bool:
    return any(bool(os.getenv(name, "").strip()) for name in group)


def check_provider(check: ProviderCheck) -> tuple[str, list[str]]:
    issues: list[str] = []
    for module in check.modules:
        if not module_available(module):
            issues.append(f"missing module {module}")
    for env_group in check.required_env_any:
        if not env_any_satisfied(env_group):
            issues.append("optional credentials/env not set: " + " or ".join(env_group))
    for env_name in check.required_env_all:
        if not os.getenv(env_name, "").strip():
            issues.append(f"required env not set: {env_name}")
    status = "ok" if not issues else "warn"
    if any(issue.startswith("missing module") for issue in issues):
        status = "fail"
    return status, issues


def main() -> int:
    load_dotenv()
    profile = provider_profile()
    print(f"Provider preflight: profile={profile}")
    failures = 0
    for check in CHECKS:
        if not enabled_kind(check.kind, profile):
            print(f"- {check.name}: skipped ({check.kind})")
            continue
        status, issues = check_provider(check)
        print(f"- {check.name}: {status}")
        for issue in issues:
            print(f"  - {issue}")
        if status == "fail":
            failures += 1
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
