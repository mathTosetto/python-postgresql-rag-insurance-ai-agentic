# AGENTS.md

Guidance for AI coding agents working in this repository. See `README.md` for the project
overview and the insurance domain.

## Commands

```bash
cp .env.example .env                                  # once: local credentials read by docker compose and the tests
uv sync                                               # install deps (test group included)
uv run pytest                                         # run the test suite (DB tests skip if the DB is down)
uv run python -m synthetic_data.generate_mocked_data  # regenerate db/data/*.csv and evals/golden_set.jsonl
docker compose down -v && docker compose up -d        # recreate the DB so db/init/ runs again
```

- Use `uv` for everything. Don't call `pip` or a bare `python`.
- Add dependencies with `uv add <pkg>`, and test-only ones with `uv add --group test <pkg>`.
- Run the generator as a **module** (`-m`) from the project root. `synthetic_data` is a
  package, so `python synthetic_data/generate_mocked_data.py` fails on the import.

## Layout

| Path | Role |
|---|---|
| `synthetic_data/generate_mocked_data.py` | Random data. `generate_dataset()` builds everything in memory; `main()` writes the files. |
| `synthetic_data/scenarios.py` | Deterministic evaluation scenarios plus the golden set. |
| `db/init/01_schema.sql` | Creates the `insurance` schema and its tables, with column comments. |
| `db/init/02_load.sql` | `COPY` statements, run in FK order. |
| `db/init/03_users-setup.sql` | Creates the read-only agent role from `POSTGRES_AGENT_*` (read with psql `\getenv`). |
| `.env.example` | Template for `.env`, which holds the DB credentials and is git-ignored. |
| `db/data/` | Generated CSVs. Never edit by hand; regenerate. |
| `evals/golden_set.jsonl` | Generated. Holds the expected agent decisions. |
| `notebooks/` | Exploration only. The script is the source of truth. |
| `tests/` | pytest. `conftest.py` provides session-scoped `dataset`, `tables` and `scenarios` fixtures. Tests marked `db` (`test_db_permissions.py`) connect to the running database and skip when it is unreachable. |

## Invariants: do not break these

### Reproducibility
- The dataset is fully determined by `SEED` and `TODAY`. Never use `date.today()`,
  `datetime.now()` or unseeded randomness.
- Seed only inside `generate_dataset()`, never at import time.
- The order of random calls defines the output. Reordering builders or adding a random call
  changes every row after it. If you do this on purpose, regenerate the data and say so.
- `scenarios.py` must stay free of randomness, and its rows are appended **after** the random
  rows. `test_planted_scenarios_do_not_shift_random_rows` guards this.

### Data consistency
- `customer_since <= start_date <= TODAY` and `end_date = start_date + 365 days`.
- `active`: in force at `TODAY`. `lapsed`: `end_date < TODAY`. `cancelled`: has `cancelled_at`
  within the policy term. All other statuses have `cancelled_at = None`.
- A policy is **in force** on a date `d` when `start_date <= d < min(end_date, cancelled_at)`:
  cover ends the day *before* the end or cancellation date. The claims handling guide
  (`docs/claims_guide.md`) and `_in_force` in `tests/test_scenarios.py` use the same rule.
- Claims only use perils the policy covers, and `loss_date` is a day the policy was in force,
  up to `TODAY`: `start_date <= loss_date < min(end_date, cancelled_at)` and `loss_date <= TODAY`.
  A policy cancelled on its start date has no claims.
- `amount_paid = max(min(loss_amount, limit_amount) - deductible, 0)`. A `denied` claim pays 0.
  `partial` means the loss exceeded the limit.
- `sum_insured` equals the product's fire limit.
- The database enforces part of this in `db/init/01_schema.sql`: `valid_status`, `valid_outcome`,
  `valid_end_date` (`end_date > start_date`), `valid_amount_paid` (`amount_paid <= loss_amount`)
  and `fk_policy_id_peril` (a claim's peril must be in its policy's `coverages`). The claim
  columns these compare are `NOT NULL`, because a `CHECK` or composite FK lets NULLs through.
  The other rules are only checked by pytest, so the generator must keep them.

### Schema and CSV must stay in sync
A column change touches **four places**:
1. The dict returned by the builder in `generate_mocked_data.py`.
2. The matching builder in `scenarios.py` (same keys, **same order**).
3. `db/init/01_schema.sql`.
4. The column list in `db/init/02_load.sql`.

`COPY ... HEADER true` skips the header but maps columns **by position**, so a key order
mismatch loads data into the wrong columns silently.
`test_planted_rows_have_the_same_columns_as_random_rows` checks items 1 and 2 only.

All tables live in the `insurance` schema, not `public`. Always schema-qualify table names in
SQL (`insurance.policies`): `COPY` and other statements don't search `insurance` by default.

### Database access
- The agent connects as the `POSTGRES_AGENT_USER` role, which has `USAGE` on the `insurance`
  schema and `SELECT` on its tables only. Never grant it write privileges.
- A new table is **not** readable by the agent until you add it to the `GRANT SELECT` in
  `db/init/03_users-setup.sql`. Add it to `TABLES` in `tests/test_db_permissions.py` too.
- Anything that writes (data loading, RAG ingestion, a checkpointer) uses a different role.

### Evaluation integrity
- The incoming claims and the expected decisions go to `evals/golden_set.jsonl` **only**.
  Never load them into the database or expose them to the agent's tools.
- Planted IDs use the `SCN` marker (`CUST-SCN-01`, `POL-SCN-<TAG>`, `CLM-NEW-SCN-01`).
  Random IDs never contain it.
- The thresholds in `scenarios.py` (`EARLY_CLAIM_DAYS`, `FREQUENT_CLAIMS_COUNT`,
  `FREQUENT_CLAIMS_MONTHS`) must match the claims handling guide used for RAG, or the
  expected decisions become impossible to derive.
- Every new scenario needs a test showing its expected decision follows from its planted
  data, as in `tests/test_scenarios.py`.

## Conventions

- Code, comments, docstrings and SQL comments are in English.
- Money is in EUR, stored as `NUMERIC` in SQL and rounded to 2 decimals in Python.
- Reference data uses `NamedTuple`s (`Coverage`, `Peril`). Generated rows are plain dicts.
- Keep functions small and pure where possible. File I/O belongs in `write_csv`,
  `write_jsonl` and `main()`.

## Before finishing a change

1. Run `uv run pytest`. All tests must pass. If the `db` tests were skipped, say so, and run
   them with the database up when the change touches `db/init/`.
2. If generated data changed, run the generator and mention it in your summary.
3. If the schema changed, remind the user to run `docker compose down -v` (it deletes the
   database volume).
4. Don't edit `db/data/` or `evals/` by hand, and don't change `SEED`/`TODAY` unless asked.

## Local credentials

Credentials live in `.env` (git-ignored), and `docker-compose.yaml` reads them with `${VAR}`.
The values in `.env.example` (`admin` / `admin`, `rag_agent` / `rag_agent`) are throwaway
development credentials. Never reuse them anywhere else, and never commit `.env` or real secrets.
When you add a variable to `.env`, add it to `.env.example` too.
