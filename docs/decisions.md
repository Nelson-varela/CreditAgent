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

## D-004 — Language: everything in English (locale superseded by D-014)

- **Status:** the English-only part stands; the Colombian locale was replaced by a US locale in D-014.

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
  original client was a US startup.
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

---

## D-009 — Schemas are strict; invariants live in the models, not in prompts

- **Date:** 2026-10-14
- **Decision:** Every Pydantic model uses `extra="forbid"`. Business invariants are enforced at
  construction time: a `Finding` must carry evidence or a `policy_rule_id`; a `CONFIRMED` proposal must
  record `confirmed_by` (and only those); datetimes must be timezone-aware; `AuditEvent` is frozen.
- **Alternatives:** lenient models that drop unknown fields; checking invariants in the pipeline.
- **Why:** The same models validate structured LLM output. A model that invents a field must fail
  loudly, not be silently accepted. Putting invariants in the type makes principle 5 ("every claim
  carries verifiable evidence") impossible to bypass by accident.
- **Trade-off:** Stricter parsing means more rejected LLM outputs (counted in the error rate) instead of
  silently degraded ones. `AuditEvent.trace_id` is optional (batch jobs may have none).

## D-010 — Application lifecycle is a transition table, with "agent never decides" in code

- **Date:** 2026-10-14
- **Decision:** `ALLOWED_TRANSITIONS` encodes the lifecycle; `can_transition(..., by_human=)` refuses
  any move into `approved` / `rejected` / `documents_requested` unless a human triggered it.
- **Alternatives:** a state-machine library; checking statuses ad hoc in each endpoint.
- **Why:** One tiny, exhaustively testable table is easy to defend and cannot drift between the API,
  the MCP tools and the pipeline. Tests assert that no non-human path reaches a decision state.
- **Trade-off:** No transition side effects or history here; the audit log records them.

## D-011 — Prices are empty by default and a missing price raises

- **Date:** 2026-10-14
- **Decision:** `model_prices`, `textract_price_per_page_usd` and `pricing_checked_on` start empty.
  `Settings.model_price()` raises `KeyError` for an unknown model.
- **Alternatives:** hard-coded prices from memory; defaulting unknown models to zero cost.
- **Why:** Prices must come from the official pages with a consultation date; a silent zero would make
  the reported cost-per-file look better than reality.
- **Trade-off:** Cost tracking cannot run until day 2 fills the table.

---

## D-012 — Policy YAML: one home per number, templated rule texts, severity per rule

- **Date:** 2026-10-14
- **Decision:** All thresholds live once under `parameters` in `data/policies/policy_v1.yaml`. Rule
  texts are templates (`{income_tolerance:.0%}`) rendered from those parameters. The loader
  (`policy.py`) validates: placeholders must be known parameters, rule ids must match their section,
  ids are unique, every `DefectType` has at least one rule, and a rule has a defect type, severity and
  action together or none of them (informational rules).
- **Alternatives:** literal numbers inside each rule text; thresholds in `config.py`; severity defined
  per defect type.
- **Why:** The manual (RAG corpus), the deterministic rules and the ground truth read the same
  numbers, so they cannot disagree; changing a threshold changes all three. Severity is per rule
  because `POLICY_VIOLATION` groups rules of different gravity (DTI limit = high, tenure = medium).
- **Trade-off:** Rule texts are templates, so reading the raw YAML is slightly less direct than reading
  the rendered manual. Severity per rule means a defect type can map to several severities; findings
  always carry the `policy_rule_id` that disambiguates.

## D-013 — Business definitions fixed in the policy (to keep rules and labels unambiguous)

- **Date:** 2026-10-14
- **Decision:** Income tolerance is relative to the **documented** amount and a difference exactly
  at the tolerance is accepted. Verified income = average net salary on payslips (declared income is
  never the DTI denominator). Existing debt = average of the installments shown on the bank
  statements. Ages are measured against `AS_OF_DATE`; a payslip's age counts from its period end.
- **Alternatives:** tolerance relative to the declared amount; strict inequality at the boundary.
- **Why:** The near-threshold hard cases (just under / just over tolerance) only make sense with an
  explicit boundary convention; the generator and the rule engine must agree on it.
- **Trade-off:** These are my modelling choices for a synthetic policy, not an industry standard.
  Initial parameter values (10% tolerance, 40% DTI, $25,000 review threshold, ...) are fictional.

---

## D-014 — US locale: names, addresses, USD and US document formats

- **Date:** 2026-10-14
- **Decision:** Synthetic applicants, addresses (street, city, state, ZIP), phone formats and currency
  (USD) follow US conventions. The policy is a US consumer-lending policy: loan limits $1,000-$50,000,
  mandatory review above $25,000, 1.00% monthly interest (about 12.7% effective annual).
  Supersedes the Colombian locale of D-004. Code identifiers keep the names from the project spec
  (`payslip`, `STALE_PAYSLIP`); policy prose says "payslips (pay stubs)".
- **Alternatives:** Colombian data and COP (original plan).
- **Why:** The original client operated in the US market, so US data mirrors the real deployment. The audience is also US-based. US documents are also the format Textract handles best,
  and Bedrock Guardrails' built-in PII entity types are US-oriented (to be confirmed when the guardrail
  is configured).
- **Trade-off:** Nothing is lost with respect to the original deployment (US client). The generator includes names with
  diacritics (e.g. José, Zoë) so the "accents are not a defect" hard negative remains meaningful.
- **Identity number:** the identity document is a state driver license / state ID, with a fictional ID
  number format. Social Security Numbers are deliberately NOT generated: even synthetic SSNs can collide
  with real people's, which is unacceptable in a public repo.

---

## D-015 — One independent RNG per file: `Random(f"{seed}:{index}")`

- **Date:** 2026-10-14
- **Decision:** Every file derives its own RNG (and re-seeds Faker) from `(seed, index)`.
- **Alternatives:** a single RNG stream consumed in order.
- **Why:** A file's persona (names, amounts, dates) depends only on `(seed, index)`, so it does not
  change when other files are added or removed, and adding a new injector does not reshuffle the
  random stream of unrelated files. Note the limit: WHICH defects a file receives comes from the
  batch plan, which depends on `(seed, n)` by design because the target mix (30/50/20, owner 60/40,
  dev/test) is defined over the whole batch. Published metrics therefore pin `--n 40 --seed 42`.
- **Trade-off:** Output depends on pinned Faker and Python `random` behaviour; a Faker upgrade changes the
  data, which is why versions are pinned (D-008) and the ground truth JSON is versioned.

## D-016 — Two views of every field: printed value and canonical truth

- **Date:** 2026-10-14
- **Decision:** `DocumentContent.fields` holds what is printed (e.g. `"$7,628.59"`, `"06/29/2026"`);
  `canonical` holds the normalized truth (`"7628.59"`, ISO date) and only for fields scored in the
  extraction eval. Money and dates come from typed values; names and addresses go through the shared
  `normalize.py`.
- **Alternatives:** compute truth by normalizing the printed text with the extraction normalizer.
- **Why:** If truth were derived with the same normalizer under test, a normalizer bug would cancel
  out and never show up in the metrics. Typed values keep that check honest where possible.
- **Trade-off:** For names and addresses the generator and the extractor share one function, so a
  bug there is not caught by the eval; explicit unit cases in `test_normalize.py` mitigate it.

## D-017 — "Clean" is clean by construction and verified by an independent check

- **Date:** 2026-10-14
- **Decision:** The persona is sized below the policy limits (DTI cap 0.30 vs policy 0.40, payslips at
  least 3 days inside the age limit, tenure at least 3 months above the minimum). A test re-states the
  policy from canonical values and asserts 300 files across several reference dates are clean, plus
  mutation tests proving that the check fails on broken files.
- **Alternatives:** trust the generator; wait for the day-3 rule engine to validate it.
- **Why:** The false-positive-rate metric is meaningless if "clean" files hide real defects. A
  generator bug would otherwise surface as a fake system error.
- **Trade-off:** The independent check duplicates policy logic in tests; on day 3 the real rule
  engine must also report zero findings on clean files, which cross-checks both.

---

## D-018 — Ground truth is verified by an independent oracle, not trusted

- **Date:** 2026-10-14
- **Decision:** `tests/test_generator_batch.py` re-evaluates every policy rule from the canonical
  values of each generated file and requires the set of violated rules to EQUAL the union of the
  `rule_ids` in the labels (hard negatives included, since a legitimate variation that the oracle
  flags would show up as an extra rule). Run on several seeds and reference dates, plus a stress run
  of 100 seeds x 2 dates (8,000 files).
- **Alternatives:** trust the generator's intent; validate only once the real rule engine exists.
- **Why:** The oracle found two real label bugs before any model ran: (1) when the employment letter
  is the altered document, the tolerance must be measured against the NEW letter value (the documented
  amount), not the original salary (an 11.1% change was only 10.0% of the new value, i.e. accepted);
  (2) month-end clamping made a "tenure just under the minimum" case equal to the reference date, not
  after it. Without the oracle these would have been charged to the system as errors.
- **Trade-off:** The oracle duplicates policy logic in test code. On day 3 the real rule engine must also
  agree with the labels, which cross-checks both implementations.

## D-019 — Coverage of hard cases is assigned by the plan, not left to chance

- **Date:** 2026-10-14
- **Decision:** Injection placement/language rotates over injection files
  (field/footer x English/foreign language), and each hard-negative kind is assigned round-robin.
  If a variation does not fit a file (for example the bill is missing), another kind is tried.
- **Alternatives:** sample placements randomly.
- **Why:** With 5 injection files, random placement left every case in the footer for seed 42 (a test
  caught it). A suite whose difficulty depends on luck is not defensible.
- **Trade-off:** Less random-looking data; exact coverage guarantees only hold for batches of at least
  4 injection files (n >= 32 with the default quota).

## D-020 — Defect ordering and dependency tracking

- **Date:** 2026-10-14
- **Decision:** Defects are applied in a fixed order; each records the fields it modified (`touched`) and
  the documents its detection depends on (`required`). `MISSING_DOC` runs last and only removes a
  document that is neither touched nor required; variations run after it and skip anything touched.
- **Alternatives:** independent random mutations; retrying until labels are consistent.
- **Why:** Mutations interact (removing the ID document would make an ID mismatch undetectable). Tracking
  dependencies makes every label true by construction instead of fixing contradictions afterwards.
- **Trade-off:** Files are somewhat less "wild": a document with one defect is not also randomly broken
  by an unrelated one.

## D-021 — Known limitation: per-type sample sizes are tiny

- **Date:** 2026-10-14
- **Decision:** Report it plainly. With `--n 40`, some defect types appear only twice in total
  (e.g. `NAME_MISMATCH`, `POLICY_VIOLATION`), so their dev/test counts are about 0-2.
- **Why it matters:** per-type recall will have very wide bootstrap intervals; the aggregate metric
  is the headline, as the project spec already states.
- **Option if time allows:** a larger batch (`--n 80`) for the final eval, with the cost implications
  of extraction checked first.
