"""Archive-driven clustering by transmission path.

Groups archived events by the mechanism / transmission path they
embody rather than by headline wording.  The input is a list of event
dicts as returned by ``db.load_recent_events`` /
``db._decode_event_row`` (or live analysis dicts before persist); the
output is a bucket per transmission signature plus a clear rationale
describing what the signature was built from.

Two channel taxonomies live in the archive and they DO NOT mix:

1. Mechanism-transmission taxonomy
   (``transmission_path[].channel`` — how the shock travels)
   Enum: policy_gate | supply | demand | pricing_power |
         capital_flow | substitution | regulatory | sanction |
         tariff | rate_transmission

2. Market-channel taxonomy
   (``expected_first_order_channels`` + ``FAMILY_CHANNEL_PACKS`` —
    where the shock lands)
   Enum: rates | fx | commodities | vol | credit | equities

The two taxonomies answer different questions, so the signature
records which one it used ("kind") and signatures of different kind
never cluster together.  That keeps the match semantics clean:

- ``transmission_path`` clusters group events the LLM authored a
  structured transmission chain for.
- ``family_channels`` clusters group events where only the family +
  market channels are known (chain not stored / thin).
- ``family_only`` clusters group events where just the family is
  known.
- ``thin`` signatures never cluster — they fall through to the
  unclustered pool.

Clustering is greedy with a deterministic pre-sort so the same input
always produces the same clusters regardless of list order.

The module is a pure composer — it never performs I/O, never raises
on malformed input, and degrades cleanly when mechanism metadata is
missing.
"""

from __future__ import annotations

from typing import Any, Iterable, Optional

from mechanism_family import FAMILY_CHANNEL_PACKS


# ---------------------------------------------------------------------------
# Constants — pin the magic numbers so calibrate_thresholds.py can audit them.
# ---------------------------------------------------------------------------

# Similarity threshold above which two same-kind signatures merge.
# Separate thresholds per kind because the signatures carry different
# amounts of information: a real transmission_path encodes ordered
# mechanism channels so we can afford a slightly lower bar; a
# family_channels signature is shallower so we require tighter overlap.
_TRANSMISSION_MERGE_THRESHOLD: float = 0.60
_FAMILY_CHANNELS_MERGE_THRESHOLD: float = 0.70

# Weights for transmission_path × transmission_path similarity.
_TP_W_FAMILY: float = 0.40
_TP_W_CHANNEL_OVERLAP: float = 0.40
_TP_W_ORDERED_PREFIX: float = 0.15
_TP_W_LENGTH_SIM: float = 0.05

# Weights for family_channels × family_channels similarity.
_FC_W_FAMILY: float = 0.50
_FC_W_CHANNEL_OVERLAP: float = 0.40
_FC_W_EXACT_TUPLE: float = 0.10

# Known signature kinds, ordered from strongest to weakest evidence.
SIGNATURE_KINDS: tuple = (
    "transmission_path",
    "family_channels",
    "family_only",
    "thin",
)

# Valid mechanism-transmission channels (``transmission_path[].channel``).
_MECHANISM_CHANNELS: frozenset = frozenset({
    "policy_gate", "supply", "demand", "pricing_power",
    "capital_flow", "substitution", "regulatory",
    "sanction", "tariff", "rate_transmission",
})

# Valid market channels (``expected_*_order_channels`` + family packs).
_MARKET_CHANNELS: frozenset = frozenset({
    "rates", "fx", "commodities", "vol", "credit", "equities",
})

_KIND_LABEL: dict[str, str] = {
    "transmission_path": "structured transmission chain",
    "family_channels":   "mechanism family + market channels",
    "family_only":       "mechanism family only",
    "thin":              "insufficient mechanism metadata",
}


# ---------------------------------------------------------------------------
# Signature extraction
# ---------------------------------------------------------------------------

def _normalize_family(raw: Any) -> str:
    if not isinstance(raw, str):
        return "none"
    fam = raw.strip().lower()
    return fam or "none"


def _extract_transmission_channels(event: dict) -> tuple[str, ...]:
    """Return the ordered mechanism-channel tuple from transmission_path.

    Tolerates malformed rows: missing key, non-list, non-dict hops, or
    hops without ``channel`` are filtered out.  Consecutive duplicates
    are preserved — they're causally distinct steps — but unknown
    channel values are dropped so the enum stays clean.
    """
    path = event.get("transmission_path")
    if not isinstance(path, list):
        return ()
    channels: list[str] = []
    for hop in path:
        if not isinstance(hop, dict):
            continue
        ch = hop.get("channel")
        if isinstance(ch, str) and ch in _MECHANISM_CHANNELS:
            channels.append(ch)
    return tuple(channels)


def _extract_market_channels(event: dict, family: str) -> tuple[str, ...]:
    """Return ordered market-channel tuple from stored or default pack.

    Preference order:
      1. Stored ``expected_first_order_channels`` (what the LLM
         committed to for this specific event).
      2. ``FAMILY_CHANNEL_PACKS[family]["first"]`` (family default
         pack) when the stored list is empty.
      3. Empty tuple when neither is available.
    """
    stored = event.get("expected_first_order_channels")
    if isinstance(stored, list) and stored:
        seen: list[str] = []
        for ch in stored:
            if isinstance(ch, str) and ch in _MARKET_CHANNELS and ch not in seen:
                seen.append(ch)
        if seen:
            return tuple(seen)

    pack = FAMILY_CHANNEL_PACKS.get(family)
    if pack and pack.get("first"):
        return tuple(ch for ch in pack["first"] if ch in _MARKET_CHANNELS)

    return ()


def transmission_signature(event: Optional[dict]) -> dict:
    """Compute the transmission signature for an archived or live event.

    Returns a dict with stable keys:
      - ``kind``: one of SIGNATURE_KINDS
      - ``family``: normalized mechanism family (or "none")
      - ``channels``: tuple of channel names in causal order
      - ``channel_taxonomy``: "mechanism" | "market" | "none"
      - ``basis_label``: human-readable description
    """
    if not isinstance(event, dict):
        return {
            "kind": "thin",
            "family": "none",
            "channels": (),
            "channel_taxonomy": "none",
            "basis_label": _KIND_LABEL["thin"],
        }

    family = _normalize_family(event.get("mechanism_family"))

    mech_channels = _extract_transmission_channels(event)
    if mech_channels:
        return {
            "kind": "transmission_path",
            "family": family,
            "channels": mech_channels,
            "channel_taxonomy": "mechanism",
            "basis_label": _KIND_LABEL["transmission_path"],
        }

    if family != "none":
        market_channels = _extract_market_channels(event, family)
        if market_channels:
            return {
                "kind": "family_channels",
                "family": family,
                "channels": market_channels,
                "channel_taxonomy": "market",
                "basis_label": _KIND_LABEL["family_channels"],
            }
        return {
            "kind": "family_only",
            "family": family,
            "channels": (),
            "channel_taxonomy": "none",
            "basis_label": _KIND_LABEL["family_only"],
        }

    return {
        "kind": "thin",
        "family": "none",
        "channels": (),
        "channel_taxonomy": "none",
        "basis_label": _KIND_LABEL["thin"],
    }


# ---------------------------------------------------------------------------
# Similarity scoring (kind-aware)
# ---------------------------------------------------------------------------

def _jaccard(a: Iterable[str], b: Iterable[str]) -> float:
    sa, sb = set(a), set(b)
    if not sa and not sb:
        return 0.0
    inter = len(sa & sb)
    union = len(sa | sb)
    return inter / union if union else 0.0


def _ordered_prefix_match(a: tuple[str, ...], b: tuple[str, ...], k: int = 2) -> float:
    """Fraction of the first ``k`` channels that match in order.

    Returns 0.0 when either tuple is shorter than ``k``.
    """
    if len(a) < k or len(b) < k:
        return 0.0
    matches = sum(1 for i in range(k) if a[i] == b[i])
    return matches / k


def _length_similarity(a: tuple[str, ...], b: tuple[str, ...]) -> float:
    """1.0 when |len(a) - len(b)| <= 1, else 0.0."""
    return 1.0 if abs(len(a) - len(b)) <= 1 else 0.0


def transmission_similarity(sig_a: dict, sig_b: dict) -> float:
    """Kind-aware similarity in [0.0, 1.0].

    Different-kind pairs always score 0.0 — a transmission_path
    signature and a family_channels signature describe different
    things and cannot be meaningfully compared.
    """
    if not isinstance(sig_a, dict) or not isinstance(sig_b, dict):
        return 0.0
    kind = sig_a.get("kind")
    if kind != sig_b.get("kind"):
        return 0.0

    fam_match = 1.0 if sig_a.get("family") == sig_b.get("family") and sig_a.get("family") != "none" else 0.0
    ch_a = tuple(sig_a.get("channels") or ())
    ch_b = tuple(sig_b.get("channels") or ())

    if kind == "transmission_path":
        score = (
            _TP_W_FAMILY * fam_match
            + _TP_W_CHANNEL_OVERLAP * _jaccard(ch_a, ch_b)
            + _TP_W_ORDERED_PREFIX * _ordered_prefix_match(ch_a, ch_b, k=2)
            + _TP_W_LENGTH_SIM * _length_similarity(ch_a, ch_b)
        )
        return max(0.0, min(1.0, score))

    if kind == "family_channels":
        exact = 1.0 if ch_a and ch_a == ch_b else 0.0
        score = (
            _FC_W_FAMILY * fam_match
            + _FC_W_CHANNEL_OVERLAP * _jaccard(ch_a, ch_b)
            + _FC_W_EXACT_TUPLE * exact
        )
        return max(0.0, min(1.0, score))

    if kind == "family_only":
        return 1.0 if fam_match else 0.0

    return 0.0


# ---------------------------------------------------------------------------
# Clustering
# ---------------------------------------------------------------------------

def _threshold_for(kind: str) -> float:
    if kind == "transmission_path":
        return _TRANSMISSION_MERGE_THRESHOLD
    if kind == "family_channels":
        return _FAMILY_CHANNELS_MERGE_THRESHOLD
    if kind == "family_only":
        return 1.0  # only exact family matches merge
    return 2.0     # thin never merges


def _event_identity(event: dict) -> str:
    """Stable sort key / public id for an event.

    Prefers numeric id, falls back to headline + event_date so
    deduped rows still sort deterministically.
    """
    ev_id = event.get("id") or event.get("event_id")
    if ev_id is not None:
        return f"id:{ev_id}"
    hl = (event.get("headline") or "").strip().lower()
    dt = (event.get("event_date") or "").strip()
    return f"hl:{hl}|{dt}"


def _cluster_summary(members: list[dict]) -> dict:
    """Human-readable description of a cluster's basis."""
    if not members:
        return {"family": "none", "channels": (), "basis": "thin"}
    # All members share a kind by construction; use the first.
    sig = members[0]["signature"]
    return {
        "family": sig["family"],
        "channels": sig["channels"],
        "kind": sig["kind"],
        "basis": sig["kind"],
        "basis_label": sig["basis_label"],
    }


def cluster_events_by_transmission_path(
    events: Optional[list[dict]],
    threshold_override: Optional[float] = None,
) -> dict[str, Any]:
    """Group events by transmission signature.

    The algorithm:
      1. Compute each event's signature via ``transmission_signature``.
      2. Drop ``thin`` signatures into the ``unclustered`` pool.
      3. Sort the rest by (kind_rank, family, channels, identity) for
         deterministic greedy clustering.
      4. Walk sorted events; each one joins the best existing
         same-kind cluster whose representative scores above the
         kind's threshold, or opens a new cluster.
      5. Emit clusters with stable cluster_id, members, and a
         rationale describing the signature basis.

    Returns:
        {
          "available": bool,          # any clusters produced
          "clusters": [...],          # one entry per cluster
          "unclustered": [...],       # events that fell through
          "basis_distribution": {"transmission_path": n, ...},
          "rationale": str,           # one-line human summary
        }

    Never raises on malformed input.  Non-dict entries are skipped;
    missing keys fall back to "thin".
    """
    events = events or []

    indexed: list[dict] = []
    basis_dist: dict[str, int] = {k: 0 for k in SIGNATURE_KINDS}

    for ev in events:
        if not isinstance(ev, dict):
            continue
        sig = transmission_signature(ev)
        basis_dist[sig["kind"]] += 1
        indexed.append({
            "event": ev,
            "signature": sig,
            "identity": _event_identity(ev),
        })

    if not indexed:
        return {
            "available":          False,
            "clusters":           [],
            "unclustered":        [],
            "basis_distribution": basis_dist,
            "rationale":          "No events provided.",
        }

    kind_rank = {k: i for i, k in enumerate(SIGNATURE_KINDS)}

    # Deterministic sort: strongest-evidence kinds first, then by
    # family, then by channel tuple, then by identity.  Within a kind
    # bucket the earliest event opens the cluster.
    indexed.sort(key=lambda e: (
        kind_rank.get(e["signature"]["kind"], len(SIGNATURE_KINDS)),
        e["signature"]["family"],
        e["signature"]["channels"],
        e["identity"],
    ))

    clusters: list[dict] = []
    unclustered: list[dict] = []

    for entry in indexed:
        sig = entry["signature"]
        kind = sig["kind"]

        if kind == "thin":
            unclustered.append(entry)
            continue

        threshold = threshold_override if threshold_override is not None else _threshold_for(kind)

        best_cluster_idx: Optional[int] = None
        best_score: float = -1.0

        for idx, cluster in enumerate(clusters):
            # Compare against the cluster representative (first member
            # by insertion order) — cheap and deterministic.  We could
            # take the max over all members for a slightly looser
            # merge; representative-only keeps clusters tight and is
            # order-stable under the deterministic pre-sort above.
            rep_sig = cluster["members"][0]["signature"]
            if rep_sig["kind"] != kind:
                continue
            score = transmission_similarity(sig, rep_sig)
            if score >= threshold and score > best_score:
                best_score = score
                best_cluster_idx = idx

        if best_cluster_idx is not None:
            clusters[best_cluster_idx]["members"].append({
                "event": entry["event"],
                "signature": sig,
                "identity": entry["identity"],
                "similarity_to_rep": round(best_score, 3),
            })
        else:
            clusters.append({
                "members": [{
                    "event": entry["event"],
                    "signature": sig,
                    "identity": entry["identity"],
                    "similarity_to_rep": 1.0,  # representative of itself
                }],
            })

    # Shape the final output.  cluster_id is assigned after clustering
    # so numbering is stable under the deterministic pre-sort.
    out_clusters: list[dict] = []
    for i, c in enumerate(clusters):
        summary = _cluster_summary(c["members"])
        member_rows = [
            {
                "identity":           m["identity"],
                "event_id":           m["event"].get("id") or m["event"].get("event_id"),
                "headline":           m["event"].get("headline"),
                "event_date":         m["event"].get("event_date"),
                "mechanism_family":   m["signature"]["family"],
                "similarity_to_rep":  m["similarity_to_rep"],
            }
            for m in c["members"]
        ]
        out_clusters.append({
            "cluster_id":       i,
            "kind":             summary["kind"],
            "basis":            summary["basis"],
            "basis_label":      summary["basis_label"],
            "family":           summary["family"],
            "channels":         list(summary["channels"]),
            "size":             len(member_rows),
            "members":          member_rows,
            "rationale":        _cluster_rationale(summary, len(member_rows)),
        })

    unclustered_rows = [
        {
            "identity":         u["identity"],
            "event_id":         u["event"].get("id") or u["event"].get("event_id"),
            "headline":         u["event"].get("headline"),
            "event_date":       u["event"].get("event_date"),
            "mechanism_family": u["signature"]["family"],
            "kind":             u["signature"]["kind"],
        }
        for u in unclustered
    ]

    rationale = _aggregate_rationale(out_clusters, len(unclustered_rows), basis_dist)

    return {
        "available":          bool(out_clusters),
        "clusters":           out_clusters,
        "unclustered":        unclustered_rows,
        "basis_distribution": basis_dist,
        "rationale":          rationale,
    }


def _cluster_rationale(summary: dict, size: int) -> str:
    kind = summary.get("kind", "thin")
    family = summary.get("family", "none")
    channels = summary.get("channels") or ()
    ch_str = " → ".join(channels) if channels else "no channels"
    if kind == "transmission_path":
        return (
            f"{size} event(s) share the {family} family over the "
            f"transmission chain {ch_str}."
        )
    if kind == "family_channels":
        return (
            f"{size} event(s) share the {family} family with market "
            f"channels {ch_str} (no structured chain stored)."
        )
    if kind == "family_only":
        return (
            f"{size} event(s) share the {family} family; no channel "
            "detail available."
        )
    return f"{size} event(s) clustered on thin signature."


def _aggregate_rationale(
    clusters: list[dict],
    n_unclustered: int,
    basis: dict[str, int],
) -> str:
    if not clusters and not n_unclustered:
        return "No events provided."
    n_clusters = len(clusters)
    tp = basis.get("transmission_path", 0)
    fc = basis.get("family_channels", 0)
    fo = basis.get("family_only", 0)
    th = basis.get("thin", 0)
    parts: list[str] = []
    if n_clusters:
        parts.append(f"{n_clusters} cluster(s)")
    if tp:
        parts.append(f"{tp} on transmission chain")
    if fc:
        parts.append(f"{fc} on family+channels")
    if fo:
        parts.append(f"{fo} on family only")
    if th:
        parts.append(f"{th} unclustered (thin metadata)")
    return "; ".join(parts) if parts else "No signal."
