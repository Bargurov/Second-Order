"""Tests for ``news_fetch`` candidate_id contract and record shape.

Pin the contract:

* Every record built by ``_make_record`` (and therefore every row
  returned by ``load_local`` / ``load_rss`` / ``fetch_all``) carries a
  non-empty string ``candidate_id``.
* ``candidate_id`` is deterministic — same logical inputs produce the
  same id across calls and across processes.
* ``candidate_id`` distinguishes rows that differ on any of the four
  inputs that feed it (``source``, ``title``, ``published_at``,
  ``url``).
* ``candidate_id`` is invariant under the cosmetic normalizers already
  in the module — source aliases (``normalize_source``) and headline
  prefix / attribution noise (``normalize_headline``) — so the same
  logical row produces the same id under publisher rebrands or feed
  prefix variants.
* ``load_local`` exposes ``candidate_id`` on every row it returns from
  a local JSON fixture.  No DB, no provider, no FastAPI surface is
  imported by these tests.
"""
from __future__ import annotations

import json
import os
import sys
import tempfile
import unittest
import uuid

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from news_fetch import (  # noqa: E402
    _candidate_id,
    _make_record,
    load_local,
)


_RECORD_KEYS = {
    "source",
    "title",
    "published_at",
    "url",
    "candidate_id",
}


class TestRecordShape(unittest.TestCase):
    def test_make_record_has_candidate_id(self) -> None:
        rec = _make_record(
            source="Reuters World",
            title="OPEC agrees to extend voluntary output cuts through next quarter",
            published_at="2026-04-05T10:30:00",
            url="https://example.com/opec-extends-cuts",
        )
        self.assertEqual(set(rec.keys()), _RECORD_KEYS)
        cid = rec["candidate_id"]
        self.assertIsInstance(cid, str)
        self.assertTrue(cid)

    def test_candidate_id_is_hex_and_fixed_length(self) -> None:
        rec = _make_record(
            source="Reuters World",
            title="OPEC agrees to extend voluntary output cuts",
            published_at="2026-04-05T10:30:00",
            url="https://example.com/opec",
        )
        cid = rec["candidate_id"]
        # 16 hex chars = 64 bits of entropy from a SHA-256 prefix.
        self.assertEqual(len(cid), 16)
        self.assertTrue(all(c in "0123456789abcdef" for c in cid))


class TestDeterminism(unittest.TestCase):
    def test_same_inputs_produce_same_id(self) -> None:
        kwargs = dict(
            source="BBC Business",
            title="Sanctions package targets Russian aluminum producer",
            published_at="2026-04-05T10:30:00",
            url="https://example.com/al-sanctions",
        )
        a = _make_record(**kwargs)
        b = _make_record(**kwargs)
        self.assertEqual(a["candidate_id"], b["candidate_id"])

    def test_candidate_id_helper_matches_make_record(self) -> None:
        # The standalone _candidate_id() helper must agree with what
        # _make_record() embeds in the record.  This pins the public
        # contract: callers can recompute the id from raw inputs.
        source = "Reuters World"
        title = "OPEC agrees to extend voluntary output cuts"
        published_at = "2026-04-05T10:30:00"
        url = "https://example.com/opec"
        rec = _make_record(
            source=source, title=title, published_at=published_at, url=url,
        )
        # _candidate_id keys on the post-normalization fields; reconstruct
        # them the same way _make_record does.
        from news_fetch import _normalize_timestamp, normalize_headline
        norm_pub = _normalize_timestamp(published_at)
        # The helper takes RAW title (it normalizes internally), so pass raw.
        self.assertEqual(
            rec["candidate_id"],
            _candidate_id(source, title, norm_pub, url.strip()),
        )
        # And invariance: passing the already-normalized title still
        # produces the same id (normalize_headline is idempotent on
        # already-clean input).
        self.assertEqual(
            rec["candidate_id"],
            _candidate_id(source, normalize_headline(title), norm_pub, url.strip()),
        )


class TestUniqueness(unittest.TestCase):
    _BASE = dict(
        source="Reuters World",
        title="OPEC agrees to extend voluntary output cuts",
        published_at="2026-04-05T10:30:00",
        url="https://example.com/opec",
    )

    def _id(self, **overrides) -> str:
        kwargs = dict(self._BASE, **overrides)
        return _make_record(**kwargs)["candidate_id"]

    def test_different_url_different_id(self) -> None:
        self.assertNotEqual(
            self._id(),
            self._id(url="https://example.com/opec-other"),
        )

    def test_different_title_different_id(self) -> None:
        self.assertNotEqual(
            self._id(),
            self._id(title="OPEC raises production quotas for next quarter"),
        )

    def test_different_published_at_different_id(self) -> None:
        self.assertNotEqual(
            self._id(),
            self._id(published_at="2026-04-06T10:30:00"),
        )

    def test_different_source_different_id(self) -> None:
        # Two genuinely different publishers (no alias mapping between
        # them) → must produce different ids.
        self.assertNotEqual(
            self._id(source="Reuters World"),
            self._id(source="BBC Business"),
        )


class TestNormalizationInvariance(unittest.TestCase):
    """Same logical row → same candidate_id even under cosmetic noise."""

    def test_source_alias_invariance(self) -> None:
        # "BBC Business" and "BBC World" both canonicalize to "BBC" via
        # normalize_source — the candidate_id should not split them.
        a = _make_record(
            source="BBC Business",
            title="Sanctions package targets Russian aluminum producer",
            published_at="2026-04-05T10:30:00",
            url="https://example.com/al-sanctions",
        )
        b = _make_record(
            source="BBC World",
            title="Sanctions package targets Russian aluminum producer",
            published_at="2026-04-05T10:30:00",
            url="https://example.com/al-sanctions",
        )
        self.assertEqual(a["candidate_id"], b["candidate_id"])

    def test_headline_prefix_invariance(self) -> None:
        # The same row arriving with a "Reuters: " prefix and without
        # one should produce the same candidate_id, because the id is
        # keyed on normalize_headline(title).
        plain = _make_record(
            source="Reuters World",
            title="OPEC agrees to extend voluntary output cuts",
            published_at="2026-04-05T10:30:00",
            url="https://example.com/opec",
        )
        prefixed = _make_record(
            source="Reuters World",
            title="Reuters: OPEC agrees to extend voluntary output cuts",
            published_at="2026-04-05T10:30:00",
            url="https://example.com/opec",
        )
        self.assertEqual(plain["candidate_id"], prefixed["candidate_id"])

    def test_headline_attribution_invariance(self) -> None:
        # Trailing "- Reuters" attribution noise must also collapse.
        plain = _make_record(
            source="Reuters World",
            title="OPEC agrees to extend voluntary output cuts",
            published_at="2026-04-05T10:30:00",
            url="https://example.com/opec",
        )
        attributed = _make_record(
            source="Reuters World",
            title="OPEC agrees to extend voluntary output cuts - Reuters",
            published_at="2026-04-05T10:30:00",
            url="https://example.com/opec",
        )
        self.assertEqual(plain["candidate_id"], attributed["candidate_id"])


class TestLoadLocalEmitsCandidateId(unittest.TestCase):
    def test_every_loaded_row_has_candidate_id(self) -> None:
        fixture = [
            {
                "source": "Reuters World",
                "title": "OPEC agrees to extend voluntary output cuts",
                "published_at": "2026-04-05T10:30:00",
                "url": "https://example.com/opec",
            },
            {
                "source": "BBC Business",
                "title": "Sanctions package targets Russian aluminum producer",
                "published_at": "2026-04-05T11:00:00",
                "url": "https://example.com/al-sanctions",
            },
            {
                "source": "local",
                "title": "Operator-curated headline with no url",
                "published_at": "2026-04-05",
                # no url field on purpose
            },
        ]
        path = os.path.join(
            tempfile.gettempdir(),
            f"test_news_inbox_{uuid.uuid4().hex}.json",
        )
        try:
            with open(path, "w", encoding="utf-8") as fh:
                json.dump(fixture, fh)
            records = load_local(path)
        finally:
            if os.path.exists(path):
                os.unlink(path)

        self.assertEqual(len(records), len(fixture))
        seen_ids: set[str] = set()
        for rec in records:
            self.assertEqual(set(rec.keys()), _RECORD_KEYS)
            cid = rec["candidate_id"]
            self.assertIsInstance(cid, str)
            self.assertEqual(len(cid), 16)
            seen_ids.add(cid)
        # Three distinct fixture rows → three distinct candidate_ids.
        self.assertEqual(len(seen_ids), len(fixture))

    def test_missing_file_returns_empty_list(self) -> None:
        # Sanity: pre-existing load_local contract still holds — no
        # candidate_id work blows up when the file is absent.
        missing = os.path.join(
            tempfile.gettempdir(),
            f"definitely_does_not_exist_{uuid.uuid4().hex}.json",
        )
        self.assertEqual(load_local(missing), [])


if __name__ == "__main__":
    unittest.main()
