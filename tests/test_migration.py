import json
import os
import sys
import tempfile
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "scripts"))

from core.storage import (  # noqa: E402
    KILL_KEY, LOG_KEYS, ORDER_IDS_KEY, STATE_KEY, LocalStorage,
)
from migrate_local_to_redis import migrate  # noqa: E402


class FakeRemote:
    """Tiruan kecil Upstash REST untuk menguji migrasi tanpa jaringan."""

    def __init__(self):
        self.state = None
        self.logs = {}
        self.orders = set()
        self.kill = None

    def _exists(self, key):
        if key == STATE_KEY:
            return self.state is not None
        if key == ORDER_IDS_KEY:
            return bool(self.orders)
        if key == KILL_KEY:
            return self.kill is not None
        return key in self.logs

    def _del(self, key):
        if key == STATE_KEY:
            self.state = None
        elif key == ORDER_IDS_KEY:
            self.orders = set()
        elif key == KILL_KEY:
            self.kill = None
        else:
            self.logs.pop(key, None)

    def pipeline(self, cmds):
        out = []
        for c in cmds:
            op = str(c[0]).upper()
            if op == "EXISTS":
                out.append(1 if self._exists(c[1]) else 0)
            elif op == "DEL":
                self._del(c[1])
                out.append(1)
            elif op == "RPUSH":
                self.logs.setdefault(c[1], []).extend(c[2:])
                out.append(len(self.logs[c[1]]))
            elif op == "LTRIM":
                keep = self.logs.get(c[1], [])
                start, stop = int(c[2]), int(c[3])
                self.logs[c[1]] = keep[start:] if stop == -1 else keep[start:stop + 1]
                out.append(True)
            elif op == "SADD":
                self.orders.update(c[2:])
                out.append(1)
            else:
                out.append(None)
        return out

    def cmd(self, *args):
        op = str(args[0]).upper()
        if op == "SET":
            if args[1] == KILL_KEY:
                self.kill = args[2]
            return True
        if op == "GET":
            return self.state
        if op == "SCARD":
            return len(self.orders)
        return None

    def set_state(self, state):
        self.state = json.dumps(state)

    def get_state(self):
        return json.loads(self.state) if self.state else {}

    def read(self, kind, limit=5000):
        key = LOG_KEYS.get(kind, "uas:log:" + kind)
        rows = self.logs.get(key, [])
        if limit:
            rows = rows[-int(limit):]
        return [json.loads(x) for x in rows]


class TestMigration(unittest.TestCase):
    def _local(self, d):
        local = LocalStorage(root=d)
        local.set_state({"forward_test_start": "2026-11-09T00:35:58Z", "tick_count": 2})
        local.append("ticks", {"i": 1})
        local.append("ticks", {"i": 2})
        local.append("decisions", {"pair": "btcidr", "candle_time": 1})
        with open(os.path.join(d, "order_ids.json"), "w", encoding="utf-8") as f:
            json.dump({"ids": ["o1", "o2"]}, f)
        with open(os.path.join(d, "kill_switch.json"), "w", encoding="utf-8") as f:
            json.dump({"on": True}, f)
        return local

    def test_migrate_copies_state_and_logs(self):
        with tempfile.TemporaryDirectory() as d:
            local = self._local(d)
            remote = FakeRemote()
            s = migrate(local, remote, write=True)
            self.assertTrue(s["written"])
            self.assertEqual(remote.get_state()["forward_test_start"], "2026-11-09T00:35:58Z")
            self.assertEqual(len(remote.read("ticks", limit=0)), 2)
            self.assertEqual(len(remote.read("decisions", limit=0)), 1)
            self.assertEqual(remote.orders, {"o1", "o2"})
            self.assertEqual(remote.kill, "1")

    def test_refuses_non_empty_without_force(self):
        with tempfile.TemporaryDirectory() as d:
            local = self._local(d)
            remote = FakeRemote()
            migrate(local, remote, write=True)
            with self.assertRaises(SystemExit):
                migrate(local, remote, write=True)

    def test_force_replaces_without_duplicating(self):
        with tempfile.TemporaryDirectory() as d:
            local = self._local(d)
            remote = FakeRemote()
            migrate(local, remote, write=True)
            migrate(local, remote, write=True, force=True)
            self.assertEqual(len(remote.read("ticks", limit=0)), 2)

    def test_dry_run_writes_nothing(self):
        with tempfile.TemporaryDirectory() as d:
            local = self._local(d)
            remote = FakeRemote()
            s = migrate(local, remote, write=False)
            self.assertFalse(s["written"])
            self.assertIsNone(remote.state)
            self.assertEqual(s["logs"]["ticks"], 2)


if __name__ == "__main__":
    unittest.main()
