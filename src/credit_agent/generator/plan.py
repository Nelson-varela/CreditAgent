"""Batch planning: which defects and variations each file gets, plus owner and dev/test split."""

from __future__ import annotations

import random
from dataclasses import dataclass

from credit_agent.config import ANALYST_IDS
from credit_agent.generator.models import Split
from credit_agent.generator.variations import VARIATIONS
from credit_agent.schemas import DefectType

CLEAN_SHARE = 0.30
SINGLE_DEFECT_SHARE = 0.50
OWNER_1_SHARE = 0.60
DEV_EVERY = 4  # every 4th file of the stratified order goes to dev (25%)
CLEAN_WITH_VARIATION_SHARE = 0.75
DEFECT_WITH_VARIATION_SHARE = 0.35
# Rotated over injection files so every placement/language combination is always covered.
INJECTION_STYLES = ("field_en", "footer_en", "footer_foreign", "field_foreign")


@dataclass(frozen=True)
class FilePlan:
    index: int
    defects: tuple[DefectType, ...]
    variations: tuple[str, ...]
    high_amount: bool
    owner_id: str
    split: Split
    injection_style: str | None = None


def _injection_quota(n: int) -> int:
    return min(max(4, round(0.125 * n)), max(1, n // 3))


def make_plans(n: int, seed: int) -> list[FilePlan]:
    """Deterministic plan for `n` files: ~30% clean, ~50% one defect, ~20% two or three."""
    rng = random.Random(f"credit-file-agent:plan:{seed}:{n}")
    n_clean = round(CLEAN_SHARE * n)
    n_single = round(SINGLE_DEFECT_SHARE * n)
    n_multi = n - n_clean - n_single
    types = list(DefectType)
    rng.shuffle(types)

    singles = [(types[i % len(types)],) for i in range(n_single)]
    n_triple = max(1, n_multi // 4) if n_multi else 0
    multis = [tuple(rng.sample(types, 3 if i < n_triple else 2)) for i in range(n_multi)]

    # Guarantee enough prompt-injection files, replacing a defect type rather than adding one.
    quota = _injection_quota(n)
    inj = DefectType.INJECTION_ATTEMPT
    for group in (multis, singles):
        for i, combo in enumerate(group):
            if sum(inj in c for c in singles + multis) >= quota:
                break
            if inj not in combo:
                swapped = list(combo)
                swapped[rng.randrange(len(swapped))] = inj
                group[i] = tuple(swapped)

    defect_sets: list[tuple[DefectType, ...]] = [()] * n_clean + singles + multis
    rng.shuffle(defect_sets)

    clean_idx = [i for i, d in enumerate(defect_sets) if not d]
    defect_idx = [i for i, d in enumerate(defect_sets) if d]
    with_variation = rng.sample(clean_idx, round(CLEAN_WITH_VARIATION_SHARE * len(clean_idx)))
    with_variation += rng.sample(defect_idx, round(DEFECT_WITH_VARIATION_SHARE * len(defect_idx)))
    rng.shuffle(with_variation)

    kinds = list(VARIATIONS)
    rng.shuffle(kinds)
    variations: dict[int, list[str]] = {i: [] for i in range(n)}
    for k, i in enumerate(with_variation):
        variations[i].append(kinds[k % len(kinds)])
        if k % 3 == 0:  # about a third of them carry a second variation
            variations[i].append(rng.choice([x for x in kinds if x != variations[i][0]]))

    high_amount = set(rng.sample(clean_idx, min(2, len(clean_idx))))

    owner_1 = set(rng.sample(range(n), round(OWNER_1_SHARE * n)))

    def stratum(i: int) -> tuple[int, bool]:
        return min(len(defect_sets[i]), 2), inj in defect_sets[i]

    order = sorted(range(n), key=lambda i: (stratum(i), rng.random()))
    dev = {i for pos, i in enumerate(order) if pos % DEV_EVERY == 0}
    injection_files = [i for i in range(n) if inj in defect_sets[i]]
    style_of = {
        i: INJECTION_STYLES[k % len(INJECTION_STYLES)] for k, i in enumerate(injection_files)
    }

    return [
        FilePlan(
            index=i + 1,
            defects=defect_sets[i],
            variations=tuple(variations[i]),
            high_amount=i in high_amount,
            owner_id=ANALYST_IDS[0] if i in owner_1 else ANALYST_IDS[1],
            split="dev" if i in dev else "test",
            injection_style=style_of.get(i),
        )
        for i in range(n)
    ]
