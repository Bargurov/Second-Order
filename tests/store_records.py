"""Stored records as freezes wrote them before freshness policy B (decided 2026-10-11). Not a test module.

Tests of reading, evaluating and rebuilding stored records use these: a store may hold hypotheses frozen with a
baseline that ends before the last session before publication (the policy now refuses such a new freeze), and those
records are read, evaluated and prepared exactly as stored. The rows are exactly what store.freeze inserted then:
the hypothesis (its ID, request identity, recording time and canonical payload) and, for source-bound legs, its
baseline binding. Nothing is checked here; tests of the freeze itself use store.freeze.
"""
import sqlite3
from datetime import datetime

from second_order.schema import Hypothesis, utc
from second_order.store import canonical, digest, request_identity


def stored_before_policy_b(connection: sqlite3.Connection, hypothesis: Hypothesis, recorded_at: datetime,
                           baseline_snapshot_id: str | None = None) -> str:
    """Insert a hypothesis (and its baseline binding) as a pre-policy freeze stored it; returns its ID."""
    payload = hypothesis.model_dump(mode="json")
    identity = digest(payload)
    recorded = utc(recorded_at).isoformat()
    with connection:
        connection.execute("INSERT INTO hypotheses VALUES (?,?,?,?)",
                           (identity, request_identity(hypothesis), recorded, canonical(payload)))
        if baseline_snapshot_id is not None:
            connection.execute("INSERT INTO freeze_bindings VALUES (?,?,?)", (identity, baseline_snapshot_id, recorded))
    return identity
