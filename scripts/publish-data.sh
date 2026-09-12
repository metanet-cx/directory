#!/usr/bin/env bash
# Publish the machine-written attestation store to the `data` branch.
#
# The store (data/attested/*.json, data/series/*.jsonl) is gitignored on `main`
# by design — main holds only human-authored claims + code, never machine data.
# This script pushes the current store to a dedicated orphan `data` branch, which
# serves two purposes at once:
#   1. it IS the off-box backup of the attestation history (gemcity lesson: never
#      let the metrics store become opaque on-box-only state), and
#   2. it's what the Cloudflare Pages build fetches so the live site can render
#      real, earned scores (pages-build.sh pulls it before running build.py).
#
# Safe to run on a timer: uses a throwaway worktree, never touches the main
# checkout, and is a no-op commit-wise when nothing changed.
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

BRANCH="data"
WT="$(mktemp -d)"
trap 'git worktree remove --force "$WT" 2>/dev/null || true; rm -rf "$WT"' EXIT

# Fetch the remote data branch if it exists; otherwise we'll create it orphaned.
if git ls-remote --exit-code --heads origin "$BRANCH" >/dev/null 2>&1; then
  git fetch origin "$BRANCH":"refs/remotes/origin/$BRANCH" >/dev/null 2>&1 || true
  git worktree add --force -B "$BRANCH" "$WT" "origin/$BRANCH" >/dev/null
else
  git worktree add --force --detach "$WT" >/dev/null
  git -C "$WT" checkout --orphan "$BRANCH" >/dev/null 2>&1
  git -C "$WT" rm -rf . >/dev/null 2>&1 || true
fi

# Replace the store wholesale with the current local store.
rm -rf "$WT/attested" "$WT/series"
mkdir -p "$WT/attested" "$WT/series"
# Copy only if there's something to copy (globs may be empty on a first run).
if compgen -G "data/attested/*.json" >/dev/null; then cp data/attested/*.json "$WT/attested/"; fi
if compgen -G "data/series/*.jsonl" >/dev/null; then cp data/series/*.jsonl "$WT/series/"; fi

cat > "$WT/README.md" <<'EOF'
# metanet.cx — attestation store (machine-written)

This branch is **not** human-authored. It is the output of `scripts/attestor.py`,
published each attestor cycle. `pages-build.sh` fetches it so the live site can
render real, earned scores. Do not open PRs against this branch — submit listings
via `entries/` on `main`.

- `attested/<slug>.json` — latest attested block per entry
- `series/<slug>.jsonl` — append-only liveness history (feeds uptime_90d)
EOF

git -C "$WT" add -A
if git -C "$WT" diff --cached --quiet; then
  echo "publish-data: store unchanged, nothing to publish"
  exit 0
fi

STAMP="$(date -u +%Y-%m-%dT%H:%M:%SZ)"
git -C "$WT" commit -q -m "attestor store: $STAMP"
git -C "$WT" push -q origin "$BRANCH"
echo "publish-data: pushed attestation store to origin/$BRANCH ($STAMP)"

# Trigger a Cloudflare Pages rebuild so the live site reflects the new store.
# Pages only auto-builds on `main`, not `data`, so the data push alone won't
# refresh the site — this deploy hook does. The hook URL is a secret: it's read
# from a mode-600 env file outside the repo (never committed, never echoed). If
# the file/var is absent (e.g. a local run), we skip the trigger silently; the
# store is still published and will show on the next main-triggered build.
HOOK_ENV="${METANET_CX_HOOK_ENV:-$HOME/.openclaw/secrets/metanet-cx.env}"
if [ -z "${METANET_CX_DEPLOY_HOOK:-}" ] && [ -f "$HOOK_ENV" ]; then
  set -a; . "$HOOK_ENV"; set +a
fi
if [ -n "${METANET_CX_DEPLOY_HOOK:-}" ]; then
  code="$(curl -s -o /dev/null -w '%{http_code}' -X POST "$METANET_CX_DEPLOY_HOOK" || echo 000)"
  echo "publish-data: deploy hook POST -> HTTP $code"
else
  echo "publish-data: no deploy hook configured; skipping rebuild trigger"
fi
