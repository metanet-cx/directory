"""Shared schema + loader for metanet.cx directory entries.

One entry per file in entries/<slug>.json. Two blocks:
  claimed:  author-written (via PR). Validated on PR.
  attested: machine-written (by attestor.py). Never present in a PR.

Entries are JSON (stdlib parse, no third-party dep). One flat object per file:
{"claimed": {...}, "attested": {...}}.

This module is the single source of truth for both the CI guard (check_pr.py)
and the attestor. Keep field lists here, not duplicated elsewhere.
"""
from __future__ import annotations
import datetime as dt
import pathlib
import urllib.parse

CATEGORIES = {
    "node", "sdk", "overlay", "indexer", "wallet", "identity",
    "token", "storage", "payments", "social", "other",
}
SELF_TIERS = {"S", "A", "B", "C", None}

# --- per-protocol four-state conformance model -------------------------------
#
# Each (entry x claimed-protocol) resolves to exactly one state:
#   "confirmed" : a real measurement (probe or human) said it's there.
#   "failed"    : a real measurement said it isn't (an earned red mark).
#   "pending"   : manually-reviewable, but no human has confirmed it yet
#                 (the honest default — "we haven't measured this").
#   "na"        : there is no externally-probeable surface for this entry's
#                 KIND, so conformance simply doesn't apply here.
#
# A state is stored as an object with provenance:
#   {"state": <one of PROTOCOL_STATES>,
#    "method": "probe:ship-slap" | "probe:paymail" | "manual" | "na",
#    "by": <who or null>, "at": <ISO8601>, "note": <optional>}
PROTOCOL_STATES = {"confirmed", "failed", "pending", "na"}

# A manual confirm/fail is a point-in-time human judgement. It auto-decays to
# "pending" once it's older than this, computed at READ time (we never mutate
# the stored file to decay — see effective_state).
MANUAL_DECAY_DAYS = 90

# Hosts that are libraries / package pages / spec pages, not a running service.
# A url on one of these is source/spec, so a service-only probe is "na".
LIBRARY_HOST_SUFFIXES = (
    "npmjs.com", "npmjs.org", "registry.npmjs.org",
    "github.com", "gitlab.com", "brc.dev", "bitcoinschema.org",
)
LIBRARY_HOST_PREFIXES = ("docs.",)  # docs.scrypt.io, docs.* etc.


def _is_library_url(url: str | None) -> bool:
    """True iff the url is a package/source/spec page (not a live host we can
    probe as a running service). npm/github/gitlab/brc.dev + docs.* are code
    or specs, not deployed endpoints."""
    if not url:
        return True  # no hittable surface at all -> treat as library/na
    host = (urllib.parse.urlparse(url).netloc or "").lower().split(":")[0]
    if not host:
        return True
    if any(host == s or host.endswith("." + s) for s in LIBRARY_HOST_SUFFIXES):
        return True
    if any(host.startswith(p) for p in LIBRARY_HOST_PREFIXES):
        return True
    return False


# Protocols that, for a deployed SERVICE, are backed by a real overlay probe.
_OVERLAY_SERVICE_PROTOCOLS = {"ship", "slap"}
# brc-100 is manually reviewable only for these "has a live wallet surface"
# categories; everywhere else it's na (libraries/CLIs/indexers have no endpoint).
_BRC100_MANUAL_CATEGORIES = {
    "wallet", "identity", "payments", "social", "token", "storage", "overlay",
}


def protocol_state_rule(category: str | None, protocol: str,
                        url: str | None) -> str:
    """THE single source of truth for how a claimed protocol is graded.

    Returns one of:
      "probe:ship-slap" | "probe:paymail"  -> a real probe decides confirmed/failed
      "manual"                             -> human-reviewable; starts "pending"
      "na"                                 -> no probeable surface for this KIND

    Derived purely from (category, protocol, url) so grading is rule-driven and
    auditable, never a per-entry free choice. A url on npm/github/brc.dev/docs.*
    is a library or spec (not a live host), so service-only probes resolve "na".
    """
    proto = (protocol or "").lower()
    cat = (category or "").lower()
    is_lib = _is_library_url(url)

    # paymail (and brc-28 when it travels with paymail) is probe-backed via
    # BSVAlias .well-known service discovery on the entry's own domain.
    if proto == "paymail":
        return "na" if is_lib else "probe:paymail"
    if proto == "brc-28":
        # brc-28 is the paymail transaction spec; it's only probe-backed when it
        # rides along a paymail service. On its own (a spec page) it's na.
        return "na"

    # ship/slap: probe-backed ONLY when the entry is a deployed overlay service
    # with a hittable URL. For sdk/overlay entries that are actually a library
    # or source repo, the code is not a running host -> na.
    if proto in _OVERLAY_SERVICE_PROTOCOLS:
        if cat in ("overlay", "storage", "social", "indexer") and not is_lib:
            return "probe:ship-slap"
        return "na"

    # brc-100: manually reviewable where there's a live wallet surface; na for
    # libraries/CLIs/indexers (sdk, other, indexer) which have no endpoint.
    if proto == "brc-100":
        if cat in _BRC100_MANUAL_CATEGORIES and not is_lib:
            return "manual"
        return "na"

    # brc-102 (LARS/CARS local dev tooling): always na — local dev tools.
    if proto == "brc-102":
        return "na"

    # Everything else (gasp, uhrp, brc-26, beef, brc-42, brc-121, x402, sigma,
    # bitcoin-script, junglebus, 1sat, ...) has no probe defined yet -> na.
    # (When a real probe is added, wire it above and it flips on automatically.)
    return "na"


def effective_state(state_obj: dict | None, now: dt.datetime | None = None) -> dict:
    """Return the state as it should be READ right now, applying manual decay.

    A state written with method "manual" whose `at` is older than
    MANUAL_DECAY_DAYS is downgraded to a fresh "pending" object — a human
    confirm is a point-in-time judgement and goes stale. We never mutate the
    stored file; decay is computed here at render/score time.

    Non-manual states (probe:*/na) and anything still fresh pass through
    unchanged. Malformed/missing objects return an honest "pending".
    """
    if not isinstance(state_obj, dict):
        return {"state": "pending", "method": "manual", "by": None,
                "at": None, "note": None}
    if state_obj.get("method") != "manual":
        return state_obj
    if state_obj.get("state") not in ("confirmed", "failed"):
        return state_obj  # a manual "pending" is already the decayed target
    now = now or dt.datetime.now(dt.timezone.utc)
    at_raw = state_obj.get("at")
    try:
        at = dt.datetime.fromisoformat(str(at_raw).replace("Z", "+00:00"))
        if at.tzinfo is None:
            at = at.replace(tzinfo=dt.timezone.utc)
    except (ValueError, TypeError):
        return state_obj  # unparsable timestamp: leave as-is rather than guess
    if (now - at).days > MANUAL_DECAY_DAYS:
        return {"state": "pending", "method": "manual",
                "by": state_obj.get("by"), "at": state_obj.get("at"),
                "note": "decayed: manual confirm older than "
                        f"{MANUAL_DECAY_DAYS}d"}
    return state_obj

# Fields a PR author may set. Anything else under claimed: is rejected.
# probe_url is optional: the URL the attestor hits for the liveness check when
# `url` is a human-facing page the attestor can't fairly probe (e.g. an npm
# package page that bot-walls automated requests). If omitted, liveness probes
# `url` itself. It never affects what's displayed — only what's measured.
CLAIMED_FIELDS = {
    "name", "slug", "category", "summary", "repo", "url",
    "protocols", "onchain_txid", "self_tier", "submitted_by", "probe_url",
}
CLAIMED_REQUIRED = {"name", "slug", "category", "summary", "submitted_by"}

# Fields the attestor writes. A PR that includes an attested: block at all is rejected.
ATTESTED_FIELDS = {
    "checked_at", "live", "uptime_90d", "latency_ms", "protocol_checks",
    "protocol_states", "onchain_verified", "repo_public", "last_commit",
    "attestor_version",
}

ENTRIES_DIR = pathlib.Path(__file__).resolve().parent.parent / "entries"
ENTRY_GLOB = "*.json"


def validate_claimed(slug: str, claimed: dict) -> list[str]:
    """Return a list of human-readable errors; empty means valid."""
    errs: list[str] = []
    if not isinstance(claimed, dict):
        return [f"{slug}: `claimed:` must be a mapping"]

    unknown = set(claimed) - CLAIMED_FIELDS
    if unknown:
        errs.append(f"{slug}: unknown claimed field(s): {sorted(unknown)}")
    missing = CLAIMED_REQUIRED - set(claimed)
    if missing:
        errs.append(f"{slug}: missing required claimed field(s): {sorted(missing)}")

    if claimed.get("slug") != slug:
        errs.append(f"{slug}: claimed.slug ({claimed.get('slug')!r}) must equal filename slug")
    cat = claimed.get("category")
    if cat not in CATEGORIES:
        errs.append(f"{slug}: category {cat!r} not in {sorted(CATEGORIES)}")
    if claimed.get("self_tier") not in SELF_TIERS:
        errs.append(f"{slug}: self_tier {claimed.get('self_tier')!r} must be one of S|A|B|C or omitted")
    protos = claimed.get("protocols")
    if protos is not None and not (isinstance(protos, list) and all(isinstance(p, str) for p in protos)):
        errs.append(f"{slug}: protocols must be a list of strings")
    probe = claimed.get("probe_url")
    if probe is not None and not (isinstance(probe, str) and probe.startswith("https://")):
        errs.append(f"{slug}: probe_url must be an https:// URL or omitted")
    return errs
