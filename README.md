# US Census Chat Agent (Snowflake)

Hosted demo: <PASTE_STREAMLIT_URL_HERE>

## What it does
A web-based chat agent that answers natural-language questions about US population-related census data using Snowflake Marketplace (US Open Census).

Supported question areas:
- Rent burden (share of renters spending >= X% of income on rent) — county level
- Commute time — state level
- Migration (moved in past year) — county/state level
- Language (non-English at home) — county/state level

Guardrails:
- Refuses off-topic questions
- Refuses NSFW requests
- Queries are restricted to read-only SELECTs over curated views

## How it works (high level)
- User asks a question in chat
- Router extracts intent + parameters (top N, state filter, % threshold)
- App runs a safe SELECT query against curated Snowflake views
- App returns a short natural-language summary + a table of results

## Snowflake objects used
All queries are run against these views (derived from the Marketplace dataset):
- APP_DB.APP_SCHEMA.V_RENT_BURDEN_COUNTY_NAMED
- APP_DB.APP_SCHEMA.V_COMMUTE_STATE_NAMED
- APP_DB.APP_SCHEMA.V_MIGRATION_COUNTY_NAMED
- APP_DB.APP_SCHEMA.V_MIGRATION_STATE_NAMED
- APP_DB.APP_SCHEMA.V_LANGUAGE_COUNTY_NAMED
- APP_DB.APP_SCHEMA.V_LANGUAGE_STATE_NAMED

## Access
The demo is publicly accessible at the link above.
If prompted for credentials (not expected), use those provided in the repo notes.

