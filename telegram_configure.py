from __future__ import annotations

import argparse
import getpass
import os
from pathlib import Path


TOKEN_KEYS = ("TELEGRAM_BOT_TOKEN", "BOT_TOKEN")
ADMIN_KEY = "TELEGRAM_ADMIN_IDS"


def read_env(path: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    if not path.is_file():
        return values
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        if not raw_line or raw_line.lstrip().startswith("#") or "=" not in raw_line:
            continue
        key, value = raw_line.split("=", 1)
        values[key.strip()] = value.strip().strip('"').strip("'")
    return values


def write_env(path: Path, updates: dict[str, str]) -> None:
    lines: list[str] = []
    seen: set[str] = set()
    if path.is_file():
        for raw_line in path.read_text(encoding="utf-8").splitlines():
            if not raw_line or raw_line.lstrip().startswith("#") or "=" not in raw_line:
                lines.append(raw_line)
                continue
            key = raw_line.split("=", 1)[0].strip()
            if key in updates:
                lines.append(f"{key}={updates[key]}")
                seen.add(key)
            else:
                lines.append(raw_line)
    for key, value in updates.items():
        if key not in seen:
            lines.append(f"{key}={value}")
    path.write_text("\n".join(lines).rstrip() + "\n", encoding="utf-8")


def current_token(values: dict[str, str]) -> str:
    return next((values.get(key, "").strip() for key in TOKEN_KEYS if values.get(key, "").strip()), "")


def configure(env_file: Path, assume_yes: bool, require_token: bool) -> int:
    values = read_env(env_file)
    updates: dict[str, str] = {}

    token = os.getenv("TELEGRAM_BOT_TOKEN", "").strip() or os.getenv("BOT_TOKEN", "").strip()
    if token:
        updates["TELEGRAM_BOT_TOKEN"] = token
        print("TELEGRAM_BOT_TOKEN: set from environment")
    elif current_token(values):
        print("TELEGRAM_BOT_TOKEN: already set in .env")
    elif not assume_yes:
        prompt = "Telegram bot token from BotFather [TELEGRAM_BOT_TOKEN] (Enter to skip): "
        entered = getpass.getpass(prompt).strip()
        if entered:
            updates["TELEGRAM_BOT_TOKEN"] = entered
            print("TELEGRAM_BOT_TOKEN: written to .env")

    admin_ids = os.getenv("TELEGRAM_ADMIN_IDS", "").strip()
    if admin_ids:
        updates[ADMIN_KEY] = admin_ids
        print("TELEGRAM_ADMIN_IDS: set from environment")
    elif values.get(ADMIN_KEY, "").strip():
        print("TELEGRAM_ADMIN_IDS: already set in .env")
    elif not assume_yes:
        entered = input("Telegram admin ids, comma-separated [TELEGRAM_ADMIN_IDS] (Enter to skip): ").strip()
        if entered:
            updates[ADMIN_KEY] = entered
            print("TELEGRAM_ADMIN_IDS: written to .env")

    if updates:
        write_env(env_file, updates)
        values.update(updates)

    if require_token and not current_token(values):
        print(
            "Telegram configuration failed: TELEGRAM_BOT_TOKEN is empty. "
            "Set TELEGRAM_BOT_TOKEN in /opt/marine_track/.env or pass it as environment variable.",
        )
        return 2
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="Configure Telegram bot token/admin ids in .env")
    parser.add_argument("--env-file", default=".env")
    parser.add_argument("--yes", action="store_true", help="Do not prompt")
    parser.add_argument("--require-token", action="store_true", help="Exit non-zero when token is still empty")
    args = parser.parse_args()
    return configure(Path(args.env_file), assume_yes=args.yes, require_token=args.require_token)


if __name__ == "__main__":
    raise SystemExit(main())
