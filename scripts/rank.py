#!/usr/bin/env python3
"""Objective ranking for metanet.cx — computed only from the attested: block.

Score inputs (all machine-measured, never author claims):
  uptime_90d            weight 0.45
  protocol pass-ratio   weight 0.30   (pass / (pass+fail); untested excluded)
  onchain_verified      weight 0.15
  repo freshness        weight 0.10   (1.0 if commit <90d, linear to 0 at 365d)

self_tier (author claim) and any editorial interop tier are NEVER inputs here.
Editorial tiers render in a separate labeled column in the site — never blended
into this number. Mixing them is the credibility leak the project exists to avoid.
"""
from __future__ import annotations
import datetime as dt
import json

import pathlib

from schema import ENTRIES_DIR, ENTRY_GLOB

ATTESTED_DIR = pathlib.Path(__file__).resolve().parent.parent / "data" / "attested"

W_UPTIME, W_PROTO, W_ONCHAIN, W_REPO = 0.45, 0.30, 0.15, 0.10


def repo_freshness(last_commit: str | None) -> float:
    if not last_commit:
        return 0.0
    try:
        d = dt.datetime.fromisoformat(last_commit.replace("Z", "+00:00"))
    except ValueError:
        return 0.0
    age = (dt.datetime.now(dt.timezone.utc) - d).days
    if age <= 90:
        return 1.0
    if age >= 365:
        return 0.0
    return round(1 - (age - 90) / (365 - 90), 4)


def proto_pass_ratio(checks: dict) -> float | None:
    graded = [v for v in checks.values() if v in ("pass", "fail")]
    if not graded:
        return None
    return sum(1 for v in graded if v == "pass") / len(graded)


def score(attested: dict) -> float:
    uptime = float(attested.get("uptime_90d") or 0.0)
    pr = proto_pass_ratio(attested.get("protocol_checks") or {})
    onchain = 1.0 if attested.get("onchain_verified") else 0.0
    fresh = repo_freshness(attested.get("last_commit"))
    # If no protocol was gradeable, redistribute its weight to uptime rather than
    # penalizing a project for having no probe defined yet.
    if pr is None:
        return round((W_UPTIME + W_PROTO) * uptime + W_ONCHAIN * onchain + W_REPO * fresh, 4)
    return round(W_UPTIME * uptime + W_PROTO * pr + W_ONCHAIN * onchain + W_REPO * fresh, 4)


def main() -> int:
    rows = []
    for path in sorted(ENTRIES_DIR.glob(ENTRY_GLOB)):
        claimed = (json.loads(path.read_text()) or {}).get("claimed") or {}
        apath = ATTESTED_DIR / f"{path.stem}.json"
        attested = json.loads(apath.read_text()) if apath.exists() else None
        if not attested:
            rows.append((-1.0, claimed.get("name", path.stem), "UNATTESTED"))
            continue
        rows.append((score(attested), claimed.get("name", path.stem),
                     f"up={attested.get('uptime_90d')} onchain={attested.get('onchain_verified')} "
                     f"self_tier={claimed.get('self_tier')}"))
    rows.sort(key=lambda r: r[0], reverse=True)
    print(f"{'rank':<5}{'score':<8}{'name':<22}detail")
    for i, (s, name, detail) in enumerate(rows, 1):
        shown = "  n/a " if s < 0 else f"{s:.3f} "
        print(f"{i:<5}{shown:<8}{name:<22}{detail}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
