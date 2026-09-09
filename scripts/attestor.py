#!/usr/bin/env python3
"""metanet.cx attestor (stub, v0.1).

The one always-on piece. For each entries/<slug>.json it:
  1. HTTP-probes claimed.url         -> live, latency_ms, append to uptime series
  2. runs a probe per claimed.protocol -> protocol_checks{proto: pass|fail|untested}
  3. verifies claimed.onchain_txid   -> onchain_verified   (via local SPV node)
  4. fetches repo metadata           -> repo_public, last_commit
  5. recomputes uptime_90d from the stored series
  6. writes the attested: block back into the entry file

STUB STATUS: network probes are gated behind --live. Without it, the attestor
runs the full pipeline against a deterministic mock so the loop, the series
store, the ranking, and the file round-trip can all be exercised with no box,
no network, and no SPV node. Swap the `_probe_*` bodies for real calls when we
wire it to the bsv.cx box.

SEPARATION OF WRITERS (critical): the attestor NEVER writes into entries/. Entry
files are claimed-only, PR-authored. Attestations are written to their own store:
  data/attested/<slug>.json   latest attested block (what the site renders)
  data/series/<slug>.jsonl    append-only liveness history (for uptime_90d)
This is what lets the CI guard flatly reject any attested: in entries/ without
ever fighting the attestor's own output. claimed and attested physically never
share a file. rank.py / the site join the two at read time.

PORTABILITY: the ONLY box-coupled call is spv_verify(). It talks to the SPV
node over localhost today. To move this to Render later, replace that one
function with an authenticated POST to bsv.cx/verify — nothing else changes.

Metrics store: data/ is append-only/replaceable machine output. In production
data/ is a git data branch pushed every cycle, so the store IS the backup (no
separate backup job). Never let it become opaque on-box-only state (gemcity lesson).
"""
from __future__ import annotations
import argparse
import datetime as dt
import hashlib
import json
import pathlib

from schema import ENTRIES_DIR, ENTRY_GLOB

ATTESTOR_VERSION = "0.1.0"
ROOT = pathlib.Path(__file__).resolve().parent.parent
SERIES_DIR = ROOT / "data" / "series"
ATTESTED_DIR = ROOT / "data" / "attested"

# Protocols we have a real probe defined for. Anything else -> "untested"
# (honestly labeled, never faked as pass).
PROBE_DEFINED = {"paymail", "brc-100"}


def _now() -> str:
    return dt.datetime.now(dt.timezone.utc).replace(microsecond=0).isoformat()


def _mock(seed: str) -> float:
    """Deterministic 0..1 from a string, so stub runs are stable/testable."""
    h = hashlib.sha256(seed.encode()).digest()
    return int.from_bytes(h[:4], "big") / 0xFFFFFFFF


# --- probes (stubbed; --live will swap these for real network calls) ---------

def probe_liveness(slug: str, url: str | None, live_net: bool) -> tuple[bool, int | None]:
    if not url:
        return False, None
    if live_net:
        raise NotImplementedError("real HTTP probe not wired yet — run without --live")
    r = _mock(slug + "|live")
    up = r > 0.05  # ~95% of mocked hosts up
    return up, (int(80 + r * 400) if up else None)


def probe_protocol(slug: str, proto: str, url: str | None, live_net: bool) -> str:
    if proto not in PROBE_DEFINED:
        return "untested"
    if not url:
        return "fail"
    if live_net:
        raise NotImplementedError("real protocol probe not wired yet — run without --live")
    return "pass" if _mock(slug + "|" + proto) > 0.15 else "fail"


def spv_verify(txid: str | None, live_net: bool) -> bool:
    """THE ONLY BOX-COUPLED CALL. Today: local SPV node over localhost.
    To relocate off-box, replace this body with an auth'd POST to bsv.cx/verify."""
    if not txid:
        return False
    if live_net:
        raise NotImplementedError("SPV localhost call not wired yet — run without --live")
    return _mock(txid + "|spv") > 0.5


def probe_repo(slug: str, repo: str | None, live_net: bool) -> tuple[bool, str | None]:
    if not repo:
        return False, None
    if live_net:
        raise NotImplementedError("real repo probe not wired yet — run without --live")
    days_ago = int(_mock(slug + "|commit") * 400)
    last = (dt.datetime.now(dt.timezone.utc) - dt.timedelta(days=days_ago)).date().isoformat()
    return True, last + "T00:00:00Z"


# --- series store (append-only) ---------------------------------------------

def append_series(slug: str, checked_at: str, live: bool) -> float:
    SERIES_DIR.mkdir(parents=True, exist_ok=True)
    f = SERIES_DIR / f"{slug}.jsonl"
    with f.open("a") as fh:
        fh.write(json.dumps({"t": checked_at, "live": live}) + "\n")
    cutoff = dt.datetime.now(dt.timezone.utc) - dt.timedelta(days=90)
    total = up = 0
    for line in f.read_text().splitlines():
        try:
            rec = json.loads(line)
            if dt.datetime.fromisoformat(rec["t"]) >= cutoff:
                total += 1
                up += 1 if rec["live"] else 0
        except (ValueError, KeyError):
            continue
    return round(up / total, 4) if total else 0.0


# --- main loop ---------------------------------------------------------------

def attest_entry(path: pathlib.Path, live_net: bool) -> dict:
    claimed = (json.loads(path.read_text()) or {}).get("claimed") or {}
    slug = claimed.get("slug", path.stem)
    checked_at = _now()

    live, latency = probe_liveness(slug, claimed.get("url"), live_net)
    checks = {p: probe_protocol(slug, p, claimed.get("url"), live_net)
              for p in (claimed.get("protocols") or [])}
    onchain = spv_verify(claimed.get("onchain_txid"), live_net)
    repo_public, last_commit = probe_repo(slug, claimed.get("repo"), live_net)
    uptime_90d = append_series(slug, checked_at, live)

    attested = {
        "checked_at": checked_at,
        "live": live,
        "uptime_90d": uptime_90d,
        "latency_ms": latency,
        "protocol_checks": checks,
        "onchain_verified": onchain,
        "repo_public": repo_public,
        "last_commit": last_commit,
        "attestor_version": ATTESTOR_VERSION,
    }
    # Write to the attestation store ONLY. Never touch entries/ — that keeps
    # claimed (PR-authored) and attested (machine) in physically separate files.
    ATTESTED_DIR.mkdir(parents=True, exist_ok=True)
    (ATTESTED_DIR / f"{slug}.json").write_text(
        json.dumps(attested, indent=2, ensure_ascii=False) + "\n")
    return attested


def main() -> int:
    ap = argparse.ArgumentParser(description="metanet.cx attestor (stub)")
    ap.add_argument("--live", action="store_true",
                    help="use real network/SPV probes (not wired yet — will raise)")
    ap.add_argument("--slug", help="attest a single entry by slug")
    args = ap.parse_args()

    files = sorted(ENTRIES_DIR.glob(ENTRY_GLOB))
    if args.slug:
        files = [f for f in files if f.stem == args.slug]
        if not files:
            print(f"no entry with slug {args.slug!r}")
            return 1

    for path in files:
        a = attest_entry(path, args.live)
        flag = "up " if a["live"] else "DOWN"
        print(f"[{flag}] {path.stem:16} uptime90={a['uptime_90d']:.3f} "
              f"checks={a['protocol_checks']} onchain={a['onchain_verified']}")
    print(f"attested {len(files)} entr{'y' if len(files) == 1 else 'ies'} "
          f"(mode={'LIVE' if args.live else 'stub'})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
