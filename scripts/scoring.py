#!/usr/bin/env python3
"""
scoring.py - rank every line of the resume against a target role.

The model is deliberately simple and explainable; `build.py --explain` prints
the per-item breakdown so you can see exactly why a bullet won or lost.

    score = W_TAG    * tag_overlap
          + W_KEYWORD* keyword_hits
          + W_MANUAL * manual_weight
          + W_PARENT * parent_weight
          + recency_bonus
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

# ── Tunable weights ──────────────────────────────────────────────────────────
W_TAG     = 3.0   # per matching role tag
W_KEYWORD = 2.5   # per matching keyword (scaled by that keyword's demand)
W_MANUAL  = 1.5   # per point of hand-set `weight`
W_PARENT  = 0.6   # per point of the parent role/project's `weight`
W_RECENCY = 2.0   # max bonus for the most recent role

# Keywords named explicitly on the command line count for more than keywords
# merely inferred from a job description.
EXPLICIT_KEYWORD_BOOST = 2.0


def normalize(s: str) -> str:
    """Lowercase and collapse punctuation so 'CI/CD' matches 'ci cd'."""
    return re.sub(r"[^a-z0-9+#.]+", " ", s.lower()).strip()


@dataclass
class Target:
    """What we are tailoring toward."""
    role: str = ""
    # keyword -> demand multiplier (1.0 baseline; higher = mentioned more)
    keywords: dict[str, float] = field(default_factory=dict)

    @property
    def tags(self) -> set[str]:
        return {self.role} if self.role else set()

    def keyword_demand(self, kw: str) -> float:
        return self.keywords.get(normalize(kw), 0.0)


@dataclass
class Scored:
    item: dict
    score: float
    matched_tags: list[str]
    matched_keywords: list[str]

    def explain(self) -> str:
        bits = []
        if self.matched_tags:
            bits.append("tags=" + ",".join(self.matched_tags))
        if self.matched_keywords:
            bits.append("kw=" + ",".join(self.matched_keywords[:6]))
        w = self.item.get("weight", 0)
        if w:
            bits.append(f"weight={w:+d}")
        return "; ".join(bits) or "no match"


def score_item(
    item: dict,
    target: Target,
    parent_weight: int = 0,
    recency: float = 0.0,
) -> Scored:
    """Score one bullet / skill / line against the target."""
    item_tags = set(item.get("tags", []))
    matched_tags = sorted(item_tags & target.tags)

    tag_component = W_TAG * len(matched_tags)

    matched_keywords: list[str] = []
    keyword_component = 0.0
    for kw in item.get("keywords", []):
        demand = target.keyword_demand(kw)
        if demand > 0:
            matched_keywords.append(kw)
            keyword_component += W_KEYWORD * demand

    manual_component  = W_MANUAL  * item.get("weight", 0)
    parent_component  = W_PARENT  * parent_weight
    recency_component = W_RECENCY * recency

    total = (
        tag_component
        + keyword_component
        + manual_component
        + parent_component
        + recency_component
    )
    return Scored(item, total, matched_tags, matched_keywords)


# ── Keyword vocabulary + job-description extraction ──────────────────────────
def build_vocabulary(base: dict) -> set[str]:
    """Every keyword that appears anywhere in base_content.yml."""
    vocab: set[str] = set()

    def harvest(obj):
        if isinstance(obj, dict):
            for kw in obj.get("keywords", []) or []:
                vocab.add(normalize(kw))
            if "name" in obj and "tags" in obj:
                vocab.add(normalize(obj["name"]))
            for v in obj.values():
                harvest(v)
        elif isinstance(obj, list):
            for v in obj:
                harvest(v)

    harvest(base)
    vocab.discard("")
    return vocab


def extract_from_jd(text: str, vocab: set[str]) -> dict[str, float]:
    """
    Find which known keywords the job description actually asks for, weighted by
    how often it mentions them. Matching against our own vocabulary (rather than
    doing open-ended NLP) keeps this predictable and dependency-free.
    """
    haystack = normalize(text)
    found: dict[str, float] = {}

    for kw in vocab:
        # Word-boundary match so "go" doesn't fire on "going" or "algorithm".
        pattern = r"(?<![a-z0-9])" + re.escape(kw) + r"(?![a-z0-9])"
        hits = len(re.findall(pattern, haystack))
        if hits:
            # Diminishing returns: 1 mention = 1.0, 2 = 1.5, 4 = 2.0, 8 = 2.5
            found[kw] = 1.0 + 0.5 * (hits - 1) ** 0.5 if hits > 1 else 1.0

    return found


def make_target(
    role: str,
    explicit_keywords: list[str],
    jd_text: str | None,
    vocab: set[str],
) -> Target:
    """Combine --role, --keywords and --jd into a single scoring target."""
    keywords: dict[str, float] = {}

    if jd_text:
        keywords.update(extract_from_jd(jd_text, vocab))

    # Explicit --keywords always win and outweigh anything inferred from a JD.
    for kw in explicit_keywords:
        k = normalize(kw)
        if k:
            keywords[k] = keywords.get(k, 1.0) * EXPLICIT_KEYWORD_BOOST

    return Target(role=role, keywords=keywords)
