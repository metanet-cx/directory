#!/usr/bin/env python3
"""CI guard for metanet.cx entry PRs.

Enforces the trust model at the gate:
  1. Every entries/*.json has a valid `claimed:` block (schema.validate_claimed).
  2. NO entry file contains an `attested:` block. Attestations are machine-written
     only; a PR that sets them is the exact spoof this project exists to prevent.

Exit non-zero on any violation so the PR check fails. Reads all entries so a PR
can't sneak a bad file past by only touching one.
"""
from __future__ import annotations
import json
import sys

from schema import ENTRIES_DIR, ENTRY_GLOB, ATTESTED_FIELDS, validate_claimed


def main() -> int:
    errors: list[str] = []
    files = sorted(ENTRIES_DIR.glob(ENTRY_GLOB))
    if not files:
        print("no entries found under entries/ — nothing to check")
        return 0

    for path in files:
        slug = path.stem
        try:
            doc = json.loads(path.read_text()) or {}
        except json.JSONDecodeError as e:
            errors.append(f"{slug}: invalid JSON: {e}")
            continue
        if not isinstance(doc, dict):
            errors.append(f"{slug}: top level must be a mapping with a claimed: block")
            continue

        # Rule 2: attestations are machine-only. Reject any attested: in a PR.
        if "attested" in doc:
            errors.append(
                f"{slug}: PRs must not include an `attested:` block — "
                f"attestations are machine-written by the attestor. Remove it."
            )
        # Also catch attested fields smuggled into claimed:.
        smuggled = ATTESTED_FIELDS & set(doc.get("claimed") or {})
        if smuggled:
            errors.append(f"{slug}: attested-only field(s) in claimed: {sorted(smuggled)}")

        if "claimed" not in doc:
            errors.append(f"{slug}: missing required `claimed:` block")
            continue
        errors.extend(validate_claimed(slug, doc["claimed"]))

    if errors:
        print("PR CHECK FAILED:\n" + "\n".join(f"  - {e}" for e in errors))
        return 1
    print(f"PR check passed: {len(files)} entr{'y' if len(files) == 1 else 'ies'} valid, no attested blocks.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
