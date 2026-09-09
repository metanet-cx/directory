# data/ — the attestation store (machine-written)

Nothing in here is authored by hand, and nothing measured ships in the main
branch. This directory is the output of `scripts/attestor.py`:

- `attested/<slug>.json` — the latest attested block for each entry (what the
  site renders and `rank.py` scores).
- `series/<slug>.jsonl` — append-only liveness history, feeds `uptime_90d`.

Both globs are `.gitignore`d on `main`. In production the attestor runs on the
bsv.cx box and pushes its results to a dedicated **data branch** every cycle, so
the store is its own off-box backup — never opaque on-box-only state.

Running the stub attestor locally (`python3 scripts/attestor.py`) fills these
paths with **deterministic mock** values for testing the pipeline. Those are not
real measurements and must never be committed — publishing mock uptime numbers
would be the exact fake-attestation this project exists to reject.
