-- Global monthly counter for Azure OpenAI chat completion tokens (UTC calendar month).
-- Apply on Azure Postgres before deploying backend code that calls increment_monthly_azure_chat_tokens.

CREATE TABLE IF NOT EXISTS monthly_azure_chat_usage (
    billing_month DATE PRIMARY KEY,
    total_tokens BIGINT NOT NULL DEFAULT 0
);
