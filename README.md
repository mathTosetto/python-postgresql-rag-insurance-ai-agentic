# Insurance Claims Agent: PostgreSQL + RAG

An agentic AI exercise for **home-insurance claims handling**. An agent receives an incoming
claim, looks up the policy, coverages and claims history in PostgreSQL, checks the policy
wording and claims guide through RAG, and returns a decision: `approve`, `partial`, `deny`,
`escalate` or `request_info`.

The data is synthetic and modelled on the Irish market (EUR, Irish counties, `en_IE` names).

> **Status:** the database, synthetic data generator and evaluation golden set are in place.
> The RAG documents and the agent itself are not built yet.

## Domain

Three home-insurance products. Each covers a set of perils, and each peril has its own limit
and deductible:

| Peril | HOME-BASIC | HOME-STD | HOME-PLUS |
|---|---|---|---|
| fire | €150,000 / €500 | €300,000 / €350 | €500,000 / €250 |
| theft | €10,000 / €250 | €25,000 / €250 | €50,000 / €150 |
| storm | €50,000 / €500 | €100,000 / €350 | €200,000 / €250 |
| water_damage | not covered | €30,000 / €350 | €60,000 / €250 |
| accidental_damage | not covered | not covered | €15,000 / €150 |

*Values are limit / deductible.*

Key terms:

- **sum_insured**: rebuild value of the home, equal to the fire limit.
- **annual_premium**: what the customer pays per year (sum insured × product rate).
- **limit_amount**: the most the insurer pays for one claim of a peril.
- **deductible**: the part of every claim the customer pays themselves.

Payout rule:

```
amount_paid = max(min(loss_amount, limit_amount) - deductible, 0)
```

## Project layout

```
.
├── docker-compose.yaml          # PostgreSQL + Adminer
├── db/
│   ├── init/
│   │   ├── 01_schema.sql        # tables (run on first DB start)
│   │   └── 02_load.sql          # COPY from the CSVs
│   └── data/                    # generated CSVs (mounted at /data)
├── evals/
│   └── golden_set.jsonl         # planted incoming claims + expected decisions
├── synthetic_data/
│   ├── generate_mocked_data.py  # random data generator + CSV/JSONL export
│   └── scenarios.py             # hand-crafted evaluation scenarios
├── notebooks/
│   └── generate_mocked_data.ipynb  # exploration notebook that preceded the script
└── tests/                       # pytest suite for the generator and scenarios
```

## Database schema

| Table | Key | Description |
|---|---|---|
| `customers` | `customer_id` | Policyholders (`CUST-00042`). |
| `policies` | `policy_id` | One annual policy per customer (`POL-2026-00117`): product, status, dates, premium, sum insured. |
| `coverages` | `(policy_id, peril)` | One row per covered peril with its limit and deductible. |
| `claims_history` | `claim_id` | Past claims: loss date, peril, loss amount, amount paid, outcome (`paid` / `denied` / `partial`). |

Column-level descriptions are in [`db/init/01_schema.sql`](db/init/01_schema.sql).

## Getting started

Requirements: [uv](https://docs.astral.sh/uv/), Python 3.14, and Docker (Docker Desktop or Colima).

```bash
# 1. Install dependencies (includes the test group)
uv sync

# 2. Generate the CSVs and the golden set
uv run python -m synthetic_data.generate_mocked_data

# 3. Start PostgreSQL and Adminer; schema and data load on first start
docker compose up -d
docker compose logs db | grep -iE "COPY|error"
```

| Service | Address | Credentials |
|---|---|---|
| PostgreSQL | `localhost:5432` | user `admin`, password `admin`, database `insurance` |
| Adminer (web UI) | http://localhost:8080 | System **PostgreSQL**, server `db` |

```bash
psql -h localhost -U admin -d insurance
```

### Reloading the data

The scripts in `db/init/` only run when the data volume is empty. After changing the schema
or regenerating the CSVs, recreate the volume:

```bash
uv run python -m synthetic_data.generate_mocked_data
docker compose down -v && docker compose up -d
```

## Synthetic data

`generate_mocked_data.py` creates 1,000 random customers, each with one policy, plus their
coverages and claims. The data is **reproducible**: a fixed seed (`SEED = 26`) and a fixed
reference date (`TODAY = 2026-11-15`) always produce the same files.

What makes the data realistic:

- **Dates are consistent.** The status is drawn first (85% active, 10% lapsed, 5% cancelled)
  and the dates are then chosen to match it. A policy never starts before the customer
  joined, and no claim happens outside the coverage window or after a cancellation.
- **Premiums follow the product.** Each premium is the sum insured × a product-specific rate.
- **Claims follow per-peril frequencies.** Losses are skewed towards small amounts, which
  gives a loss ratio of roughly 0.6–0.8.

## Evaluation scenarios (golden set)

`scenarios.py` adds 12 hand-crafted cases on top of the random data. Each case plants
database rows (with a `SCN` marker, e.g. `POL-SCN-LAPSED`) plus one **incoming claim** with
its expected decision.

| Scenario | Expected decision | What it tests |
|---|---|---|
| SCN-01-CLEAN | approve | Covered peril, under the limit. |
| SCN-02-BURST-PIPE | approve | Sudden water damage is covered. |
| SCN-03-GRADUAL-LEAK | deny | Exclusion that only appears in the policy wording (RAG). |
| SCN-04-NOT-COVERED | deny | Peril not included in the product. |
| SCN-05-OVER-LIMIT | partial | Loss above the limit. |
| SCN-06-BELOW-DEDUCTIBLE | deny | Loss smaller than the deductible. |
| SCN-07-LAPSED | deny | Loss after the policy ended. |
| SCN-08-CANCELLED | deny | Loss after the cancellation. |
| SCN-09-EARLY-CLAIM | escalate | Claim within 30 days of the policy start (fraud signal). |
| SCN-10-FREQUENT | escalate | 3+ claims in 12 months (fraud signal). |
| SCN-11-MISSING-INFO | request_info | No loss date or amount. |
| SCN-12-UNKNOWN-POLICY | request_info | Policy number does not exist. |

The incoming claims and the expected answers live **only** in `evals/golden_set.jsonl` and are
never loaded into the database, so the agent cannot read the answer through SQL.

## Tests

```bash
uv run pytest
```

The tests check date and status consistency, the payout rules, primary and foreign key
integrity, reproducibility, CSV/JSONL export, and that each scenario's expected decision
actually follows from its planted data.

## Roadmap

- [ ] Policy wording and claims handling guide documents (RAG source)
- [ ] pgvector extension and embeddings for the documents
- [ ] Agent tools: `get_policy`, `get_coverage`, `get_claims_history`, document search
- [ ] Claims agent
- [ ] Evaluation runner against `evals/golden_set.jsonl`
