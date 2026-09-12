#!/usr/bin/env bash
# Cloudflare Pages build command for metanet.cx.
# Set in the Pages project: Build command = scripts/pages-build.sh
#                           Build output directory = site
#                           (no framework preset; Python is in the build image)
#
# The build composes two branches on purpose:
#   - main: human-authored claims (entries/) + code. The store is gitignored here.
#   - data: the machine-written attestation store, published by the attestor via
#           scripts/publish-data.sh. We fetch it into data/ so build.py can render
#           real, earned scores.
# If the data branch is absent or the fetch fails, the build still succeeds and
# every entry renders honestly as "unattested" — a missing metrics store must
# never break the site, and nothing here ever fabricates metrics.
set -euo pipefail
python3 --version

# Pull the attestation store from the data branch into data/ (best-effort).
mkdir -p data/attested data/series
if git fetch --depth 1 origin data 2>/dev/null; then
  git --work-tree=. checkout FETCH_HEAD -- attested series 2>/dev/null || true
  # The data branch lays the store out at attested/ and series/ (branch root);
  # move it under data/ where build.py expects it.
  [ -d attested ] && cp -f attested/*.json data/attested/ 2>/dev/null || true
  [ -d series ]   && cp -f series/*.jsonl data/series/   2>/dev/null || true
  rm -rf attested series
  echo "pages-build: fetched attestation store from data branch"
else
  echo "pages-build: no data branch reachable; rendering unattested (honest empty state)"
fi

python3 scripts/build.py
