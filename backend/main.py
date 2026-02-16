from fastapi import FastAPI
from pydantic import BaseModel
import snowflake.connector
import os

app = FastAPI(title="Census Chat Agent")

class ChatRequest(BaseModel):
    question: str


def get_conn():
    return snowflake.connector.connect(
        account=os.environ["SNOWFLAKE_ACCOUNT"],
        user=os.environ["SNOWFLAKE_USER"],
        authenticator="externalbrowser",
        role="SYSADMIN",
        warehouse="WH_AGENT",
        database="APP_DB",
        schema="APP_SCHEMA",
    )


@app.get("/")
def health():
    return {"ok": True}


@app.post("/chat")
def chat(req: ChatRequest):

    q = req.question.lower()

    if "commute" in q:
        sql = """
        SELECT *
        FROM STATE_COMMUTE_SUMMARY
        ORDER BY AVG_COMMUTE_MINUTES DESC
        LIMIT 20
        """

        message = "States with the longest average commute time (minutes)."
        intent = "commute"

    elif "rent" in q:
        sql = """
        SELECT *
        FROM COUNTY_RENT_SUMMARY
        ORDER BY PCT_RENT_OVER_30 DESC
        LIMIT 20
        """

        message = "Top counties by share of renters spending ≥30% income on rent."
        intent = "rent"

    else:
        return {"ok": False, "message": "Unknown question"}

    conn = get_conn()
    cur = conn.cursor()
    cur.execute(sql)

    cols = [c[0] for c in cur.description]
    rows = [dict(zip(cols, r)) for r in cur.fetchall()]

    cur.close()
    conn.close()

    return {
        "ok": True,
        "intent": intent,
        "message": message,
        "rows": rows
    }

