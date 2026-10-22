#!/usr/bin/env python3
"""
build.py - score every line of base_content.yml against a target role, pack the
highest scorers onto exactly one page, and compile the PDF.

    # ad-hoc, nothing to commit
    python scripts/build.py --role ai --keywords pytorch,rag,aws

    # score against an actual posting
    python scripts/build.py --role backend --jd ~/Downloads/posting.txt

    # saved preset
    python scripts/build.py --variant ai

    # see exactly why each line won or lost, and what got cut to fit
    python scripts/build.py --role ml --explain

    # everything in variants/, plus dist/resume.pdf as the canonical default
    python scripts/build.py --all
"""

from __future__ import annotations

import argparse
import re
import shutil
import subprocess
import sys
from pathlib import Path

import jinja2
import yaml

from scoring import Scored, Target, build_vocabulary, make_target, score_item

ROOT         = Path(__file__).parent.parent
BASE_YAML    = ROOT / "resume" / "base_content.yml"
TEMPLATE_DIR = ROOT / "resume"
TEMPLATE     = "resume.tex.j2"
VARIANTS_DIR = ROOT / "variants"

# dist/ is what GitHub Pages publishes, so only --variant / --all write there.
# Ad-hoc builds (a resume tailored to one specific posting) land in out/, which
# is gitignored and never deployed - those are yours, not the world's.
PUBLISHED_OUT = ROOT / "dist"
SCRATCH_OUT   = ROOT / "out"

# Layout knobs the packer may tighten before it starts deleting content.
LAYOUT_STEPS = [
    {"fontsize": 11, "itemsep": 2, "topsep": 4, "parsep": 4, "topmargin": -0.5, "textheight": 1.0},
    {"fontsize": 11, "itemsep": 1, "topsep": 3, "parsep": 3, "topmargin": -0.6, "textheight": 1.2},
    {"fontsize": 10, "itemsep": 1, "topsep": 3, "parsep": 3, "topmargin": -0.7, "textheight": 1.4},
]

MAX_PACK_ITERATIONS = 80


# jinja environment with custom delimiters to avoid clashing with LaTeX syntax
def make_jinja_env() -> jinja2.Environment:
    return jinja2.Environment(
        loader=jinja2.FileSystemLoader(str(TEMPLATE_DIR)),
        block_start_string="<%",
        block_end_string="%>",
        variable_start_string="<<",
        variable_end_string=">>",
        comment_start_string="<#",
        comment_end_string="#>",
        trim_blocks=True,
        lstrip_blocks=True,
    )

# ═══════════════════════════════════════════════════════════════════════════
# Selection model
#
# A Unit is one removable thing. The packer deletes units bottom-up by score
# until the document fits, honouring `protected`.
# ═══════════════════════════════════════════════════════════════════════════
class Unit:
    __slots__ = ("kind", "parent_id", "item", "score", "detail", "protected", "dropped", "shortened")

    def __init__(self, kind, parent_id, item, scored: Scored, protected=False):
        self.kind      = kind          # bullet | role | project | skill | pub | extra | eduline
        self.parent_id = parent_id
        self.item      = item
        self.score     = scored.score
        self.detail    = scored.explain()
        self.protected = protected
        self.dropped   = False
        self.shortened = False

    @property
    def id(self) -> str:
        return self.item.get("id") or self.item.get("name", "?")

    @property
    def label(self) -> str:
        return f"{self.parent_id}/{self.id}" if self.parent_id else self.id

    def text(self) -> str:
        if self.shortened and self.item.get("short"):
            return self.item["short"]
        return self.item.get("text", "")

    def can_shorten(self) -> bool:
        return bool(self.item.get("short")) and not self.shortened


def recency_of(index: int, total: int) -> float:
    """1.0 for the first (most recent) role, decaying to 0 for the oldest."""
    if total <= 1:
        return 1.0
    return max(0.0, 1.0 - index / (total - 1))


def select(base: dict, target: Target, opts: dict) -> tuple[dict, list[Unit]]:
    """Score everything and build the initial (generous) selection."""
    units: list[Unit] = []
    floor = opts["score_floor"]

    # ── Experience ───────────────────────────────────────────────────────────
    roles_in = base.get("experience", [])
    role_units: list[tuple[dict, Unit, list[Unit]]] = []

    for i, role in enumerate(roles_in):
        rec     = recency_of(i, len(roles_in))
        r_score = score_item(role, target, recency=rec)
        r_unit  = Unit("role", "", role, r_score)

        b_units = []
        for b in role.get("bullets", []):
            s = score_item(b, target, parent_weight=role.get("weight", 0), recency=rec)
            b_units.append(Unit("bullet", role["id"], b, s))

        b_units.sort(key=lambda u: u.score, reverse=True)

        # A role only earns space if its best bullet clears the floor.
        if not b_units or b_units[0].score < floor:
            r_unit.dropped = True
            for u in b_units:
                u.dropped = True
        else:
            for u in b_units[opts["max_bullets_per_role"]:]:
                u.dropped = True
            for u in b_units:
                if u.score < floor:
                    u.dropped = True
            # Never leave a visible role with zero bullets.
            if all(u.dropped for u in b_units):
                b_units[0].dropped = False
            # The top-scoring bullet of the top role is the resume's anchor.
            if i == 0:
                b_units[0].protected = True
                r_unit.protected = True

        role_units.append((role, r_unit, b_units))
        units.append(r_unit)
        units.extend(b_units)

    # ── Projects ─────────────────────────────────────────────────────────────
    proj_in = base.get("projects", [])
    proj_units: list[tuple[dict, Unit, list[Unit]]] = []

    for proj in proj_in:
        p_score = score_item(proj, target)
        p_unit  = Unit("project", "", proj, p_score)

        b_units = []
        for b in proj.get("bullets", []):
            s = score_item(b, target, parent_weight=proj.get("weight", 0))
            b_units.append(Unit("bullet", proj["id"], b, s))
        b_units.sort(key=lambda u: u.score, reverse=True)

        if not b_units or b_units[0].score < floor:
            p_unit.dropped = True
            for u in b_units:
                u.dropped = True
        else:
            for u in b_units[opts["max_bullets_per_project"]:]:
                u.dropped = True
            for u in b_units:
                if u.score < floor:
                    u.dropped = True
            if all(u.dropped for u in b_units):
                b_units[0].dropped = False

        proj_units.append((proj, p_unit, b_units))
        units.append(p_unit)
        units.extend(b_units)

    # Cap visible projects by score.
    live_projects = sorted(
        (t for t in proj_units if not t[1].dropped),
        key=lambda t: t[1].score, reverse=True,
    )
    for _, p_unit, b_units in live_projects[opts["max_projects"]:]:
        p_unit.dropped = True
        for u in b_units:
            u.dropped = True

    # ── Education (headings always survive; coursework lines are droppable) ──
    edu_units: list[tuple[dict, list[Unit]]] = []
    for edu in base.get("education", []):
        lines = []
        for ln in edu.get("lines", []):
            s = score_item(ln, target, parent_weight=edu.get("weight", 0))
            u = Unit("eduline", edu["id"], ln, s)
            lines.append(u)
        lines.sort(key=lambda u: u.score, reverse=True)
        # At most one coursework line per school.
        for u in lines[1:]:
            u.dropped = True
        edu_units.append((edu, lines))
        units.extend(lines)

    # ── Skills ───────────────────────────────────────────────────────────────
    skill_units: list[tuple[str, dict, list[Unit]]] = []
    for key, section in (base.get("skills") or {}).items():
        s_units = []
        for item in section.get("items", []):
            s = score_item(item, target)
            u = Unit("skill", key, item, s, protected=item.get("always", False))
            s_units.append(u)
        s_units.sort(key=lambda u: u.score, reverse=True)
        for u in s_units:
            if u.score < floor and not u.protected:
                u.dropped = True
        for u in s_units[opts["max_skills_per_section"]:]:
            if not u.protected:
                u.dropped = True
        skill_units.append((key, section, s_units))
        units.extend(s_units)

    # ── Publications / extras - only when they genuinely match ───────────────
    pub_units = []
    for pub in base.get("publications", []):
        s = score_item(pub, target)
        u = Unit("pub", "", pub, s)
        u.dropped = s.score < max(floor, opts["section_floor"])
        pub_units.append(u)
        units.append(u)

    extra_units = []
    for ex in base.get("extras", []):
        s = score_item(ex, target)
        u = Unit("extra", "", ex, s)
        u.dropped = s.score < max(floor, opts["section_floor"])
        extra_units.append(u)
        units.append(u)

    model = {
        "roles":    role_units,
        "projects": proj_units,
        "edu":      edu_units,
        "skills":   skill_units,
        "pubs":     pub_units,
        "extras":   extra_units,
    }
    return model, units


# ── Model -> Jinja context ───────────────────────────────────────────────────
CONTACT_RENDERERS = {
    "location": lambda p: p["location"],
    "email":    lambda p: f"\\href{{mailto:{p['email']}}}{{{p['email']}}}",
    "linkedin": lambda p: f"\\href{{https://{p['linkedin']}}}{{{p['linkedin']}}}",
    "github":   lambda p: f"\\href{{https://{p['github']}}}{{{p['github']}}}",
    "phone":    lambda p: p["phone"],
}


def make_context(base: dict, model: dict, opts: dict, layout: dict) -> dict:
    p = base["personal"]
    fields = list(p.get("contact_fields", ["location", "linkedin", "github", "email"]))
    if opts["with_phone"] and "phone" not in fields:
        fields.append("phone")
    contact_line = " $|$\n    ".join(CONTACT_RENDERERS[f](p) for f in fields if f in CONTACT_RENDERERS)

    experience = []
    for role, r_unit, b_units in model["roles"]:
        if r_unit.dropped:
            continue
        bullets = [u.text() for u in b_units if not u.dropped]
        if bullets:
            experience.append({**role, "bullets": bullets})

    projects = []
    for proj, p_unit, b_units in model["projects"]:
        if p_unit.dropped:
            continue
        bullets = [u.text() for u in b_units if not u.dropped]
        if bullets:
            projects.append({**proj, "bullets": bullets})
    projects.sort(key=lambda pr: next(
        u.score for _, u, _ in model["projects"] if u.item is pr or u.item["id"] == pr["id"]
    ), reverse=True)

    education = []
    for edu, lines in model["edu"]:
        education.append({
            "heading": edu["heading"],
            "dates":   edu["dates"],
            "lines":   [u.text() for u in lines if not u.dropped],
        })

    skills = []
    for key, section, s_units in model["skills"]:
        items = [u.item["name"] for u in s_units if not u.dropped]
        if items:
            skills.append({"label": section["label"], "items": items})

    summary = None
    if opts["summary"]:
        summary = (base.get("summaries") or {}).get(opts["role"])

    return {
        "personal":     {**p, "contact_line": contact_line},
        "summary":      summary,
        "education":    education,
        "skills":       skills,
        "experience":   experience,
        "projects":     projects,
        "publications": [u.text() for u in model["pubs"] if not u.dropped],
        "extras":       [u.item for u in model["extras"] if not u.dropped],
        "extras_label": base.get("extras_label", "Other"),
        "layout":       layout,
    }


# ── Compile ──────────────────────────────────────────────────────────────────
PAGECOUNT_RE = re.compile(r"Output written on \S+ \((\d+) pages?")


def compile_latex(tex_path: Path, out_dir: Path, passes: int = 1) -> tuple[Path, int]:
    """Compile and return (pdf_path, page_count). Page count comes from the
    pdflatex log, so there is no runtime dependency on a PDF library."""
    log_text = ""
    for _ in range(passes):
        result = subprocess.run(
            ["pdflatex", "-interaction=nonstopmode", "-halt-on-error",
             "-output-directory", str(out_dir), str(tex_path)],
            capture_output=True, text=True,
        )
        log_text = result.stdout
        if result.returncode != 0:
            print("── pdflatex failed ──────────────────────────────")
            print(log_text[-2500:])
            raise RuntimeError(f"pdflatex failed for {tex_path.name}")

    pdf = out_dir / tex_path.with_suffix(".pdf").name

    # pdflatex hard-wraps its log at 79 columns, so "(2 pages" can be split
    # across lines. Unwrap before matching, and never silently assume 1 page -
    # a missed match here would make the packer think everything fits.
    unwrapped = log_text.replace("\n", "")
    m = PAGECOUNT_RE.search(unwrapped)
    if not m:
        raise RuntimeError(
            f"Could not read page count from pdflatex output for {tex_path.name}. "
            "The packer cannot verify the one-page constraint; aborting."
        )
    return pdf, int(m.group(1))


def clean_aux(out_dir: Path, stem: str):
    for ext in (".aux", ".log", ".out"):
        f = out_dir / f"{stem}{ext}"
        if f.exists():
            f.unlink()


# ── The packing loop ─────────────────────────────────────────────────────────
def droppable(units: list[Unit], model: dict) -> list[Unit]:
    """Units that may still be removed, lowest score first."""
    # A role/project must keep at least one bullet, so its last live bullet is
    # only removable together with its parent.
    live_counts: dict[str, int] = {}
    for u in units:
        if u.kind == "bullet" and not u.dropped:
            live_counts[u.parent_id] = live_counts.get(u.parent_id, 0) + 1

    live_skill_counts: dict[str, int] = {}
    for u in units:
        if u.kind == "skill" and not u.dropped:
            live_skill_counts[u.parent_id] = live_skill_counts.get(u.parent_id, 0) + 1

    out = []
    for u in units:
        if u.dropped or u.protected:
            continue
        if u.kind == "bullet" and live_counts.get(u.parent_id, 0) <= 1:
            continue  # last bullet standing - drop the parent instead
        if u.kind == "skill" and live_skill_counts.get(u.parent_id, 0) <= 2:
            continue  # keep each skills line meaningful
        if u.kind in ("role", "project"):
            continue  # handled via cascade below
        out.append(u)

    # Whole roles/projects become droppable once they are down to one bullet.
    for u in units:
        if u.kind in ("role", "project") and not u.dropped and not u.protected:
            if live_counts.get(u.id, 0) <= 1:
                out.append(u)

    out.sort(key=lambda u: u.score)
    return out


def cascade_drop(unit: Unit, units: list[Unit]):
    unit.dropped = True
    if unit.kind in ("role", "project"):
        for u in units:
            if u.parent_id == unit.id:
                u.dropped = True


def pack(base, model, units, opts, out_dir: Path, stem: str, env, verbose: bool):
    """Compile, and if it spills past one page, tighten then cut until it fits."""
    template = env.get_template(TEMPLATE)
    tex_path = out_dir / f"{stem}.tex"
    cuts: list[tuple[str, float, str]] = []

    for layout_i, layout in enumerate(LAYOUT_STEPS):
        for _ in range(MAX_PACK_ITERATIONS):
            ctx = make_context(base, model, opts, layout)
            tex_path.write_text(template.render(**ctx), encoding="utf-8")
            pdf, pages = compile_latex(tex_path, out_dir)

            if pages <= 1:
                return pdf, pages, cuts, layout, layout_i

            # Always act on the globally weakest line. If it has a tighter
            # phrasing, spend that first - shortening costs less than deleting,
            # and the line stays in the pool to be dropped later if still needed.
            candidates = droppable(units, model)
            if not candidates:
                break  # nothing left to cut at this layout; try a tighter one

            u = candidates[0]
            if u.can_shorten():
                u.shortened = True
                cuts.append((u.label, u.score, "shortened"))
                if verbose:
                    print(f"     ~ shortened {u.label} (score {u.score:.1f})")
            else:
                cascade_drop(u, units)
                cuts.append((u.label, u.score, f"dropped ({u.kind})"))
                if verbose:
                    print(f"     - dropped {u.label} (score {u.score:.1f}, {u.kind})")

        if verbose and layout_i + 1 < len(LAYOUT_STEPS):
            print(f"     tightening layout (step {layout_i + 2})")

    ctx = make_context(base, model, opts, LAYOUT_STEPS[-1])
    tex_path.write_text(template.render(**ctx), encoding="utf-8")
    pdf, pages = compile_latex(tex_path, out_dir)
    return pdf, pages, cuts, LAYOUT_STEPS[-1], len(LAYOUT_STEPS) - 1


# ── One build ────────────────────────────────────────────────────────────────
def run_build(opts: dict, out_dir: Path) -> Path:
    base  = yaml.safe_load(BASE_YAML.read_text())
    vocab = build_vocabulary(base)

    jd_text = None
    if opts["jd"]:
        jd_path = Path(opts["jd"]).expanduser()
        if not jd_path.exists():
            sys.exit(f"ERROR: job description not found: {jd_path}")
        jd_text = jd_path.read_text(errors="ignore")

    target = make_target(opts["role"], opts["keywords"], jd_text, vocab)

    label = opts["name"] or opts["role"] or "resume"
    print(f"\n── Building: {label} ─────────────────────────────────")
    print(f"   role:     {opts['role'] or '(none)'}")
    if target.keywords:
        top = sorted(target.keywords.items(), key=lambda kv: -kv[1])[:12]
        print(f"   keywords: {', '.join(k for k, _ in top)}"
              + (f" (+{len(target.keywords) - len(top)} more)" if len(target.keywords) > len(top) else ""))
    if jd_text:
        print(f"   jd:       {opts['jd']} → {len(target.keywords)} keywords matched")

    model, units = select(base, target, opts)

    if opts["explain"]:
        print("\n   ── ranked content ──────────────────────────────")
        for u in sorted(units, key=lambda u: -u.score):
            if u.kind in ("role", "project"):
                continue
            mark = " " if not u.dropped else "·"
            print(f"   {mark} {u.score:6.1f}  {u.label:<34} {u.detail}")
        print()

    out_dir.mkdir(parents=True, exist_ok=True)
    stem = f"resume_{label}"
    env  = make_jinja_env()

    pdf, pages, cuts, layout, layout_i = pack(
        base, model, units, opts, out_dir, stem, env, verbose=opts["explain"]
    )
    clean_aux(out_dir, stem)
    if not opts["keep_tex"]:
        (out_dir / f"{stem}.tex").unlink(missing_ok=True)

    status = "✓ 1 page" if pages <= 1 else f"✗ STILL {pages} PAGES"
    print(f"   {status}  →  {pdf.name}")
    if layout_i:
        print(f"   layout:   tightened to step {layout_i + 1} "
              f"({layout['fontsize']}pt, itemsep {layout['itemsep']}pt)")
    if cuts:
        print(f"   cut {len(cuts)} to fit:")
        for lbl, score, how in cuts:
            print(f"     · {lbl:<34} {score:6.1f}  {how}")
    if pages > 1:
        print("   ⚠  Could not reach one page. Lower --max-bullets or raise --floor.")

    return pdf


# ── CLI ──────────────────────────────────────────────────────────────────────
def load_variant(name: str) -> dict:
    f = VARIANTS_DIR / f"{name}.yml"
    if not f.exists():
        available = ", ".join(sorted(p.stem for p in VARIANTS_DIR.glob("*.yml")))
        sys.exit(f"ERROR: no variant '{name}'. Available: {available}")
    return yaml.safe_load(f.read_text()) or {}


def main():
    ap = argparse.ArgumentParser(
        description="Build a one-page resume tailored to a role.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    ap.add_argument("--role", default="", help="Target role tag: ai, ml, backend, data, devops, fullstack, frontend, research, systems")
    ap.add_argument("--keywords", default="", help="Comma-separated skills to prioritize, e.g. pytorch,aws,rag")
    ap.add_argument("--jd", default="", help="Path to a job description; keywords are extracted from it")
    ap.add_argument("--variant", help="Use a saved preset from variants/")
    ap.add_argument("--all", action="store_true", help="Build every variant plus the canonical resume.pdf")
    ap.add_argument("--name", default="", help="Output filename stem (default: role or variant name)")
    ap.add_argument("--output", default="", help="Output directory (default: dist/ for presets, out/ for ad-hoc builds)")

    ap.add_argument("--max-bullets", type=int, default=3, dest="max_bullets_per_role")
    ap.add_argument("--max-project-bullets", type=int, default=3, dest="max_bullets_per_project")
    ap.add_argument("--max-projects", type=int, default=2)
    ap.add_argument("--max-skills", type=int, default=14, dest="max_skills_per_section")
    ap.add_argument("--floor", type=float, default=0.0, dest="score_floor",
                    help="Minimum score for a line to be considered at all")
    ap.add_argument("--section-floor", type=float, default=4.0, dest="section_floor",
                    help="Minimum score for optional sections (publications, extras)")

    ap.add_argument("--summary", action="store_true", help="Include the role summary paragraph")
    ap.add_argument("--with-phone", action="store_true", help="Include phone number in the header")
    ap.add_argument("--keep-tex", action="store_true", help="Keep the generated .tex next to the PDF")
    ap.add_argument("--explain", action="store_true", help="Print the ranked content and every cut")
    args = ap.parse_args()

    publishing = bool(args.all or args.variant)
    out_dir = Path(args.output) if args.output else (PUBLISHED_OUT if publishing else SCRATCH_OUT)

    def opts_from(ns, overrides: dict | None = None) -> dict:
        o = {
            "role": ns.role,
            "keywords": [k.strip() for k in ns.keywords.split(",") if k.strip()],
            "jd": ns.jd,
            "name": ns.name,
            "max_bullets_per_role": ns.max_bullets_per_role,
            "max_bullets_per_project": ns.max_bullets_per_project,
            "max_projects": ns.max_projects,
            "max_skills_per_section": ns.max_skills_per_section,
            "score_floor": ns.score_floor,
            "section_floor": ns.section_floor,
            "summary": ns.summary,
            "with_phone": ns.with_phone,
            "keep_tex": ns.keep_tex,
            "explain": ns.explain,
        }
        if overrides:
            o.update(overrides)
        return o

    def opts_for_variant(name: str) -> dict:
        v = load_variant(name)
        o = opts_from(args, {
            "role":     v.get("role", name),
            "keywords": v.get("keywords", []),
            "name":     v.get("filename", name),
        })
        for key in ("max_bullets_per_role", "max_bullets_per_project", "max_projects",
                    "max_skills_per_section", "score_floor", "section_floor",
                    "summary", "with_phone"):
            if key in v:
                o[key] = v[key]
        return o

    if args.all:
        names = sorted(p.stem for p in VARIANTS_DIR.glob("*.yml"))
        if not names:
            sys.exit("No variants found in variants/")
        print(f"Building {len(names)} variants: {', '.join(names)}")
        built = {}
        for n in names:
            built[n] = run_build(opts_for_variant(n), out_dir)

        # Canonical permalink target: dist/resume.pdf never 404s.
        default_variant = next(
            (n for n in names if (load_variant(n) or {}).get("default")), names[0]
        )
        canonical = out_dir / "resume.pdf"
        shutil.copyfile(built[default_variant], canonical)
        print(f"\n   ★ resume.pdf  ←  {built[default_variant].name}  (canonical permalink)")
    elif args.variant:
        run_build(opts_for_variant(args.variant), out_dir)
    else:
        if not (args.role or args.keywords or args.jd):
            ap.error("give at least one of --role, --keywords, --jd, --variant, or --all")
        run_build(opts_from(args), out_dir)

    print(f"\n✅  Output in {out_dir.resolve()}")


if __name__ == "__main__":
    main()
