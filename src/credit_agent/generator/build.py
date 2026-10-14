"""Builds one file (clean persona + planned defects + planned variations) and whole batches."""

from __future__ import annotations

from datetime import date

from credit_agent.generator.defects import APPLY_ORDER, INJECTORS, inject_missing_doc
from credit_agent.generator.files import FAKE, assemble, build_documents, file_rng
from credit_agent.generator.models import GeneratedFile
from credit_agent.generator.mutate import Ctx
from credit_agent.generator.persona import build_persona
from credit_agent.generator.plan import FilePlan, make_plans
from credit_agent.generator.variations import VARIATIONS, apply_variation
from credit_agent.policy import Policy
from credit_agent.schemas import DefectType


def build_file(plan: FilePlan, *, seed: int, policy: Policy, as_of: date) -> GeneratedFile:
    rng = file_rng(seed, plan.index)
    FAKE.seed_instance(rng.randrange(2**32))
    persona = build_persona(rng, FAKE, policy, as_of, high_amount=plan.high_amount)
    ctx = Ctx(
        rng=rng,
        fake=FAKE,
        persona=persona,
        policy=policy,
        as_of=as_of,
        docs=build_documents(persona),
        injection_style=plan.injection_style or "footer_en",
    )

    # 1) every defect except MISSING_DOC, which must not erase evidence the others rely on
    for defect_type in APPLY_ORDER:
        if defect_type in plan.defects:
            INJECTORS[defect_type](ctx)
    if DefectType.MISSING_DOC in plan.defects:
        inject_missing_doc(ctx)

    # 2) legitimate variations; if one does not fit this file, try another kind instead
    spare = [k for k in VARIATIONS if k not in plan.variations]
    rng.shuffle(spare)
    for kind in plan.variations:
        if not apply_variation(kind, ctx):
            while spare and not apply_variation(spare.pop(), ctx):
                pass

    return assemble(
        persona=persona,
        documents=ctx.docs,
        application_id=f"APP-{plan.index:04d}",
        owner_id=plan.owner_id,
        split=plan.split,
        seed=seed,
        policy=policy,
        as_of=as_of,
        defects=ctx.defects,
        hard_negatives=ctx.hard_negatives,
    )


def generate_batch(n: int, seed: int, policy: Policy, as_of: date) -> list[GeneratedFile]:
    return [build_file(plan, seed=seed, policy=policy, as_of=as_of) for plan in make_plans(n, seed)]
