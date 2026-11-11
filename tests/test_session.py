"""Who is asking (user-api-0.1): a server without an accounts store is the local operator, as before accounts existed.

The served session must equal the published SYNTHETIC contract fixture frontend/tests/fixtures/
user-contract-session-local-operator.json, so the shell and the Client read exactly what the server sends.
"""
import json
from pathlib import Path
import tempfile
import unittest

from fastapi.testclient import TestClient

from second_order.api import create_app
from second_order.auth import USER_CONTRACT

ROOT = Path(__file__).resolve().parent.parent
FIXTURES = ROOT / "frontend" / "tests" / "fixtures"
BASE = "http://127.0.0.1:8000"


class LocalOperatorSessionTests(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.TemporaryDirectory()
        root = Path(self.folder.name)
        self.client = TestClient(create_app(root / "prepared", None, intake=root / "intake"), base_url=BASE)

    def tearDown(self):
        self.client.close()
        self.folder.cleanup()

    def test_the_session_is_the_local_operator_with_the_admin_role(self):
        response = self.client.get("/api/session")
        self.assertEqual(response.status_code, 200)
        served = response.json()
        self.assertEqual(served["contract"], USER_CONTRACT)
        self.assertEqual((served["mode"], served["state"], served["user"]["role"]), ("local-operator", "signed_in",
                                                                                     "admin"))
        published = json.loads((FIXTURES / "user-contract-session-local-operator.json").read_text(encoding="utf-8"))
        self.assertEqual(served, published)

    def test_the_session_answers_only_through_a_local_host(self):
        self.assertEqual(self.client.get("/api/session", headers={"host": "example.com"}).status_code, 403)

    def test_reading_the_session_writes_nothing(self):
        self.client.get("/api/session")
        self.assertEqual(list(Path(self.folder.name).iterdir()), [])


if __name__ == "__main__":
    unittest.main()
