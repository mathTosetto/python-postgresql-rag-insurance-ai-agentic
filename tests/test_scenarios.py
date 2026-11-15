from datetime import date, timedelta

import pytest

from synthetic_data.generate_mocked_data import PRODUCTS, TODAY
from synthetic_data.scenarios import (
    APPROVE,
    DENY,
    EARLY_CLAIM_DAYS,
    ESCALATE,
    FREQUENT_CLAIMS_COUNT,
    FREQUENT_CLAIMS_MONTHS,
    PARTIAL,
    REQUEST_INFO,
    build_scenarios,
)

DECISIONS = {APPROVE, PARTIAL, DENY, ESCALATE, REQUEST_INFO}


@pytest.fixture(scope="module")
def tables(scenarios):
    return scenarios[0]


@pytest.fixture(scope="module")
def golden(scenarios):
    return scenarios[1]


@pytest.fixture(scope="module")
def by_id(golden):
    return {g["scenario_id"]: g for g in golden}


@pytest.fixture(scope="module")
def policies(tables):
    return {p["policy_id"]: p for p in tables["policies"]}


def _in_force(policy: dict, loss_date: date) -> bool:
    end = min(d for d in (policy["end_date"], policy["cancelled_at"]) if d)
    return policy["start_date"] <= loss_date < end


def _covered(policy: dict, peril: str) -> bool:
    return peril in PRODUCTS[policy["product_code"]]


# ---------------------------------------------------------------------------
# Structure
# ---------------------------------------------------------------------------

def test_build_scenarios_is_deterministic():
    assert build_scenarios(TODAY, PRODUCTS) == build_scenarios(TODAY, PRODUCTS)


def test_scenario_ids_are_unique(golden):
    ids = [g["scenario_id"] for g in golden]
    assert len(ids) == len(set(ids))
    assert all(i.startswith("SCN-") for i in ids)


def test_golden_records_have_expected_shape(golden):
    for g in golden:
        assert set(g) == {"scenario_id", "summary", "input", "expected"}
        assert set(g["expected"]) == {"decision", "payout", "reason", "required_tools", "required_docs"}
        assert g["expected"]["decision"] in DECISIONS
        assert g["expected"]["required_tools"], "every scenario needs at least one tool"
        assert g["input"]["description"].strip()


def test_every_decision_is_exercised(golden):
    assert {g["expected"]["decision"] for g in golden} == DECISIONS


def test_planted_ids_use_the_scn_marker(tables):
    assert all(c["customer_id"].startswith("CUST-SCN-") for c in tables["customers"])
    assert all(p["policy_id"].startswith("POL-SCN-") for p in tables["policies"])
    assert all(c["claim_id"].startswith("CLM-SCN-") for c in tables["claims_history"])


def test_planted_rows_have_the_same_columns_as_random_rows(tables, dataset):
    random_tables, _ = dataset
    for name, rows in tables.items():
        for row in rows:
            assert list(row) == list(random_tables[name][0]), name


def test_planted_dates_are_consistent(tables, policies):
    customers = {c["customer_id"]: c for c in tables["customers"]}
    for p in policies.values():
        assert customers[p["customer_id"]]["customer_since"] <= p["start_date"] <= TODAY
        if p["status"] == "active":
            assert p["start_date"] <= TODAY < p["end_date"]
        elif p["status"] == "lapsed":
            assert p["end_date"] < TODAY
        elif p["status"] == "cancelled":
            assert p["start_date"] <= p["cancelled_at"] <= TODAY


# ---------------------------------------------------------------------------
# The golden answer must never be reachable through the database
# ---------------------------------------------------------------------------

def test_incoming_claims_are_not_in_the_database(golden, dataset):
    db_claim_ids = {c["claim_id"] for c in dataset[0]["claims_history"]}
    assert not {g["input"]["claim_id"] for g in golden} & db_claim_ids


def test_unknown_policy_does_not_exist_anywhere(by_id, dataset):
    policy_id = by_id["SCN-12-UNKNOWN-POLICY"]["input"]["policy_id"]
    assert policy_id not in {p["policy_id"] for p in dataset[0]["policies"]}


def test_planted_rows_are_in_the_full_dataset(tables, dataset):
    full_policy_ids = {p["policy_id"] for p in dataset[0]["policies"]}
    assert {p["policy_id"] for p in tables["policies"]} <= full_policy_ids


# ---------------------------------------------------------------------------
# Each expected decision must follow from the planted data
# ---------------------------------------------------------------------------

def test_payout_matches_coverage_math(golden, policies):
    for g in golden:
        if g["expected"]["decision"] not in {APPROVE, PARTIAL}:
            assert g["expected"]["payout"] == 0.0, g["scenario_id"]
            continue
        inc = g["input"]
        cov = PRODUCTS[policies[inc["policy_id"]]["product_code"]][inc["reported_peril"]]
        expected = round(min(inc["claimed_amount"], cov.limit) - cov.deductible, 2)
        assert g["expected"]["payout"] == expected, g["scenario_id"]
        assert expected > 0


def test_approved_and_partial_claims_are_valid(golden, policies):
    for g in golden:
        decision = g["expected"]["decision"]
        if decision not in {APPROVE, PARTIAL}:
            continue
        inc = g["input"]
        policy = policies[inc["policy_id"]]
        cov = PRODUCTS[policy["product_code"]][inc["reported_peril"]]

        assert _in_force(policy, inc["loss_date"]), g["scenario_id"]
        assert inc["claimed_amount"] > cov.deductible
        if decision == PARTIAL:
            assert inc["claimed_amount"] > cov.limit
        else:
            assert inc["claimed_amount"] <= cov.limit


@pytest.mark.parametrize("scenario_id", ["SCN-07-LAPSED", "SCN-08-CANCELLED"])
def test_not_in_force(by_id, policies, scenario_id):
    inc = by_id[scenario_id]["input"]
    assert by_id[scenario_id]["expected"]["reason"] == "policy_not_in_force"
    assert not _in_force(policies[inc["policy_id"]], inc["loss_date"])


def test_peril_not_covered(by_id, policies):
    inc = by_id["SCN-04-NOT-COVERED"]["input"]
    assert not _covered(policies[inc["policy_id"]], inc["reported_peril"])


def test_below_deductible(by_id, policies):
    inc = by_id["SCN-06-BELOW-DEDUCTIBLE"]["input"]
    policy = policies[inc["policy_id"]]
    assert _covered(policy, inc["reported_peril"])
    assert inc["claimed_amount"] <= PRODUCTS[policy["product_code"]][inc["reported_peril"]].deductible


def test_gradual_leak_is_only_deniable_through_the_wording(by_id, policies):
    """SQL alone would approve it: in force, covered, within limit."""
    g = by_id["SCN-03-GRADUAL-LEAK"]
    inc = g["input"]
    policy = policies[inc["policy_id"]]
    cov = PRODUCTS[policy["product_code"]][inc["reported_peril"]]

    assert _in_force(policy, inc["loss_date"])
    assert cov.deductible < inc["claimed_amount"] <= cov.limit
    assert g["expected"]["decision"] == DENY
    assert g["expected"]["required_docs"]


def test_early_claim_is_within_threshold(by_id, policies):
    inc = by_id["SCN-09-EARLY-CLAIM"]["input"]
    policy = policies[inc["policy_id"]]
    assert _in_force(policy, inc["loss_date"])
    assert (inc["loss_date"] - policy["start_date"]).days < EARLY_CLAIM_DAYS


def test_frequent_claims_reach_threshold(by_id, policies, tables):
    inc = by_id["SCN-10-FREQUENT"]["input"]
    window_start = inc["reported_date"] - timedelta(days=FREQUENT_CLAIMS_MONTHS * 30)
    prior = [
        c for c in tables["claims_history"]
        if c["policy_id"] == inc["policy_id"] and window_start <= c["loss_date"] < inc["loss_date"]
    ]
    assert len(prior) >= FREQUENT_CLAIMS_COUNT
    assert "get_claims_history" in by_id["SCN-10-FREQUENT"]["expected"]["required_tools"]


def test_only_escalation_scenarios_are_near_fraud_thresholds(golden, policies):
    """Non-fraud scenarios must not accidentally trigger the early-claim rule."""
    for g in golden:
        inc = g["input"]
        policy = policies.get(inc["policy_id"])
        if g["expected"]["decision"] == ESCALATE or not policy or not inc["loss_date"]:
            continue
        if _in_force(policy, inc["loss_date"]):
            assert (inc["loss_date"] - policy["start_date"]).days >= EARLY_CLAIM_DAYS, g["scenario_id"]


def test_missing_info_has_no_date_or_amount(by_id):
    inc = by_id["SCN-11-MISSING-INFO"]["input"]
    assert inc["loss_date"] is None
    assert inc["claimed_amount"] is None
