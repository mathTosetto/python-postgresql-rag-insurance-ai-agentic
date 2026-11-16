# TODO

Goal: a **synthetic home-insurance claims agent** built with **LangGraph**. It
- retrieves policy wording and the claims handling guide via **RAG**,
- queries the policy tables in PostgreSQL through tools exposed by an **MCP server**,
- asks for **human approval** before recommending any payment,

and is evaluated against `evals/golden_set.jsonl`.

Legend: `[x]` done · `[ ]` to do · *(decision)* = choice still open

---

## Done: data layer (SQL)

### Infrastructure
- [x] Docker Compose with PostgreSQL 18 (pinned) and Adminer
- [x] Volume mount fixed for the Postgres 18+ layout (`/var/lib/postgresql`)
- [x] `db/init/01_schema.sql`: `customers`, `policies`, `coverages`, `claims_history`, with column comments
- [x] `db/init/02_load.sql`: `COPY` from CSVs in FK order (loads 1,011 / 1,011 / 4,071 / 65 rows)

### Synthetic data
- [x] Reproducible generator (`SEED`, fixed `TODAY`) in `synthetic_data/generate_mocked_data.py`
- [x] 3 products (HOME-BASIC / STD / PLUS) with per-peril limits and deductibles
- [x] Status-first date generation (active / lapsed / cancelled), consistent with `customer_since`
- [x] Premium = sum insured × product rate
- [x] Claims with per-peril frequency and skewed severity (loss ratio ≈ 0.6–0.8)
- [x] Payout rule `max(min(loss, limit) − deductible, 0)` and `paid` / `partial` / `denied` outcomes

### Evaluation data
- [x] 12 planted scenarios in `synthetic_data/scenarios.py`, covering all 5 decisions
- [x] Golden set exported to `evals/golden_set.jsonl` and kept out of the database
- [x] Each scenario lists its `required_tools` and `required_docs`

### Quality and docs
- [x] pytest suite (46 tests): data invariants, PK/FK integrity, reproducibility, scenario consistency
- [x] `README.md`, `AGENTS.md`, `CLAUDE.md`

---

## 1. Database hardening
- [x] Switch the image to `pgvector/pgvector:pg18` (needed for RAG in step 3)
- [x] Read-only role for the agent (`GRANT SELECT` only); the agent must never write to the DB
  - [x] `db/init/03_users-setup.sql`, tables moved to the `insurance` schema
  - [x] `tests/test_db_permissions.py`: agent can read, cannot write or create tables
- [x] Move credentials to `.env` (+ `.env.example`), and add `.env` to `.gitignore`
- [ ] Make the Compose variables required, so a missing `.env` fails early
- [ ] Optional: `CHECK` constraints (`status`, `outcome`, `end_date > start_date`, `amount_paid <= loss_amount`)
- [ ] Optional: composite FK `claims_history (policy_id, peril) → coverages`

## 2. RAG source documents
Without these, scenarios SCN-02, SCN-03, SCN-09 and SCN-10 can't be decided correctly.
- [ ] Policy wording for each product (`docs/policy_wording/HOME-*.md`): what's covered, limits, deductibles, conditions
- [ ] Exclusions section, including **gradual damage / slow leaks** (SCN-03) and a contrasting **sudden escape of water** cover (SCN-02)
- [ ] Claims handling guide (`docs/claims_guide.md`):
  - [ ] Decision taxonomy: `approve`, `partial`, `deny`, `escalate`, `request_info`
  - [ ] Payout rule (limit and deductible)
  - [ ] Fraud indicators with **the same thresholds as `scenarios.py`**: claim within 30 days of inception, 3+ claims in 12 months
  - [ ] When to request information (missing loss date or amount, unknown policy)
- [ ] Test that the guide's thresholds match `EARLY_CLAIM_DAYS`, `FREQUENT_CLAIMS_COUNT` and `FREQUENT_CLAIMS_MONTHS`
- [ ] Keep the document values in sync with `PRODUCTS` (add a test or generate the tables from code)

## 3. RAG pipeline
- [ ] *(decision)* Embedding model and chunk size
- [ ] Ingestion script: load docs → chunk by section → embed → store
- [ ] `document_chunks` table in pgvector with metadata (`doc_type`, `product_code`, `section`)
  - [ ] Grant the agent role `SELECT` on it (and add it to `TABLES` in `test_db_permissions.py`)
- [ ] Retriever with a metadata filter by product, so HOME-BASIC wording never answers a HOME-PLUS claim
- [ ] Retrieval eval: for each scenario, check that its `required_docs` show up in the top-k

## 4. MCP server (SQL tools)
- [ ] *(decision)* Transport: stdio (local) or streamable HTTP
- [ ] Tools named to match the golden set:
  - [ ] `get_policy(policy_id)`: status, dates, product, `cancelled_at`
  - [ ] `get_coverage(policy_id)`: perils with limit and deductible
  - [ ] `get_claims_history(policy_id)`: past claims
- [ ] Optional: `search_documents(query, product_code)` exposed as an MCP tool too
- [ ] Parameterized queries only, using the read-only role
- [ ] Explicit "not found" result for an unknown policy (SCN-12), so the agent doesn't invent data
- [ ] Tests for each tool against the planted `SCN` rows

## 5. LangGraph agent
- [ ] *(decision)* LLM provider and model
- [ ] State schema: incoming claim, policy, coverages, history, retrieved docs, decision, payout, reason, rationale
- [ ] Nodes:
  - [ ] **Intake**: validate the input; missing date or amount → `request_info` (SCN-11)
  - [ ] **Policy lookup** (MCP): not found → `request_info` (SCN-12)
  - [ ] **In-force check**: lapsed or cancelled at the loss date → `deny` (SCN-07, SCN-08)
  - [ ] **Coverage check**: peril not in the product → `deny` (SCN-04)
  - [ ] **Wording retrieval** (RAG): exclusions → `deny` (SCN-03)
  - [ ] **Fraud checks**: early claim or claim frequency → `escalate` (SCN-09, SCN-10)
  - [ ] **Payout calculation** in deterministic Python, not by the LLM (SCN-01, 02, 05, 06)
  - [ ] **Recommendation**: structured output (decision, payout, reason, cited sources)
- [ ] **Human-in-the-loop**: `interrupt()` before any `approve` / `partial` recommendation
  - [ ] Reviewer can approve, reject or edit; the graph resumes from the checkpoint
  - [ ] Checkpointer *(decision)*: Postgres saver (same DB) or SQLite for local work
- [ ] Audit trail: store tools called, docs cited, reviewer decision and timestamp

## 6. Evaluation runner
- [ ] Run every golden-set scenario through the graph (auto-approve or simulate the human step)
- [ ] Metrics:
  - [ ] Decision accuracy
  - [ ] Exact payout match
  - [ ] Reason match
  - [ ] Tool recall (`required_tools` ⊆ tools called)
  - [ ] Document recall (`required_docs` cited)
  - [ ] HITL triggered whenever the decision is `approve` or `partial`
- [ ] Report per scenario plus a summary; fail on regressions

## 7. Engineering
- [ ] GitHub Actions: `uv sync` + `pytest` on every push
- [ ] Linting with `ruff`
- [ ] Tracing / observability for agent runs *(decision: LangSmith, Langfuse, ...)*
- [ ] Update `README.md` and `AGENTS.md` as each part lands

## 8. Optional
- [ ] Simple UI for the human reviewer (CLI or Streamlit)
- [ ] More scenarios: several claims for the same event, partially covered loss, reported much later than the loss date
