# Development Process – US Census Chat Agent

## 1. Objective

Build a hosted, interactive chat-based agent capable of answering natural language questions about US Census population data using Snowflake Marketplace.

The agent must:

* Support rent burden, commute, migration, and language questions
* Handle natural language input
* Enforce guardrails (off-topic + NSFW)
* Be safely deployable
* Restrict queries to curated, read-only views

---

## 2. Data Layer Design

### 2.1 Marketplace Dataset

Used **US Open Census dataset** from Snowflake Marketplace.

Relevant raw CBG tables identified:

| Topic        | Table  |
| ------------ | ------ |
| Rent burden  | B25070 |
| Commute time | B08303 |
| Migration    | B07201 |
| Language     | C16002 |

Raw Census tables are wide, encoded (e.g., B08303e1, B08303e2, etc.), and not user-friendly for direct querying.

---

### 2.2 Curated View Strategy

To avoid dynamic SQL over raw tables, I created curated views with:

* Clean column names
* Pre-aggregated metrics
* Explicit geography joins
* Stable schema contract for the agent

Final production views:

* `V_RENT_BURDEN_COUNTY_NAMED`
* `V_RENT_BURDEN_AVG_COUNTY_NAMED`
* `V_COMMUTE_STATE_NAMED`
* `V_MIGRATION_COUNTY_NAMED`
* `V_MIGRATION_STATE_NAMED`
* `V_LANGUAGE_COUNTY_NAMED`
* `V_LANGUAGE_STATE_NAMED`

Key design decision:

* County-level for rent burden
* State-level for commute
* County/state for migration and language
* No city-level naming (not available in dataset)

This ensured:

* Predictable schema
* Safe query compilation
* No raw-table exposure

---

## 3. Agent Architecture

Final system architecture:

User → LLM Planner → Structured QuerySpec → SQL Compiler → Validator → Snowflake → Results → Natural Language Response

### 3.1 LLM Planner

Using Snowflake Cortex (`mistral-large`).

The model:

* Does NOT generate SQL directly
* Generates structured JSON (QuerySpec or JoinSpec)
* Must choose mode:

  * `chat`
  * `clarify`
  * `sql`
  * `join_sql`
  * `refuse`

This prevents uncontrolled SQL generation.

---

### 3.2 Deterministic SQL Compilation

Two compilation paths:

#### A) Single-view QuerySpec → SQL

Strict validation:

* View must be in approved schema
* Columns must exist
* Operators must be allowed
* LIMIT capped at 50

#### B) JoinSpec → SQL

Enabled only for approved view pairs:

* Rent + Migration (county level)
* Rent + Language (county level)
* Migration + Language (county level)

Join enforced on:

```
(state_abbrev, county_name)
```

No arbitrary joins allowed.

---

## 4. Guardrails

Implemented multiple guard layers:

### 4.1 LLM-level constraints

* Hard scope: US only
* No general knowledge
* Reject unsupported geography levels
* Reject non-schema metrics

### 4.2 SQL Validator

* SELECT-only enforcement
* No CTEs
* No comments
* No INFORMATION_SCHEMA
* No DDL/DML keywords
* Only curated views allowed

### 4.3 Lightweight NSFW Filter

Local string-based filter before LLM call (cheap + fast).

---

## 5. Advanced Features Added

### 5.1 Join Queries (Beyond Requirements)

The original requirement did not explicitly require cross-metric queries.

Implemented join support for queries like:

> “Top counties where pct_rent_over_30 > 0.6 and migration_rate > 0.14 ranked by migrants.”

This required:

* JoinSpec schema
* Approved join pairs
* Left/right view validation
* Operator alias handling (GT → >, etc.)
* Safe compilation

---

### 5.2 Ordinal Reasoning (Post-Query)

Added local post-processing to handle:

* “Which county has the 5th highest migration?”
* “Which state has the 3rd longest commute?”

This is done via:

* Extract ordinal (e.g., 5th)
* Apply rank on already-ordered results
* Return derived explanation

No extra SQL required.

---

### 5.3 Context-Aware Followups

The planner receives:

* Last table preview (top rows)
* Conversation history (last 10 turns)

This allows:

* Explaining previous results
* Clarifying ambiguous references (e.g., “why is MD 2nd?”)

---

## 6. Deployment

* Built using Streamlit
* Hosted on Streamlit Community Cloud
* Snowflake credentials stored securely in Streamlit secrets
* Auto-redeploy on GitHub push to `main`

---

## 7. Key Engineering Decisions

### Why structured JSON planning?

Safer than free-form SQL generation.
Allows deterministic compilation + validation.

### Why curated views instead of raw tables?

* Reduced schema complexity
* Prevented wide-table SQL errors
* Stable contract between agent and data

### Why not pure LLM SQL generation?

Unsafe.
Hard to validate.
Difficult to enforce view-level restriction.

### Why no city-level migration?

Dataset does not provide city-level naming keys.
Explicitly clarified instead of hallucinating.

---

## 8. Known Limitations

* No pagination
* No CSV export
* No caching
* No city-level support
* LLM planning occasionally requires retries for strict JSON compliance
* Ranking logic relies on correct ordering in QuerySpec

---

## 9. What I Would Improve With More Time

1. Add evaluation harness for:

   * Required 4 email questions
   * Join queries
   * Edge cases

2. Add deterministic rank extraction directly in SQL (OFFSET-based ranking).

3. Add a lightweight semantic classifier before LLM to reduce planning calls.

4. Add logging + latency tracking.

5. Add result explanation generation via second LLM pass (optional enhancement).

6. Add stronger schema grounding prompt injection resistance testing.

---

## 10. Final Notes

The final system is:

* Safe (guardrails enforced at multiple layers)
* Structured (LLM does planning, not execution)
* Deterministic in SQL generation
* Deployable
* Extendable to additional views or metrics

The implementation goes beyond the minimal requirement by adding:

* Join-based reasoning
* Rank reasoning
* Context-aware followups
* Strict schema validation layer

---