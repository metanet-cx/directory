#!/usr/bin/env python3
"""Objective ranking for metanet.cx — computed only from the attested: block.

Score inputs (all machine-measured, never author claims):
  uptime_90d            weight 0.45
  protocol pass-ratio   weight 0.30   (pass / (pass+fail); untested excluded)
  onchain_verified      weight 0.15
  repo freshness        weight 0.10   (1.0 if commit <90d, linear to 0 at 365d)

A weight is only levied when it is actually measurable for an entry. If no
protocol is gradeable (no probe defined / all untested), the 0.30 folds back so
the entry isn't penalized for a probe we haven't written. Likewise, onchain is
only scored when the entry CLAIMS an onchain_txid; an entry that makes no
on-chain claim has nothing to verify, so the 0.15 folds back rather than docking
every entry for a dimension it never entered. (This also means our own
not-yet-synced SPV node can't silently cap the whole field at 0.85.) An entry
that DOES claim a txid but fails verification keeps the 0.15 and scores 0 on it —
that's a real, earned penalty for an unbacked claim.

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


def score(attested: dict, claims_onchain: bool = False) -> float:
    """Weighted score. A weight is only levied when it's measurable for the entry.

    `claims_onchain` is True iff the entry's claim carries an onchain_txid. When
    False there is nothing to verify, so the onchain weight folds away rather
    than docking the entry for a dimension it never entered. When True, a failed
    verification keeps the weight and scores 0 on it — an earned penalty.
    """
    uptime = float(attested.get("uptime_90d") or 0.0)
    pr = proto_pass_ratio(attested.get("protocol_checks") or {})
    fresh = repo_freshness(attested.get("last_commit"))

    # Base weights for the always-present dimensions.
    w_up, w_proto, w_onchain, w_repo = W_UPTIME, W_PROTO, W_ONCHAIN, W_REPO
    score_proto = pr if pr is not None else 0.0
    score_onchain = 1.0 if attested.get("onchain_verified") else 0.0

    # Fold away unlevied weights onto the measurable dimensions (uptime/repo),
    # so an entry is never penalized for a dimension it can't enter.
    slack = 0.0
    if pr is None:
        slack += w_proto
        w_proto = 0.0
    if not claims_onchain:
        slack += w_onchain
        w_onchain = 0.0
    # Redistribute the slack proportionally across the remaining levied weights.
    levied = w_up + w_proto + w_onchain + w_repo
    if levied > 0:
        w_up += slack * (w_up / levied)
        w_proto += slack * (w_proto / levied)
        w_onchain += slack * (w_onchain / levied)
        w_repo += slack * (w_repo / levied)

    return round(w_up * uptime + w_proto * score_proto
                 + w_onchain * score_onchain + w_repo * fresh, 4)


def main() -> int:
    rows = []
    for path in sorted(ENTRIES_DIR.glob(ENTRY_GLOB)):
        claimed = (json.loads(path.read_text()) or {}).get("claimed") or {}
        apath = ATTESTED_DIR / f"{path.stem}.json"
        attested = json.loads(apath.read_text()) if apath.exists() else None
        if not attested:
            rows.append((-1.0, claimed.get("name", path.stem), "UNATTESTED"))
            continue
        claims_onchain = bool(claimed.get("onchain_txid"))
        rows.append((score(attested, claims_onchain), claimed.get("name", path.stem),
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
