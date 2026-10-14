# Decision log

Each entry: decision, alternatives considered, why, and the trade-off accepted.
This is the study material for defending the architecture in interviews.

---

## D-001 — AWS region: `us-east-2` (Ohio)

- **Date:** 2026-10-14
- **Decision:** Run everything in `us-east-2`.
- **Alternatives:** `us-east-1` (widest model/feature coverage), `us-west-2`.
- **Why:** Chosen by the owner. AgentCore Runtime appears to be available in Ohio
  (indirect evidence in AWS announcements; the official regions page does not state it directly).
- **Trade-off / open risk:** The official regions page lists Ohio as **without** AgentCore Evaluations
  and AgentCore Policy (we build our own evals, so this does not matter). Textract `AnalyzeDocument`
  with QUERIES and Bedrock Guardrails (`ApplyGuardrail`) availability in `us-east-2` is **not yet verified**.
  Verified on day 2, before any resource is created. If a service is missing, this decision is revisited.

## D-002 — Models: Claude (primary) + Amazon Nova (fallback)

- **Date:** 2026-10-14
- **Decision:** Primary = a Claude model, fallback = an Amazon Nova model, so the fallback survives an
  outage or throttling of one model *family*. Exact model/inference-profile IDs are pinned on day 2
  after listing what the account can actually invoke in `us-east-2`.
- **Alternatives:** two Claude models (cheaper to reason about, but one family-wide incident takes out both).
- **Trade-off:** Two model families means two prompt-compatibility surfaces to evaluate.
  Embeddings / rerank model: to be decided on day 5 from the enabled list.

## D-003 — Observability: Langfuse cloud (free tier)

- **Date:** 2026-10-14
- **Decision:** Langfuse cloud free tier.
- **Alternatives:** self-hosted with Docker.
- **Why:** Zero infrastructure and minutes to set up; time is the scarcest resource (10-day plan).
- **Trade-off:** Trace data leaves the machine. Mitigation: ID numbers are masked in traces even though
  all data is synthetic. Free-tier limits apply.

## D-004 — Language: everything in English, Colombian data

- **Date:** 2026-10-14
- **Decision:** Documents, policy manual, code, comments, README, docs and eval report are all in
  English. Names, addresses and currency (COP) are Colombian.
- **Alternatives:** Spanish documents.
- **Why:** Interviews are in English; it avoids verifying Bedrock Guardrails' Spanish support and keeps
  evals and the demo simpler.
- **Trade-off:** Less realistic for a Colombian lender; accent handling is still exercised through
  Colombian names (tildes are part of the hard negatives).

## D-005 — Public repo from day 1, `CLAUDE.md` not versioned

- **Date:** 2026-10-14
- **Decision:** Public repository from the first commit; `CLAUDE.md` and `.claude/` are in `.gitignore`.
- **Alternatives:** private until the end; public with `CLAUDE.md` committed.
- **Why:** A visible commit history shows the work as it happened. `CLAUDE.md` holds personal process
  notes and interview preparation that do not belong in a portfolio repo.
- **Trade-off:** Everything committed is public immediately. No secrets, no real data, ever;
  `.env` is ignored and a pre-push check of the diff is required.

## D-006 — Repository name: `credit-file-agent`

- **Date:** 2026-10-14
- **Decision:** `credit-file-agent` for the GitHub repo and Python package.
- **Alternatives:** keep the local folder name (`scotiabank-ops`).
- **Why:** A public repo named after a real bank suggests an affiliation that does not exist; the
  original client was a startup.
- **Trade-off:** The local folder still has the old name because it is open in the editor; renaming it
  is cosmetic and does not affect the repo.

## D-007 — AWS access: dedicated profile `credit-agent`, reusing the existing IAM user's keys

- **Date:** 2026-10-14
- **Decision:** Named profile `credit-agent` (region `us-east-2`) that currently reuses the access keys
  of the existing IAM user. Not the `default` profile, so project commands are explicit.
- **Alternatives:** a new least-privilege IAM user dedicated to the project (recommended practice).
- **Why:** Owner's choice, to move faster on days 1–2.
- **Trade-off (open):** The user's permissions are broader than the project needs, which violates
  least privilege. `scripts/iam_policy.json` (no `*`) is generated on day 2; moving the profile to a
  dedicated user with only that policy is a **pre-publication TODO**.

## D-008 — Dependencies: pinned exactly, added incrementally

- **Date:** 2026-10-14
- **Decision:** `uv` with exact `==` pins in `pyproject.toml` and a committed `uv.lock`; CI installs with
  `--frozen`. Only the dependencies needed for the current day are added.
- **Alternatives:** install the whole stack upfront; version ranges.
- **Why:** Reproducible metrics require reproducible environments, and heavy libraries
  (e.g. `sentence-transformers`) should not be pinned before we know we use them.
- **Trade-off:** Each new day may need a lockfile update.
