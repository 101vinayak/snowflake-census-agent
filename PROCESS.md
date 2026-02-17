# Development process

## Steps taken
1) Connected to Snowflake trial and installed US Open Census dataset from Marketplace.
2) Identified relevant CBG tables for:
   - Rent burden (B25070)
   - Commute time (B08303)
   - Migration (B07201)
   - Language (C16002)
3) Built curated Snowflake views with consistent, query-friendly metrics and geography joins (state/county).
4) Built a Streamlit chat UI.
5) Implemented a deterministic router (intent + parameter extraction) to map NL questions to safe SQL templates.
6) Added guardrails (off-topic + NSFW).
7) Deployed to Streamlit Community Cloud.

## What I would improve with more time
- Add a stronger semantic intent classifier (LLM or small model) instead of keyword routing.
- Add richer geography support (cities/metros) using an additional lookup dataset.
- Add caching + pagination for large results, and downloadable CSV.
- Add unit tests for routing/SQL templates and golden outputs for the 4 required queries.
- Add query explanations + data citations in the UI.
- Add observability (request logs, latency, error tracing).

