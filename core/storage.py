"""Persistence storage.

Dua backend:
  1. Upstash Redis REST (produksi Vercel) - state, log, order id, kill switch.
  2. File lokal (pengembangan/forward test di laptop) - data/local/*.jsonl.

Vercel tidak punya filesystem permanen. Jika berjalan di Vercel tanpa
UPSTASH_REDIS_REST_URL/TOKEN, bot menolak berjalan (fail loud) supaya tidak
menyimpan state ke /tmp yang hilang.
"""
import json
import os
import time
import urllib.error
import urllib.request

from .config import ROOT, load_json, save_json, utc_now, iso_utc

LOG_KEYS = {
    "ticks": "uas:log:ticks",
    "decisions": "uas:log:decisions",
    "orders": "uas:log:orders",
    "trades": "uas:log:trades",
    "errors": "uas:log:errors",
    "equity": "uas:log:equity",
    "daily_equity": "uas:log:daily_equity",
    "snapshots": "uas:log:snapshots",
    "kill_log": "uas:log:kill",
}
STATE_KEY = "uas:state"
ORDER_IDS_KEY = "uas:order_ids"
KILL_KEY = "uas:kill_switch"
LOG_RETENTION = 50000


class StorageConfigError(RuntimeError):
    pass


class BaseStorage:
    name = "base"

    def get_state(self):
        raise NotImplementedError

    def set_state(self, state):
        raise NotImplementedError

    def append(self, kind, obj):
        raise NotImplementedError

    def read(self, kind, limit=5000):
        raise NotImplementedError

    def claim_order(self, order_id):
        raise NotImplementedError

    def get_kill(self):
        raise NotImplementedError

    def set_kill(self, on, actor="manual", note=""):
        raise NotImplementedError

    def acquire_lock(self, name, ttl_seconds=300):
        """Ambil lock singkat agar dua penjadwal tidak menulis state bersamaan."""
        raise NotImplementedError

    def release_lock(self, name, token):
        raise NotImplementedError

    def health(self):
        raise NotImplementedError


class LocalStorage(BaseStorage):
    name = "local"

    def __init__(self, root=None):
        self.root = root or os.environ.get("LOCAL_STORAGE_DIR") or os.path.join(ROOT, "data", "local")
        os.makedirs(self.root, exist_ok=True)
        self.state_path = os.path.join(self.root, "state.json")
        self.order_ids_path = os.path.join(self.root, "order_ids.json")
        self.kill_path = os.path.join(self.root, "kill_switch.json")

    def _log_path(self, kind):
        return os.path.join(self.root, ("%s.jsonl" % kind))

    def get_state(self):
        return load_json(self.state_path, default={}) or {}

    def set_state(self, state):
        save_json(self.state_path, state)

    def append(self, kind, obj):
        path = self._log_path(kind)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "a", encoding="utf-8") as f:
            f.write(json.dumps(obj, ensure_ascii=False, separators=(",", ":")) + "\n")

    def read(self, kind, limit=5000):
        path = self._log_path(kind)
        if not os.path.exists(path):
            return []
        out = []
        with open(path, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    out.append(json.loads(line))
                except json.JSONDecodeError:
                    continue
        return out[-int(limit):] if limit else out

    def claim_order(self, order_id):
        ids = load_json(self.order_ids_path, default={"ids": []}) or {"ids": []}
        if order_id in ids.get("ids", []):
            return False
        ids.setdefault("ids", []).append(order_id)
        # simpan hanya 20.000 id terakhir
        ids["ids"] = ids["ids"][-20000:]
        save_json(self.order_ids_path, ids)
        return True

    def get_kill(self):
        d = load_json(self.kill_path, default={"on": False}) or {"on": False}
        env = os.environ.get("KILL_SWITCH", "")
        return bool(d.get("on")) or env.strip().lower() in ("1", "true", "on", "yes")

    def set_kill(self, on, actor="manual", note=""):
        save_json(self.kill_path, {"on": bool(on), "updated_at": iso_utc(), "actor": actor, "note": note})
        self.append("kill_log", {"at": iso_utc(), "on": bool(on), "actor": actor, "note": note})
        return bool(on)

    def acquire_lock(self, name, ttl_seconds=300):
        import uuid
        path = os.path.join(self.root, "lock_%s" % name)
        token = uuid.uuid4().hex
        now = time.time()
        for _ in range(2):
            try:
                fd = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o644)
                with os.fdopen(fd, "w", encoding="utf-8") as f:
                    json.dump({"token": token, "pid": os.getpid(), "at": now}, f)
                return token
            except FileExistsError:
                try:
                    with open(path, "r", encoding="utf-8") as f:
                        old = json.load(f)
                    age = now - float(old.get("at", 0))
                except Exception:
                    age = ttl_seconds + 1
                if age > ttl_seconds:
                    try:
                        os.remove(path)
                    except FileNotFoundError:
                        pass
                    continue
                return None
        return None

    def release_lock(self, name, token):
        path = os.path.join(self.root, "lock_%s" % name)
        try:
            with open(path, "r", encoding="utf-8") as f:
                old = json.load(f)
            if old.get("token") == token:
                os.remove(path)
                return True
        except (FileNotFoundError, json.JSONDecodeError, OSError):
            pass
        return False

    def health(self):
        return {"ok": True, "backend": "local", "root": self.root}


class RepoSnapshotStorage(LocalStorage):
    """Baca-saja dari `data/local/` yang ikut dibundel ke deployment Vercel.

    Dipakai hanya bila deployment Vercel tidak dikonfigurasi dengan Upstash.
    Dashboard dan `/api/health` tetap menampilkan data nyata dari commit
    terakhir (bukan angka kosong), sedangkan semua operasi tulis ditolak
    dengan pesan jelas supaya tidak ada state yang hilang diam-diam.
    """

    name = "repo_snapshot"

    def _readonly(self, *args, **kwargs):
        raise StorageConfigError(
            "Deployment ini hanya punya penyimpanan baca-saja (snapshot repo). "
            "Tick dari cloud butuh UPSTASH_REDIS_REST_URL dan "
            "UPSTASH_REDIS_REST_TOKEN. Scheduler GitHub Actions menulis lewat "
            "commit repo, bukan lewat endpoint ini."
        )

    set_state = _readonly
    append = _readonly
    claim_order = _readonly
    set_kill = _readonly
    acquire_lock = _readonly
    release_lock = _readonly

    def health(self):
        state = self.get_state() or {}
        return {
            "ok": True,
            "backend": "repo_snapshot",
            "writable": False,
            "last_tick_in_snapshot": state.get("last_tick"),
            "note": "Data dibaca dari data/local/*.jsonl pada commit terakhir.",
        }


class RedisStorage(BaseStorage):
    name = "upstash_redis"

    def __init__(self, url, token):
        self.url = url.rstrip("/")
        self.token = token
        self.timeout = 15

    def _post(self, path, payload):
        req = urllib.request.Request(
            self.url + (path or ""),
            data=json.dumps(payload).encode("utf-8"),
            headers={"Authorization": "Bearer " + self.token, "Content-Type": "application/json"},
            method="POST",
        )
        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                data = json.loads(resp.read().decode("utf-8"))
        except urllib.error.HTTPError as e:
            body = ""
            try:
                body = e.read().decode("utf-8", errors="replace")
            except Exception:
                pass
            raise RuntimeError("Upstash HTTP %s: %s" % (e.code, body[:300]))
        except Exception as e:
            raise RuntimeError("Upstash request gagal: %s" % e)
        if isinstance(data, dict) and data.get("error"):
            raise RuntimeError("Upstash error: %s" % data.get("error"))
        return data

    def cmd(self, *args):
        d = self._post("", list(args))
        return d.get("result") if isinstance(d, dict) else d

    def pipeline(self, cmds):
        if not cmds:
            return []
        d = self._post("/pipeline", cmds)
        if isinstance(d, list):
            return [x.get("result") if isinstance(x, dict) else x for x in d]
        return d

    def get_state(self):
        raw = self.cmd("GET", STATE_KEY)
        if not raw:
            return {}
        try:
            return json.loads(raw)
        except (TypeError, json.JSONDecodeError):
            return {}

    def set_state(self, state):
        self.cmd("SET", STATE_KEY, json.dumps(state, ensure_ascii=False, separators=(",", ":")))

    def append(self, kind, obj):
        key = LOG_KEYS.get(kind, "uas:log:" + kind)
        raw = json.dumps(obj, ensure_ascii=False, separators=(",", ":"))
        self.pipeline([["RPUSH", key, raw], ["LTRIM", key, -LOG_RETENTION, -1]])

    def read(self, kind, limit=5000):
        key = LOG_KEYS.get(kind, "uas:log:" + kind)
        n = int(limit) if limit else -1
        if n > 0:
            raw = self.cmd("LRANGE", key, -n, -1)
        else:
            raw = self.cmd("LRANGE", key, 0, -1)
        if not isinstance(raw, list):
            return []
        out = []
        for line in raw:
            try:
                out.append(json.loads(line))
            except (TypeError, json.JSONDecodeError):
                continue
        return out

    def claim_order(self, order_id):
        return int(self.cmd("SADD", ORDER_IDS_KEY, order_id) or 0) == 1

    def get_kill(self):
        v = self.cmd("GET", KILL_KEY)
        env = os.environ.get("KILL_SWITCH", "")
        return str(v).lower() in ("1", "true", "on", "yes") or env.strip().lower() in ("1", "true", "on", "yes")

    def set_kill(self, on, actor="manual", note=""):
        self.cmd("SET", KILL_KEY, "1" if on else "0")
        self.append("kill_log", {"at": iso_utc(), "on": bool(on), "actor": actor, "note": note})
        return bool(on)

    def acquire_lock(self, name, ttl_seconds=300):
        import uuid
        token = uuid.uuid4().hex
        res = self.cmd("SET", "uas:lock:" + name, token, "NX", "EX", int(ttl_seconds))
        return token if res == "OK" else None

    def release_lock(self, name, token):
        script = ("if redis.call('GET', KEYS[1]) == ARGV[1] then "
                  "return redis.call('DEL', KEYS[1]) else return 0 end")
        return int(self.cmd("EVAL", script, 1, "uas:lock:" + name, token) or 0) == 1

    def health(self):
        t0 = time.time()
        pong = self.cmd("PING")
        return {"ok": str(pong).upper() == "PONG", "backend": "upstash_redis",
                "latency_ms": int((time.time() - t0) * 1000)}


def get_storage():
    url = os.environ.get("UPSTASH_REDIS_REST_URL", "").strip()
    token = os.environ.get("UPSTASH_REDIS_REST_TOKEN", "").strip()
    if url and token:
        return RedisStorage(url, token)
    if os.environ.get("VERCEL"):
        # Tanpa Upstash, Vercel tidak punya filesystem permanen. Fallback
        # baca-saja: dashboard tetap menampilkan snapshot commit terakhir,
        # sedangkan tick ditolak dengan pesan jelas (lihat RepoSnapshotStorage).
        return RepoSnapshotStorage()
    return LocalStorage()
