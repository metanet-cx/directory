# metanet.cx — attestation store (machine-written)

This branch is **not** human-authored. It is the output of `scripts/attestor.py`,
published each attestor cycle. `pages-build.sh` fetches it so the live site can
render real, earned scores. Do not open PRs against this branch — submit listings
via `entries/` on `main`.

- `attested/<slug>.json` — latest attested block per entry
- `series/<slug>.jsonl` — append-only liveness history (feeds uptime_90d)
