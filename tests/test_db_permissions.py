"""Checks that the agent's database role is read-only.

These tests need the database from `docker compose up -d` and the credentials in `.env`.
They are skipped when the database is unreachable, so the rest of the suite runs without
Docker.
"""

from pathlib import Path

import psycopg
import pytest
from dotenv import dotenv_values

ENV_FILE = Path(__file__).resolve().parent.parent / ".env"
SCHEMA = "insurance"
TABLES = ["customers", "policies", "coverages", "claims_history"]

pytestmark = pytest.mark.db


@pytest.fixture(scope="module")
def env():
    if not ENV_FILE.exists():
        pytest.skip(".env not found; copy .env.example to .env")
    return dotenv_values(ENV_FILE)


@pytest.fixture(scope="module")
def agent_conn(env):
    try:
        conn = psycopg.connect(
            host="localhost",
            port=5432,
            dbname=env["POSTGRES_DB"],
            user=env["POSTGRES_AGENT_USER"],
            password=env["POSTGRES_AGENT_PASSWORD"],
            autocommit=True,  # each statement stands alone, so a failed one doesn't abort the next
            connect_timeout=3,
        )
    except psycopg.OperationalError as exc:
        pytest.skip(f"database not reachable as the agent role: {exc}")
    with conn:
        yield conn


@pytest.mark.parametrize("table", TABLES)
def test_agent_can_read_every_table(agent_conn, table):
    count = agent_conn.execute(f"SELECT count(*) FROM {SCHEMA}.{table}").fetchone()[0]
    assert count > 0


@pytest.mark.parametrize(
    "statement",
    [
        f"INSERT INTO {SCHEMA}.customers (customer_id, full_name) VALUES ('CUST-TEST', 'Test')",
        f"UPDATE {SCHEMA}.policies SET status = 'cancelled'",
        f"DELETE FROM {SCHEMA}.claims_history",
        f"TRUNCATE {SCHEMA}.coverages",
    ],
    ids=["insert", "update", "delete", "truncate"],
)
def test_agent_cannot_modify_data(agent_conn, statement):
    with pytest.raises(psycopg.errors.InsufficientPrivilege):
        agent_conn.execute(statement)


@pytest.mark.parametrize("schema", [SCHEMA, "public"])
def test_agent_cannot_create_tables(agent_conn, schema):
    with pytest.raises(psycopg.errors.InsufficientPrivilege):
        agent_conn.execute(f"CREATE TABLE {schema}.agent_should_not_create (id INT)")


def test_agent_is_not_a_superuser(agent_conn):
    is_superuser = agent_conn.execute(
        "SELECT rolsuper FROM pg_roles WHERE rolname = current_user"
    ).fetchone()[0]
    assert is_superuser is False
