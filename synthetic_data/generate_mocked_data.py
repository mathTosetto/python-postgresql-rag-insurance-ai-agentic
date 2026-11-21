"""Generate mocked home-insurance data (Ireland, EUR) and export it as CSV files.

Outputs (in <project_root>/db/data):
    customers.csv, policies.csv, coverages.csv, claims_history.csv

Run from the project root (as a module, so the package import resolves):
    uv run python -m synthetic_data.generate_mocked_data
"""

import csv
import json
import random
from datetime import date, timedelta
from pathlib import Path
from typing import NamedTuple

from faker import Faker

from synthetic_data.scenarios import build_scenarios

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

SEED = 26
N_CUSTOMERS = 1_000
TODAY = date(2026, 11, 15)  # fixed reference date, keeps the dataset reproducible

# Resolved from this file's location, so it works regardless of the current directory
PROJECT_ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = PROJECT_ROOT / "db" / "data"
GOLDEN_PATH = PROJECT_ROOT / "evals" / "golden_set.jsonl"  # kept out of the DB on purpose

fake = Faker("en_IE")


# ---------------------------------------------------------------------------
# Domain types and reference data
# ---------------------------------------------------------------------------

class Coverage(NamedTuple):
    limit: int       # max payout per claim (€)
    deductible: int  # paid by the customer per claim (€)


class Peril(NamedTuple):
    annual_frequency: float  # probability of a claim per policy per year
    loss_min: int            # min damage per claim (€)
    loss_max: int            # max damage per claim (€)


PRODUCTS: dict[str, dict[str, Coverage]] = {
    "HOME-BASIC": {
        "fire":  Coverage(limit=150_000, deductible=500),
        "theft": Coverage(limit=10_000, deductible=250),
        "storm": Coverage(limit=50_000, deductible=500),
    },
    "HOME-STD": {
        "fire":         Coverage(limit=300_000, deductible=350),
        "theft":        Coverage(limit=25_000, deductible=250),
        "storm":        Coverage(limit=100_000, deductible=350),
        "water_damage": Coverage(limit=30_000, deductible=350),
    },
    "HOME-PLUS": {
        "fire":              Coverage(limit=500_000, deductible=250),
        "theft":             Coverage(limit=50_000, deductible=150),
        "storm":             Coverage(limit=200_000, deductible=250),
        "water_damage":      Coverage(limit=60_000, deductible=250),
        "accidental_damage": Coverage(limit=15_000, deductible=150),
    },
}

# Annual premium rate range (fraction of sum insured)
RATES: dict[str, tuple[float, float]] = {
    "HOME-BASIC": (0.0015, 0.0025),  # ~€225 – €375
    "HOME-STD":   (0.0013, 0.0020),  # ~€390 – €600
    "HOME-PLUS":  (0.0012, 0.0018),  # ~€600 – €900
}

CLAIM_PROFILE: dict[str, Peril] = {
    "water_damage":      Peril(annual_frequency=0.030, loss_min=1_000, loss_max=15_000),
    "theft":             Peril(annual_frequency=0.015, loss_min=500, loss_max=10_000),
    "storm":             Peril(annual_frequency=0.020, loss_min=500, loss_max=20_000),
    "accidental_damage": Peril(annual_frequency=0.020, loss_min=200, loss_max=3_000),
    "fire":              Peril(annual_frequency=0.0015, loss_min=5_000, loss_max=300_000),
}


# ---------------------------------------------------------------------------
# Builders
# ---------------------------------------------------------------------------

def random_customer(i: int) -> dict:
    customer_since = fake.date_between(date(2024, 1, 1), TODAY)
    return {
        "customer_id": f"CUST-{i:05d}",
        "full_name": f"{fake.first_name()} {fake.last_name()}",
        "county": fake.county(),
        "customer_since": customer_since,
    }


def random_policy(i: int, customer: dict) -> dict:
    product = random.choice(list(PRODUCTS))

    since = customer["customer_since"]
    status = random.choices(["active", "lapsed", "cancelled"], [85, 10, 5])[0]

    sum_insured = PRODUCTS[product]["fire"].limit
    annual_premium = round(sum_insured * random.uniform(*RATES[product]), 2)

    # A policy can only be lapsed if the customer has been around for over a year
    if status == "lapsed" and since > TODAY - timedelta(days=366):
        status = "active"

    if status == "active":
        start = fake.date_between(max(since, TODAY - timedelta(days=364)), TODAY)
    elif status == "lapsed":
        start = fake.date_between(since, TODAY - timedelta(days=366))
    else:
        start = fake.date_between(since, TODAY)

    end = start + timedelta(days=365)
    cancelled_at = fake.date_between(start, min(end, TODAY)) if status == "cancelled" else None

    return {
        "policy_id": f"POL-{start.year}-{i:05d}",
        "customer_id": customer["customer_id"],
        "product_code": product,
        "status": status,
        "start_date": start,
        "end_date": end,
        "cancelled_at": cancelled_at,
        "annual_premium": annual_premium,
        "sum_insured": sum_insured,
    }


def build_coverages(policy: dict) -> list[dict]:
    return [
        {
            "policy_id": policy["policy_id"],
            "peril": peril,
            "limit_amount": coverage.limit,
            "deductible": coverage.deductible,
        }
        for peril, coverage in PRODUCTS[policy["product_code"]].items()
    ]


def build_claims(policy: dict, coverages: list[dict]) -> list[dict]:
    claims = []
    # Cover runs from start_date up to, but not including, end_date or cancelled_at
    cover_ends = min(d for d in (policy["end_date"], policy["cancelled_at"]) if d)
    window_end = min(cover_ends - timedelta(days=1), TODAY)
    if window_end < policy["start_date"]:  # cancelled on its start date: never in force
        return claims

    for coverage in coverages:
        freq, lo, hi = CLAIM_PROFILE[coverage["peril"]]
        if random.random() >= freq:
            continue

        loss = round(random.triangular(lo, hi, lo), 2)
        payable = max(min(loss, coverage["limit_amount"]) - coverage["deductible"], 0)

        if payable == 0 or random.random() < 0.08:
            outcome, paid = "denied", 0
        elif loss > coverage["limit_amount"]:
            outcome, paid = "partial", payable
        else:
            outcome, paid = "paid", payable

        claims.append({
            "claim_id": f"CLM-{policy['policy_id'][4:]}-{coverage['peril'][:3].upper()}",
            "policy_id": policy["policy_id"],
            "loss_date": fake.date_between(policy["start_date"], window_end),
            "peril": coverage["peril"],
            "loss_amount": loss,
            "amount_paid": round(paid, 2),
            "outcome": outcome,
        })
    return claims


# ---------------------------------------------------------------------------
# Export
# ---------------------------------------------------------------------------

def write_csv(name: str, rows: list[dict]) -> None:
    path = DATA_DIR / f"{name}.csv"
    with path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=rows[0].keys())
        writer.writeheader()
        writer.writerows(rows)
    print(f"{path.relative_to(PROJECT_ROOT)}: {len(rows)} rows")


def write_jsonl(path: Path, records: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as f:
        for record in records:
            f.write(json.dumps(record, default=str, ensure_ascii=False) + "\n")
    print(f"{path.relative_to(PROJECT_ROOT)}: {len(records)} scenarios")


def generate_dataset(
    n_customers: int = N_CUSTOMERS, seed: int = SEED
) -> tuple[dict[str, list[dict]], list[dict]]:
    """Build all tables in memory. Returns (rows per table, golden set records)."""
    random.seed(seed)
    Faker.seed(seed)

    customers = [random_customer(i) for i in range(1, n_customers + 1)]
    policies = [random_policy(i, c) for i, c in enumerate(customers, 1)]

    coverages, claims = [], []
    for policy in policies:
        policy_coverages = build_coverages(policy)
        coverages.extend(policy_coverages)
        claims.extend(build_claims(policy, policy_coverages))

    # Planted scenarios go after the random rows, so they never shift the random sequence
    scenario_rows, golden = build_scenarios(TODAY, PRODUCTS)
    customers += scenario_rows["customers"]
    policies += scenario_rows["policies"]
    coverages += scenario_rows["coverages"]
    claims += scenario_rows["claims_history"]

    tables = {
        "customers": customers,
        "policies": policies,
        "coverages": coverages,
        "claims_history": claims,
    }
    return tables, golden


def main() -> None:
    tables, golden = generate_dataset()

    DATA_DIR.mkdir(parents=True, exist_ok=True)
    for name, rows in tables.items():  # insertion order respects the FKs
        write_csv(name, rows)
    write_jsonl(GOLDEN_PATH, golden)


if __name__ == "__main__":
    main()
