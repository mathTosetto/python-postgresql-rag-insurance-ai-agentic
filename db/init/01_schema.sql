CREATE SCHEMA insurance;

CREATE TABLE insurance.customers (
    customer_id     TEXT PRIMARY KEY,      -- 'CUST-00042'
    full_name       TEXT NOT NULL,
    county          TEXT,
    customer_since  DATE
);

CREATE TABLE insurance.policies (
    policy_id       TEXT PRIMARY KEY,      -- 'POL-2025-00117'
    customer_id     TEXT REFERENCES insurance.customers,
    product_code    TEXT NOT NULL,         -- 'HOME-BASIC' | 'HOME-STD' | 'HOME-PLUS'
    status          TEXT NOT NULL
        CONSTRAINT valid_status CHECK (status IN ('active', 'lapsed', 'cancelled')),
    start_date      DATE NOT NULL,
    end_date        DATE NOT NULL,
    cancelled_at    DATE,                  -- Date the policy was cancelled, if applicable
    annual_premium  NUMERIC(10,2),         -- Amount the customer pays per year for the coverage
    sum_insured     NUMERIC(12,2),         -- Maximum amount the insurer pays out if a claim occurs
    CONSTRAINT valid_end_date CHECK (end_date > start_date)
);

CREATE TABLE insurance.coverages (
    policy_id       TEXT REFERENCES insurance.policies,
    peril           TEXT NOT NULL,         -- Event covered by the policy: 'fire' | 'theft' | 'water_damage' | 'storm' | 'accidental_damage'
    limit_amount    NUMERIC(12,2),         -- Maximum amount the insurer pays for a single claim of this peril; losses above it are borne by the customer
    deductible      NUMERIC(10,2),         -- Amount the customer pays out of pocket on each claim before the insurer pays; deducted from the payout
    PRIMARY KEY (policy_id, peril)
);

CREATE TABLE insurance.claims_history (
    claim_id        TEXT PRIMARY KEY,
    policy_id       TEXT          NOT NULL,
    loss_date       DATE,
    peril           TEXT          NOT NULL,         -- Event that caused the loss: 'fire' | 'theft' | 'water_damage' | 'storm' | 'accidental_damage'
    loss_amount     NUMERIC(12,2) NOT NULL,         -- Total damage assessed for the event, before limit and deductible
    amount_paid     NUMERIC(12,2) NOT NULL,         -- Amount the insurer paid to the customer for this claim, after applying limit and deductible
    outcome         TEXT          NOT NULL CONSTRAINT valid_outcome CHECK (outcome IN ('paid', 'denied', 'partial')),
    CONSTRAINT valid_amount_paid CHECK (amount_paid <= loss_amount),
    CONSTRAINT fk_policy_id_peril FOREIGN KEY (policy_id, peril) REFERENCES insurance.coverages (policy_id, peril)
);
