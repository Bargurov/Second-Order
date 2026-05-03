"""Cached country macro-vulnerability backdrop.

A small in-process registry of stable external-balance facts per
country, plus a deterministic normaliser that turns those raw numbers
into a compact vulnerability block consumers can render or score
against.  Pure module-level constants — no I/O, no live fetches.

Why a fourth country module
---------------------------
``country_profiles.py`` carries qualitative tiers + integer commodity
sensitivities, ``country_vulnerability.py`` carries a hand-curated
``resilient / moderate / vulnerable / fragile`` tier per country, and
``country_fx_passthrough.py`` carries FX betas + commodity exposure
ints.  None of them carry the six quantitative external-balance
fields a desk research engine actually wants when it asks "is this
country running a thin reserve buffer or a thick one?":

    reserves_months_import      – imports of goods+services (months)
    current_account_pct_gdp     – +ve = surplus
    external_debt_pct_exports   – % of annual exports of g+s
    fuel_import_dependence      – 0..1 share of fuel needs imported
    food_import_dependence      – 0..1 share of food needs imported
    commodity_export_share      – 0..1 share of exports that are
                                  unprocessed commodities (oil, gas,
                                  metals, ag).  Two-edged: high =
                                  windfall under up-trend, exposure
                                  under down-trend.

These six are stable enough to live in a vendored fixture (annual
numbers move slowly; the buckets are coarse).  When a feed lands
later, the fixture path can be replaced with a refresher without
changing the normaliser or any caller.

Public surface
--------------
* ``COUNTRY_BACKDROP_FIXTURE`` — the registry itself, keyed by
  canonical country name.  ``"iso"`` is supplied for resolver use
  but not consumed by the normaliser.
* ``get_country_backdrop(name)`` — return the raw fixture entry or
  ``None`` when the country is not profiled.  Match is
  case-insensitive on canonical name.
* ``normalize_country_backdrop(name)`` — return the normalised output
  block.  ``None`` when the country isn't profiled (callers should
  treat that as "no block to attach", per the task contract).
* ``attach_country_backdrop(exposures)`` — list-mutation helper used
  by the overlay composers: walks an existing exposure list and
  stamps a ``country_backdrop`` block onto every entry whose
  ``country`` resolves.  Entries that don't resolve pass through
  byte-identically (no key added).

Vocabulary alignment
--------------------
Bucket names match ``country_vulnerability.TIER_ORDER``
(``resilient / moderate / vulnerable / fragile``) so a caller doesn't
have to reconcile two stress vocabularies.  ``commodity_dependence``
uses its own ``low / moderate / high / dominant`` axis because it
isn't a stress dimension — high commodity dependence is two-edged.
"""

from __future__ import annotations

from typing import Any, Optional


# ---------------------------------------------------------------------------
# Fixture — six stable fields per country.  Numbers are coarse desk
# priors, not feed-grade exactness.  Add countries in alphabetical
# order within each region for grep-ability.
# ---------------------------------------------------------------------------

_REQUIRED_FIELDS: tuple[str, ...] = (
    "reserves_months_import",
    "current_account_pct_gdp",
    "external_debt_pct_exports",
    "fuel_import_dependence",
    "food_import_dependence",
    "commodity_export_share",
)

# Each profile is the same closed shape: ``iso`` + the six fields.
COUNTRY_BACKDROP_FIXTURE: dict[str, dict[str, Any]] = {
    # ---- DM: included where they help validate the bucketing.
    "Norway": {
        "iso":                       "NO",
        "reserves_months_import":    36.0,   # SWF dwarfs reserves; effectively "infinite"
        "current_account_pct_gdp":   18.0,
        "external_debt_pct_exports": 110.0,
        "fuel_import_dependence":    0.00,
        "food_import_dependence":    0.30,
        "commodity_export_share":    0.65,
    },
    # ---- GCC
    "Saudi Arabia": {
        "iso":                       "SA",
        "reserves_months_import":    28.0,
        "current_account_pct_gdp":   4.0,
        "external_debt_pct_exports": 50.0,
        "fuel_import_dependence":    0.00,
        "food_import_dependence":    0.85,
        "commodity_export_share":    0.85,
    },
    # ---- EM EMEA
    "Turkey": {
        "iso":                       "TR",
        "reserves_months_import":    4.0,
        "current_account_pct_gdp":   -1.5,
        "external_debt_pct_exports": 240.0,
        "fuel_import_dependence":    0.95,
        "food_import_dependence":    0.20,
        "commodity_export_share":    0.05,
    },
    "Egypt": {
        "iso":                       "EG",
        "reserves_months_import":    5.0,
        "current_account_pct_gdp":   -1.5,
        "external_debt_pct_exports": 280.0,
        "fuel_import_dependence":    0.30,
        "food_import_dependence":    0.50,
        "commodity_export_share":    0.15,
    },
    "South Africa": {
        "iso":                       "ZA",
        "reserves_months_import":    5.0,
        "current_account_pct_gdp":   -2.5,
        "external_debt_pct_exports": 50.0,
        "fuel_import_dependence":    0.85,
        "food_import_dependence":    0.05,
        "commodity_export_share":    0.50,
    },
    # ---- EM Asia
    "India": {
        "iso":                       "IN",
        "reserves_months_import":    11.0,
        "current_account_pct_gdp":   -1.0,
        "external_debt_pct_exports": 80.0,
        "fuel_import_dependence":    0.85,
        "food_import_dependence":    0.05,
        "commodity_export_share":    0.10,
    },
    "Indonesia": {
        "iso":                       "ID",
        "reserves_months_import":    7.0,
        "current_account_pct_gdp":   -1.0,
        "external_debt_pct_exports": 100.0,
        "fuel_import_dependence":    0.50,
        "food_import_dependence":    0.10,
        "commodity_export_share":    0.45,
    },
    "Pakistan": {
        "iso":                       "PK",
        "reserves_months_import":    2.0,
        "current_account_pct_gdp":   -1.5,
        "external_debt_pct_exports": 270.0,
        "fuel_import_dependence":    0.85,
        "food_import_dependence":    0.20,
        "commodity_export_share":    0.10,
    },
    # ---- EM LatAm
    "Argentina": {
        "iso":                       "AR",
        "reserves_months_import":    1.0,
        "current_account_pct_gdp":   -2.0,
        "external_debt_pct_exports": 320.0,
        "fuel_import_dependence":    0.20,
        "food_import_dependence":    0.05,
        "commodity_export_share":    0.65,
    },
    "Brazil": {
        "iso":                       "BR",
        "reserves_months_import":    15.0,
        "current_account_pct_gdp":   -2.0,
        "external_debt_pct_exports": 150.0,
        "fuel_import_dependence":    0.10,
        "food_import_dependence":    0.05,
        "commodity_export_share":    0.55,
    },
    "Chile": {
        "iso":                       "CL",
        "reserves_months_import":    9.0,
        "current_account_pct_gdp":   -3.0,
        "external_debt_pct_exports": 200.0,
        "fuel_import_dependence":    0.85,
        "food_import_dependence":    0.30,
        "commodity_export_share":    0.55,
    },
}


# ---------------------------------------------------------------------------
# Bucket vocabularies.  Names match country_vulnerability.TIER_ORDER for
# the two stress dimensions; commodity_dependence uses its own axis
# because high commodity exports are two-edged, not strictly worse.
# ---------------------------------------------------------------------------

VULNERABILITY_TIERS: tuple[str, ...] = (
    "resilient", "moderate", "vulnerable", "fragile",
)

COMMODITY_TIERS: tuple[str, ...] = (
    "low", "moderate", "high", "dominant",
)

_TIER_RANK: dict[str, int] = {t: i for i, t in enumerate(VULNERABILITY_TIERS)}


# ---------------------------------------------------------------------------
# Bucketing — every threshold pinned as a module constant so a reviewer
# can trace any output back to a single place and ``calibrate_thresholds``
# could audit them later.
# ---------------------------------------------------------------------------

# Reserve coverage in months of imports.
_RESERVE_THIN_MO:    float = 3.0
_RESERVE_MOD_MO:     float = 6.0
_RESERVE_STRONG_MO:  float = 12.0

# Current account as % of GDP (negative = deficit).
_CA_DEEP_DEFICIT:   float = -4.0
_CA_DEFICIT:        float = -2.0
_CA_NEUTRAL:        float = 0.0

# External debt as % of annual exports.
_EXT_DEBT_LOW:      float = 100.0
_EXT_DEBT_MOD:      float = 200.0
_EXT_DEBT_HIGH:     float = 300.0

# Import-dependence shares (0..1).
_IMPORT_LOW:        float = 0.25
_IMPORT_MOD:        float = 0.50
_IMPORT_HIGH:       float = 0.80

# Commodity-export shares (0..1).
_COMMODITY_LOW:     float = 0.10
_COMMODITY_MOD:     float = 0.30
_COMMODITY_HIGH:    float = 0.60


def _reserve_tier(months: float) -> str:
    if months >= _RESERVE_STRONG_MO:
        return "resilient"
    if months >= _RESERVE_MOD_MO:
        return "moderate"
    if months >= _RESERVE_THIN_MO:
        return "vulnerable"
    return "fragile"


def _ca_tier(ca_pct: float) -> str:
    if ca_pct >= _CA_NEUTRAL:
        return "resilient"
    if ca_pct >= _CA_DEFICIT:
        return "moderate"
    if ca_pct >= _CA_DEEP_DEFICIT:
        return "vulnerable"
    return "fragile"


def _ext_debt_tier(ratio: float) -> str:
    if ratio < _EXT_DEBT_LOW:
        return "resilient"
    if ratio < _EXT_DEBT_MOD:
        return "moderate"
    if ratio < _EXT_DEBT_HIGH:
        return "vulnerable"
    return "fragile"


def _import_tier(share: float) -> str:
    if share < _IMPORT_LOW:
        return "resilient"
    if share < _IMPORT_MOD:
        return "moderate"
    if share < _IMPORT_HIGH:
        return "vulnerable"
    return "fragile"


def _commodity_tier(share: float) -> str:
    if share < _COMMODITY_LOW:
        return "low"
    if share < _COMMODITY_MOD:
        return "moderate"
    if share < _COMMODITY_HIGH:
        return "high"
    return "dominant"


def _worst(*tiers: str) -> str:
    """Return the most-fragile tier among the inputs (rank order)."""
    best_rank = -1
    worst_label = VULNERABILITY_TIERS[0]
    for t in tiers:
        rank = _TIER_RANK.get(t, -1)
        if rank > best_rank:
            best_rank = rank
            worst_label = t
    return worst_label


# ---------------------------------------------------------------------------
# Lookup + normalisation
# ---------------------------------------------------------------------------

def get_country_backdrop(name: Optional[str]) -> Optional[dict[str, Any]]:
    """Return the raw fixture entry for ``name`` or ``None`` if unknown.

    Matching is case-insensitive on the canonical fixture key.  No
    alias resolution — if a caller passes an alternative spelling that
    doesn't match a fixture key the result is ``None`` and the caller
    skips attachment, which preserves the "no profile → unchanged"
    contract.
    """
    if not isinstance(name, str) or not name.strip():
        return None
    key = name.strip().lower()
    for fixture_name, payload in COUNTRY_BACKDROP_FIXTURE.items():
        if fixture_name.lower() == key:
            return payload
    return None


def _missing_fields(profile: dict) -> list[str]:
    """Return field names with non-numeric / missing values."""
    missing: list[str] = []
    for f in _REQUIRED_FIELDS:
        v = profile.get(f)
        if v is None or isinstance(v, bool) or not isinstance(v, (int, float)):
            missing.append(f)
    return missing


def normalize_country_backdrop(
    name: Optional[str],
    profile: Optional[dict[str, Any]] = None,
) -> Optional[dict[str, Any]]:
    """Return the normalised vulnerability block for a country.

    Pass ``profile`` to skip the fixture lookup (used by tests +
    callers that already hold the fixture row).  Returns ``None`` when
    ``name`` doesn't resolve to a fixture entry — callers should treat
    that as "no block to attach".

    The returned dict has the stable shape:

        {
          "country":               str,
          "external_balance_risk": tier,
          "import_shock_risk":     tier,
          "commodity_dependence":  commodity tier,
          "overall_vulnerability": tier,
          "rationale":             str,
          "stale":                 bool,    # True when any input field missing
        }

    ``overall_vulnerability`` is the *worst* of
    ``external_balance_risk`` / ``import_shock_risk``, except that a
    ``resilient`` external balance caps overall at ``resilient``: a
    country whose reserves dwarf any import bill (Saudi Arabia, Norway)
    is not "vulnerable" because of food import dependence — it can pay
    for the food.  ``commodity_dependence`` is reported but does not
    drive the overall — high commodity exports are two-edged.
    """
    if profile is None:
        profile = get_country_backdrop(name)
    if profile is None:
        return None

    missing = _missing_fields(profile)

    def _f(field: str, default: float) -> float:
        v = profile.get(field)
        if isinstance(v, bool) or not isinstance(v, (int, float)):
            return default
        return float(v)

    reserves = _f("reserves_months_import",    6.0)
    ca       = _f("current_account_pct_gdp",   0.0)
    ext_debt = _f("external_debt_pct_exports", 100.0)
    fuel     = _f("fuel_import_dependence",    0.0)
    food     = _f("food_import_dependence",    0.0)
    cmdty    = _f("commodity_export_share",    0.0)

    reserve_t  = _reserve_tier(reserves)
    ca_t       = _ca_tier(ca)
    ext_debt_t = _ext_debt_tier(ext_debt)

    external_balance_risk = _worst(reserve_t, ca_t, ext_debt_t)
    import_shock_risk     = _import_tier(max(fuel, food))
    commodity_dependence  = _commodity_tier(cmdty)

    if external_balance_risk == "resilient":
        # A country with deep reserves + surplus + low ext-debt absorbs
        # import shocks via the balance sheet — don't degrade the
        # overall read because of food/fuel reliance alone.
        overall_vulnerability = "resilient"
    else:
        overall_vulnerability = _worst(external_balance_risk, import_shock_risk)
        # Cap: a moderate external balance still buffers against pure
        # import-dependence shocks.  Don't escalate the overall to
        # ``fragile`` when ``external_balance_risk`` is ``moderate``;
        # only an external-balance miss should land that label.  Same
        # spirit as the resilient cap above.  Validated on India
        # (reserves 11mo + ext_debt 80%, fuel imports 85%) — without
        # this cap that profile would land ``fragile`` purely on fuel
        # dependence, which contradicts the desk prior.
        if (
            external_balance_risk == "moderate"
            and _TIER_RANK[overall_vulnerability] > _TIER_RANK["vulnerable"]
        ):
            overall_vulnerability = "vulnerable"

    bits: list[str] = []
    bits.append(
        f"reserves {reserves:.0f}mo · CA {ca:+.1f}% · "
        f"ext debt {ext_debt:.0f}% of exports → external {external_balance_risk}"
    )
    bits.append(
        f"fuel imports {int(round(fuel * 100))}% · "
        f"food imports {int(round(food * 100))}% → imports {import_shock_risk}"
    )
    if commodity_dependence != "low":
        bits.append(
            f"commodity exports {int(round(cmdty * 100))}% of total → "
            f"{commodity_dependence}"
        )
    rationale = "; ".join(bits)

    canonical_name = name
    if isinstance(name, str):
        for fixture_name in COUNTRY_BACKDROP_FIXTURE:
            if fixture_name.lower() == name.strip().lower():
                canonical_name = fixture_name
                break

    return {
        "country":               canonical_name,
        "external_balance_risk": external_balance_risk,
        "import_shock_risk":     import_shock_risk,
        "commodity_dependence":  commodity_dependence,
        "overall_vulnerability": overall_vulnerability,
        "rationale":             rationale,
        "stale":                 bool(missing),
    }


def _find_country_in_text(text: Optional[str]) -> Optional[str]:
    """Return the first fixture country name mentioned in ``text``.

    Case-insensitive substring match.  Longest-name-first to avoid
    short prefixes swallowing a more-specific entry (e.g. a future
    registry that added both "India" and "Indonesia" would still
    resolve "Indonesia" correctly on a headline about Indonesia).
    Returns ``None`` when nothing matches — callers should treat that
    as "no country mapping for this event" and write ``{}``.
    """
    if not isinstance(text, str) or not text.strip():
        return None
    needle = text.lower()
    # Sort by descending length so "Saudi Arabia" takes precedence
    # over any hypothetical "Saudi" entry.
    for name in sorted(COUNTRY_BACKDROP_FIXTURE.keys(), key=len, reverse=True):
        if name.lower() in needle:
            return name
    return None


def build_event_country_vulnerability_context(event: Optional[dict]) -> dict:
    """Return the ``country_vulnerability_context`` block for an event.

    Scans ``headline`` (then ``mechanism_summary``) for a fixture
    country name and delegates to ``normalize_country_backdrop`` when
    one is found.  Returns ``{}`` when the event doesn't mention any
    profiled country — callers rely on the route-side
    ``coerce_country_vulnerability_context`` helper for a fully-keyed
    default shape at the HTTP boundary.
    """
    if not isinstance(event, dict):
        return {}
    headline = event.get("headline") or ""
    mech = event.get("mechanism_summary") or ""
    name = _find_country_in_text(headline) or _find_country_in_text(mech)
    if name is None:
        return {}
    block = normalize_country_backdrop(name)
    return block or {}


_EMPTY_COUNTRY_VULNERABILITY_CONTEXT: dict = {
    "country":               None,
    "external_balance_risk": None,
    "import_shock_risk":     None,
    "commodity_dependence":  None,
    "overall_vulnerability": None,
    "rationale":             "",
    "stale":                 False,
}


def coerce_country_vulnerability_context(block: Optional[dict]) -> dict:
    """Return the canonical ``country_vulnerability_context`` shape.

    ``{}`` / ``None`` / any non-dict input collapses to the stable
    empty-shape dict (every key present, values ``None`` / ``""`` /
    ``False``).  Populated blocks keep their values; missing keys
    fill from the defaults so consumers can rely on the same keyset
    regardless of schema version or match state.
    """
    if not isinstance(block, dict) or not block:
        return dict(_EMPTY_COUNTRY_VULNERABILITY_CONTEXT)
    out = dict(_EMPTY_COUNTRY_VULNERABILITY_CONTEXT)
    for key in _EMPTY_COUNTRY_VULNERABILITY_CONTEXT:
        if key in block and block[key] is not None:
            out[key] = block[key]
    if out.get("rationale") is None:
        out["rationale"] = ""
    return out


def attach_country_backdrop(
    exposures: Optional[list[dict]],
) -> list[dict]:
    """Walk ``exposures`` and stamp a ``country_backdrop`` block on each
    entry whose ``country`` resolves to a fixture.

    Returns a NEW list — the input is not mutated.  Entries without a
    fixture profile pass through unchanged (no key added) so the "no
    country profile → keep current behavior" contract holds.  Non-dict
    or empty inputs come back as ``[]`` / passthrough so the helper
    never raises.
    """
    out: list[dict] = []
    for entry in exposures or []:
        if not isinstance(entry, dict):
            out.append(entry)
            continue
        name = entry.get("country")
        block = normalize_country_backdrop(name)
        if block is None:
            out.append(entry)
            continue
        new_entry = dict(entry)
        new_entry["country_backdrop"] = block
        out.append(new_entry)
    return out
