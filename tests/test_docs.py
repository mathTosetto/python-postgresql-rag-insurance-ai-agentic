"""RAG source documents must agree with the code.

The claims guide states the fraud thresholds used by the planted scenarios, and each policy
wording states the limits and deductibles of its product. If either drifts from the code,
the expected decisions in the golden set can no longer be derived from the documents.
"""

import re
from pathlib import Path

import pytest

from synthetic_data.generate_mocked_data import PRODUCTS
from synthetic_data.scenarios import (
    EARLY_CLAIM_DAYS,
    FREQUENT_CLAIMS_COUNT,
    FREQUENT_CLAIMS_MONTHS,
)

DOCS = Path(__file__).resolve().parent.parent / "docs"
CLAIMS_GUIDE = DOCS / "claims_guide.md"
WORDINGS = DOCS / "policy_wording"

ALL_PERILS = {peril for coverages in PRODUCTS.values() for peril in coverages}
NOT_COVERED = "Not covered"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def sections(text: str) -> dict[str, str]:
    """Split a markdown document into {level-2 heading: body}."""
    parts = re.split(r"^## (.+)$", text, flags=re.MULTILINE)
    return {title.strip(): body for title, body in zip(parts[1::2], parts[2::2])}


def flat(text: str) -> str:
    """Collapse line wraps and repeated spaces, so a phrase can span lines in the source."""
    return " ".join(text.split())


def front_matter(text: str) -> dict[str, str]:
    match = re.match(r"^---\n(.*?)\n---\n", text, flags=re.DOTALL)
    assert match, "document has no front matter"
    return dict(
        (key.strip(), value.strip().strip('"'))
        for key, value in (line.split(":", 1) for line in match.group(1).splitlines())
    )


def euros(cell: str) -> int:
    """'€25,000' -> 25000."""
    assert re.fullmatch(r"€[\d,]+", cell), f"not a euro amount: {cell!r}"
    return int(cell[1:].replace(",", ""))


def search_int(pattern: str, text: str) -> int:
    match = re.search(pattern, text)
    assert match, f"pattern not found: {pattern}"
    return int(match.group(1))


def schedule_of_cover(text: str) -> dict[str, tuple[int, int] | None]:
    """Parse section 3 into {peril code: (limit, deductible)}, or None when not covered."""
    table = sections(text)["3. Schedule of cover"]
    rows = [line for line in table.splitlines() if line.startswith("|")][2:]  # header, ---
    schedule = {}
    for row in rows:
        _, code, limit, deductible = [cell.strip() for cell in row.strip("|").split("|")]
        peril = code.strip("`")
        assert peril not in schedule, f"duplicate row for {peril}"
        if limit == NOT_COVERED:
            assert deductible == NOT_COVERED, peril
            schedule[peril] = None
        else:
            schedule[peril] = (euros(limit), euros(deductible))
    return schedule


def peril_section(text: str, peril: str) -> str:
    """Body of the 'N. <Peril> cover' section, e.g. '7. Water damage cover'."""
    name = peril.replace("_", " ").capitalize()
    matches = [body for title, body in sections(text).items()
               if re.fullmatch(rf"\d+\. {name} cover", title)]
    assert len(matches) == 1, f"expected one section for {peril}, found {len(matches)}"
    return matches[0]


@pytest.fixture(scope="module")
def guide() -> dict[str, str]:
    return sections(CLAIMS_GUIDE.read_text(encoding="utf-8"))


def wording(product: str) -> str:
    return (WORDINGS / f"{product}.md").read_text(encoding="utf-8")


# ---------------------------------------------------------------------------
# Claims guide: fraud thresholds
# ---------------------------------------------------------------------------

def test_fraud_indicator_thresholds_match_scenarios(guide):
    rules = guide["9. Fraud indicators"]
    assert search_int(r"fewer than \*\*(\d+) days\*\*", rules) == EARLY_CLAIM_DAYS
    assert search_int(r"\*\*(\d+) or more\*\*", rules) == FREQUENT_CLAIMS_COUNT
    assert search_int(r"\*\*(\d+) months\*\*", rules) == FREQUENT_CLAIMS_MONTHS


def test_reason_code_table_repeats_the_same_thresholds(guide):
    codes = guide["12. Reason codes"]
    assert search_int(r"fewer than (\d+) days", codes) == EARLY_CLAIM_DAYS
    assert search_int(r"(\d+) or more previous claims", codes) == FREQUENT_CLAIMS_COUNT
    assert search_int(r"in the last (\d+) months", codes) == FREQUENT_CLAIMS_MONTHS


def test_early_claim_boundary_example_matches_threshold(guide):
    """The notes show one day under the threshold (early) and the threshold itself (not)."""
    rules = flat(guide["9. Fraud indicators"])
    assert f"A loss {EARLY_CLAIM_DAYS - 1} days after" in rules
    assert f"a loss {EARLY_CLAIM_DAYS} days after it is not" in rules


# ---------------------------------------------------------------------------
# Policy wordings: in sync with PRODUCTS
# ---------------------------------------------------------------------------

def test_one_wording_per_product():
    assert {path.stem for path in WORDINGS.glob("*.md")} == set(PRODUCTS)


@pytest.mark.parametrize("product", PRODUCTS)
def test_front_matter_names_the_product(product):
    meta = front_matter(wording(product))
    assert meta["doc_type"] == "policy_wording"
    assert meta["product_code"] == product


@pytest.mark.parametrize("product", PRODUCTS)
def test_schedule_of_cover_matches_products(product):
    schedule = schedule_of_cover(wording(product))

    assert set(schedule) == ALL_PERILS, "every peril needs a row, covered or not"
    covered = {peril: value for peril, value in schedule.items() if value is not None}
    assert covered == PRODUCTS[product]


@pytest.mark.parametrize("product", PRODUCTS)
def test_peril_sections_state_the_same_limits(product):
    text = wording(product)
    for peril in ALL_PERILS:
        body = flat(peril_section(text, peril))
        coverage = PRODUCTS[product].get(peril)
        if coverage is None:
            assert f"**not covered** under {product}" in body, peril
        else:
            assert (
                f"up to €{coverage.limit:,} per claim, minus a deductible of "
                f"€{coverage.deductible:,}"
            ) in body, peril


@pytest.mark.parametrize("product", PRODUCTS)
def test_sum_insured_is_the_fire_limit(product):
    fire_limit = PRODUCTS[product]["fire"].limit
    assert f"sum insured of a {product} policy is €{fire_limit:,}" in flat(wording(product))


@pytest.mark.parametrize("product", PRODUCTS)
def test_settlement_examples_follow_the_payout_rule(product):
    """Each example in section 9: loss, limit and deductible give the stated payment."""
    body = sections(wording(product))["9. How we settle claims"]
    examples = re.findall(
        r"Example: an? (.+?) loss of (€[\d,]+) under .+?"
        r"The limit is (€[\d,]+).+?The deductible is (€[\d,]+), so we pay (€[\d,]+)\.",
        body,
        flags=re.DOTALL,
    )
    assert examples, "no settlement examples found"

    for peril_name, loss, limit, deductible, paid in examples:
        peril = peril_name.lower().replace(" ", "_")
        coverage = PRODUCTS[product][peril]
        assert (euros(limit), euros(deductible)) == coverage, peril
        expected = max(min(euros(loss), coverage.limit) - coverage.deductible, 0)
        assert euros(paid) == expected, peril
