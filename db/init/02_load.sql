COPY customers (customer_id, full_name, county, customer_since)
FROM '/data/customers.csv' WITH (FORMAT csv, HEADER true);

COPY policies (policy_id, customer_id, product_code, status, start_date, end_date, cancelled_at, annual_premium, sum_insured)
FROM '/data/policies.csv' WITH (FORMAT csv, HEADER true);

COPY coverages (policy_id, peril, limit_amount, deductible)
FROM '/data/coverages.csv' WITH (FORMAT csv, HEADER true);

COPY claims_history (claim_id, policy_id, loss_date, peril, loss_amount, amount_paid, outcome)
FROM '/data/claims_history.csv' WITH (FORMAT csv, HEADER true);