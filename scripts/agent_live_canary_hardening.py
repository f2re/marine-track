from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

live = ROOT / "src" / "marine_track" / "live_canary.py"
text = live.read_text(encoding="utf-8")
text = text.replace(
    'SECRET_PATTERN = re.compile(\n'
    '    r"(?i)(authorization|bearer|token|secret|password|api[_-]?key)"\n'
    '    r"(\\s*[:=]\\s*)([^\\s,;]+)"\n'
    ')\n',
    'SECRET_PATTERN = re.compile(\n'
    '    r"(?i)(authorization|bearer|token|secret|password|api[_-]?key)"\n'
    '    r"(\\s*[:=]\\s*)([^\\s,;]+)"\n'
    ')\n'
    'ABSOLUTE_PATH_PATTERN = re.compile(\n'
    '    r"(?<![:/\\w])/(?:[^/\\s]+/)*[^/\\s,;]+"\n'
    ')\n',
    1,
)
text = text.replace(
    '    text = SECRET_PATTERN.sub(lambda match: f"{match.group(1)}{match.group(2)}<redacted>", text)\n'
    '    return " ".join(text.split())[:700]\n',
    '    text = SECRET_PATTERN.sub(\n'
    '        lambda match: f"{match.group(1)}{match.group(2)}<redacted>",\n'
    '        text,\n'
    '    )\n'
    '    text = ABSOLUTE_PATH_PATTERN.sub("<path-redacted>", text)\n'
    '    return " ".join(text.split())[:700]\n',
    1,
)
live.write_text(text, encoding="utf-8")

selftest = ROOT / "src" / "marine_track" / "telegram_selftest.py"
text = selftest.read_text(encoding="utf-8")
text = text.replace(
    'from marine_track.live_canary import LiveCanaryResult, run_live_canary\n',
    'from marine_track.live_canary import (\n'
    '    LiveCanaryResult,\n'
    '    run_live_canary,\n'
    '    sanitize_detail,\n'
    ')\n',
    1,
)
text = text.replace(
    '                    f"⛔ Live self-test не запущен\\n<code>{html.escape(str(exc))}</code>",\n',
    '                    "⛔ Live self-test не запущен\\n"\n'
    '                    f"<code>{html.escape(sanitize_detail(exc))}</code>",\n',
    1,
)
selftest.write_text(text, encoding="utf-8")

bot = ROOT / "src" / "marine_track" / "telegram_bot.py"
text = bot.read_text(encoding="utf-8")
text = text.replace(
    'async def selftest_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:\n'
    '    await admin_selftest_command(update, context, get_config())\n',
    'async def selftest_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:\n'
    '    async with get_semaphore():\n'
    '        await admin_selftest_command(update, context, get_config())\n',
    1,
)
text = text.replace(
    'async def selftest_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:\n'
    '    await admin_selftest_callback(update, context, get_config())\n',
    'async def selftest_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:\n'
    '    async with get_semaphore():\n'
    '        await admin_selftest_callback(update, context, get_config())\n',
    1,
)
bot.write_text(text, encoding="utf-8")

test = ROOT / "tests" / "test_live_canary.py"
text = test.read_text(encoding="utf-8")
text = text.replace(
    '        "GET https://example.test/a.tif?sig=abc token=abc Authorization:Bearer-abc"\n',
    '        "GET https://example.test/a.tif?sig=abc token=abc "\n'
    '        "Authorization:Bearer-abc /var/lib/marine-track/private/report.json"\n',
    1,
)
text = text.replace(
    '    assert "Bearer-abc" not in text\n',
    '    assert "Bearer-abc" not in text\n'
    '    assert "/var/lib/marine-track" not in text\n'
    '    assert "<path-redacted>" in text\n',
    1,
)
test.write_text(text, encoding="utf-8")

print("live canary hardening applied")
