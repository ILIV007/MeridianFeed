#!/usr/bin/env python3
"""Restore the governance state for a verify run (2026-11-25).

The auto-retire guard (pipeline/governance.py, ZERO_ROUNDS=6) needs
yield history ACROSS runs, but the repo file next to the registry is
a frozen seed: every run reloaded it, so 6 zero samples could never
accumulate and the guard could never fire (found in the 2026-11-25
debug review). The live state now round-trips through Actions
artifacts — the same pattern the pipeline already uses for run
stats (verify uploads artifacts, the composer downloads them):

  1. this script (run first in verify.yml) finds the newest
     completed verify run carrying a `governance-state-*` artifact
     and downloads its `governance-state.json` to --out;
  2. the verifier appends this cycle's yields and applies disables
     (governance.record_yield), saving back to the same file;
  3. the workflow uploads it as `governance-state-<run_id>`.

Fail-open by design: when no artifact exists yet (first run after
this lands), when the token is missing, or when any API step fails,
the script prints a warning and exits 0 — the verifier then falls
back to the repo seed and the run proceeds. It never breaks a run.

Usage (in verify.yml, GITHUB_TOKEN from secrets.GITHUB_TOKEN):
  python3 pipeline/fetch_governance_state.py --out governance-state.json

— Agent: Rick
"""
import http.client
import io
import json
import os
import socket
import sys
import time
import urllib.error
import urllib.request
import zipfile

REPO = os.environ.get("GITHUB_REPOSITORY", "ILIV007/MeridianFeed")
WORKFLOW = "verify.yml"
ARTIFACT_PREFIX = "governance-state-"
STATE_FILENAME = "governance-state.json"

# Transient transport failures worth retrying — the same set the
# local composer hardened on 2026-11-25 (get_stats._read_with_retry):
# IncompleteRead is an HTTPException, not a RemoteDisconnected, and
# the artifact endpoint goes through ~1 min dead spells.
_TRANSIENT = (http.client.RemoteDisconnected, http.client.IncompleteRead,
              TimeoutError, socket.timeout, ConnectionResetError)


def _is_transient(exc):
    """True only for transient transport failures. HTTPError is never
    transient here (a 302 is the redirect signal, a 4xx/5xx is a real
    answer) — it must propagate at once, not burn retries."""
    if isinstance(exc, urllib.error.HTTPError):
        return False
    if isinstance(exc, _TRANSIENT):
        return True
    if isinstance(exc, urllib.error.URLError):
        return isinstance(getattr(exc, "reason", None), _TRANSIENT)
    return False


def _read_with_retry(read_fn, attempts=5):
    """Retries on transient transport failures only; any other error
    re-raises at once. Backoff 5s, 15s, 30s, 60s (~110 s window)."""
    delays = (5, 15, 30, 60)
    last = None
    for attempt in range(attempts):
        try:
            return read_fn()
        except Exception as exc:
            if _is_transient(exc):
                last = exc
            else:
                raise
        if attempt < attempts - 1:
            time.sleep(delays[attempt] if attempt < len(delays)
                       else delays[-1])
    raise last


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *args):
        return None


def _read_response(resp):
    with resp:
        return resp.read()


def api_get(token, path):
    """GET a GitHub API path, parsed as JSON. 404 -> None (the
    caller treats a missing object as 'not found'); anything else
    non-2xx raises."""
    req = urllib.request.Request(
        "https://api.github.com" + path,
        headers={"Authorization": "Bearer " + token,
                 "Accept": "application/vnd.github+json",
                 "User-Agent": "meridianfeed-governance-restore"})
    try:
        raw = _read_with_retry(
            lambda: _read_response(
                urllib.request.build_opener(NoRedirect()).open(
                    req, timeout=30)))
    except urllib.error.HTTPError as exc:
        if exc.code == 404:
            return None
        raise
    return json.loads(raw)


def download_zip(token, artifact_id):
    """Download an artifact zip. The API answers 302 to a signed
    blob URL; the redirect target is fetched WITHOUT the bearer
    token (the signed URL is the credential) — same discipline as
    the composer's get_stats._download_artifact."""
    req = urllib.request.Request(
        "https://api.github.com/repos/%s/actions/artifacts/%s/zip"
        % (REPO, artifact_id),
        headers={"Authorization": "Bearer " + token,
                 "Accept": "application/vnd.github+json",
                 "User-Agent": "meridianfeed-governance-restore"})
    try:
        return _read_with_retry(
            lambda: _read_response(
                urllib.request.build_opener(NoRedirect()).open(
                    req, timeout=60)))
    except urllib.error.HTTPError as exc:
        if exc.code not in (301, 302, 307, 308):
            raise
        return _read_with_retry(
            lambda: _read_response(
                urllib.request.urlopen(exc.headers["Location"],
                                       timeout=60)))


def find_latest(token, repo, workflow, skip_run_id):
    """(run_id, artifact) of the newest completed workflow run that
    carries a non-expired governance-state artifact, or (None, None).
    The current run is skipped (it is not completed yet, but the
    guard is cheap). Runs list newest-first."""
    runs = api_get(
        token,
        "/repos/%s/actions/workflows/%s/runs?status=completed"
        "&per_page=10" % (repo, workflow))
    if not runs:
        return None, None
    for run in runs.get("workflow_runs", []):
        if skip_run_id and str(run.get("id")) == str(skip_run_id):
            continue
        arts = api_get(
            token,
            "/repos/%s/actions/runs/%s/artifacts?per_page=100"
            % (repo, run.get("id")))
        if not arts:
            continue
        for art in arts.get("artifacts", []):
            if (art.get("name", "").startswith(ARTIFACT_PREFIX)
                    and not art.get("expired")):
                return run.get("id"), art
    return None, None


def extract_state(payload):
    """The governance-state.json inside an artifact zip, validated
    as a governance state (dict with a sources dict). Raises on a
    bad zip, a missing file, or a wrong shape — the caller treats
    that as 'no usable artifact'."""
    zf = zipfile.ZipFile(io.BytesIO(payload))
    if STATE_FILENAME not in zf.namelist():
        raise ValueError("artifact has no %s" % STATE_FILENAME)
    state = json.loads(zf.read(STATE_FILENAME))
    if not isinstance(state, dict) or not isinstance(
            state.get("sources"), dict):
        raise ValueError("artifact state has the wrong shape")
    return state


def restore(out_path, token=None, repo=REPO, workflow=WORKFLOW,
            skip_run_id=None):
    """Download the newest governance state to out_path. Returns
    ("artifact", run_id) on success, ("fallback", reason) when the
    verifier should use the repo seed instead. Never raises for
    API/transport/shape problems — those are all fallback."""
    token = token or os.environ.get("GITHUB_TOKEN")
    if not token:
        return "fallback", "no GITHUB_TOKEN"
    try:
        run_id, art = find_latest(token, repo, workflow, skip_run_id)
        if not art:
            return "fallback", "no governance-state artifact found"
        state = extract_state(download_zip(token, art["id"]))
    except Exception as exc:  # noqa: BLE001 - every failure is fallback
        return "fallback", "%s: %s" % (type(exc).__name__, exc)
    with open(out_path, "w", encoding="utf-8") as handle:
        json.dump(state, handle, indent=1, sort_keys=True)
    return "artifact", run_id


def main(argv):
    args = argv[1:]

    def opt(name, default=None):
        return args[args.index(name) + 1] if name in args else default

    out_path = opt("--out")
    if not out_path:
        print("usage: fetch_governance_state.py --out <path>",
              file=sys.stderr)
        return 2
    kind, detail = restore(
        out_path, skip_run_id=os.environ.get("GITHUB_RUN_ID"))
    if kind == "artifact":
        print("governance state restored from run %s" % detail)
    else:
        print("governance state restore skipped (%s) — verifier "
              "falls back to the repo seed" % detail)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
