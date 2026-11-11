"""Source-page continuation delegates to the server's current preparation, never the first history row at an Effort.

All accounts and sources are SYNTHETIC; preparation and reopening never quote, charge or call the fake provider.
The browser regression exercises the actual SourcePage button; these checks verify the server action it invokes.
"""
from unittest import mock

from account_fakes import every_file
from second_order import research_analysis as ra
from test_user_research import Base


class SourceContinuation(Base):
    def test_continuing_past_an_older_analysis_prepares_once_and_keeps_both_readable(self):
        source_id = self.source()
        with mock.patch.object(ra, "PROMPT_VERSION", "research-prompt-1"):
            older = self.prepare(source_id).json()["analysis"]["analysis_id"]
        saved = every_file(self.world.root / "research-analyses")
        account = self.account()
        detail = self.user.get(f"/api/user/sources/{source_id}").json()
        self.assertEqual([row["analysis_id"] for row in detail["analyses"]], [older])
        self.assertEqual(every_file(self.world.root / "research-analyses"), saved)

        reply = self.prepare(source_id)
        self.assertEqual(reply.status_code, 201, reply.text)
        current = reply.json()["analysis"]["analysis_id"]
        self.assertTrue(current.endswith(".research-prompt-2.high"), current)
        self.assertNotEqual(current, older)
        for path, contents in saved.items():
            self.assertEqual(every_file(self.world.root / "research-analyses")[path], contents)
        for analysis_id in (older, current):
            self.assertEqual(self.analysis(analysis_id)["state"], "prepared")
        detail = self.user.get(f"/api/user/sources/{source_id}").json()
        self.assertEqual({row["analysis_id"] for row in detail["analyses"]}, {older, current})

        # Continuing again returns the same current request, regardless of the earlier history entry.
        saved = every_file(self.world.root / "research-analyses")
        again = self.prepare(source_id)
        self.assertEqual((again.status_code, again.json()["created"], again.json()["analysis"]["analysis_id"]),
                         (200, False, current))
        self.assertEqual(every_file(self.world.root / "research-analyses"), saved)
        self.assertEqual(self.account()["credits"], account["credits"])
        self.assertEqual(self.account()["daily"], account["daily"])
        self.assertEqual(self.world.provider.requests, [])
        with self.world.accounts.reading() as db:
            self.assertEqual(db.execute("SELECT COUNT(*) FROM quotes").fetchone()[0], 0)
            self.assertEqual(db.execute("SELECT COUNT(*) FROM attempts").fetchone()[0], 0)

    def test_continuing_never_opens_another_readers_preparation(self):
        source_id = self.source()
        current = self.prepare(source_id).json()["analysis"]["analysis_id"]
        other = self.client("reader-b")
        saved = every_file(self.world.root / "research-analyses")
        self.assertEqual(self.prepare(source_id, client=other).status_code, 404)
        self.assertEqual(other.get(f"/api/user/analyses/{current}").status_code, 404)
        self.assertEqual(every_file(self.world.root / "research-analyses"), saved)
        self.assertEqual(self.world.provider.requests, [])
