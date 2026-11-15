import pytest

from synthetic_data.generate_mocked_data import PRODUCTS, TODAY, generate_dataset
from synthetic_data.scenarios import build_scenarios

N_TEST_CUSTOMERS = 2_000  # large enough to exercise every status, outcome and peril


@pytest.fixture(scope="session")
def dataset():
    tables, golden = generate_dataset(n_customers=N_TEST_CUSTOMERS)
    return tables, golden


@pytest.fixture(scope="session")
def tables(dataset):
    return dataset[0]


@pytest.fixture(scope="session")
def scenarios():
    return build_scenarios(TODAY, PRODUCTS)
