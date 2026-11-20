#!/usr/bin/env python3
"""Per-source exact-key survival harness (Phase C/D).

A config "survives" iff its exact dedup key (protocol|server|port|
SHA-256(credential), the production collector's key) is present in a
later snapshot of the same source. Survival at a horizon is the mean,
over all snapshot pairs separated by ~that horizon, of the fraction of
the earlier snapshot's keys still present in the later one.

Adoption bar (wolf, 2026-11-20): >=85% key survival at 24 h, measured
over >=24 h of snapshots. Endpoint-class sources may instead show
>=95% eligible-key retention at 8 h (see the churn audit).

Modes:
  gh  <owner/repo> <path> [--max-snaps 12]
      Snapshots from the file's GitHub commit history (public API).
  dir <directory>
      Snapshots from local files named <epoch>__<source>.txt (raw
      bodies), grouped per source — used for endpoint / Telegram
      sources whose observation windows accrue locally.

Output is counts and fractions only — never URIs or credentials.

— Agent: Rick
"""
import json
import os
import sys
import urllib.request

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import collector  # noqa: E402

HORIZONS = (("1h", 3600, 0.5), ("6h", 21600, 0.4), ("24h", 86400, 0.35))


def keys_of(body, source):
    if isinstance(body, str):
        body = body.encode("utf-8", "replace")
    keys = set()
    for text in collector.candidate_texts(body):
        for uri in collector.extract_candidates(text):
            record = collector.parse_uri(uri, source)
            if record is not None:
                keys.add(collector.dedup_key(record))
    return keys


def survival(snaps):
    """snaps: list of (ts, keyset) sorted by ts. Returns a report dict."""
    snaps = sorted(snaps)
    report = {"snapshots": len(snaps),
              "span_hours": round((snaps[-1][0] - snaps[0][0]) / 3600, 1)
              if len(snaps) > 1 else 0.0,
              "keys_now": len(snaps[-1][1]) if snaps else 0,
              "survival": {}}
    for label, horizon, tol in HORIZONS:
        values = []
        for i, (t0, k0) in enumerate(snaps):
            if not k0:
                continue
            for t1, k1 in snaps[i + 1:]:
                gap = t1 - t0
                if gap > horizon * (1 + tol):
                    break
                if abs(gap - horizon) <= horizon * tol:
                    values.append(len(k0 & k1) / len(k0))
                    break
        if values:
            report["survival"][label] = round(
                sum(values) / len(values), 3)
            report["survival"][label + "_pairs"] = len(values)
    s24 = report["survival"].get("24h")
    report["bar_85_at_24h"] = (s24 >= 0.85) if s24 is not None else None
    return report


def _gh(path, token=None):
    req = urllib.request.Request("https://api.github.com" + path)
    req.add_header("Accept", "application/vnd.github+json")
    req.add_header("User-Agent", "meridian-survival-harness")
    if token:
        req.add_header("Authorization", "Bearer " + token)
    else:
        # On Rick's VM, ride the sanctioned PAT surrogate (unauthenticated
        # GitHub API is rate-limited to uselessness on shared egress IPs).
        try:
            sys.path.insert(
                0, "/opt/muse/skills/custom-connector-setup/bin")
            from dynamic_credentials import add_surrogate_to_request
            add_surrogate_to_request(req, "custom.github-pat",
                                     allowed_hosts=["api.github.com"])
        except Exception:
            pass
    with urllib.request.urlopen(req, timeout=30) as resp:
        return json.loads(resp.read())


def gh_snapshots(repo, path, max_snaps, token=None):
    import base64
    from datetime import datetime
    commits = _gh(f"/repos/{repo}/commits?path={path}&per_page=100", token)
    # All recent commits as snapshots (cap by count, newest first from
    # the API; stride-sampling would space them too far apart for the
    # 24 h horizon to ever match a pair).
    picks = commits[:max_snaps * 8]
    snaps = []
    for commit in picks:
        sha = commit["sha"]
        try:
            data = _gh(f"/repos/{repo}/contents/{path}?ref={sha}", token)
            body = base64.b64decode(data["content"]).decode(
                "utf-8", "replace")
        except Exception as exc:  # file absent/huge at this ref — skip
            print(f"skip {sha[:8]}: {exc}", file=sys.stderr)
            continue
        ts = datetime.fromisoformat(
            commit["commit"]["committer"]["date"].replace(
                "Z", "+00:00")).timestamp()
        snaps.append((ts, keys_of(body, repo)))
    return snaps


def dir_snapshots(directory):
    from collections import defaultdict
    by_source = defaultdict(list)
    for name in sorted(os.listdir(directory)):
        if "__" not in name or not name.endswith(".txt"):
            continue
        epoch, source = name[:-4].split("__", 1)
        with open(os.path.join(directory, name), encoding="utf-8",
                  errors="replace") as handle:
            by_source[source].append(
                (float(epoch), keys_of(handle.read(), source)))
    return by_source


def main(argv):
    token = os.environ.get("GITHUB_TOKEN")
    if len(argv) >= 4 and argv[1] == "gh":
        max_snaps = 12  # x8 commits fetched; see gh_snapshots
        if "--max-snaps" in argv:
            max_snaps = int(argv[argv.index("--max-snaps") + 1])
        snaps = gh_snapshots(argv[2], argv[3], max_snaps, token)
        print(json.dumps({f"{argv[2]}:{argv[3]}": survival(snaps)},
                         indent=1))
        return 0
    if len(argv) >= 3 and argv[1] == "dir":
        print(json.dumps({src: survival(snaps) for src, snaps
                          in dir_snapshots(argv[2]).items()}, indent=1))
        return 0
    print(__doc__)
    return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv))
