#!/usr/bin/env python3
"""GitHub Actions runner for the MeridianFeed composer.

Independence migration (wolf's rule: systems run themselves; Rick is
never part of the loop). This runner replaces the local hourly cron:
it downloads the newest verify artifacts with the built-in
GITHUB_TOKEN, snapshots KV feedback/previous pools, runs the strict
composer unchanged, and writes KV only in live mode.

Modes:
- dry-run (default until cutover): compose and report; never writes
  KV. If the Cloudflare token is absent it still composes for proof
  with empty feedback/previous snapshots and marks kv_reads
  unavailable in the summary.
- live: requires CF_KV_API_TOKEN + CF_ACCOUNT_ID +
  CF_KV_NAMESPACE_ID. Missing configuration or a KV read failure
  fails closed (exit 2, no KV writes). Empty fresh pools never
  overwrite last-known-good.

Secrets are read from the environment only and never printed.
"""
import argparse
import base64
import hashlib
import http.client
import io
import json
import os
import socket
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
import zipfile
from datetime import datetime, timezone
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO_ROOT = HERE.parents[1]
STATE_DIR = Path(os.environ.get("MERIDIAN_STATE_DIR", REPO_ROOT / ".composer-state"))
OUT_DIR = Path(os.environ.get("MERIDIAN_OUT_DIR", STATE_DIR / "out"))
os.environ.setdefault("MERIDIAN_STATE_DIR", str(STATE_DIR))
os.environ.setdefault("MERIDIAN_OUT_DIR", str(OUT_DIR))
os.environ.setdefault("COLLECTOR_CACHE_DIR", str(STATE_DIR / "source_cache"))
sys.path.insert(0, str(HERE))
import compose  # noqa: E402

REPO = os.environ.get("GITHUB_REPOSITORY", "ILIV007/MeridianFeed")
GH_TOKEN = os.environ.get("GITHUB_TOKEN", "")
CF_TOKEN = os.environ.get("CF_KV_API_TOKEN", "")
CF_ACCOUNT = os.environ.get("CF_ACCOUNT_ID", "")
CF_NS = os.environ.get("CF_KV_NAMESPACE_ID", "")

_TRANSIENT = (http.client.RemoteDisconnected, http.client.IncompleteRead,
              TimeoutError, socket.timeout, ConnectionResetError)


class FailClosed(Exception):
    pass


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *args):
        return None


def _is_transient(exc):
    if isinstance(exc, urllib.error.HTTPError):
        return False
    if isinstance(exc, _TRANSIENT):
        return True
    if isinstance(exc, urllib.error.URLError):
        return isinstance(getattr(exc, "reason", None), _TRANSIENT)
    return False


def _read_with_retry(read_fn, attempts=6):
    delays = (5, 15, 30, 60, 120)
    last = None
    for attempt in range(attempts):
        try:
            return read_fn()
        except Exception as e:
            if _is_transient(e):
                last = e
            else:
                raise
        if attempt < attempts - 1:
            time.sleep(delays[attempt] if attempt < len(delays) else delays[-1])
    raise last


def _read_response(resp):
    with resp:
        return resp.read()


def _open_no_redirect(req, timeout=60):
    return _read_with_retry(lambda: _read_response(
        urllib.request.build_opener(NoRedirect()).open(req, timeout=timeout)))


def gh_json(method, path, data=None):
    body = json.dumps(data).encode() if data is not None else None
    req = urllib.request.Request(f"https://api.github.com{path}", data=body, method=method)
    req.add_header("Authorization", f"Bearer {GH_TOKEN}")
    req.add_header("Accept", "application/vnd.github+json")
    req.add_header("X-GitHub-Api-Version", "2022-11-28")
    req.add_header("User-Agent", "meridianfeed-composer")
    if body is not None:
        req.add_header("Content-Type", "application/json")
    raw = _open_no_redirect(req, timeout=30)
    return json.loads(raw.decode("utf-8")) if raw else {}


def _download_artifact_json(run_id, name_prefix):
    arts = gh_json("GET", f"/repos/{REPO}/actions/runs/{run_id}/artifacts?per_page=100")
    matches = [a for a in arts.get("artifacts", [])
               if a.get("name", "").startswith(name_prefix) and not a.get("expired")]
    if not matches:
        return None
    art = matches[0]
    req = urllib.request.Request(
        f"https://api.github.com/repos/{REPO}/actions/artifacts/{art['id']}/zip")
    req.add_header("Authorization", f"Bearer {GH_TOKEN}")
    req.add_header("Accept", "application/vnd.github+json")
    req.add_header("User-Agent", "meridianfeed-composer")
    try:
        payload = _open_no_redirect(req, timeout=60)
    except urllib.error.HTTPError as e:
        if e.code not in (301, 302, 307, 308):
            raise
        payload = _read_with_retry(lambda: _read_response(
            urllib.request.urlopen(e.headers["Location"], timeout=60)))
    zf = zipfile.ZipFile(io.BytesIO(payload))
    names = [n for n in zf.namelist() if n.endswith(".json")]
    if not names:
        return None
    return json.loads(zf.read(names[0]).decode("utf-8"))


def _cf_configured():
    return bool(CF_TOKEN and CF_ACCOUNT and CF_NS)


def _cf_url(key):
    return ("https://api.cloudflare.com/client/v4/accounts/"
            f"{CF_ACCOUNT}/storage/kv/namespaces/{CF_NS}/values/"
            f"{urllib.parse.quote(key, safe='')}")


def cf_kv_get(key):
    """Raw KV value text, or None when the key does not exist.

    Raises FailClosed on any other failure so live mode never
    composes from silently-empty feedback/previous state."""
    req = urllib.request.Request(_cf_url(key), method="GET")
    req.add_header("Authorization", f"Bearer {CF_TOKEN}")
    req.add_header("User-Agent", "meridianfeed-composer")
    try:
        return _read_with_retry(lambda: _read_response(
            urllib.request.urlopen(req, timeout=30))).decode("utf-8", "replace")
    except urllib.error.HTTPError as e:
        if e.code == 404:
            return None
        raise FailClosed(f"KV read {key} HTTP {e.code}")
    except Exception as e:
        raise FailClosed(f"KV read {key} failed: {type(e).__name__}")


def cf_kv_put(key, body):
    req = urllib.request.Request(_cf_url(key), data=body, method="PUT")
    req.add_header("Authorization", f"Bearer {CF_TOKEN}")
    req.add_header("User-Agent", "meridianfeed-composer")
    try:
        raw = _read_with_retry(lambda: _read_response(
            urllib.request.urlopen(req, timeout=30)))
    except Exception as e:
        raise FailClosed(f"KV write {key} failed: {type(e).__name__}")
    try:
        ok = json.loads(raw.decode("utf-8")).get("success") is True
    except Exception:
        ok = False
    if not ok:
        raise FailClosed(f"KV write {key} not confirmed")


def _sha(text):
    return hashlib.sha256(text.encode()).hexdigest()


def pool_counts(new_pool, new_sub):
    try:
        pub_n = len(json.loads(new_pool).get("configs", []))
    except Exception:
        pub_n = 0
    try:
        body = base64.b64decode(new_sub).decode("utf-8", "replace") if new_sub.strip() else ""
        sub_n = len([ln for ln in body.splitlines() if ln.strip()])
    except Exception:
        sub_n = 0
    return pub_n, sub_n


def public_pool_changed(prev, new_pool_text):
    if prev is None:
        return True
    try:
        return prev != json.loads(new_pool_text)
    except Exception:
        return True


def _write_json(path, obj):
    Path(path).write_text(json.dumps(obj), encoding="utf-8")


def _finish(result, code=0):
    _write_json(STATE_DIR / "compose-summary.json", result)
    print(json.dumps(result))
    return code


def main(argv=None):
    parser = argparse.ArgumentParser()
    parser.add_argument("--mode", choices=["", "dry-run", "live"], default="")
    args = parser.parse_args(argv)
    mode = args.mode or ("live" if os.environ.get("COMPOSER_LIVE") == "true" else "dry-run")
    live = mode == "live"
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    Path(os.environ["COLLECTOR_CACHE_DIR"]).mkdir(parents=True, exist_ok=True)

    if not GH_TOKEN:
        return _finish({"ok": False, "mode": mode, "error": "missing GITHUB_TOKEN"}, 2)
    if live and not _cf_configured():
        return _finish({"ok": False, "mode": mode,
                        "error": "live mode requires CF_KV_API_TOKEN, CF_ACCOUNT_ID, CF_KV_NAMESPACE_ID"}, 2)

    now = datetime.now(timezone.utc)
    listing = gh_json("GET", f"/repos/{REPO}/actions/workflows/verify.yml/runs?per_page=10")
    runs = [r for r in listing.get("workflow_runs", [])
            if r.get("status") == "completed" and r.get("conclusion") == "success"]
    if not runs:
        return _finish({"ok": False, "mode": mode, "error": "no completed verify runs"}, 1)
    newest_done = datetime.fromisoformat(runs[0]["updated_at"].replace("Z", "+00:00"))
    age_min = (now - newest_done).total_seconds() / 60.0
    if age_min > 50:
        in_flight = any(r.get("status") in ("in_progress", "queued")
                        for r in listing.get("workflow_runs", []))
        if not in_flight:
            gh_json("POST", f"/repos/{REPO}/actions/workflows/verify.yml/dispatches",
                    {"ref": "main", "inputs": {"limit": "300"}})
        return _finish({"ok": True, "mode": mode, "action": "dispatched_verify",
                        "newest_run_age_min": round(age_min),
                        "note": "verify run already in flight" if in_flight
                                else "dispatched; next tick composes"})

    chosen = runs[:5]
    for r in chosen:
        stats = _download_artifact_json(str(r["id"]), "verify-stats-")
        if not isinstance(stats, dict):
            return _finish({"ok": False, "mode": mode,
                            "error": f"missing verify stats artifact for run {r['id']}"}, 1)
        _write_json(STATE_DIR / f"stats-{r['id']}.json", stats)
        pin = _download_artifact_json(str(r["id"]), "verify-uri-map-")
        if isinstance(pin, dict) and pin:
            _write_json(STATE_DIR / f"pin-{r['id']}.json", pin)
    _write_json(STATE_DIR / "runs.json", [
        {"id": str(r["id"]),
         "ts": datetime.fromisoformat(r["created_at"].replace("Z", "+00:00")).timestamp()}
        for r in reversed(chosen)])

    kv_reads = "unavailable"
    feedback = {}
    prev_pub = None
    current_sub = ""
    if _cf_configured():
        try:
            fb_raw = cf_kv_get("feedback")
            fb = json.loads(fb_raw) if fb_raw else {}
            feedback = fb if isinstance(fb, dict) else {}
            idx_raw = cf_kv_get("vip_index")
            idx = json.loads(idx_raw) if idx_raw else {}
            if isinstance(idx, dict) and idx.get("items"):
                _write_json(STATE_DIR / "prev_vip_index.json", idx)
            pub_raw = cf_kv_get("public_pool")
            pub = json.loads(pub_raw) if pub_raw else {}
            if isinstance(pub, dict):
                prev_pub = pub
                if pub.get("configs") is not None:
                    _write_json(STATE_DIR / "prev_public_pool.json", pub)
            current_sub = cf_kv_get("vip_sub") or ""
            kv_reads = "available"
        except FailClosed as e:
            if live:
                return _finish({"ok": False, "mode": mode, "error": str(e)}, 2)
            kv_reads = "unavailable"
    if kv_reads != "available":
        for name in ("prev_vip_index.json", "prev_public_pool.json"):
            p = STATE_DIR / name
            if p.exists():
                p.unlink()
    _write_json(STATE_DIR / "feedback.json", feedback)

    try:
        compose.main()
        summary = json.loads((OUT_DIR / "summary.json").read_text(encoding="utf-8"))
    except SystemExit as exc:
        return _finish({"ok": False, "mode": mode, "error": f"compose aborted: {exc}"}, 1)

    new_pool = (OUT_DIR / "public_pool.json").read_text(encoding="utf-8")
    new_sub = (OUT_DIR / "vip_sub.txt").read_text(encoding="utf-8")
    pub_n, sub_n = pool_counts(new_pool, new_sub)
    would_write = []
    if pub_n > 0 and public_pool_changed(prev_pub, new_pool):
        would_write.append("public_pool")
    if sub_n > 0 and _sha(new_sub) != _sha(current_sub):
        would_write.extend(["vip_sub", "vip_index"])
    lkg_kept = []
    if pub_n == 0:
        lkg_kept.append("public_pool")
    if sub_n == 0:
        lkg_kept.append("vip_sub")

    changed = []
    if live:
        try:
            if "public_pool" in would_write:
                cf_kv_put("public_pool", new_pool.encode("utf-8"))
                changed.append("public_pool")
            if "vip_sub" in would_write:
                cf_kv_put("vip_sub", new_sub.encode("utf-8"))
                cf_kv_put("vip_index", (OUT_DIR / "vip_index.json").read_bytes())
                changed.extend(["vip_sub", "vip_index"])
        except FailClosed as e:
            return _finish({"ok": False, "mode": mode, "error": str(e),
                            "kv_changed_before_error": changed}, 2)

    return _finish({"ok": True, "mode": mode, "action": "composed",
                    "kv_reads": kv_reads, "runs": summary["runs"],
                    "public_pool_size": summary["public_pool_after_quotas"],
                    "rescue_removed": summary.get("rescue_removed"),
                    "vip_pool_size": summary["vip_pool_after_quotas"],
                    "vip_tiers": summary.get("vip_tiers"),
                    "funnel": summary.get("funnel"),
                    "vip_ceiling_relaxed": summary.get("vip_ceiling_relaxed"),
                    "vip_ceiling_relaxed_slots": summary.get("vip_ceiling_relaxed_slots"),
                    "vip_ir_excluded": summary.get("vip_ir_excluded"),
                    "vip_floor_shortfall": summary.get("vip_floor_shortfall"),
                    "vip_floor_shortfall_reason": summary.get("vip_floor_shortfall_reason"),
                    "vip_fill_refused": summary.get("vip_fill_refused"),
                    "would_write": would_write, "kv_changed": changed,
                    "lkg_kept": lkg_kept})


if __name__ == "__main__":
    raise SystemExit(main())
