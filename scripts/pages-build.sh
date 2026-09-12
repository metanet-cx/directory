#!/usr/bin/env bash
# Cloudflare Pages build command for metanet.cx.
# Set in the Pages project: Build command = scripts/pages-build.sh
#                           Build output directory = site
#                           (no framework preset; Python is in the build image)
#
# Builds from a CLEAN checkout: data/attested and data/series are gitignored, so
# a Pages build has no attestation store and the site renders every entry as
# "unattested" — the correct, honest state until the real attestor publishes to
# a data branch. Nothing here fabricates metrics.
set -euo pipefail
python3 --version
python3 scripts/build.py
