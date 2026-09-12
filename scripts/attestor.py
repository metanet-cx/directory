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
import ssl
import time
import urllib.error
import urllib.parse
import urllib.request

from schema import ENTRIES_DIR, ENTRY_GLOB, protocol_state_rule

ATTESTOR_VERSION = "0.3.0"
ROOT = pathlib.Path(__file__).resolve().parent.parent
SERIES_DIR = ROOT / "data" / "series"
ATTESTED_DIR = ROOT / "data" / "attested"

# Protocols we have a REAL probe defined for. Anything else is graded "na" by
# protocol_state_rule (honestly labeled, never faked as a pass). paymail uses
# BSVAlias service discovery; ship/slap use the overlay host's unauthenticated
# /listTopicManagers + /listLookupServiceProviders endpoints. Claiming a pass
# we didn't measure is the exact lie the project forbids.
PROBE_DEFINED = {"paymail", "ship", "slap"}

HTTP_TIMEOUT = 10  # seconds
USER_AGENT = f"metanet.cx-attestor/{ATTESTOR_VERSION} (+https://metanet.cx)"


def _http_get(url: str, timeout: int = HTTP_TIMEOUT) -> tuple[int, bytes, float]:
    """GET a URL. Returns (status, body, elapsed_ms). Raises on network error."""
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    ctx = ssl.create_default_context()
    t0 = time.monotonic()
    with urllib.request.urlopen(req, timeout=timeout, context=ctx) as resp:
        body = resp.read()
        elapsed = (time.monotonic() - t0) * 1000
        return resp.status, body, elapsed


def _now() -> str:
    return dt.datetime.now(dt.timezone.utc).replace(microsecond=0).isoformat()


def _mock(seed: str) -> float:
    """Deterministic 0..1 from a string, so stub runs are stable/testable."""
    h = hashlib.sha256(seed.encode()).digest()
    return int.from_bytes(h[:4], "big") / 0xFFFFFFFF


# --- probes (stubbed; --live will swap these for real network calls) ---------

def probe_liveness(slug: str, url: str | None, live_net: bool,
                   probe_url: str | None = None) -> tuple[bool, int | None]:
    """Liveness check. Probes `probe_url` when the entry provides one (for pages
    the attestor can't fairly hit directly, e.g. npm package pages behind a
    bot-wall); otherwise probes `url`. A 403/429 from a bot-wall CDN is NOT
    treated as "down" — the host answered, it just refused an automated client.
    That's an honest "unverified", not a claim the service is dead."""
    target = probe_url or url
    if not target:
        return False, None
    if live_net:
        try:
            status, _, elapsed = _http_get(target)
        except urllib.error.HTTPError as e:
            # Bot-wall / rate-limit: the host IS up, it just blocks automated
            # clients. Don't libel a live service as down — report not-live
            # without latency, same as any unverified case.
            if e.code in (403, 429):
                return False, None
            # Other error statuses: host answered but the service isn't serving.
            return (200 <= e.code < 400), None
        except (urllib.error.URLError, ssl.SSLError, OSError, ValueError):
            return False, None
        return (200 <= status < 400), int(elapsed)
    r = _mock(slug + "|live")
    up = r > 0.05  # ~95% of mocked hosts up
    return up, (int(80 + r * 400) if up else None)


def _paymail_probe(url: str | None) -> str:
    """Real BSVAlias service discovery: fetch <domain>/.well-known/bsvalias and
    confirm it's a valid capabilities document. pass|fail only (never faked)."""
    if not url:
        return "fail"
    host = urllib.parse.urlparse(url).netloc or urllib.parse.urlparse("//" + url).netloc
    host = host.split("@")[-1].split(":")[0]  # strip any userinfo/port
    if not host:
        return "fail"
    try:
        status, body, _ = _http_get(f"https://{host}/.well-known/bsvalias")
    except (urllib.error.HTTPError, urllib.error.URLError, ssl.SSLError, OSError, ValueError):
        return "fail"
    if status != 200:
        return "fail"
    try:
        doc = json.loads(body)
    except (ValueError, UnicodeDecodeError):
        return "fail"
    # A valid bsvalias doc advertises a bsvalias version + a capabilities map.
    if isinstance(doc, dict) and "bsvalias" in doc and isinstance(doc.get("capabilities"), dict):
        return "pass"
    return "fail"


def _ship_slap_probe(url: str | None) -> str:
    """SHIP/SLAP overlay-host probe (PROVEN live mechanism).

    A deployed BSV overlay host answers unauthenticated GET /listTopicManagers
    (SHIP) and GET /listLookupServiceProviders (SLAP) with a JSON object/array.
    We hit the host root derived from `url`. Returns:
      "pass"  : status 200 AND body parses as a JSON dict/list.
      "soft"  : 403/429 — the host is up but bot-walls automated clients; an
                honest "unverified", NOT a failure (mirrors probe_liveness).
      "fail"  : network error, or non-2xx that isn't 403/429, or a 200 whose
                body is not valid JSON dict/list.
    Both endpoints must be consulted; a single verified PASS is enough to
    confirm the overlay surface, a soft answer holds, otherwise fail.
    """
    if not url:
        return "fail"
    p = urllib.parse.urlparse(url if "://" in url else "//" + url)
    host = (p.netloc or "").split("@")[-1]
    if not host:
        return "fail"
    base = f"https://{host}"
    soft = False
    for path in ("/listTopicManagers", "/listLookupServiceProviders"):
        try:
            status, body, _ = _http_get(base + path)
        except urllib.error.HTTPError as e:
            if e.code in (403, 429):
                soft = True
            continue
        except (urllib.error.URLError, ssl.SSLError, OSError, ValueError):
            continue
        if status != 200:
            continue
        try:
            doc = json.loads(body)
        except (ValueError, UnicodeDecodeError):
            continue
        if isinstance(doc, (dict, list)):
            return "pass"  # a single verified endpoint confirms the surface
    if soft:
        return "soft"  # host up but unverified (botwall) -> pending, not failed
    return "fail"  # no verified endpoint and not merely bot-walled


def probe_protocol(slug: str, proto: str, url: str | None, live_net: bool) -> str:
    """Run the defined probe for a protocol. Returns one of:
      "pass" | "fail" | "soft" | "untested".
    "soft" means a live-but-bot-walled host (403/429) — honest pending, never a
    failure. Callers map pass->confirmed, fail->failed, soft/untested->pending.
    Only ever called for protocols whose state rule resolved to a probe.
    """
    if proto not in PROBE_DEFINED:
        return "untested"
    if not url:
        return "fail"
    if live_net:
        if proto == "paymail":
            return _paymail_probe(url)
        if proto in ("ship", "slap"):
            return _ship_slap_probe(url)
        return "untested"
    return "pass" if _mock(slug + "|" + proto) > 0.15 else "fail"


def spv_verify(txid: str | None, live_net: bool) -> bool:
    """THE ONLY BOX-COUPLED CALL. Intended: local SPV node over localhost.
    To relocate off-box, replace this body with an auth'd POST to bsv.cx/verify.

    NOT YET WIRED: the SV node is still syncing and not reachable from here, so
    in live mode we honestly return False (unverified) rather than fabricate a
    result. No current seed entry claims an onchain_txid, so this is a no-op for
    now — it becomes real once the node is synced and this body calls it."""
    if not txid:
        return False
    if live_net:
        return False  # node not yet available; unverified is the honest answer
    return _mock(txid + "|spv") > 0.5


def _github_repo_probe(repo: str) -> tuple[bool, str | None]:
    """Real GitHub probe. Returns (repo_public, last_commit_iso).
    Unauthenticated API (fine for a handful of entries); on rate-limit or any
    error we return (False, None) rather than guessing."""
    p = urllib.parse.urlparse(repo)
    if p.netloc.lower() not in ("github.com", "www.github.com"):
        return False, None  # only GitHub probe defined; others honestly unknown
    parts = [x for x in p.path.split("/") if x]
    if len(parts) < 2:
        return False, None
    owner, name = parts[0], parts[1].removesuffix(".git")
    try:
        status, body, _ = _http_get(f"https://api.github.com/repos/{owner}/{name}")
    except (urllib.error.HTTPError, urllib.error.URLError, ssl.SSLError, OSError, ValueError):
        return False, None
    if status != 200:
        return False, None
    try:
        meta = json.loads(body)
    except (ValueError, UnicodeDecodeError):
        return False, None
    public = (meta.get("private") is False)
    last_commit = meta.get("pushed_at")  # ISO8601 of most recent push
    return public, last_commit


def probe_repo(slug: str, repo: str | None, live_net: bool) -> tuple[bool, str | None]:
    if not repo:
        return False, None
    if live_net:
        return _github_repo_probe(repo)
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


# --- per-protocol state (four-state model) -----------------------------------

def _load_prior_states(slug: str) -> dict:
    """Read the previously-stored protocol_states for this slug, so a cycle can
    PRESERVE human work. Missing/corrupt store -> empty (start fresh)."""
    f = ATTESTED_DIR / f"{slug}.json"
    if not f.exists():
        return {}
    try:
        prior = json.loads(f.read_text()) or {}
    except (ValueError, OSError):
        return {}
    states = prior.get("protocol_states")
    return states if isinstance(states, dict) else {}


def _probe_state(slug: str, proto: str, url: str | None, live_net: bool,
                 method: str, checked_at: str) -> dict:
    """Run the defined probe and wrap the result as a state object.
    pass->confirmed, fail->failed, soft(botwall)/untested->pending (honest:
    a live-but-bot-walled host is unverified, never a failure)."""
    res = probe_protocol(slug, proto, url, live_net)
    state = {"pass": "confirmed", "fail": "failed"}.get(res, "pending")
    return {"state": state, "method": method, "by": None, "at": checked_at,
            "note": "bot-walled (403/429): host up, unverified"
                    if res == "soft" else None}


def compute_protocol_states(slug: str, claimed: dict, live_net: bool,
                            checked_at: str, prior_states: dict) -> dict:
    """Compute the state object for every claimed protocol.

    MERGE-PRESERVE RULE (critical): probe-backed and "na" states are recomputed
    and overwritten every cycle (they're machine-derived). But an existing
    "manual" state object is PRESERVED untouched — a cycle must never clobber a
    human confirm/fail. Only if no manual state exists yet do we seed a fresh
    honest "pending". Manual decay is applied at READ time (effective_state),
    not here, so the stored human judgement stays intact with its real `at`.
    """
    category = claimed.get("category")
    url = claimed.get("url")
    out: dict = {}
    for proto in (claimed.get("protocols") or []):
        rule = protocol_state_rule(category, proto, url)
        prior = prior_states.get(proto)
        prior_is_manual = isinstance(prior, dict) and prior.get("method") == "manual"

        if rule.startswith("probe:"):
            out[proto] = _probe_state(slug, proto, url, live_net, rule, checked_at)
        elif rule == "manual":
            # Preserve a human's prior manual state; else seed honest pending.
            if prior_is_manual:
                out[proto] = prior
            else:
                out[proto] = {"state": "pending", "method": "manual",
                              "by": None, "at": checked_at, "note": None}
        else:  # "na"
            # Even na is overwritten each cycle — UNLESS a human explicitly
            # recorded a manual judgement, which we never silently erase.
            if prior_is_manual:
                out[proto] = prior
            else:
                out[proto] = {"state": "na", "method": "na", "by": None,
                              "at": checked_at, "note": None}
    return out


def states_to_checks(states: dict) -> dict:
    """Derive the legacy protocol_checks {proto: pass|fail|untested} from the
    four-state model so rank.py keeps working unchanged:
      confirmed -> pass, failed -> fail, pending/na -> untested."""
    mapping = {"confirmed": "pass", "failed": "fail"}
    return {proto: mapping.get(so.get("state"), "untested")
            for proto, so in states.items()}


# --- main loop ---------------------------------------------------------------

def attest_entry(path: pathlib.Path, live_net: bool) -> dict:
    claimed = (json.loads(path.read_text()) or {}).get("claimed") or {}
    slug = claimed.get("slug", path.stem)
    checked_at = _now()

    live, latency = probe_liveness(slug, claimed.get("url"), live_net,
                                   claimed.get("probe_url"))
    prior_states = _load_prior_states(slug)
    protocol_states = compute_protocol_states(slug, claimed, live_net,
                                              checked_at, prior_states)
    # Back-compat: rank.py still reads protocol_checks; derive it from states.
    checks = states_to_checks(protocol_states)
    onchain = spv_verify(claimed.get("onchain_txid"), live_net)
    repo_public, last_commit = probe_repo(slug, claimed.get("repo"), live_net)
    uptime_90d = append_series(slug, checked_at, live)

    attested = {
        "checked_at": checked_at,
        "live": live,
        "uptime_90d": uptime_90d,
        "latency_ms": latency,
        "protocol_checks": checks,
        "protocol_states": protocol_states,
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
                    help="use real network probes (HTTP liveness, Paymail, GitHub). "
                         "On-chain SPV verify is still stubbed until the node is synced.")
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
        st = {p: so["state"] for p, so in a["protocol_states"].items()}
        print(f"[{flag}] {path.stem:16} uptime90={a['uptime_90d']:.3f} "
              f"states={st} onchain={a['onchain_verified']}")
    print(f"attested {len(files)} entr{'y' if len(files) == 1 else 'ies'} "
          f"(mode={'LIVE' if args.live else 'stub'})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
