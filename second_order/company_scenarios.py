"""FCX stage 2, the Scenarios tab's two calculations (company-scenario-0.1), on the company's assumptions for Q4 2026 as
the read resolves them (company_research_view.resolved: the four retained documents verified on every request).

- price_volume: copper sales value S = P × V (US dollars per pound × million pounds = US$ million) for an entered price
  P and volume sold V; its change against the same arithmetic at the company's price P0 and expected sales V0; and
  that change split in one fixed order (a-price-volume-split): volume effect (V − V0) × P0, price effect (P − P0) × V,
  which add up to S − P0 × V0 exactly. An approximation of copper sales value, not reported revenue, earnings or cash
  flow.
- cash_flow: the copper sensitivity in the October results release, applied linearly: the change in 2026
  consolidated operating cash flows ≈ (P − P0) ÷ step × sensitivity. Volumes, costs and the company's other
  assumptions stay as the company states them; no volume is taken, and the 10-K's older sensitivity is not used.

Inputs are text: a price above 0 and at most 100 US dollars per pound, to the cent; a volume above 0 and at most 5,000
million pounds, with at most one decimal. Every result is then exact with at most three decimals, so nothing is
rounded. A record a calculation uses that is withheld blocks it (409, naming the document, never a value). Nothing here
writes, stores, fetches or calls a model; every reply carries "stored": false and "provider_called": false.
"""
import re
from decimal import Decimal, localcontext
from pathlib import Path

from . import company_research_view as crv

SCENARIO_VERSION = "company-scenario-0.1"
PRICE = "r3-out-cu-price-q4-2026"
VOLUME = "r3-out-cu-sales-q4-2026"
SENSITIVITY = "r3-sens-ocf-copper"
STEP = "r3-sens-ocf-copper-step"
USES = {"price_volume": {"price": PRICE, "volume": VOLUME},
        "cash_flow": {"price": PRICE, "sensitivity": SENSITIVITY, "step": STEP}}
FIELDS = {"price_volume": {"mode", "price", "volume"}, "cash_flow": {"mode", "price"}}
UNIT = "USD millions"
NUMBER = re.compile(r"\d+(?:\.\d+)?", re.ASCII)
PRICE_TEXT = re.compile(r"\d{1,3}(?:\.\d{1,2})?", re.ASCII)
VOLUME_TEXT = re.compile(r"\d{1,4}(?:\.\d)?", re.ASCII)
MAX_PRICE, MAX_VOLUME = Decimal(100), Decimal(5000)
PRICE_RULE = "A copper price is US dollars per pound, written like 6.50: above zero and at most 100, to the cent"
PRICE_UNIT = ("A copper price above 100 is not US dollars per pound: enter the price per pound, not per tonne or in "
              "cents")
VOLUME_RULE = ("Copper sold is million pounds in the quarter, written like 875: above zero and at most 5,000, with at "
               "most one decimal")
REQUEST_RULE = ('A scenario request is {"mode": "price_volume", "price", "volume"} or {"mode": "cash_flow", "price"}, '
                "with the values written as text")
PRECISION = 60


class ScenarioRefused(crv.CompanyRefused):
    """A scenario that is not computed: 422 for a request outside the rules, 409 when a record it uses is withheld."""


def _entered(value: object, strict: re.Pattern, limit: Decimal, rule: str, too_large: str) -> Decimal:
    if not isinstance(value, str) or not NUMBER.fullmatch(value):
        raise ScenarioRefused(422, rule)
    number = Decimal(value)
    if number > limit:
        raise ScenarioRefused(422, too_large)
    if not strict.fullmatch(value) or number <= 0:
        raise ScenarioRefused(422, rule)
    return number


def price_of(value: object) -> Decimal:
    """An entered copper price in US dollars per pound."""
    return _entered(value, PRICE_TEXT, MAX_PRICE, PRICE_RULE, PRICE_UNIT)


def volume_of(value: object) -> Decimal:
    """An entered copper sales volume in million pounds."""
    return _entered(value, VOLUME_TEXT, MAX_VOLUME, VOLUME_RULE, VOLUME_RULE)


def request_of(body: object) -> tuple[str, Decimal, Decimal | None]:
    """The mode and the entered values of a request, or a refusal (422)."""
    mode = body.get("mode") if isinstance(body, dict) else None
    if not isinstance(mode, str) or mode not in FIELDS or set(body) != FIELDS[mode]:
        raise ScenarioRefused(422, REQUEST_RULE)
    return mode, price_of(body["price"]), volume_of(body["volume"]) if mode == "price_volume" else None


def exact(value: Decimal) -> str:
    """An exact decimal as plain text, without trailing zeros or an exponent."""
    return "0" if value == 0 else format(value.normalize(), "f")


def _blocked(used: dict, sources: dict) -> str:
    bad = sorted({sid for record in used.values() if record["state"] != "available"
                  for sid in record.get("rests_on", []) if sources[sid]["state"] != "verified"})
    if not bad:
        names = ", ".join(sorted(record["id"] for record in used.values() if record["state"] != "available"))
        return f"Not computed: it uses {names}, which is not shown."
    parts = [f"{crv.SHORT_NAMES[sid]}, which is {sources[sid]['state']}" for sid in bad]
    return f"Not computed: this calculation rests on {' and '.join(parts)} on this machine."


def compute(body: object, research: Path = crv.RESEARCH_DIR, sources_root: Path = crv.SOURCES_DIR) -> dict:
    """One scenario, exactly, on the records verified now (see the module docstring). Reads only."""
    mode, price, volume = request_of(body)
    sources, records, _ = crv.resolved(research, sources_root)
    used = {}
    for role, rid in USES[mode].items():
        record = records.get(rid)
        if record is None or record["kind"] == "assumption":
            raise crv.CompanyRefused(500, f"facts.json: {rid}, which a scenario uses, is not a figure")
        used[role] = record
    if any(record["state"] != "available" for record in used.values()):
        raise ScenarioRefused(409, _blocked(used, sources))
    values = {role: Decimal(record["value"]) for role, record in used.items()}
    with localcontext() as ctx:
        ctx.prec = PRECISION
        if mode == "price_volume":
            p0, v0 = values["price"], values["volume"]
            value, base = price * volume, p0 * v0
            change = value - base
            volume_effect, price_effect = (volume - v0) * p0, (price - p0) * volume
            if price_effect + volume_effect != change:
                raise crv.CompanyRefused(500, "The price and volume effects do not add up to the change")
            result = {"value": value, "base": base, "change": change, "price_effect": price_effect,
                      "volume_effect": volume_effect}
        else:
            p0, sensitivity, step = values["price"], values["sensitivity"], values["step"]
            if step <= 0:
                raise crv.CompanyRefused(500, f"facts.json: {STEP} is not a positive step")
            price_change = price - p0
            steps = price_change / step
            if steps * step != price_change:
                raise crv.CompanyRefused(500, "The price change is not an exact number of the sensitivity's steps")
            result = {"price_change": price_change, "steps": steps, "change": steps * sensitivity}
    inputs = {"price": body["price"], **({"volume": body["volume"]} if mode == "price_volume" else {})}
    return {
        "view_version": SCENARIO_VERSION,
        "mode": mode,
        "inputs": inputs,
        "uses": {role: {"record": record["id"], "value": record["value"]} for role, record in used.items()},
        "result": {key: exact(number) for key, number in result.items()},
        "unit": UNIT,
        "rests_on": sorted({sid for record in used.values() for sid in record["rests_on"]}),
        "stored": False,
        "provider_called": False,
    }
