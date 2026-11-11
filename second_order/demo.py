"""The committed showcase reads local fixtures and never contacts a provider.

Its market data are the FICTIONAL demonstration series of fixtures/demo-market.json (invented by demo_market.py), and
its two cases are fictional events; nothing here is a market observation or research evidence.
"""
from datetime import datetime, timezone
import json
from pathlib import Path
from .data import Observation, Series
from .demo_market import VERSION as DEMO_VERSION
from .evaluation import evaluate, scoreboard
from .registry import is_demo
from .schema import Hypothesis
from .scoring import Rules
from .store import freeze, open_store, save_evaluation

FIXTURES = Path(__file__).resolve().parent.parent / "fixtures"
DEMO_MARKET = FIXTURES / "demo-market.json"
SHOWCASE_AS_OF = datetime(2024, 12, 31, 23, 59, 59, tzinfo=timezone.utc)  # End of the committed fixture.


def load_showcases(path: Path = FIXTURES / "showcase.json") -> list[Hypothesis]:
    return [Hypothesis.model_validate(value) for value in json.loads(path.read_text(encoding="utf-8"))]


def load_provenance(path: Path = DEMO_MARKET) -> dict[str, dict]:
    """Per-series provenance of the fictional series: what they are, their generator and version, the timestamp
    caveat."""
    payload = json.loads(path.read_text(encoding="utf-8"))
    shared = {key: payload[key] for key in ("description", "version", "generator", "timestamp_basis",
                                            "timestamp_note")}
    return {key: {**shared, "provider": row["provider"], "ticker": row["ticker"], "price_basis": row["price_basis"]}
            for key, row in payload["rows"].items()}


def load_market(path: Path = DEMO_MARKET) -> dict[str, Series]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    return {
        key: Series(key, tuple(Observation(datetime.fromisoformat(day + "T23:59:59+00:00"), value)
                               for day, value in row["rows"]),
                    source=f'{row["provider"]}:{row["ticker"]}',
                    basis=row["price_basis"], timestamp_basis=payload["timestamp_basis"])
        for key, row in payload["rows"].items()
    }


def demo_only(hypothesis: Hypothesis) -> bool:
    """Whether the demo fixture is the data for every leg: each one names a fictional demonstration series."""
    return all(is_demo(leg.observable_id) for leg in hypothesis.legs)


def run_demo(db_path: str = ":memory:") -> dict:
    hypotheses = load_showcases()
    market = load_market()
    as_of = SHOWCASE_AS_OF
    recorded_at = datetime.now(timezone.utc)
    connection = open_store(db_path)
    dossiers = []
    try:
        for hypothesis in hypotheses:
            identity = freeze(connection, hypothesis, recorded_at)
            result = evaluate(hypothesis, market, as_of)
            save_evaluation(connection, identity, result, recorded_at)
            dossiers.append({"id": identity, "headline": hypothesis.event.headline, **result})
    finally:
        connection.close()
    return {
        "mode": ("retrospective showcase of fictional events; manual hypotheses; FICTIONAL demonstration series "
                 f"({DEMO_VERSION}), not market observations"),
        "dossiers": dossiers,
        "research_scoreboards": {kind: scoreboard(dossiers, kind, Rules().hash) for kind in ("prospective", "replay")},
    }
