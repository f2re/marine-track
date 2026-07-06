from __future__ import annotations

import argparse
import getpass
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class EnvPrompt:
    key: str
    label: str
    kind: str
    secret: bool = False


SCENE_PROMPTS = (
    EnvPrompt("EARTHDATA_USERNAME", "NASA Earthdata username", "ASF / NASA Earthdata"),
    EnvPrompt("EARTHDATA_PASSWORD", "NASA Earthdata secret value", "ASF / NASA Earthdata", True),
    EnvPrompt("EARTHDATA_TOKEN", "NASA Earthdata bearer token", "ASF / NASA Earthdata", True),
    EnvPrompt("CDSE_ACCESS_TOKEN", "Copernicus Data Space access token", "Copernicus Data Space", True),
    EnvPrompt("CDSE_USERNAME", "Copernicus Data Space username", "Copernicus Data Space"),
    EnvPrompt("CDSE_PASSWORD", "Copernicus Data Space secret value", "Copernicus Data Space", True),
    EnvPrompt("CDSE_CLIENT_ID", "Copernicus Data Space OAuth client id", "Copernicus Data Space"),
    EnvPrompt("CDSE_CLIENT_SECRET", "Copernicus Data Space OAuth client secret", "Copernicus Data Space", True),
    EnvPrompt("SENTINELHUB_ACCESS_TOKEN", "Sentinel Hub access token", "Sentinel Hub", True),
    EnvPrompt("SENTINELHUB_CLIENT_ID", "Sentinel Hub OAuth client id", "Sentinel Hub"),
    EnvPrompt("SENTINELHUB_CLIENT_SECRET", "Sentinel Hub OAuth client secret", "Sentinel Hub", True),
)

AUX_PROMPTS = (
    EnvPrompt("COPERNICUSMARINE_SERVICE_USERNAME", "Copernicus Marine username", "Copernicus Marine"),
    EnvPrompt("COPERNICUSMARINE_SERVICE_PASSWORD", "Copernicus Marine secret value", "Copernicus Marine", True),
    EnvPrompt("MARINE_TRACK_AIS_CSV", "Local AIS CSV path", "AIS / tracks"),
    EnvPrompt("NOAA_MARINECADASTRE_BASE_URL", "NOAA MarineCadastre daily ZIP base URL", "AIS / tracks"),
    EnvPrompt("NOAA_MARINECADASTRE_CACHE_DIR", "NOAA AIS cache directory", "AIS / tracks"),
)

INSTRUCTIONS = {
    "ASF / NASA Earthdata": "Create a NASA Earthdata Login account. Use username plus secret value, or an EDL bearer token.",
    "Copernicus Data Space": "Create a Copernicus Data Space account. Use an access token, or username plus secret value with the public cdse client.",
    "Sentinel Hub": "Create an OAuth client in Sentinel Hub Dashboard. Use client id plus client secret, or an access token.",
    "Copernicus Marine": "Create a Copernicus Marine account, or log in with the official toolbox. Server deployment should store username and secret value.",
    "AIS / tracks": "Use a local AIS CSV for validation. NOAA archive access requires a base URL or local mirror containing daily AIS ZIP files.",
}


def normalize_profile(value: str) -> str:
    value = value.lower().strip()
    if value == "none":
        return "core"
    if value not in {"all", "scene", "aux", "core"}:
        raise ValueError("profile must be all, scene, aux, core or none")
    return value


def read_env(path: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    if not path.is_file():
        return values
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line or line.lstrip().startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        values[key.strip()] = value.strip()
    return values


def write_env(path: Path, updates: dict[str, str]) -> None:
    existing = read_env(path)
    existing.update(updates)
    lines: list[str] = []
    seen: set[str] = set()
    if path.is_file():
        for line in path.read_text(encoding="utf-8").splitlines():
            if not line or line.lstrip().startswith("#") or "=" not in line:
                lines.append(line)
                continue
            key = line.split("=", 1)[0].strip()
            if key in existing:
                lines.append(f"{key}={existing[key]}")
                seen.add(key)
            else:
                lines.append(line)
    for key, value in updates.items():
        if key not in seen:
            lines.append(f"{key}={value}")
    path.write_text("\n".join(lines).rstrip() + "\n", encoding="utf-8")


def prompts_for_profile(profile: str) -> tuple[EnvPrompt, ...]:
    if profile == "all":
        return SCENE_PROMPTS + AUX_PROMPTS
    if profile == "scene":
        return SCENE_PROMPTS
    if profile == "aux":
        return AUX_PROMPTS
    return ()


def configure(path: Path, profile: str, assume_yes: bool = False) -> int:
    profile = normalize_profile(profile)
    if assume_yes or profile == "core":
        print(f"Provider key prompts skipped (profile={profile}, assume_yes={assume_yes}).")
        return 0
    current = read_env(path)
    updates: dict[str, str] = {"MARINE_TRACK_PROVIDER_PROFILE": profile}
    current_kind = ""
    for item in prompts_for_profile(profile):
        if item.kind != current_kind:
            current_kind = item.kind
            print(f"\n{current_kind}")
            print(INSTRUCTIONS[current_kind])
        if current.get(item.key):
            print(f"  {item.key}: already set")
            continue
        prompt = f"  {item.label} [{item.key}] (Enter to skip): "
        value = getpass.getpass(prompt) if item.secret else input(prompt)
        if value:
            updates[item.key] = value
    write_env(path, updates)
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="Configure Marine Track provider access keys in .env")
    parser.add_argument("--env-file", default=".env")
    parser.add_argument("--profile", default="all")
    parser.add_argument("--yes", action="store_true", help="Do not prompt; only persist provider profile")
    args = parser.parse_args()
    return configure(Path(args.env_file), args.profile, args.yes)


if __name__ == "__main__":
    raise SystemExit(main())
