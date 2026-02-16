import os
from typing import Optional, List, Dict, Any

import snowflake.connector
from fastapi import FastAPI
from pydantic import BaseModel
from dotenv import load_dotenv

load_dotenv()

def get_conn():
    return snowflake.connector.connect(
        user=os.environ["SNOWFLAKE_USER"],
        password=os.environ["SNOWFLAKE_PASSWORD"],
        account=os.environ["SNOWFLAKE_ACCOUNT"],
        authenticator="snowflake",
        warehouse=os.environ["SNOWFLAKE_WAREHOUSE"],
        database=os.environ["SNOWFLAKE_DATABASE"],
        schema=os.environ["SNOWFLAKE_SCHEMA"],
        role=os.environ["SNOWFLAKE_ROLE"],
    )

def run_query(sql: str) -> List[Dict[str, Any]]:
    conn = get_conn()
    cur = conn.cursor()
    try:
        cur.execute(sql)
        cols = [c[0] for c in cur.description]
        rows = cur.fetchall()
        return [dict(zip(cols, r)) for r in rows]
    finally:
        cur.close()
        conn.close()

# --- Guardrails (simple but effective for this assignment) ---
ALLOWED_TOPICS = [
    "population", "rent", "housing", "commute", "travel time",
    "migration", "move", "language", "english", "census",
    "county", "state", "city", "workers", "income"
]
NSFW_KEYWORDS = ["porn", "sex", "nude", "xxx", "erotic"]

def is_off_topic(q: str) -> bool:
    ql = q.lower()
    return not any(t in ql for t in ALLOWED_TOPICS)

def is_nsfw(q: str) -> bool:
    ql = q.lower()
    return any(k in ql for k in NSFW_KEYWORDS)

# --- Router: maps question -> a view query ---
def route_question(q: str) -> Dict[str, str]:
    ql = q.lower()

    if "rent" in ql and ("30%" in ql or "30 percent" in ql or "over 30" in ql):
        return {
            "intent": "rent_burden",
            "sql": """
                SELECT state_abbrev, county_name, renter_total_computed, pct_rent_over_30
                FROM V_RENT_BURDEN_COUNTY_NAMED
                WHERE renter_total_computed >= 200
                ORDER BY pct_rent_over_30 DESC
                LIMIT 20
            """
        }

    if "commute" in ql or "travel time" in ql:
        return {
            "intent": "commute",
            "sql": """
                SELECT state_abbrev, total_workers, avg_commute_minutes
                FROM V_COMMUTE_STATE_NAMED
                ORDER BY avg_commute_minutes DESC
                LIMIT 20
            """
        }

    if "migration" in ql or "moving" in ql or "move in" in ql or "people moving" in ql:
        return {
            "intent": "migration",
            "sql": """
                SELECT state_abbrev, county_name, migrants, migration_rate
                FROM V_MIGRATION_COUNTY_NAMED
                ORDER BY migrants DESC
                LIMIT 20
            """
        }

    if "non-english" in ql or "non english" in ql or "language" in ql:
        return {
            "intent": "non_english",
            "sql": """
                SELECT state_abbrev, county_name, non_english_population, non_english_rate
                FROM V_LANGUAGE_COUNTY_NAMED
                ORDER BY non_english_population DESC
                LIMIT 20
            """
        }

    return {
        "intent": "unknown",
        "sql": """
            SELECT
              'Try asking about rent burden (30%), commute time, migration, or non-English populations.' AS hint
        """
    }

class ChatRequest(BaseModel):
    question: str

class ChatResponse(BaseModel):
    ok: bool
    intent: str
    message: str
    rows: List[Dict[str, Any]]

app = FastAPI(title="Snowflake Census Agent")

@app.get("/health")
def health():
    return {"ok": True}

@app.post("/chat", response_model=ChatResponse)
def chat(req: ChatRequest):
    q = req.question.strip()

    if is_nsfw(q):
        return ChatResponse(
            ok=False,
            intent="blocked_nsfw",
            message="I can’t help with NSFW content. Ask about US population topics like rent burden, commutes, migration, or language.",
            rows=[],
        )

    if is_off_topic(q):
        return ChatResponse(
            ok=False,
            intent="blocked_off_topic",
            message="I’m only able to answer questions about US population using Census data (rent burden, commute time, migration, language).",
            rows=[],
        )

    route = route_question(q)
    rows = run_query(route["sql"])

    # simple natural-language response
    msg_map = {
        "rent_burden": "Top counties by share of renters spending ≥30% of household income on gross rent (computed renters).",
        "commute": "States with the longest average commute time (minutes).",
        "migration": "Counties with the highest number of residents who moved in the past year (migrants = total − same house).",
        "non_english": "Counties with the largest non-English-speaking population (total − English-only).",
        "unknown": "I couldn’t map that question to one of the supported intents yet."
    }

    return ChatResponse(
        ok=True,
        intent=route["intent"],
        message=msg_map.get(route["intent"], "Results"),
        rows=rows,
    )

