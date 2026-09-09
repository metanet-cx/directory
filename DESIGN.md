# metanet.cx — Directory Design (draft v0.1)

Status: **v0.1 — scaffolding published, nothing deployed.** Repo is live under the `metanet-cx` org; the attestor is a stub (mock probes) and no box/site is stood up yet. Written 2026-09-09 by Mike, from the design discussion with Andy.

## What it is

A public, self-verifying map of the BSV / Metanet ecosystem. Permissive on *submission* (anyone can list via PR), ruthless on *claims* (nothing earns a badge or a rank it can't prove). Ranking is computed from measured variables — uptime, conformance, on-chain presence — not hand-assigned opinion. Andy's interop tiers ride alongside as a clearly-labeled editorial overlay, never blended into the objective score.

Seed data: `memory/bsv-ecosystem-inventory-2026-09-08.md` (50 entries + interop ranking). Maps ~1:1 onto entry files.

## Trust model (the whole thing in one sentence)

**Claims are author-written; attestations are machine-written; the site ranks and badges only on attestations.** Getting *in* is free. Getting ranked well is earned by passing checks the submitter does not control.

## Architecture

- **GitHub-backed.** One entry file per project. Repo is the source of truth. PRs are the submission + moderation queue (public diff, git history of who claimed what, when).
- **Static site** renders the repo (metanet.cx). CI on merge → rebuild → deploy. No app server.
- **Scheduled attestor** (the one always-on piece): a small worker runs every N minutes, probes each entry's endpoints, and writes results to a metrics store. This is what makes "sortable by uptime over 90 days" real — build-time-only can't produce a time series.
- **bsv.cx** is the on-chain verification backend: txid claims are checked against the self-hosted SPV headers node → issues the ⛓ badge nobody else can issue.

```
 submitter ──PR──▶ GitHub repo (claimed: block only)
                        │  merge
                        ▼
                   static build ──▶ metanet.cx (renders claimed + attested)
                        ▲
 scheduled attestor ────┘  (writes attested: block; probes uptime/conformance;
        │                   calls bsv.cx SPV for on-chain verify)
        ▼
   metrics store (append-only time series — backed up off-box)
```

## Entry schema (two blocks)

The PR author edits **only** `claimed:`. CI rejects any PR that touches `attested:`. The attestor is the sole writer of `attested:`.

```yaml
# entries/<slug>.yaml
claimed:
  name: string
  slug: string                 # unique, kebab-case, = filename
  category: enum               # node|sdk|overlay|indexer|wallet|identity|token|storage|payments|social|other
  summary: string              # one line
  repo: url|null
  url: url|null                # primary live endpoint / site
  protocols: [string]          # e.g. [brc-100, paymail, 1sat, uhrp, brc-26]
  onchain_txid: string|null    # a tx the project asserts as its on-chain presence
  self_tier: enum|null         # submitter's own interop claim (S|A|B|C) — display-only, never scored
  submitted_by: string         # github handle (from PR author, auto-filled)

attested:                      # MACHINE-WRITTEN ONLY — do not hand-edit
  checked_at: iso8601
  live: bool                   # last probe reachable
  uptime_90d: float            # 0.0–1.0 from stored series
  latency_ms: int|null
  protocol_checks:             # each protocol from claimed.protocols, actually probed
    brc-100: pass|fail|untested
    paymail: pass|fail|untested
    # ...
  onchain_verified: bool       # txid confirmed against bsv.cx SPV node
  repo_public: bool
  last_commit: iso8601|null    # zombie detector
  attestor_version: string
```

### Sample entry — Yours Wallet (from inventory #26)

```yaml
claimed:
  name: Yours Wallet
  slug: yours-wallet
  category: wallet
  summary: Non-custodial Chrome extension wallet; BRC-100, 1Sat, MNEE, on-chain identity, dApps.
  repo: https://github.com/yours-org/yours-wallet
  url: https://yours.org
  protocols: [brc-100, 1sat, paymail]
  onchain_txid: null
  self_tier: B
  submitted_by: yours-org

attested:                      # simulated — illustrates what the attestor would write
  checked_at: 2026-09-09T22:00:00Z
  live: true
  uptime_90d: 0.997
  latency_ms: 210
  protocol_checks:
    brc-100: pass            # BRC-100 endpoint answered a probe
    1sat: untested           # no programmatic probe defined yet
    paymail: pass            # .well-known/bsvalias resolved
  onchain_verified: false    # no txid claimed → nothing to verify
  repo_public: true
  last_commit: 2026-08-30T00:00:00Z
  attestor_version: 0.1.0
```

Note: `self_tier: B` is the submitter's *claim* and renders as such (greyed / "self-reported"). The **objective sort** ignores it entirely and orders by `uptime_90d`, then `protocol_checks` pass-count, then `onchain_verified`. Andy's editorial interop tier (if assigned) is a separate labeled column.

## Attestor loop (spec, ~1 paragraph)

A scheduled job (cron or worker, every ~15 min for liveness; heavier conformance + on-chain checks hourly). For each entry: (1) HTTP-probe `claimed.url` → record `live`, `latency_ms`, append to the uptime series; (2) for each `claimed.protocols`, run its defined probe (Paymail → fetch `.well-known/bsvalias`; BRC-100 → hit the wallet-interface endpoint; others `untested` until a probe exists) → `protocol_checks`; (3) if `claimed.onchain_txid`, ask bsv.cx to verify it against the SPV node → `onchain_verified`; (4) fetch repo metadata for `repo_public` + `last_commit`; (5) recompute `uptime_90d` from the stored series; (6) write the `attested:` block. Metrics store = append-only (JSON-per-entry in a data branch, or SQLite on the box) — **must be backed up off-box** (the gemcity lesson: state you don't back up is state you'll lose). Attestor never edits `claimed:`; CI never lets a PR edit `attested:`. Clean separation of who-writes-what is what makes permissive-but-trustworthy actually hold.

## Ranking (objective, then editorial)

- **Objective score** (the default sort, fully computed): weighted `uptime_90d` + `protocol_checks` pass-ratio + `onchain_verified` + `repo activity`. Every input is measured. Sortable by any single variable (uptime, latency, protocol count, last-commit).
- **Editorial overlay** (opt-in view): Andy/Mike's interop-tier read from the inventory, in its own labeled column — "our take," never laundered as a computed number. Mixing the two is the exact credibility leak the whole project exists to avoid.

## Decisions

Resolved (2026-09-09):

1. **Attestor host** — **bsv.cx box**, alongside the SPV node, so on-chain verify stays a local call with no new internet-facing surface. Built portable: the only box-coupled call is `spv_verify()` in `attestor.py`; swap it for an auth'd `POST bsv.cx/verify` to relocate off-box (e.g. to a Render worker) with no other changes.
2. **Metrics store** — **append-only JSON in a git data branch.** `data/attested/<slug>.json` (latest) + `data/series/<slug>.jsonl` (history), pushed each cycle so the store is its own off-box backup. Chosen over SQLite-on-box specifically to avoid opaque local state (the gemcity lesson) and to self-host the proof.
4. **Repo location** — dedicated **`metanet-cx` GitHub org**, this repo (`metanet-cx/directory`). A directory that ranks other people's projects needs a neutral home, not a personal page or a project-owned org.

Still open:

3. **Probe cadence** — 15 min liveness / hourly conformance is a starting guess; tune to not hammer listed projects.
5. **Scope of v1** — this repo ships with 8 real seed entries (claimed-block only); the rest of the ~50-entry inventory gets added via the same PR flow a stranger uses, so we dogfood the submission path without launching a ghost town.

Note on format: the schema samples above are shown as YAML for readability, but the live entry files are **JSON** (`entries/<slug>.json`) — the box has no YAML parser and JSON keeps the scripts dependency-free (stdlib only).

## Why this is differentiated

Every other directory (MCP included, bitcoinsv.it, the awesome-lists) is trust-the-maintainer. This one verifies its own listings and shows the proof. That *is* the mission — verify-don't-trust, demonstrated by being the thing instead of preaching it — and nobody in BSV has a self-verifying, uptime-ranked map.
