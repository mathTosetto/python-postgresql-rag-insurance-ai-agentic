CREATE TABLE customers (
    customer_id     TEXT PRIMARY KEY,      -- 'CUST-00042'
    full_name       TEXT NOT NULL,
    county          TEXT,
    customer_since  DATE
);

CREATE TABLE policies (
    policy_id       TEXT PRIMARY KEY,      -- 'POL-2025-00117'
    customer_id     TEXT REFERENCES customers,
    product_code    TEXT NOT NULL,         -- 'HOME-BASIC' | 'HOME-STD' | 'HOME-PLUS'
    status          TEXT NOT NULL,         -- 'active' | 'lapsed' | 'cancelled'
    start_date      DATE NOT NULL,
    end_date        DATE NOT NULL,
    cancelled_at    DATE,                  -- Date the policy was cancelled, if applicable
    annual_premium  NUMERIC(10,2),         -- Amount the customer pays per year for the coverage
    sum_insured     NUMERIC(12,2)          -- Maximum amount the insurer pays out if a claim occurs
);

CREATE TABLE coverages (
    policy_id       TEXT REFERENCES policies,
    peril           TEXT NOT NULL,         -- Event covered by the policy: 'fire' | 'theft' | 'water_damage' | 'storm' | 'accidental_damage'
    limit_amount    NUMERIC(12,2),         -- Maximum amount the insurer pays for a single claim of this peril; losses above it are borne by the customer
    deductible      NUMERIC(10,2),         -- Amount the customer pays out of pocket on each claim before the insurer pays; deducted from the payout
    PRIMARY KEY (policy_id, peril)
);

CREATE TABLE claims_history (
    claim_id        TEXT PRIMARY KEY,
    policy_id       TEXT REFERENCES policies,
    loss_date       DATE,
    peril           TEXT,
    loss_amount     NUMERIC(12,2),         -- Total damage assessed for the event, before limit and deductible
    amount_paid     NUMERIC(12,2),         -- Amount the insurer paid to the customer for this claim, after applying limit and deductible
    outcome         TEXT                   -- 'paid' | 'denied' | 'partial'
);