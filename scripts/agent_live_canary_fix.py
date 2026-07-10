from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

test = ROOT / "tests" / "test_live_canary.py"
text = test.read_text(encoding="utf-8")
text = text.replace(
    "    assert maxx - minx <= pytest.approx(0.08, abs=1e-9)\n"
    "    assert maxy - miny <= pytest.approx(0.08, abs=1e-9)\n",
    "    assert maxx - minx <= 0.080000001\n"
    "    assert maxy - miny <= 0.080000001\n",
    1,
)
test.write_text(text, encoding="utf-8")

module = ROOT / "src" / "marine_track" / "telegram_selftest.py"
text = module.read_text(encoding="utf-8")
text = text.replace("from pathlib import Path\n\n", "", 1)
module.write_text(text, encoding="utf-8")

print("live canary focused repairs applied")
