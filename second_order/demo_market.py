"""FICTIONAL demonstration series for the offline demo (demo-market-0.1).

Every number this module produces is invented. Nothing here is, copies or approximates a market observation, and no
provider, ticker, capture or vintage stands behind it. Two series are made for business days (Monday to Friday) from
2022-01-03 to 2024-12-31:
- demo:rate, a fictional interest rate in percent (roughly 2.5 to 5.5);
- demo:fx-index, a fictional currency index (roughly 90 to 110).

Each value is an invented piecewise-linear path, plus a mean-reverting deviation driven by a fixed integer recurrence
(a linear congruential generator seeded with 20261110), plus two invented moves placed after the two fictional events
of fixtures/showcase.json: demo:rate falls clearly over the five sessions after the first (2024-06-12) and rises
clearly over the five sessions after the second (2024-10-30), and demo:fx-index falls on the session after the first.
All arithmetic is on integers (thousandths of a percent or of an index point), so the same code always gives the same
bytes; no clock, system randomness or network is used.

`python -m second_order.demo_market` rewrites fixtures/demo-market.json; a test checks that the committed file equals
build() byte for byte.
"""
from datetime import date, timedelta
import json
from pathlib import Path

VERSION = "demo-market-0.1"
GENERATOR = "second_order/demo_market.py"
FIXTURE = Path(__file__).resolve().parent.parent / "fixtures" / "demo-market.json"
SEED = 20261110
FIRST, LAST = date(2022, 1, 3), date(2024, 12, 31)
SCALE = 1000  # Values are integers in thousandths of the quoted unit until they are written.
DESCRIPTION = ("FICTIONAL demonstration series: every number is invented by second_order/demo_market.py; nothing here "
               "is a market observation. They serve only the offline demo's two showcase replays of fictional events "
               "and can never be research evidence.")
TIMESTAMP_NOTE = ("Each invented value is stamped 23:59:59 UTC on its business day for illustration; no observation "
                  "time exists, so research evaluation is gated.")

# Invented paths: (date, level in thousandths). Linear between the points; the shapes are made up for the demo.
RATE_PATH = ((date(2022, 1, 3), 2700), (date(2022, 8, 15), 3400), (date(2023, 3, 1), 4600),
             (date(2023, 8, 15), 4100), (date(2024, 2, 20), 5150), (date(2024, 6, 11), 4800),
             (date(2024, 9, 20), 4500), (date(2024, 12, 31), 4250))
FX_PATH = ((date(2022, 1, 3), 100000), (date(2022, 8, 10), 96000), (date(2023, 5, 15), 103500),
           (date(2024, 1, 22), 99000), (date(2024, 6, 11), 101500), (date(2024, 12, 31), 97500))
# Invented moves: the change added on each of the sessions after a fictional event, kept thereafter.
EVENT_MOVES = {
    "demo:rate": ((date(2024, 6, 12), (-150, -110, -80, -60, -50)),  # -45 bp over five sessions.
                  (date(2024, 10, 30), (120, 100, 80, 60, 40))),  # +40 bp over five sessions.
    "demo:fx-index": ((date(2024, 6, 12), (-1400,)),),  # -1.4 index points on one session.
}
SHOCKS = {"demo:rate": 80, "demo:fx-index": 450}  # Largest daily shock, in thousandths.
REVERSION = {"demo:rate": 8, "demo:fx-index": 16}  # A deviation loses 1/n of itself each session.
SERIES = (
    ("demo:rate", {"provider": "fictional-demo", "ticker": "DEMO-RATE", "price_basis": "fictional",
                   "unit": "percent", "label": "Fictional Demoland interest rate"}, RATE_PATH),
    ("demo:fx-index", {"provider": "fictional-demo", "ticker": "DEMO-FX", "price_basis": "fictional",
                       "unit": "index points", "label": "Fictional Demoland currency index"}, FX_PATH),
)


def business_days(first: date = FIRST, last: date = LAST) -> list[date]:
    days, day = [], first
    while day <= last:
        if day.weekday() < 5:
            days.append(day)
        day += timedelta(days=1)
    return days


class Recurrence:
    """A 64-bit linear congruential generator (Knuth's MMIX constants): a fixed integer recurrence, nothing more."""

    def __init__(self, seed: int = SEED):
        self.state = seed

    def shock(self, span: int) -> int:
        """An integer from -span to span."""
        self.state = (self.state * 6364136223846793005 + 1442695040888963407) % 2 ** 64
        return (self.state >> 33) % (2 * span + 1) - span


def path_level(path: tuple, day: date) -> int:
    for (start, low), (end, high) in zip(path, path[1:]):
        if start <= day <= end:
            return low + (high - low) * (day - start).days // (end - start).days
    raise ValueError(f"{day} is outside the invented path")


def toward_zero(value: int, divisor: int) -> int:
    return value // divisor if value >= 0 else -(-value // divisor)


def event_offsets(days: list[date], moves: tuple) -> list[int]:
    """Cumulative invented move at each day: each step applies from its session on and is kept thereafter."""
    steps = [0] * len(days)
    for start, changes in moves:
        first = next(i for i, day in enumerate(days) if day >= start)
        for i, change in enumerate(changes):
            steps[first + i] += change
    total, offsets = 0, []
    for step in steps:
        total += step
        offsets.append(total)
    return offsets


def build() -> dict:
    """The whole fixture payload, the same on every run."""
    days = business_days()
    recurrence = Recurrence()
    deviations = {key: 0 for key, _, _ in SERIES}
    levels = {key: [] for key, _, _ in SERIES}
    for day in days:
        for key, _, path in SERIES:  # One shock per series per day, always in this order.
            deviation = deviations[key]
            deviations[key] = deviation - toward_zero(deviation, REVERSION[key]) + recurrence.shock(SHOCKS[key])
            levels[key].append(path_level(path, day) + deviations[key])
    rows = {}
    for key, meta, _ in SERIES:
        offsets = event_offsets(days, EVENT_MOVES[key])
        rows[key] = {**meta, "rows": [[day.isoformat(), (level + offset) / SCALE]
                                      for day, level, offset in zip(days, levels[key], offsets)]}
    return {"description": DESCRIPTION, "version": VERSION, "generator": GENERATOR, "fictional": True,
            "timestamp_basis": "fictional_daily", "timestamp_note": TIMESTAMP_NOTE, "rows": rows}


def text() -> str:
    """The fixture file's exact text: JSON with one-space indents and a trailing newline (LF only)."""
    return json.dumps(build(), indent=1, ensure_ascii=False) + "\n"


def write(path: Path = FIXTURE) -> None:
    path.write_bytes(text().encode("utf-8"))


if __name__ == "__main__":
    write()
