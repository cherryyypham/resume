# Cheriana de jian li

_Or in other words, Cherry's resume! :>_

:cherry_blossom::cherry_blossom::cherry_blossom::cherry_blossom::cherry_blossom::cherry_blossom::cherry_blossom::cherry_blossom::cherry_blossom::cherry_blossom::cherry_blossom::cherry_blossom::cherry_blossom::cherry_blossom::cherry_blossom::cherry_blossom::cherry_blossom::cherry_blossom::cherry_blossom::cherry_blossom::cherry_blossom::cherry_blossom::cherry_blossom::cherry_blossom::cherry_blossom::cherry_blossom::cherry_blossom::cherry_blossom::cherry_blossom::cherry_blossom::cherry_blossom::cherry_blossom::cherry_blossom::cherry_blossom::cherry_blossom::cherry_blossom:

<br>

## GENERIC RESUME LINK

```
https://cherryyypham.github.io/resume/resume.pdf
```

`resume.pdf` is a fallback copy of the variant marked `default: true`. Every push to `main` rebuilds it at the same URL, so the link never goes stale.

<br>

## "Automatically" Tailoring Resume!

```bash
# by role
python scripts/build.py --role backend

# by role + skills
python scripts/build.py --role ai --keywords pytorch,rag,aws

# by actual job posting's keywords
python scripts/build.py --jd ~/Downloads/posting.txt

# a saved preset from variants/
python scripts/build.py --variant ai

# everything :ooo
python scripts/build.py --all
```

#### Seeing why a line won or lost

```bash
python scripts/build.py --role ai --keywords pytorch --explain
```

```
   ── ranked content ──────────────────────────────
       20.5  fcrr/fcrr_llm           tags=ai; kw=pytorch; weight=+5
       19.0  fcrr/fcrr_rag           tags=ai; kw=rag; weight=+4
       18.5  encom/encom_speedup     tags=ai; kw=pytorch; weight=+5
   ·   12.0  encom/encom_ablation    tags=ai; weight=+4      <- "·" = not used
```

It also prints every cut the packer made to reach one page.

#### Flags

| Flag | Default | Effect |
|---|---|---|
| `--max-bullets N` | 3 | Bullets per job |
| `--max-projects N` | 2 | Projects shown |
| `--max-skills N` | 14 | Skills per line |
| `--floor N` | 0 | Minimum score to be considered at all |
| `--summary` | off | Include the role summary paragraph |
| `--with-phone` | off | Add phone to the header |
| `--keep-tex` | off | Keep the generated `.tex` |
| `--explain` | off | Ranked content + every cut |


#### How scoring works

Every bullet, skill and coursework line in `base_content.yml` carries:


- **`tags`** - which role buckets the line speaks to (`--role` matches these)
- **`keywords`** - concrete tech tokens; matched against `--keywords` and against the text of a `--jd` posting
- **`weight`** - your thumb on the scale, `-3..+5`. Use `+5` for lines that belong on every version
- **`short`** - an optional tighter phrasing the packer falls back to before dropping the line entirely

```
score = 3.0 x matching tags
      + 2.5 x matching keywords (x how often the JD mentions each)
      + 1.5 x weight
      + 0.6 x parent role/project weight
      + up to 2.0 recency bonus
```

Tune the constants at the top of [`scripts/scoring.py`](scripts/scoring.py).

#### One-page enforcement

The packer compiles, reads the real page count from the pdflatex log, and if the
resume spills over it repeatedly takes the globally lowest-scoring line and:
1. swaps in its `short` phrasing, if it has one; otherwise
2. drops it,

recompiling each time until it fits. Only once content cuts are exhausted does it
tighten the layout (11pt -> 10pt, reduced itemsep) and try again. Every cut is reported and headers/title fields stay the same. CI additionally fails the build if any PDF is not exactly one page.

<br>

## Local setup

```bash
pip install -r requirements.txt
brew install --cask mactex        # macOS
# sudo apt install texlive-latex-extra texlive-fonts-recommended   # Debian/Ubuntu
```

```bash
python scripts/build.py --all
python scripts/generate_index.py --dist dist/
open dist/index.html
```
