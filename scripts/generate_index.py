#!/usr/bin/env python3
"""
generate_index.py - build the GitHub Pages landing page from whatever PDFs are
in dist/.

    python scripts/generate_index.py --dist dist/

The page leads with the canonical resume.pdf (the link to actually hand out)
and lists the role-specific builds underneath.
"""

import argparse
from datetime import datetime, timezone
from pathlib import Path

import yaml

ROOT = Path(__file__).parent.parent
BASE_YAML = ROOT / "resume" / "base_content.yml"
VARIANTS_DIR = ROOT / "variants"

ICONS = {
    "ai": "◆", "ml": "◇", "backend": "▣", "data": "▤",
    "devops": "▦", "frontend": "◈", "research": "◉",
}


def variant_meta() -> dict[str, dict]:
    meta = {}
    for f in sorted(VARIANTS_DIR.glob("*.yml")):
        v = yaml.safe_load(f.read_text()) or {}
        stem = v.get("filename", f.stem)
        meta[stem] = {
            "label": v.get("variant_name", stem.replace("_", " ").title()),
            "icon": ICONS.get(v.get("role", stem), "◆"),
            "default": bool(v.get("default")),
        }
    return meta


def generate(dist: Path):
    base = yaml.safe_load(BASE_YAML.read_text())
    person = base["personal"]
    meta = variant_meta()

    canonical = dist / "resume.pdf"
    built = datetime.now(timezone.utc).strftime("%B %d, %Y")

    # Only list PDFs that correspond to a declared variant. An ad-hoc build
    # tailored to one company must never publish itself just by sitting here.
    variants = sorted(p for p in dist.glob("resume_*.pdf")
                      if p.stem.replace("resume_", "") in meta)
    strays = sorted(p for p in dist.glob("resume_*.pdf")
                    if p.stem.replace("resume_", "") not in meta)
    for p in strays:
        print(f"  ! ignoring {p.name} - not a declared variant (will not be linked)")

    cards = []
    for pdf in variants:
        stem = pdf.stem.replace("resume_", "")
        m = meta[stem]
        cards.append(
            f'      <a class="card" href="{pdf.name}">'
            f'<span class="icon">{m["icon"]}</span>'
            f'<span class="label">{m["label"]}</span></a>'
        )
    cards_html = "\n".join(cards)

    primary = (
        f'    <a class="primary" href="resume.pdf">Download résumé (PDF)</a>'
        if canonical.exists() else ""
    )

    html = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8" />
<meta name="viewport" content="width=device-width, initial-scale=1" />
<title>{person['name']} - Résumé</title>
<meta name="description" content="Résumé of {person['name']}." />
<style>
  :root {{
    --bg: #fbfbfa; --fg: #1a1a18; --muted: #6b6b66;
    --line: #e4e4e0; --card: #ffffff; --accent: #1a1a18;
  }}
  @media (prefers-color-scheme: dark) {{
    :root {{
      --bg: #141413; --fg: #eeeeec; --muted: #9a9a94;
      --line: #2c2c29; --card: #1d1d1b; --accent: #eeeeec;
    }}
  }}
  * {{ box-sizing: border-box; margin: 0; padding: 0; }}
  body {{
    background: var(--bg); color: var(--fg);
    font: 16px/1.6 -apple-system, BlinkMacSystemFont, "Segoe UI", Helvetica, sans-serif;
    display: flex; align-items: center; justify-content: center;
    min-height: 100vh; padding: 2rem 1.25rem;
  }}
  main {{ width: 100%; max-width: 620px; }}
  h1 {{ font-size: 1.9rem; letter-spacing: -0.02em; margin-bottom: 0.3rem; }}
  .meta {{ color: var(--muted); font-size: 0.93rem; margin-bottom: 0.4rem; }}
  .links {{ font-size: 0.93rem; margin-bottom: 2rem; }}
  .links a {{ color: var(--muted); text-decoration: none; border-bottom: 1px solid var(--line); }}
  .links a:hover {{ color: var(--fg); }}
  .links span {{ color: var(--line); margin: 0 0.5rem; }}
  .primary {{
    display: block; text-align: center; background: var(--accent);
    color: var(--bg); text-decoration: none; padding: 0.9rem 1rem;
    border-radius: 9px; font-weight: 600; margin-bottom: 2.25rem;
  }}
  .primary:hover {{ opacity: 0.88; }}
  h2 {{
    font-size: 0.78rem; text-transform: uppercase; letter-spacing: 0.09em;
    color: var(--muted); font-weight: 600; margin-bottom: 0.85rem;
  }}
  .grid {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(170px, 1fr)); gap: 0.6rem; }}
  .card {{
    display: flex; align-items: center; gap: 0.6rem;
    background: var(--card); border: 1px solid var(--line);
    border-radius: 9px; padding: 0.8rem 0.9rem;
    text-decoration: none; color: var(--fg); font-size: 0.93rem;
  }}
  .card:hover {{ border-color: var(--muted); }}
  .icon {{ color: var(--muted); }}
  footer {{ margin-top: 2.5rem; color: var(--muted); font-size: 0.82rem; }}
</style>
</head>
<body>
  <main>
    <h1>{person['name']}</h1>
    <p class="meta">{person['location']}</p>
    <p class="links">
      <a href="mailto:{person['email']}">{person['email']}</a><span>·</span>
      <a href="https://{person['github']}">GitHub</a><span>·</span>
      <a href="https://{person['linkedin']}">LinkedIn</a>
    </p>
{primary}
    <h2>Tailored versions</h2>
    <div class="grid">
{cards_html}
    </div>
    <footer>Built from source on {built}.</footer>
  </main>
</body>
</html>
"""

    dist.mkdir(parents=True, exist_ok=True)
    (dist / "index.html").write_text(html, encoding="utf-8")
    print(f"✓ index.html - 1 canonical + {len(variants)} variants")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dist", default=str(ROOT / "dist"))
    args = ap.parse_args()
    generate(Path(args.dist))


if __name__ == "__main__":
    main()
