import json
from typing import Any, Dict

def build_planner_prompt(question: str) -> str:
    # Keep prompt small + strict to reduce failures
    return f"""You are a strict JSON generator for a US Census data agent.
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
- Migration/moved/moved in last year -> intent="migration", measure="count" unless they explicitly ask "rate".
- Non-English/language spoken at home/English ability -> intent="language", measure="count" unless they ask "rate".
Geo:
- If user says state/states -> geo_level="state"
- If user says county/counties -> geo_level="county"
- If unclear, default geo_level="county" for rent/migration/language, and "state" for commute.
top_k default 20.

User question: {question}
"""

def parse_plan(raw: str) -> Dict[str, Any]:
    # raw should be JSON text; be defensive
    plan = json.loads(raw)
    # normalize / clamp
    plan["top_k"] = int(plan.get("top_k", 20) or 20)
    if plan["top_k"] < 1: plan["top_k"] = 1
    if plan["top_k"] > 50: plan["top_k"] = 50

    if plan.get("threshold_pct") is not None:
        plan["threshold_pct"] = float(plan["threshold_pct"])
        if plan["threshold_pct"] < 0: plan["threshold_pct"] = 0
        if plan["threshold_pct"] > 100: plan["threshold_pct"] = 100

    # allow only known values
    allowed_intents = {"rent_burden","commute","migration","language","off_topic","nsfw"}
    if plan.get("intent") not in allowed_intents:
        plan["intent"] = "off_topic"

    if plan.get("geo_level") not in {"state","county"}:
        plan["geo_level"] = "county"

    allowed_measures = {"rate","count","avg_minutes"}
    if plan.get("measure") not in allowed_measures:
        plan["measure"] = "count"

    return plan

