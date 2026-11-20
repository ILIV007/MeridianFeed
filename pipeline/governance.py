#!/usr/bin/env python3
"""Per-source unique-yield governance (Plan Rev.2 R1).

The pattern is Radikal state.py's (MIT): a source is judged by its
UNIQUE yield — configs it contributes that no earlier source already
had — never by raw counts or HTTP 200s. A source whose yield stays
zero is dead weight: it costs a fetch + parse every cycle and adds
nothing. This module keeps a rolling per-source yield history in a
small JSON state file next to the registry and auto-disables
zero-yield sources under four safety conditions:

  1. the source is currently enabled in the registry and not already
     governance-disabled;
  2. at least ZERO_ROUNDS yield samples exist and the last
     ZERO_ROUNDS are all zero (a single bad cycle never disables);
  3. the most recent sample is zero (zero again this round);
  4. a global floor: disabling never takes the active registry below
     MIN_ACTIVE sources — least lifetime yield first.

Only successful fetches count as samples: a network failure is not a
yield measurement. Governance never breaks collection — the collector
treats every governance error as "no governance". Re-enabling is a
deliberate act (enable()), recorded like disables in the state file
and surfaced in docs/survival-log.md by the weekly audit.

State shape:
  {"version": 1,
   "sources": {name: {"unique_history": [int, ...],   # newest last
                      "lifetime_unique": int,
                      "disabled": bool,
                      "disabled_reason": str | null,
                      "disabled_ts": float | null}}}

— Agent: Rick
"""
import json
import os

HISTORY_MAX = 12
ZERO_ROUNDS = 6
MIN_ACTIVE = 4


def empty_state():
    return {"version": 1, "sources": {}}


def load(path):
    try:
        with open(path, encoding="utf-8") as handle:
            state = json.load(handle)
        if isinstance(state, dict) and isinstance(
                state.get("sources"), dict):
            return state
    except Exception:
        pass
    return empty_state()


def save(path, state):
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as handle:
        json.dump(state, handle, indent=1, sort_keys=True)
    os.replace(tmp, path)


def disabled_names(state):
    if not state:
        return set()
    return {name for name, ent in state.get("sources", {}).items()
            if ent.get("disabled")}


def update(state, per_source_stats, ts):
    """Append this cycle's unique yields. Only successful, non-stub
    source results count as samples."""
    sources = state.setdefault("sources", {})
    for stats in per_source_stats:
        if not stats.get("ok") or stats.get("governance_disabled"):
            continue
        ent = sources.setdefault(stats["name"], {
            "unique_history": [], "lifetime_unique": 0,
            "disabled": False, "disabled_reason": None,
            "disabled_ts": None})
        ent["unique_history"] = (
            list(ent.get("unique_history", []))
            + [int(stats.get("unique_new", 0))])[-HISTORY_MAX:]
        ent["lifetime_unique"] = int(ent.get("lifetime_unique", 0)) \
            + int(stats.get("unique_new", 0))
    state["updated_ts"] = ts
    return state


def disable_candidates(state, registry_sources):
    """{name: reason} for sources meeting all four safety conditions,
    least lifetime yield first (dict order is the disable order)."""
    if not state:
        return {}
    entries = state.get("sources", {})
    active = [s for s in registry_sources
              if s.get("enabled", True)
              and not entries.get(s["name"], {}).get("disabled")]
    candidates = []
    for source in active:
        ent = entries.get(source["name"])
        if not ent:
            continue
        history = ent.get("unique_history", [])
        if len(history) < ZERO_ROUNDS:
            continue
        if history[-1] != 0 or any(history[-ZERO_ROUNDS:]):
            continue
        candidates.append(source["name"])
    candidates.sort(key=lambda n: entries[n].get("lifetime_unique", 0))
    allowed = max(0, len(active) - MIN_ACTIVE)
    return {name: (f"zero unique yield in the last {ZERO_ROUNDS} "
                   f"rounds (and zero again this round)")
            for name in candidates[:allowed]}


def apply_disables(state, registry_sources):
    """Mark this round's candidates disabled. Returns {name: reason}
    of the newly disabled (empty when nothing changed)."""
    newly = disable_candidates(state, registry_sources)
    import time
    for name, reason in newly.items():
        ent = state["sources"][name]
        ent["disabled"] = True
        ent["disabled_reason"] = reason
        ent["disabled_ts"] = time.time()
    return newly


def enable(state, name):
    """Manual re-enable (deliberate; history is kept)."""
    ent = state.get("sources", {}).get(name)
    if ent and ent.get("disabled"):
        ent["disabled"] = False
        ent["disabled_reason"] = None
        ent["disabled_ts"] = None
        return True
    return False
