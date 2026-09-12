#!/usr/bin/env python3
"""Static site generator for metanet.cx — renders the directory to site/.

Stdlib only (no pip on the box; keeps the build reproducible anywhere Python
3.12 runs). Reads:
  entries/<slug>.json        claimed block (PR-authored)
  data/attested/<slug>.json  attested block (machine-written; may be ABSENT)

Joins the two at read time exactly like rank.py, then writes:
  site/index.html            the directory (ranked table + per-entry cards)
  site/style.css             styling
  site/entry/<slug>.html     one page per entry

HONESTY RULE (the whole point of the project): when no attested block exists for
an entry, the site says so — "unattested", no badges, sorted last. It never
invents uptime, latency, or pass marks. A fresh checkout with an empty data/
dir renders a fully valid, honest site that simply has nothing attested yet.

self_tier is the submitter's own claim: it renders in its own clearly-labeled
"self-reported" column and is NEVER an input to the objective score (see rank.py).
"""
from __future__ import annotations

import datetime as dt
import html
import json
import pathlib
import shutil

from schema import ENTRIES_DIR, ENTRY_GLOB, CATEGORIES
from rank import score, proto_pass_ratio, ATTESTED_DIR

ROOT = pathlib.Path(__file__).resolve().parent.parent
SITE_DIR = ROOT / "site"
GENERATED_AT = dt.datetime.now(dt.timezone.utc).replace(microsecond=0).isoformat()


def esc(x) -> str:
    return html.escape("" if x is None else str(x))


def load() -> list[dict]:
    """Return joined rows: {slug, claimed, attested|None, score|None}."""
    rows = []
    for path in sorted(ENTRIES_DIR.glob(ENTRY_GLOB)):
        slug = path.stem
        claimed = (json.loads(path.read_text()) or {}).get("claimed") or {}
        apath = ATTESTED_DIR / f"{slug}.json"
        attested = json.loads(apath.read_text()) if apath.exists() else None
        rows.append({
            "slug": slug,
            "claimed": claimed,
            "attested": attested,
            "score": score(attested) if attested else None,
        })
    # Attested entries first, by score desc; unattested last, alpha by name.
    rows.sort(key=lambda r: (
        r["score"] is None,
        -(r["score"] or 0.0),
        (r["claimed"].get("name") or r["slug"]).lower(),
    ))
    return rows


def uptime_cell(att: dict | None) -> str:
    if not att or att.get("uptime_90d") is None:
        return '<span class="muted">—</span>'
    pct = float(att["uptime_90d"]) * 100
    cls = "good" if pct >= 99 else "ok" if pct >= 95 else "bad"
    return f'<span class="pct {cls}">{pct:.1f}%</span>'


def proto_cell(att: dict | None) -> str:
    if not att:
        return '<span class="muted">—</span>'
    checks = att.get("protocol_checks") or {}
    if not checks:
        return '<span class="muted">none</span>'
    bits = []
    for proto, res in sorted(checks.items()):
        cls = {"pass": "good", "fail": "bad"}.get(res, "muted")
        mark = {"pass": "✓", "fail": "✗"}.get(res, "·")
        bits.append(f'<span class="chk {cls}" title="{esc(proto)}: {esc(res)}">'
                    f'{mark} {esc(proto)}</span>')
    return " ".join(bits)


def onchain_cell(att: dict | None) -> str:
    if not att:
        return '<span class="muted">—</span>'
    return '<span class="badge chain" title="txid confirmed against bsv.cx SPV node">⛓ verified</span>' \
        if att.get("onchain_verified") else '<span class="muted">—</span>'


def self_tier_cell(claimed: dict) -> str:
    t = claimed.get("self_tier")
    if not t:
        return '<span class="muted">—</span>'
    return f'<span class="selftier" title="Submitter’s own claim — not scored">{esc(t)}</span>'


def row_html(i: int, r: dict) -> str:
    c, att = r["claimed"], r["attested"]
    name = esc(c.get("name") or r["slug"])
    url = c.get("url")
    name_link = f'<a href="{esc(url)}" rel="noopener">{name}</a>' if url else name
    score_txt = f'{r["score"]:.3f}' if r["score"] is not None else \
        '<span class="muted" title="No attestation yet">unattested</span>'
    return f"""      <tr>
        <td class="rank">{i}</td>
        <td class="name">{name_link}<div class="sum">{esc(c.get('summary'))}</div>
            <a class="detail" href="entry/{esc(r['slug'])}.html">details →</a></td>
        <td class="cat">{esc(c.get('category'))}</td>
        <td class="score">{score_txt}</td>
        <td>{uptime_cell(att)}</td>
        <td class="proto">{proto_cell(att)}</td>
        <td>{onchain_cell(att)}</td>
        <td class="st">{self_tier_cell(c)}</td>
      </tr>"""


def index_html(rows: list[dict]) -> str:
    attested_n = sum(1 for r in rows if r["attested"])
    body = "\n".join(row_html(i, r) for i, r in enumerate(rows, 1))
    return f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>metanet.cx — self-verifying BSV / Metanet directory</title>
<meta name="description" content="A self-verifying directory of the BSV / Metanet ecosystem. Claims are author-written; attestations are machine-written; the site ranks only on attestations.">
<link rel="stylesheet" href="style.css">
</head>
<body>
<header>
  <h1>metanet<span class="dot">.</span>cx</h1>
  <p class="tag">A self-verifying map of the BSV&nbsp;/&nbsp;Metanet ecosystem.
     Permissive on submission, ruthless on claims.</p>
  <p class="rule"><strong>The one rule:</strong> claims are author-written,
     attestations are machine-written, the site ranks and badges
     <em>only</em> on attestations. <a href="https://github.com/metanet-cx/directory">Submit a listing →</a></p>
</header>
<main>
  <table class="dir">
    <thead>
      <tr>
        <th>#</th><th>Project</th><th>Category</th>
        <th title="Objective score — computed only from attested metrics">Score</th>
        <th title="Measured uptime over 90 days">Uptime</th>
        <th title="Per-protocol conformance probes">Protocols</th>
        <th title="txid confirmed against the bsv.cx SPV node">On-chain</th>
        <th title="Submitter&#39;s own interop claim — display only, never scored">Self&#8209;tier</th>
      </tr>
    </thead>
    <tbody>
{body}
    </tbody>
  </table>
</main>
<footer>
  <p>{len(rows)} listed · {attested_n} attested · Score, uptime, protocol and
     on-chain columns are machine-measured. <strong>Self-tier</strong> is the
     submitter&#39;s own unscored claim.</p>
  <p class="gen">Generated {esc(GENERATED_AT)} ·
     <a href="https://github.com/metanet-cx/directory">source</a></p>
</footer>
</body>
</html>
"""


def entry_html(r: dict) -> str:
    c, att = r["claimed"], r["attested"]
    name = esc(c.get("name") or r["slug"])
    protos = ", ".join(esc(p) for p in (c.get("protocols") or [])) or "—"
    repo = c.get("repo")
    url = c.get("url")
    links = []
    if url:
        links.append(f'<a href="{esc(url)}" rel="noopener">site ↗</a>')
    if repo:
        links.append(f'<a href="{esc(repo)}" rel="noopener">repo ↗</a>')
    links_html = " · ".join(links) or "—"

    if att:
        pr = proto_pass_ratio(att.get("protocol_checks") or {})
        att_rows = f"""
      <tr><th>Checked</th><td>{esc(att.get('checked_at'))}</td></tr>
      <tr><th>Live</th><td>{'yes' if att.get('live') else 'no'}</td></tr>
      <tr><th>Uptime (90d)</th><td>{uptime_cell(att)}</td></tr>
      <tr><th>Latency</th><td>{esc(att.get('latency_ms'))}{' ms' if att.get('latency_ms') is not None else ''}</td></tr>
      <tr><th>Protocols</th><td>{proto_cell(att)}{'' if pr is None else f' &middot; pass-ratio {pr:.0%}'}</td></tr>
      <tr><th>On-chain</th><td>{onchain_cell(att)}</td></tr>
      <tr><th>Repo public</th><td>{'yes' if att.get('repo_public') else 'no'}</td></tr>
      <tr><th>Last commit</th><td>{esc(att.get('last_commit'))}</td></tr>
      <tr><th>Attestor</th><td>v{esc(att.get('attestor_version'))}</td></tr>"""
        score_line = f'<p class="bigscore">{r["score"]:.3f}<span>objective score</span></p>'
        attested_block = f'<table class="kv">{att_rows}\n    </table>'
    else:
        score_line = '<p class="bigscore muted">unattested<span>no machine attestation yet</span></p>'
        attested_block = ('<p class="muted">No attestation has been recorded for this '
                          'entry yet. Nothing here is claimed as verified until the '
                          'attestor probes it.</p>')

    return f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{name} — metanet.cx</title>
<link rel="stylesheet" href="../style.css">
</head>
<body>
<header class="entry">
  <p class="crumb"><a href="../index.html">← metanet.cx</a></p>
  <h1>{name}</h1>
  <p class="tag">{esc(c.get('summary'))}</p>
  {score_line}
</header>
<main>
  <section>
    <h2>Claimed <span class="by">author-written</span></h2>
    <table class="kv">
      <tr><th>Category</th><td>{esc(c.get('category'))}</td></tr>
      <tr><th>Protocols</th><td>{protos}</td></tr>
      <tr><th>Links</th><td>{links_html}</td></tr>
      <tr><th>On-chain txid</th><td>{esc(c.get('onchain_txid')) or '—'}</td></tr>
      <tr><th>Self-tier</th><td>{self_tier_cell(c)} <span class="muted">(submitter&#39;s claim, unscored)</span></td></tr>
      <tr><th>Submitted by</th><td>{esc(c.get('submitted_by'))}</td></tr>
    </table>
  </section>
  <section>
    <h2>Attested <span class="by">machine-written</span></h2>
    {attested_block}
  </section>
</main>
<footer><p class="gen">Generated {esc(GENERATED_AT)} ·
  <a href="https://github.com/metanet-cx/directory">source</a></p></footer>
</body>
</html>
"""


CSS = """:root{
  --bg:#0d1117; --panel:#161b22; --line:#30363d; --fg:#e6edf3; --muted:#7d8590;
  --acc:#f7931a; --good:#3fb950; --ok:#d29922; --bad:#f85149; --link:#58a6ff;
}
*{box-sizing:border-box}
body{margin:0;background:var(--bg);color:var(--fg);
  font:16px/1.5 system-ui,-apple-system,Segoe UI,Roboto,sans-serif}
a{color:var(--link);text-decoration:none}
a:hover{text-decoration:underline}
header{max-width:1100px;margin:0 auto;padding:2.4rem 1.2rem 1rem}
h1{margin:0;font-size:2.6rem;letter-spacing:-.02em}
h1 .dot{color:var(--acc)}
.tag{color:var(--muted);font-size:1.05rem;margin:.4rem 0 0;max-width:60ch}
.rule{margin:1rem 0 0;padding:.7rem .9rem;background:var(--panel);
  border:1px solid var(--line);border-radius:8px;font-size:.92rem}
main{max-width:1100px;margin:0 auto;padding:1rem 1.2rem 2rem}
table.dir{width:100%;border-collapse:collapse;font-size:.92rem}
.dir th,.dir td{padding:.55rem .5rem;border-bottom:1px solid var(--line);
  text-align:left;vertical-align:top}
.dir thead th{color:var(--muted);font-weight:600;font-size:.8rem;
  text-transform:uppercase;letter-spacing:.03em;cursor:help}
.dir td.rank{color:var(--muted);font-variant-numeric:tabular-nums;width:2.2rem}
.dir td.name{min-width:15rem}
.dir td.name a{font-weight:600}
.dir .sum{color:var(--muted);font-size:.82rem;margin:.15rem 0 .1rem;max-width:46ch}
.dir a.detail{font-size:.78rem;color:var(--muted)}
.dir td.cat{color:var(--muted);text-transform:capitalize}
.dir td.score{font-variant-numeric:tabular-nums;font-weight:600}
.pct{font-variant-numeric:tabular-nums;font-weight:600}
.pct.good,.chk.good,.good{color:var(--good)}
.pct.ok,.ok{color:var(--ok)}
.pct.bad,.chk.bad,.bad{color:var(--bad)}
.muted{color:var(--muted)}
.proto{font-size:.8rem}
.chk{display:inline-block;margin:0 .3rem .2rem 0;white-space:nowrap}
.badge.chain{color:var(--acc);font-weight:600;font-size:.82rem}
.selftier{display:inline-block;min-width:1.4rem;text-align:center;
  padding:.05rem .4rem;border:1px dashed var(--muted);border-radius:5px;
  color:var(--muted);font-size:.82rem}
footer{max-width:1100px;margin:0 auto;padding:1rem 1.2rem 3rem;
  color:var(--muted);font-size:.82rem;border-top:1px solid var(--line)}
.gen{opacity:.7}
/* entry pages */
header.entry .crumb{margin:0 0 .6rem;font-size:.9rem}
.bigscore{font-size:2.2rem;font-weight:700;margin:.6rem 0 0;
  font-variant-numeric:tabular-nums}
.bigscore span{display:block;font-size:.8rem;font-weight:400;color:var(--muted)}
section{background:var(--panel);border:1px solid var(--line);border-radius:10px;
  padding:1rem 1.2rem;margin:1.1rem 0}
section h2{margin:0 0 .6rem;font-size:1.1rem}
section h2 .by{font-size:.7rem;color:var(--muted);font-weight:400;
  text-transform:uppercase;letter-spacing:.04em;margin-left:.4rem}
table.kv{width:100%;border-collapse:collapse}
.kv th{text-align:left;color:var(--muted);font-weight:500;width:11rem;
  padding:.4rem .5rem;vertical-align:top;font-size:.9rem}
.kv td{padding:.4rem .5rem;border-bottom:1px solid var(--line)}
"""


def build() -> int:
    rows = load()
    if SITE_DIR.exists():
        shutil.rmtree(SITE_DIR)
    (SITE_DIR / "entry").mkdir(parents=True)
    (SITE_DIR / "style.css").write_text(CSS)
    (SITE_DIR / "index.html").write_text(index_html(rows))
    for r in rows:
        (SITE_DIR / "entry" / f"{r['slug']}.html").write_text(entry_html(r))
    attested_n = sum(1 for r in rows if r["attested"])
    print(f"built site/ — {len(rows)} entries ({attested_n} attested, "
          f"{len(rows) - attested_n} unattested) -> {SITE_DIR}")
    return 0


if __name__ == "__main__":
    raise SystemExit(build())
