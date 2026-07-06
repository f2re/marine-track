from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import urlopen

PROJECT_DIR = Path(__file__).resolve().parent


def load_env(path: Path = PROJECT_DIR / ".env") -> None:
    if not path.is_file():
        return
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


def token_value() -> str:
    load_env()
    return (os.getenv("TELEGRAM_BOT_TOKEN") or os.getenv("BOT_TOKEN") or "").strip()


def main() -> int:
    token = token_value()
    if not token:
        print("Telegram healthcheck failed: TELEGRAM_BOT_TOKEN is empty", file=sys.stderr)
        return 2
    url = f"https://api.telegram.org/bot{token}/getMe"
    try:
        with urlopen(url, timeout=20) as response:  # noqa: S310
            payload = json.loads(response.read().decode("utf-8"))
    except HTTPError as exc:
        print(f"Telegram healthcheck failed: HTTP {exc.code}. Token is probably invalid.", file=sys.stderr)
        return 3
    except URLError as exc:
        print(f"Telegram healthcheck failed: network error: {exc}", file=sys.stderr)
        return 4
    except Exception as exc:  # noqa: BLE001
        print(f"Telegram healthcheck failed: {exc}", file=sys.stderr)
        return 5
    if not payload.get("ok"):
        print(f"Telegram healthcheck failed: {payload}", file=sys.stderr)
        return 6
    user = payload.get("result", {})
    print(
        "Telegram healthcheck OK: "
        f"id={user.get('id')} username=@{user.get('username')} name={user.get('first_name')}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
