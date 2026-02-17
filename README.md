# US Census Chat Agent (Snowflake + Cortex)

Hosted demo: `https://app-census-agent-vinayakdhruv.streamlit.app/`

---

## Overview

A hosted AI-powered chat agent that answers natural-language questions about US Census population data using:

* Snowflake Marketplace (US Open Census dataset)
* Snowflake Cortex LLMs
* Curated, validated analytical views
* Strict SQL guardrails

The system supports structured reasoning, ranking queries, and cross-metric joins — while enforcing strict domain and safety constraints.

## Architecture

LLM Planner (Snowflake Cortex)
→ Structured QuerySpec / JoinSpec
→ Deterministic SQL Compiler
→ SQL Validator (hard guardrails)
→ Snowflake execution
→ Natural language summary
---

## Supported Question Types

### 1. Rent Burden (County Level)

* Average rent percentage of income
* Share of renters spending ≥30%
* Threshold filtering (e.g., “over 40%”)
* Ranked outputs (top N)

### 2. Commute Time (State Level)

* Longest average commutes
* Ranked queries (e.g., 5th longest)
* Threshold filters

### 3. Migration (County / State Level)

* Highest number of migrants
* Migration rate thresholds
* Ranked queries

### 4. Language (County / State Level)

* Non-English population counts
* Non-English rate
* Ranked outputs

### 5. Cross-Metric Join Queries (Advanced)

Example:

> Top 15 counties where rent over 30% > 0.60 AND migration_rate > 0.14 ranked by migrants

The system safely joins curated views using an LLM-generated JoinSpec compiled into validated SQL.

---

## Guardrails

* US-only scope enforcement
* No general knowledge responses
* NSFW detection (keyword + model restriction)
* Read-only SELECT queries
* No semicolons, CTEs, or multi-statements
* Strict column-level validation
* Whitelisted join pairs only
* Structured JSON plan required before execution

No raw SQL from user input is executed directly.

---

## Architecture

### 1. User Input

User enters natural-language question in Streamlit UI.

### 2. LLM Planner (Snowflake Cortex)

Cortex returns structured JSON:

* mode: chat | clarify | sql | join_sql | refuse
* query (QuerySpec) OR
* join_query (JoinSpec)

The LLM does NOT produce raw SQL.

---

### 3. Deterministic Compiler Layer

Two compilers:

* `compile_queryspec()` → single-view SELECT
* `compile_joinspec()` → validated INNER JOIN

All columns, operators, filters, limits, and views are validated against a strict schema.

---

### 4. SQL Validator

Before execution:

* Must be SELECT
* Must reference approved views
* No dangerous keywords
* No multiple statements

---

### 5. Snowflake Execution

Query runs against curated analytical views only.

---

### 6. Post-Processing

* Ranked result interpretation (e.g., “5th highest” logic)
* Natural-language summary
* Table display
* Optional debug mode (shows plan + SQL)

---

## Snowflake Objects Used

All queries run only against these curated views:

* APP_DB.APP_SCHEMA.V_RENT_BURDEN_AVG_COUNTY_NAMED
* APP_DB.APP_SCHEMA.V_RENT_BURDEN_COUNTY_NAMED
* APP_DB.APP_SCHEMA.V_COMMUTE_STATE_NAMED
* APP_DB.APP_SCHEMA.V_MIGRATION_COUNTY_NAMED
* APP_DB.APP_SCHEMA.V_MIGRATION_STATE_NAMED
* APP_DB.APP_SCHEMA.V_LANGUAGE_COUNTY_NAMED
* APP_DB.APP_SCHEMA.V_LANGUAGE_STATE_NAMED

These were derived from:

* B25070 — Rent burden
* B08303 — Commute time
* B07201 — Migration
* C16002 — Language

---

## Development Process

### Data Engineering

1. Connected Snowflake trial.
2. Installed US Open Census dataset from Marketplace.
3. Identified relevant ACS block-group tables.
4. Built curated views:

   * Cleaned metrics
   * Normalized geography (state/county)
   * Removed margin-of-error columns
   * Standardized units (percent vs fraction)
5. Created derived average rent metric view.

---

### AI System Engineering

1. Designed structured planner prompt.
2. Enforced JSON-only LLM outputs.
3. Built deterministic QuerySpec compiler.
4. Built deterministic JoinSpec compiler.
5. Added operator alias mapping (GT → >, etc.).
6. Added value coercion (string numbers → numeric).
7. Added SQL validator layer.
8. Added ordinal ranking logic (e.g., 5th highest).
9. Added debug mode.

---

### UI

* Streamlit chat interface
* Sidebar quick questions (email-required queries)
* SQL toggle
* Planner debug toggle
* Table rendering + narrative summary

---

## What Makes This Agentic

* LLM does planning only.
* System separates reasoning from execution.
* Structured plan → compiled SQL → validated execution.
* Join reasoning supported.
* Ranking + follow-up reasoning supported.
* Context-aware conversation (last table passed to planner).

This is not a keyword router — it is a constrained agentic pipeline.

---

## What I Would Improve With More Time

* Switch to larger Cortex model (e.g., mixtral-8x7b) for stronger planning consistency.
* Add window-function support for rank queries directly in SQL.
* Add caching layer.
* Add evaluation harness with golden queries.
* Add semantic embedding-based intent detection.
* Add geographic expansion (metro / city crosswalk dataset).
* Add observability dashboard (latency, plan failures).
* Add unit tests for compiler safety.

---

## Deployment

Deployed on Streamlit Community Cloud.

* Auto-redeploys on push to `main`
* Snowflake credentials configured in Streamlit secrets

---
