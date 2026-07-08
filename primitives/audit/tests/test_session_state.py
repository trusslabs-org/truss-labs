"""Tests for contextual session state storage."""

from __future__ import annotations

import json
import sys
import tempfile
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from audit.policy_event import PolicyEvent  # noqa: E402
from audit.session_state import (  # noqa: E402
    SessionStateError,
    SessionStateStore,
    StateUpdate,
)


def event() -> PolicyEvent:
    return PolicyEvent(
        event_id="evt_test",
        session_id="sess_test",
        type="browser_prompt",
        surface="chrome_extension",
        vendor="chatgpt",
        actor={"user_id": "alice@example.com"},
        destination="external_vendor",
        data={"text": "DOB 1978-04-12"},
        context={"policy_set_version": "abc"},
        session_state={},
    )


class SessionStateStoreTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.store = SessionStateStore(Path(self.tmp.name))

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def test_get_or_create_writes_hashed_state(self) -> None:
        record = self.store.get_or_create("sess_test", {"actor_id": "alice"})
        self.assertEqual(record.session_id, "sess_test")
        self.assertTrue(record.state_hash.startswith("sha256:"))
        self.assertTrue((Path(self.tmp.name) / "sess_test.json").exists())

    def test_apply_updates_returns_transition(self) -> None:
        self.store.get_or_create("sess_test")
        transition = self.store.apply_updates(
            "sess_test",
            [
                StateUpdate(policy_id="p1", key="risk_score", op="increment", value=20),
                StateUpdate(policy_id="p1", key="has_seen_phi", op="set", value=True),
                StateUpdate(policy_id="p1", key="events", op="append", value="evt_test"),
                StateUpdate(policy_id="p1", key="last_text", op="set_from_event", path="data.text"),
            ],
            event=event(),
        )
        self.assertEqual(transition.before, {})
        self.assertEqual(transition.after["risk_score"], 20)
        self.assertTrue(transition.after["has_seen_phi"])
        self.assertEqual(transition.after["events"], ["evt_test"])
        self.assertEqual(transition.after["last_text"], "DOB 1978-04-12")
        self.assertNotEqual(transition.before_hash, transition.after_hash)

    def test_hash_mismatch_rejected(self) -> None:
        record = self.store.get_or_create("sess_test")
        path = Path(self.tmp.name) / "sess_test.json"
        data = json.loads(path.read_text())
        data["state"]["risk_score"] = 999
        path.write_text(json.dumps(data), encoding="utf-8")
        with self.assertRaises(SessionStateError):
            self.store.get_or_create(record.session_id)

    def test_sanitized_session_ids_do_not_collide(self) -> None:
        first = self.store.get_or_create("a/b")
        second = self.store.get_or_create("a_b")
        self.assertEqual(first.session_id, "a/b")
        self.assertEqual(second.session_id, "a_b")
        self.assertEqual(len(list(Path(self.tmp.name).glob("*.json"))), 2)

    def test_concurrent_increments_are_serialized(self) -> None:
        update = StateUpdate(policy_id="p1", key="risk_score", op="increment", value=1)

        def bump() -> None:
            self.store.apply_updates("sess_concurrent", [update], event=event())

        with ThreadPoolExecutor(max_workers=8) as executor:
            list(executor.map(lambda _: bump(), range(100)))

        record = self.store.get_or_create("sess_concurrent")
        self.assertEqual(record.state["risk_score"], 100)


if __name__ == "__main__":
    unittest.main(verbosity=2)
