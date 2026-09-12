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
import pathlib

CATEGORIES = {
    "node", "sdk", "overlay", "indexer", "wallet", "identity",
    "token", "storage", "payments", "social", "other",
}
SELF_TIERS = {"S", "A", "B", "C", None}

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
    "onchain_verified", "repo_public", "last_commit", "attestor_version",
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
