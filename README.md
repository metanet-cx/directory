# metanet.cx

A self-verifying directory of the BSV / Metanet ecosystem. Permissive on
submission, ruthless on claims: anyone can list; nothing earns a badge or a
rank it can't prove. See [DESIGN.md](DESIGN.md) for the full rationale.

## The one rule

**Claims are author-written. Attestations are machine-written. The site ranks
and badges only on attestations.**

- `entries/<slug>.json` — **claimed** block only. This is what you submit via PR.
- `data/attested/<slug>.json` — **attested** block. Written *only* by the
  attestor. Never hand-edit; a PR touching it is rejected by CI.
- `data/series/<slug>.jsonl` — append-only liveness history (feeds `uptime_90d`).

`claimed` and `attested` live in physically separate files on purpose, so the
CI guard can flatly reject author-written attestations without ever colliding
with the attestor's own output.

## Submit a listing

Add one file, `entries/<your-slug>.json`:

```json
{
  "claimed": {
    "name": "Your Project",
    "slug": "your-slug",
    "category": "wallet",
    "summary": "One line.",
    "repo": "https://github.com/you/proj",
    "url": "https://yourproject.example",
    "protocols": ["brc-100", "paymail"],
    "onchain_txid": null,
    "self_tier": null,
    "submitted_by": "your-gh-handle"
  }
}
```

Open a PR. CI validates the schema and confirms you didn't include an
`attested` block. On merge, the attestor picks it up on its next cycle and
begins measuring you. Your rank is earned from those measurements, not your claims.

`category` ∈ node·sdk·overlay·indexer·wallet·identity·token·storage·payments·social·other.
`self_tier` (S·A·B·C) is your *own* interop claim — displayed as self-reported,
**never** used in the objective score.

## Scripts (Python 3, stdlib only — no dependencies)

    python3 scripts/check_pr.py          # CI guard: validate + reject author attestations
    python3 scripts/attestor.py          # stub attestor (mock probes; writes data/attested/)
    python3 scripts/attestor.py --slug X # attest one entry
    python3 scripts/rank.py              # objective ranking (join claimed + attested)
    python3 scripts/build.py             # render static site -> site/ (what Pages deploys)

`build.py` joins each entry's `claimed` block with its `attested` block (if any)
and writes `site/index.html`, `site/style.css`, and `site/entry/<slug>.html`.
With an empty `data/` (a fresh clone, and what Pages builds from) every entry
renders as **unattested** — no invented uptime, latency, or pass marks. `site/`
is build output and gitignored.

The attestor is a **stub**: probes are deterministic mocks so the whole loop,
store, ranking, and file round-trip run with no box and no network. `--live`
is reserved for wiring real HTTP / protocol / SPV probes (currently raises).

## Deployment

**Static site → Cloudflare Pages** (renders this repo on push). Create the
project against `metanet-cx/directory` with:

- **Framework preset:** None
- **Build command:** `scripts/pages-build.sh`  (runs `python3 scripts/build.py`)
- **Build output directory:** `site`
- **Production branch:** `main`

Then add `metanet.cx` (and `www`) under the project's **Custom domains** — Pages
creates the correct CNAME in the Cloudflare zone and provisions the cert. That
replaces the Namecheap parking records. No app server; merges auto-rebuild.

Remaining:
- **Attestor** → bsv.cx box, alongside the SPV node (on-chain verify stays a
  local call). The only box-coupled call is `spv_verify()` in `attestor.py`;
  swap it for an auth'd `POST bsv.cx/verify` to relocate the attestor off-box.
- **Attestation store** (`data/`) → its own git data branch, pushed each cycle,
  so the store is its own off-box backup.
