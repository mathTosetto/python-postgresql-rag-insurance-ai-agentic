-- Get the agent user and password from environment variables
\getenv agent_user POSTGRES_AGENT_USER
\getenv agent_password POSTGRES_AGENT_PASSWORD

-- Create the agent user
CREATE USER :"agent_user" WITH PASSWORD :'agent_password';

-- Grant the agent user access to the insurance schema
GRANT USAGE ON SCHEMA insurance TO :"agent_user";

-- Grant the agent user SELECT privileges on the 4 insurance tables
GRANT SELECT ON TABLE
	insurance.customers,
	insurance.policies,
	insurance.coverages,
	insurance.claims_history
TO :"agent_user";
