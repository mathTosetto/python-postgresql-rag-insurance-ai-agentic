import csv
import json
import random
from datetime import date, timedelta

import pytest

from synthetic_data import generate_mocked_data as gen
from synthetic_data.generate_mocked_data import (
    CLAIM_PROFILE,
    PRODUCTS,
    RATES,
    TODAY,
    build_claims,
    build_coverages,
    generate_dataset,
    random_customer,
    random_policy,
)


def _window_end(policy: dict) -> date:
    """Last day a loss can happen: cover ends the day before end_date or cancelled_at."""
    cover_ends = min(d for d in (policy["end_date"], policy["cancelled_at"]) if d)
    return min(cover_ends - timedelta(days=1), TODAY)


# ---------------------------------------------------------------------------
# Reference data
# ---------------------------------------------------------------------------

def test_every_product_has_a_rate_and_fire_cover():
    assert set(RATES) == set(PRODUCTS)
    for coverages in PRODUCTS.values():
        assert "fire" in coverages


def test_every_peril_has_a_claim_profile():
    perils = {peril for coverages in PRODUCTS.values() for peril in coverages}
    assert perils <= set(CLAIM_PROFILE)


# ---------------------------------------------------------------------------
# Customers
# ---------------------------------------------------------------------------

def test_random_customer_format():
    customer = random_customer(42)
    assert customer["customer_id"] == "CUST-00042"
    assert customer["full_name"].strip()
    assert date(2024, 1, 1) <= customer["customer_since"] <= TODAY


# ---------------------------------------------------------------------------
# Policies
# ---------------------------------------------------------------------------

def test_policy_dates_are_consistent_with_status(tables):
    customers = {c["customer_id"]: c for c in tables["customers"]}
    for p in tables["policies"]:
        if p["policy_id"].startswith("POL-SCN-"):
            continue
        since = customers[p["customer_id"]]["customer_since"]
        assert since <= p["start_date"] <= TODAY
        assert p["end_date"] == p["start_date"] + timedelta(days=365)

        if p["status"] == "active":
            assert p["start_date"] <= TODAY < p["end_date"]
            assert p["cancelled_at"] is None
        elif p["status"] == "lapsed":
            assert p["end_date"] < TODAY
            assert p["cancelled_at"] is None
        else:
            assert p["status"] == "cancelled"
            assert p["start_date"] <= p["cancelled_at"] <= min(p["end_date"], TODAY)


def test_policy_ids_encode_start_year(tables):
    for p in tables["policies"]:
        if not p["policy_id"].startswith("POL-SCN-"):
            assert p["policy_id"].startswith(f"POL-{p['start_date'].year}-")


def test_premium_and_sum_insured_follow_the_product(tables):
    for p in tables["policies"]:
        if p["policy_id"].startswith("POL-SCN-"):
            continue
        sum_insured = PRODUCTS[p["product_code"]]["fire"].limit
        low, high = RATES[p["product_code"]]
        assert p["sum_insured"] == sum_insured
        assert round(sum_insured * low, 2) <= p["annual_premium"] <= round(sum_insured * high, 2)


def test_all_statuses_and_products_are_generated(tables):
    random_policies = [p for p in tables["policies"] if not p["policy_id"].startswith("POL-SCN-")]
    assert {p["status"] for p in random_policies} == {"active", "lapsed", "cancelled"}
    assert {p["product_code"] for p in random_policies} == set(PRODUCTS)


def test_new_customer_cannot_have_a_lapsed_policy():
    random.seed(0)
    new_customer = {"customer_id": "CUST-00001", "customer_since": TODAY - timedelta(days=30)}
    for i in range(500):
        assert random_policy(i, new_customer)["status"] != "lapsed"


# ---------------------------------------------------------------------------
# Coverages
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("product", list(PRODUCTS))
def test_build_coverages_has_one_row_per_product_peril(product):
    policy = {"policy_id": "POL-2026-00001", "product_code": product}
    rows = build_coverages(policy)

    assert {r["peril"] for r in rows} == set(PRODUCTS[product])
    for r in rows:
        cov = PRODUCTS[product][r["peril"]]
        assert r["policy_id"] == "POL-2026-00001"
        assert (r["limit_amount"], r["deductible"]) == (cov.limit, cov.deductible)


# ---------------------------------------------------------------------------
# Claims
# ---------------------------------------------------------------------------

def test_claims_respect_coverage_window_and_payout_rules(tables):
    policies = {p["policy_id"]: p for p in tables["policies"]}
    coverages = {(c["policy_id"], c["peril"]): c for c in tables["coverages"]}

    for claim in tables["claims_history"]:
        policy = policies[claim["policy_id"]]
        cov = coverages[(claim["policy_id"], claim["peril"])]  # KeyError = uncovered peril

        assert policy["start_date"] <= claim["loss_date"] <= _window_end(policy)

        if claim["outcome"] == "denied":
            assert claim["amount_paid"] == 0
            continue

        expected = round(min(claim["loss_amount"], cov["limit_amount"]) - cov["deductible"], 2)
        assert claim["amount_paid"] == pytest.approx(expected)
        assert claim["amount_paid"] > 0
        if claim["outcome"] == "partial":
            assert claim["loss_amount"] > cov["limit_amount"]
        else:
            assert claim["outcome"] == "paid"
            assert claim["loss_amount"] <= cov["limit_amount"]


def test_claim_amounts_stay_within_peril_profile(tables):
    for claim in tables["claims_history"]:
        if claim["policy_id"].startswith("POL-SCN-"):
            continue
        profile = CLAIM_PROFILE[claim["peril"]]
        assert profile.loss_min <= claim["loss_amount"] <= profile.loss_max


def test_no_claims_after_cancellation():
    random.seed(1)
    policy = {
        "policy_id": "POL-2026-00001",
        "product_code": "HOME-PLUS",
        "start_date": TODAY - timedelta(days=200),
        "end_date": TODAY + timedelta(days=165),
        "cancelled_at": TODAY - timedelta(days=150),
    }
    coverages = build_coverages(policy) * 200  # many draws to force claims
    claims = build_claims(policy, coverages)

    assert claims, "expected at least one claim with this many draws"
    assert all(c["loss_date"] < policy["cancelled_at"] for c in claims)


def test_no_claims_when_cancelled_on_start_date():
    random.seed(1)
    start = TODAY - timedelta(days=200)
    policy = {
        "policy_id": "POL-2026-00001",
        "product_code": "HOME-PLUS",
        "start_date": start,
        "end_date": start + timedelta(days=365),
        "cancelled_at": start,
    }
    assert build_claims(policy, build_coverages(policy) * 200) == []


def test_loss_ratio_is_plausible(tables):
    random_policies = [p for p in tables["policies"] if not p["policy_id"].startswith("POL-SCN-")]
    random_claims = [c for c in tables["claims_history"] if not c["policy_id"].startswith("POL-SCN-")]

    premiums = sum(p["annual_premium"] for p in random_policies)
    paid = sum(c["amount_paid"] for c in random_claims)

    assert 0.2 < paid / premiums < 1.5


# ---------------------------------------------------------------------------
# Whole dataset
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("table, key", [
    ("customers", ("customer_id",)),
    ("policies", ("policy_id",)),
    ("coverages", ("policy_id", "peril")),
    ("claims_history", ("claim_id",)),
])
def test_primary_keys_are_unique(tables, table, key):
    keys = [tuple(row[k] for k in key) for row in tables[table]]
    assert len(keys) == len(set(keys))


def test_foreign_keys_resolve(tables):
    customer_ids = {c["customer_id"] for c in tables["customers"]}
    policy_ids = {p["policy_id"] for p in tables["policies"]}

    assert all(p["customer_id"] in customer_ids for p in tables["policies"])
    assert all(c["policy_id"] in policy_ids for c in tables["coverages"])
    assert all(c["policy_id"] in policy_ids for c in tables["claims_history"])


def test_generation_is_reproducible():
    assert generate_dataset(n_customers=50) == generate_dataset(n_customers=50)


def test_different_seeds_give_different_data():
    assert generate_dataset(n_customers=50, seed=1) != generate_dataset(n_customers=50, seed=2)


def test_planted_scenarios_do_not_shift_random_rows():
    tables, _ = generate_dataset(n_customers=50)
    random_rows = [c for c in tables["customers"] if not c["customer_id"].startswith("CUST-SCN-")]
    assert [c["customer_id"] for c in random_rows] == [f"CUST-{i:05d}" for i in range(1, 51)]


# ---------------------------------------------------------------------------
# Export
# ---------------------------------------------------------------------------

@pytest.fixture
def tmp_project(tmp_path, monkeypatch):
    monkeypatch.setattr(gen, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(gen, "DATA_DIR", tmp_path / "db" / "data")
    (tmp_path / "db" / "data").mkdir(parents=True)
    return tmp_path


def test_write_csv_round_trip(tmp_project):
    rows = [
        {"policy_id": "POL-2026-00001", "start_date": date(2026, 1, 2), "cancelled_at": None},
        {"policy_id": "POL-2026-00002", "start_date": date(2026, 3, 4), "cancelled_at": date(2026, 5, 6)},
    ]
    gen.write_csv("policies", rows)

    with (tmp_project / "db" / "data" / "policies.csv").open() as f:
        read = list(csv.DictReader(f))

    assert list(read[0]) == ["policy_id", "start_date", "cancelled_at"]
    assert read[0] == {"policy_id": "POL-2026-00001", "start_date": "2026-01-02", "cancelled_at": ""}
    assert read[1]["cancelled_at"] == "2026-05-06"


def test_write_jsonl_serialises_dates(tmp_project):
    path = tmp_project / "evals" / "golden.jsonl"
    gen.write_jsonl(path, [{"id": 1, "when": date(2026, 1, 2), "note": "Róisín"}])

    lines = path.read_text(encoding="utf-8").splitlines()
    assert len(lines) == 1
    assert json.loads(lines[0]) == {"id": 1, "when": "2026-01-02", "note": "Róisín"}
