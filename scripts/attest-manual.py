#!/usr/bin/env python3
"""Manual per-protocol attestation CLI for metanet.cx.

Records a HUMAN conformance judgement for one (entry x protocol) into the same
attestation store the attestor owns, WITHOUT ever touching entries/. Entry files
stay claim-only, PR-authored; this writes machine/human attestations to
data/attested/<slug>.json under the "protocol_states" field.

  python3 scripts/attest-manual.py --slug <slug> --protocol <proto> \
      --state confirmed|failed --by <name> [--note "..."]

Guards (honest-by-construction):
  * refuses a --slug with no entries/<slug>.json  (can't attest a non-entry).
  * refuses a --protocol the entry doesn't actually CLAIM (read claimed.protocols;
    we never confirm a protocol the author never claimed).

The written object is {"state", "method": "manual", "by", "at": now, "note"}.
The attestor's merge rule then PRESERVES this manual object on future cycles
(see compute_protocol_states) instead of clobbering it with a machine state.
Manual confirms auto-decay to "pending" after 90d at READ time (effective_state);
this file only records the point-in-time judgement, it never pre-decays.

Stdlib only — no third-party deps (the box has no pip).
"""
from __future__ import annotations
import argparse
import datetime as dt
import json
import pathlib
import sys

from schema import ENTRIES_DIR

ATTESTED_DIR = pathlib.Path(__file__).resolve().parent.parent / "data" / "attested"


def _now() -> str:
    return dt.datetime.now(dt.timezone.utc).replace(microsecond=0).isoformat()


def main() -> int:
    ap = argparse.ArgumentParser(
        description="Record a manual per-protocol conformance state for an entry "
                    "(writes the attestation store, never entries/).")
    ap.add_argument("--slug", required=True, help="entry slug (entries/<slug>.json)")
    ap.add_argument("--protocol", required=True,
                    help="a protocol the entry CLAIMS (claimed.protocols)")
    ap.add_argument("--state", required=True, choices=["confirmed", "failed"],
                    help="the human judgement")
    ap.add_argument("--by", required=True, help="who made the call (attribution)")
    ap.add_argument("--note", default=None, help="optional free-text note")
    args = ap.parse_args()

    entry_path = ENTRIES_DIR / f"{args.slug}.json"
    if not entry_path.exists():
        print(f"error: no entry file {entry_path} — can't attest a non-entry.")
        return 1
    try:
        claimed = (json.loads(entry_path.read_text()) or {}).get("claimed") or {}
    except (ValueError, OSError) as e:
        print(f"error: cannot read {entry_path}: {e}")
        return 1

    claimed_protocols = claimed.get("protocols") or []
    if args.protocol not in claimed_protocols:
        print(f"error: {args.slug} does not claim protocol {args.protocol!r}. "
              f"claimed.protocols = {claimed_protocols}. "
              f"Refusing to attest a protocol the entry never claimed.")
        return 1

    # Read-modify-write the attestation store for this slug. We only touch the
    # protocol_states entry for this protocol; everything else the attestor owns
    # is preserved so a manual call and a cycle can interleave safely.
    apath = ATTESTED_DIR / f"{args.slug}.json"
    attested: dict = {}
    if apath.exists():
        try:
            attested = json.loads(apath.read_text()) or {}
        except (ValueError, OSError):
            attested = {}
    states = attested.get("protocol_states")
    if not isinstance(states, dict):
        states = {}

    state_obj = {
        "state": args.state,
        "method": "manual",
        "by": args.by,
        "at": _now(),
        "note": args.note,
    }
    states[args.protocol] = state_obj
    attested["protocol_states"] = states

    ATTESTED_DIR.mkdir(parents=True, exist_ok=True)
    apath.write_text(json.dumps(attested, indent=2, ensure_ascii=False) + "\n")
    print(f"recorded manual {args.state} for {args.slug}/{args.protocol} "
          f"by {args.by} at {state_obj['at']} -> {apath}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
