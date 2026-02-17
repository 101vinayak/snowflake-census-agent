from __future__ import annotations

import json
import os
from typing import Any, Dict, List, Optional

import snowflake.connector
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field


# =========================
# Config
# =========================

SNOWFLAKE_ACCOUNT = os.getenv("SNOWFLAKE_ACCOUNT")  # e.g. HMFNMOY-SWC80553
SNOWFLAKE_USER = os.getenv("SNOWFLAKE_USER")        # e.g. VINAYAKD
SNOWFLAKE_PASSWORD = os.getenv("SNOWFLAKE_PASSWORD")  # optional if using externalbrowser
SNOWFLAKE_AUTHENTICATOR = os.getenv("SNOWFLAKE_AUTHENTICATOR", "externalbrowser")

SNOWFLAKE_ROLE = os.getenv("SNOWFLAKE_ROLE", "SYSADMIN")
SNOWFLAKE_WAREHOUSE = os.getenv("SNOWFLAKE_WAREHOUSE", "WH_AGENT")
SNOWFLAKE_DATABASE = os.getenv("SNOWFLAKE_DATABASE", "APP_DB")
SNOWFLAKE_SCHEMA = os.getenv("SNOWFLAKE_SCHEMA", "APP_SCHEMA")

CORTEX_MODEL = os.getenv("CORTEX_MODEL", "mistral-large")


# =========================
# FastAPI
# =========================

app = FastAPI(title="Snowflake Census Agent", version="1.0")

# allow local frontend + easy deploy; adjust later if you want stricter
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# =========================
# Models
# =========================

class ChatRequest(BaseModel):
    question: str = Field(..., min_length=1, max_length=2000)


class ChatResponse(BaseModel):
    ok: bool
    intent: str
    message: str
    rows: List[Dict[str, Any]] = []
    plan: Optional[Dict[str, Any]] = None


# =========================
# Snowflake helpers
# =========================

def get_conn():
    """
    Uses External Browser by default (good for local dev).
    For cloud deploy, you typically want password auth:
      set SNOWFLAKE_AUTHENTICATOR='snowflake' and provide SNOWFLAKE_PASSWORD.
    """
    if not SNOWFLAKE_ACCOUNT or not SNOWFLAKE_USER:
        raise RuntimeError("Missing env vars: SNOWFLAKE_ACCOUNT and/or SNOWFLAKE_USER")

    kwargs = dict(
        account=SNOWFLAKE_ACCOUNT,
        user=SNOWFLAKE_USER,
        role=SNOWFLAKE_ROLE,
        warehouse=SNOWFLAKE_WAREHOUSE,
        database=SNOWFLAKE_DATABASE,
        schema=SNOWFLAKE_SCHEMA,
    )
    kwargs["session_parameters"] = {"QUERY_TAG": "census_agent"}

    # Auth choice
    if SNOWFLAKE_AUTHENTICATOR.lower() == "externalbrowser":
        kwargs["authenticator"] = "externalbrowser"
    else:
        # default to username/password style
        kwargs["authenticator"] = SNOWFLAKE_AUTHENTICATOR
        if SNOWFLAKE_PASSWORD:
            kwargs["password"] = SNOWFLAKE_PASSWORD

    return snowflake.connector.connect(**kwargs)


def run_query(sql: str) -> List[Dict[str, Any]]:
    conn = get_conn()
    cur = conn.cursor()
    try:
        cur.execute(sql)
        cols = [c[0] for c in cur.description] if cur.description else []
        out = []
        for row in cur.fetchall():
            out.append({cols[i]: row[i] for i in range(len(cols))})
        return out
    finally:
        try:
            cur.close()
        finally:
            conn.close()


def escape_sql_literal(s: str) -> str:
    # safe for Snowflake string literal
    return s.replace("\\", "\\\\").replace("'", "''")


# =========================
# Cortex planner (NL -> JSON plan)
# =========================

def build_planner_prompt(question: str) -> str:
    # Keep strict + compact so it’s reliable
    return f"""You are a strict JSON generator for a US Census data agent.
Return ONLY valid minified JSON (no markdown, no commentary).

Schema:
{{"intent":"rent_burden"|"commute"|"migration"|"language"|"off_topic"|"nsfw","geo_level":"state"|"county","measure":"rate"|"count"|"avg_minutes","threshold_pct":number|null,"top_k":number}}

Rules:
- Any sexual/NSFW content -> intent="nsfw".
- If unrelated to US population/census topics -> intent="off_topic".
- Rent burden (>= X% income on rent) -> intent="rent_burden", measure="rate", threshold_pct = X or 30.
- Commute/travel time to work -> intent="commute", measure="avg_minutes".
- Migration/moved/moved in last year -> intent="migration", measure="count" unless user asks "rate".
- Language/non-English/English ability -> intent="language", measure="count" unless user asks "rate".

Geo:
- If user says state/states -> geo_level="state"
- If user says county/counties -> geo_level="county"
- If unclear: default geo_level="county" for rent/migration/language, and "state" for commute.

top_k default 20, cap at 50.

User question: {question}"""


def parse_plan(raw: str) -> Dict[str, Any]:
    plan = json.loads(raw)

    # normalize
    intent = plan.get("intent", "off_topic")
    geo_level = plan.get("geo_level", "county")
    measure = plan.get("measure", "count")

    # clamp top_k
    top_k = plan.get("top_k", 20)
    try:
        top_k = int(top_k)
    except Exception:
        top_k = 20
    top_k = max(1, min(50, top_k))

    thr = plan.get("threshold_pct", None)
    if thr is not None:
        try:
            thr = float(thr)
        except Exception:
            thr = None
        if thr is not None:
            thr = max(0.0, min(100.0, thr))

    allowed_intents = {"rent_burden", "commute", "migration", "language", "off_topic", "nsfw"}
    if intent not in allowed_intents:
        intent = "off_topic"

    if geo_level not in {"state", "county"}:
        geo_level = "county"

    if measure not in {"rate", "count", "avg_minutes"}:
        measure = "count"

    return {
        "intent": intent,
        "geo_level": geo_level,
        "measure": measure,
        "threshold_pct": thr,
        "top_k": top_k,
    }

def cortex_plan(question: str) -> Dict[str, Any]:
    q = escape_sql_literal(question)

    sql = f"""
    WITH prompt AS (
      SELECT
$$You are a strict JSON generator for a US Census data agent.
Return ONLY valid minified JSON (no markdown, no commentary).

Schema:
{{
  "intent": "rent_burden" | "commute" | "migration" | "language" | "off_topic" | "nsfw",
  "geo_level": "state" | "county",
  "measure": "rate" | "count" | "avg_minutes",
  "threshold_pct": number | null,
  "top_k": number
}}

Rules:
- If the user asks anything sexual/NSFW -> intent="nsfw".
- If unrelated to US population/census topics -> intent="off_topic".
- Rent burden questions (>= X% of income on rent) -> intent="rent_burden", measure="rate", threshold_pct = X or 30 if not provided.
- Commute questions -> intent="commute", measure="avg_minutes".
- Migration / moved / moved in last year -> intent="migration", measure="count" unless they explicitly ask "rate".
- Non-English / language spoken at home / English ability -> intent="language", measure="count" unless they ask "rate".

Geo:
- If user says state/states -> geo_level="state"
- If user says county/counties -> geo_level="county"
- If unclear, default geo_level="county" for rent/migration/language, and "state" for commute.

top_k default 20, cap at 50.

Now plan for the user question:
$$ AS sys
    )
    SELECT
      SNOWFLAKE.CORTEX.AI_COMPLETE(
        '{escape_sql_literal(CORTEX_MODEL)}',
        (SELECT sys FROM prompt) || ' ' || '{q}'
      ) AS OUT;
    """

    rows = run_query(sql)
    if not rows or "OUT" not in rows[0] or not rows[0]["OUT"]:
        raise RuntimeError(f"Cortex returned empty output. rows={rows}")

    return parse_plan(rows[0]["OUT"])


# =========================
# SQL templates (safe tools)
# =========================

def build_sql_from_plan(plan: Dict[str, Any]) -> (str, str):
    """
    Returns (sql, message)
    Only whitelisted templates. No free-form user SQL.
    """

    k = int(plan["top_k"])
    intent = plan["intent"]

    # NOTE: adjust these view names if yours differ
    if intent == "commute":
        sql = f"""
        SELECT state_abbrev, total_workers, avg_commute_minutes
        FROM V_COMMUTE_STATE_NAMED
        ORDER BY avg_commute_minutes DESC
        LIMIT {k}
        """
        msg = "States with the longest average commute time (minutes)."
        return sql, msg

    if intent == "rent_burden":
        thr = plan.get("threshold_pct") or 30.0
        # Your current rent feature is specifically 30%+ bucketed.
        # We'll be honest + deterministic:
        note = ""
        if abs(thr - 30.0) > 1e-9:
            note = f" (Note: ACS rent-burden buckets support 30%+; using 30%+ as closest match to {thr:.1f}%)."

        sql = f"""
        SELECT state_abbrev, county_name, renter_total_computed, pct_rent_over_30
        FROM V_RENT_BURDEN_COUNTY_NAMED
        WHERE renter_total_computed >= 200
        ORDER BY pct_rent_over_30 DESC
        LIMIT {k}
        """
        msg = f"Top counties by share of renters spending ≥30% of income on rent.{note}"
        return sql, msg

    if intent == "migration":
        if plan.get("geo_level") == "state":
            sql = f"""
            SELECT state_abbrev,
                   SUM(migrants) AS migrants,
                   (SUM(migrants) / NULLIF(SUM(total_population),0)) AS migration_rate
            FROM V_MIGRATION_COUNTY_NAMED
            GROUP BY state_abbrev
            ORDER BY migrants DESC
            LIMIT {k}
            """
            msg = "States with the highest inbound migration (moved in last year)."
            return sql, msg
        else:
            sql = f"""
            SELECT state_abbrev, county_name, migrants, migration_rate
            FROM V_MIGRATION_COUNTY_NAMED
            ORDER BY migrants DESC
            LIMIT {k}
            """
            msg = "Counties with the highest inbound migration (moved in last year)."
            return sql, msg

    if intent == "language":
        if plan.get("geo_level") == "state":
            sql = f"""
            SELECT state_abbrev,
                   SUM(non_english_population) AS non_english_population,
                   (SUM(non_english_population) / NULLIF(SUM(total_population),0)) AS non_english_rate
            FROM V_LANGUAGE_COUNTY_NAMED
            GROUP BY state_abbrev
            ORDER BY non_english_population DESC
            LIMIT {k}
            """
            msg = "States with the largest non-English-speaking populations."
            return sql, msg
        else:
            sql = f"""
            SELECT state_abbrev, county_name, non_english_population, non_english_rate
            FROM V_LANGUAGE_COUNTY_NAMED
            ORDER BY non_english_population DESC
            LIMIT {k}
            """
            msg = "Counties with the largest non-English-speaking populations."
            return sql, msg

    # fallback (shouldn’t happen if planner works)
    return "SELECT 'Unsupported question. Ask about rent burden, commutes, migration, or language.' AS hint", \
           "Unsupported question. Ask about rent burden, commutes, migration, or language."


# =========================
# Routes
# =========================

@app.get("/")
def health():
    return {"ok": True}


@app.post("/chat", response_model=ChatResponse)
def chat(req: ChatRequest):
    q = req.question.strip()

    # 1) Plan using Cortex
    try:
        plan = cortex_plan(q)
    except Exception as e:
        return ChatResponse(
            ok=False,
            intent="planner_error",
            message=f"Planner failed. Try rephrasing. ({type(e).__name__})",
            rows=[],
            plan=None,
        )

    # 2) Guardrails (from plan)
    if plan["intent"] == "nsfw":
        return ChatResponse(
            ok=False,
            intent="blocked_nsfw",
            message="I can’t help with NSFW content. Ask about US Census population topics (rent, commutes, migration, language).",
            rows=[],
            plan=plan,
        )

    if plan["intent"] == "off_topic":
        return ChatResponse(
            ok=False,
            intent="blocked_off_topic",
            message="I can answer only US population questions using Census data (rent burden, commute time, migration, language).",
            rows=[],
            plan=plan,
        )

    # 3) Execute safe template SQL
    sql, msg = build_sql_from_plan(plan)

    try:
        rows = run_query(sql)
    except Exception as e:
        return ChatResponse(
            ok=False,
            intent="query_error",
            message=f"Query failed. ({type(e).__name__})",
            rows=[],
            plan=plan,
        )

    return ChatResponse(
        ok=True,
        intent=plan["intent"],
        message=msg,
        rows=rows,
        plan=plan,  # include plan so reviewers can see agent reasoning (optional)
    )

