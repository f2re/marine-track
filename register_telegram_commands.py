from __future__ import annotations

import asyncio
import os
from pathlib import Path

from telegram import Bot

from marine_track.telegram_commands import BOT_COMMAND_LINES, BOT_COMMANDS


def load_env_file(path: Path) -> None:
    if not path.is_file():
        return
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        if key and key not in os.environ:
            os.environ[key] = value


def read_token() -> str:
    load_env_file(Path(__file__).resolve().parent / ".env")
    value = os.getenv("TELEGRAM_BOT_TOKEN") or os.getenv("BOT_TOKEN")
    if not value:
        raise RuntimeError("Telegram token is not configured")
    return value


async def register_commands() -> None:
    bot = Bot(read_token())
    await bot.set_my_commands(list(BOT_COMMANDS))


def main() -> None:
    asyncio.run(register_commands())
    print("Telegram commands registered:")
    for line in BOT_COMMAND_LINES:
        print(f"  {line}")


if __name__ == "__main__":
    main()
