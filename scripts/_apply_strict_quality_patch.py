from __future__ import annotations

from pathlib import Path


path = Path("src/forex_trader/research/backtest.py")
text = path.read_text()
old = "    reward = abs(candidate.take_profit - entry_fill)\n"
if old not in text:
    raise RuntimeError("expected reward assignment was not found")
path.write_text(text.replace(old, "", 1))
