"""Planted scenarios: hand-crafted, deterministic claim cases with a known correct decision.

Each scenario adds rows to the same tables as the random data (customers, policies,
coverages, claims_history) plus one *incoming* claim: the input the agent has to judge.

The incoming claims and their expected decisions go to the golden set (evals/), never to
the database, so the agent can't read the answer through the SQL tool.

Planted IDs use the SCN marker (CUST-SCN-01, POL-SCN-LAPSED, ...) so they are easy to
spot in the CSVs and in traces. No randomness here: adding or editing a scenario never
changes the random rows produced by the main generator.
"""

from datetime import date, timedelta
from typing import Any

# ---------------------------------------------------------------------------
# Business rules the scenarios rely on.
# The claims handling guide (RAG docs) MUST state the same thresholds, otherwise
# the expected decisions can't be derived by the agent.
# ---------------------------------------------------------------------------

EARLY_CLAIM_DAYS = 30        # claim within N days of policy inception -> escalate
FREQUENT_CLAIMS_COUNT = 3    # N or more prior claims...
FREQUENT_CLAIMS_MONTHS = 12  # ...within this window -> escalate

# Fixed premiums keep planted policies independent of the random rate ranges
PREMIUMS = {"HOME-BASIC": 300.00, "HOME-STD": 495.00, "HOME-PLUS": 750.00}

# Decisions the agent can return
APPROVE, PARTIAL, DENY, ESCALATE, REQUEST_INFO = (
    "approve", "partial", "deny", "escalate", "request_info"
)


# ---------------------------------------------------------------------------
# Row builders (same columns as the random generator)
# ---------------------------------------------------------------------------

def _customer(n: int, full_name: str, county: str, since: date) -> dict:
    return {
        "customer_id": f"CUST-SCN-{n:02d}",
        "full_name": full_name,
        "county": county,
        "customer_since": since,
    }


def _policy(
    tag: str,
    customer: dict,
    product: str,
    products: dict,
    start: date,
    status: str = "active",
    cancelled_at: date | None = None,
) -> dict:
    return {
        "policy_id": f"POL-SCN-{tag}",
        "customer_id": customer["customer_id"],
        "product_code": product,
        "status": status,
        "start_date": start,
        "end_date": start + timedelta(days=365),
        "cancelled_at": cancelled_at,
        "annual_premium": PREMIUMS[product],
        "sum_insured": products[product]["fire"].limit,
    }


def _coverages(policy: dict, products: dict) -> list[dict]:
    return [
        {
            "policy_id": policy["policy_id"],
            "peril": peril,
            "limit_amount": cov.limit,
            "deductible": cov.deductible,
        }
        for peril, cov in products[policy["product_code"]].items()
    ]


def _prior_claim(n: int, policy: dict, loss_date: date, peril: str,
                 loss: float, paid: float, outcome: str = "paid") -> dict:
    return {
        "claim_id": f"CLM-{policy['policy_id'][4:]}-{n}",
        "policy_id": policy["policy_id"],
        "loss_date": loss_date,
        "peril": peril,
        "loss_amount": loss,
        "amount_paid": paid,
        "outcome": outcome,
    }


def _incoming(n: int, policy_id: str, reported_peril: str | None,
              loss_date: date | None, claimed_amount: float | None,
              reported_date: date, description: str) -> dict:
    return {
        "claim_id": f"CLM-NEW-SCN-{n:02d}",
        "policy_id": policy_id,
        "reported_date": reported_date,
        "loss_date": loss_date,
        "reported_peril": reported_peril,
        "claimed_amount": claimed_amount,
        "description": description,
    }


def _payout(products: dict, product: str, peril: str, amount: float) -> float:
    cov = products[product][peril]
    return round(max(min(amount, cov.limit) - cov.deductible, 0), 2)


# ---------------------------------------------------------------------------
# Scenarios
# ---------------------------------------------------------------------------

def build_scenarios(today: date, products: dict) -> tuple[dict[str, list[dict]], list[dict]]:
    """Return (rows to append per table, golden set records)."""
    d = lambda days: today - timedelta(days=days)  # noqa: E731  "N days ago"
    scenarios: list[dict[str, Any]] = []

    def add(scenario_id: str, summary: str, *, customer=None, policy=None,
            prior_claims=(), incoming: dict, decision: str, payout: float,
            reason: str, required_tools: list[str], required_docs: list[str] = ()):
        scenarios.append({
            "customer": customer,
            "policy": policy,
            "coverages": _coverages(policy, products) if policy else [],
            "prior_claims": list(prior_claims),
            "golden": {
                "scenario_id": scenario_id,
                "summary": summary,
                "input": incoming,
                "expected": {
                    "decision": decision,
                    "payout": payout,
                    "reason": reason,
                    "required_tools": required_tools,
                    "required_docs": list(required_docs),
                },
            },
        })

    SQL_ALL = ["get_policy", "get_coverage"]

    # 1. Clean case: active policy, covered peril, under the limit
    c = _customer(1, "Aoife Brennan", "Dublin", d(900))
    p = _policy("CLEAN", c, "HOME-STD", products, start=d(200))
    add("SCN-01-CLEAN",
        "Active policy, covered peril, amount under the limit.",
        customer=c, policy=p,
        incoming=_incoming(1, p["policy_id"], "storm", d(10), 6_400, d(8),
                           "Storm Bram blew several slates off the roof and rain came "
                           "into the attic. Roofer quote attached: EUR 6,400."),
        decision=APPROVE, payout=_payout(products, "HOME-STD", "storm", 6_400),
        reason="covered_within_limit", required_tools=SQL_ALL)

    # 2. Sudden escape of water: covered (contrast with scenario 3)
    c = _customer(2, "Cian Murphy", "Cork", d(700))
    p = _policy("BURST-PIPE", c, "HOME-STD", products, start=d(150))
    add("SCN-02-BURST-PIPE",
        "Sudden water damage is covered; the agent must not deny all water claims.",
        customer=c, policy=p,
        incoming=_incoming(2, p["policy_id"], "water_damage", d(6), 5_200, d(5),
                           "A pipe burst in the upstairs bathroom overnight and water "
                           "came through the kitchen ceiling. Plumber and repair "
                           "invoices total EUR 5,200."),
        decision=APPROVE, payout=_payout(products, "HOME-STD", "water_damage", 5_200),
        reason="covered_within_limit", required_tools=SQL_ALL,
        required_docs=["HOME-STD policy wording: water damage cover"])

    # 3. Exclusion only visible in the policy wording (RAG): gradual damage
    c = _customer(3, "Niamh O'Sullivan", "Galway", d(1_000))
    p = _policy("GRADUAL-LEAK", c, "HOME-STD", products, start=d(220))
    add("SCN-03-GRADUAL-LEAK",
        "Peril is covered in SQL, but gradual leaks are excluded in the wording.",
        customer=c, policy=p,
        incoming=_incoming(3, p["policy_id"], "water_damage", d(12), 7_800, d(10),
                           "Noticed swollen floorboards and mould in the kitchen. "
                           "The plumber found a slow leak under the sink that had "
                           "been dripping for several months. Repairs: EUR 7,800."),
        decision=DENY, payout=0.0, reason="exclusion_gradual_damage",
        required_tools=SQL_ALL,
        required_docs=["HOME-STD policy wording: exclusions, gradual damage"])

    # 4. Peril not included in the product
    c = _customer(4, "Seán Kelly", "Limerick", d(600))
    p = _policy("NOT-COVERED", c, "HOME-BASIC", products, start=d(180))
    add("SCN-04-NOT-COVERED",
        "HOME-BASIC has no water damage cover.",
        customer=c, policy=p,
        incoming=_incoming(4, p["policy_id"], "water_damage", d(9), 4_500, d(7),
                           "Washing machine hose split and flooded the utility room. "
                           "Repair estimate EUR 4,500."),
        decision=DENY, payout=0.0, reason="peril_not_covered",
        required_tools=SQL_ALL)

    # 5. Amount above the coverage limit
    c = _customer(5, "Róisín Walsh", "Kildare", d(800))
    p = _policy("OVER-LIMIT", c, "HOME-BASIC", products, start=d(240))
    add("SCN-05-OVER-LIMIT",
        "Theft above the HOME-BASIC limit: pay limit minus deductible.",
        customer=c, policy=p,
        incoming=_incoming(5, p["policy_id"], "theft", d(14), 14_000, d(13),
                           "Break-in while on holiday. Jewellery, laptop and a bicycle "
                           "stolen. Garda report attached. Total value EUR 14,000."),
        decision=PARTIAL, payout=_payout(products, "HOME-BASIC", "theft", 14_000),
        reason="exceeds_limit", required_tools=SQL_ALL)

    # 6. Below the deductible
    c = _customer(6, "Darragh Byrne", "Wicklow", d(500))
    p = _policy("BELOW-DEDUCTIBLE", c, "HOME-STD", products, start=d(100))
    add("SCN-06-BELOW-DEDUCTIBLE",
        "Loss smaller than the deductible: nothing to pay.",
        customer=c, policy=p,
        incoming=_incoming(6, p["policy_id"], "theft", d(4), 180, d(3),
                           "Garden furniture cushions stolen from the patio. "
                           "Value about EUR 180."),
        decision=DENY, payout=0.0, reason="below_deductible",
        required_tools=SQL_ALL)

    # 7. Lapsed policy: loss after the end date
    c = _customer(7, "Ciara Doyle", "Meath", d(1_200))
    p = _policy("LAPSED", c, "HOME-STD", products, start=d(500), status="lapsed")
    add("SCN-07-LAPSED",
        "Policy ended 135 days ago and was not renewed.",
        customer=c, policy=p,
        incoming=_incoming(7, p["policy_id"], "storm", d(20), 3_100, d(18),
                           "Fence and shed roof damaged in high winds. Quote EUR 3,100."),
        decision=DENY, payout=0.0, reason="policy_not_in_force",
        required_tools=["get_policy"])

    # 8. Cancelled before the loss
    c = _customer(8, "Eoin Ryan", "Waterford", d(400))
    p = _policy("CANCELLED", c, "HOME-PLUS", products, start=d(250),
                status="cancelled", cancelled_at=d(60))
    add("SCN-08-CANCELLED",
        "Policy was cancelled 45 days before the loss date.",
        customer=c, policy=p,
        incoming=_incoming(8, p["policy_id"], "accidental_damage", d(15), 1_200, d(14),
                           "Dropped a TV while moving furniture; screen cracked. "
                           "Replacement EUR 1,200."),
        decision=DENY, payout=0.0, reason="policy_not_in_force",
        required_tools=["get_policy"])

    # 9. Fraud signal: claim right after inception
    c = _customer(9, "Orla Fitzgerald", "Dublin", d(14))
    p = _policy("EARLY-CLAIM", c, "HOME-PLUS", products, start=d(12))
    add("SCN-09-EARLY-CLAIM",
        f"Theft reported 9 days after inception (threshold: {EARLY_CLAIM_DAYS} days).",
        customer=c, policy=p,
        incoming=_incoming(9, p["policy_id"], "theft", d(3), 8_500, d(2),
                           "Burglary at the property. Watches and electronics taken. "
                           "Estimated loss EUR 8,500."),
        decision=ESCALATE, payout=0.0, reason="fraud_signal_early_claim",
        required_tools=SQL_ALL,
        required_docs=["Claims handling guide: fraud indicators"])

    # 10. Fraud signal: frequent claims in the last 12 months
    c = _customer(10, "Conor Gallagher", "Donegal", d(1_500))
    p = _policy("FREQUENT", c, "HOME-PLUS", products, start=d(300))
    prior = [
        _prior_claim(1, p, d(280), "theft", 2_300, 2_150),
        _prior_claim(2, p, d(190), "accidental_damage", 900, 750),
        _prior_claim(3, p, d(90), "water_damage", 3_400, 3_150),
    ]
    add("SCN-10-FREQUENT",
        f"{len(prior)} paid claims in the last {FREQUENT_CLAIMS_MONTHS} months "
        f"(threshold: {FREQUENT_CLAIMS_COUNT}).",
        customer=c, policy=p, prior_claims=prior,
        incoming=_incoming(10, p["policy_id"], "storm", d(7), 4_100, d(6),
                           "Storm damage to the conservatory roof. Quote EUR 4,100."),
        decision=ESCALATE, payout=0.0, reason="fraud_signal_claim_frequency",
        required_tools=SQL_ALL + ["get_claims_history"],
        required_docs=["Claims handling guide: fraud indicators"])

    # 11. Missing information: no loss date, no amount
    c = _customer(11, "Siobhán Nolan", "Kilkenny", d(650))
    p = _policy("MISSING-INFO", c, "HOME-STD", products, start=d(160))
    add("SCN-11-MISSING-INFO",
        "Claim has no loss date and no amount; the agent must ask, not guess.",
        customer=c, policy=p,
        incoming=_incoming(11, p["policy_id"], "theft", None, None, d(1),
                           "Some items were taken from the house recently. "
                           "Not sure of the total yet."),
        decision=REQUEST_INFO, payout=0.0, reason="missing_loss_date_and_amount",
        required_tools=["get_policy"])

    # 12. Unknown policy number: tool returns nothing, the agent must not invent data
    add("SCN-12-UNKNOWN-POLICY",
        "Policy number does not exist in the database.",
        incoming=_incoming(12, "POL-2026-99999", "fire", d(5), 25_000, d(4),
                           "Kitchen fire caused by a chip pan. Smoke damage throughout "
                           "the ground floor. Estimate EUR 25,000."),
        decision=REQUEST_INFO, payout=0.0, reason="policy_not_found",
        required_tools=["get_policy"])

    tables = {
        "customers": [s["customer"] for s in scenarios if s["customer"]],
        "policies": [s["policy"] for s in scenarios if s["policy"]],
        "coverages": [row for s in scenarios for row in s["coverages"]],
        "claims_history": [row for s in scenarios for row in s["prior_claims"]],
    }
    golden = [s["golden"] for s in scenarios]
    return tables, golden
