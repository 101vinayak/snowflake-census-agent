import streamlit as st
import snowflake.connector
import re
import json
def extract_ordinal_k(q: str) -> int | None:
    s = q.lower()
    m = re.search(r"\b(\d+)\s*(st|nd|rd|th)\b", s)
    if m:
        k = int(m.group(1))
        return k if 1 <= k <= 50 else None
    return None

def derive_final_answer(question: str, rows: list[dict]) -> str | None:
    if not rows:
        return None

    k = extract_ordinal_k(question)
    if not k:
        return None

    if len(rows) < k:
        return f"I only have {len(rows)} rows shown. Ask me to show top {k} and I’ll give the {k}th item."

    r = rows[k - 1]
    # migration case
    if "migr" in question.lower() and ("COUNTY_NAME" in r or "county_name" in r):
        st_abbrev = r.get("STATE_ABBREV") or r.get("state_abbrev")
        county = r.get("COUNTY_NAME") or r.get("county_name")
        migrants = r.get("MIGRANTS") or r.get("migrants")
        if migrants is not None:
            return f"The {k}th highest is **{county}, {st_abbrev}** with **{migrants:,}** migrants."
        return f"The {k}th highest is **{county}, {st_abbrev}**."

    return f"The {k}th row in the ranked results is: {r}"


st.set_page_config(page_title="US Census Chat Agent", page_icon="🧠")

# ---------------------------
# Config / Scope
# ---------------------------
ALLOWED_TOPICS = [
    "rent", "renter", "commute", "travel time", "migration", "moving",
    "language", "non-english", "english only", "census", "population",
    "county", "state", "usa", "united states", "u.s.", "city", "cities"
]


NSFW_TERMS = [
    "porn", "sex", "nude", "xxx", "onlyfans", "fetish", "blowjob", "anal",
    "rape", "incest", "child porn", "cp"
]

ALLOWED_VIEWS = [
    "APP_DB.APP_SCHEMA.V_RENT_BURDEN_COUNTY_NAMED",
    "APP_DB.APP_SCHEMA.V_COMMUTE_STATE_NAMED",
    "APP_DB.APP_SCHEMA.V_MIGRATION_COUNTY_NAMED",
    "APP_DB.APP_SCHEMA.V_MIGRATION_STATE_NAMED",
    "APP_DB.APP_SCHEMA.V_LANGUAGE_COUNTY_NAMED",
    "APP_DB.APP_SCHEMA.V_LANGUAGE_STATE_NAMED",
    "APP_DB.APP_SCHEMA.V_RENT_BURDEN_AVG_COUNTY_NAMED"
]

SCHEMA_CONTEXT = """

Rent has TWO supported views:

1) Share of renters spending >= 30% of income on rent:
APP_DB.APP_SCHEMA.V_RENT_BURDEN_COUNTY_NAMED
  columns: state_abbrev, county_name, renter_total_computed, renter_over_30, pct_rent_over_30
  pct_rent_over_30 is a FRACTION (0-1)

2) Average percent of income spent on rent:
APP_DB.APP_SCHEMA.V_RENT_BURDEN_AVG_COUNTY_NAMED
  columns: state_abbrev, county_name, renter_total_computed, avg_rent_pct
  avg_rent_pct is a PERCENT (0-100)

Rule:
- If user says "on average" -> use V_RENT_BURDEN_AVG_COUNTY_NAMED (avg_rent_pct)
- Otherwise if user asks about renters spending >=30% -> use V_RENT_BURDEN_COUNTY_NAMED (pct_rent_over_30)


Scope is UNITED STATES (and territories like PR) ONLY. Reject questions about anything else.

Capability constraints (IMPORTANT):
- Commute: STATE level only (V_COMMUTE_STATE_NAMED). No county/city commute available.
- Rent burden: COUNTY level only (V_RENT_BURDEN_COUNTY_NAMED). No state-level rent view available.
- Migration: COUNTY and STATE available (V_MIGRATION_COUNTY_NAMED, V_MIGRATION_STATE_NAMED). No city-level naming available.
- Language: COUNTY and STATE available (V_LANGUAGE_COUNTY_NAMED, V_LANGUAGE_STATE_NAMED). No city-level naming available.

If user asks for an unavailable level (e.g., “city migration” or “county commute” or “state rent burden”):
- mode="clarify"
- explain what levels are available
- offer the closest alternative
- DO NOT invent views.

You can generate SQL only using these views:

APP_DB.APP_SCHEMA.V_RENT_BURDEN_COUNTY_NAMED
  columns: state_abbrev, county_name, renter_total_computed, renter_over_30, pct_rent_over_30
  NOTE: Commute data is available at STATE level only. No county-level commute view exists.

APP_DB.APP_SCHEMA.V_COMMUTE_STATE_NAMED
  columns: state_abbrev, total_workers, avg_commute_minutes

APP_DB.APP_SCHEMA.V_MIGRATION_COUNTY_NAMED
  columns: state_abbrev, county_name, total_population, migrants, migration_rate

APP_DB.APP_SCHEMA.V_MIGRATION_STATE_NAMED
  columns: state_abbrev, total_population, migrants, migration_rate

APP_DB.APP_SCHEMA.V_LANGUAGE_COUNTY_NAMED
  columns: state_abbrev, county_name, total_population, non_english_population, non_english_rate

APP_DB.APP_SCHEMA.V_LANGUAGE_STATE_NAMED
  columns: state_abbrev, total_population, non_english_population, non_english_rate

Rules:
- Only SELECT statements
- No semicolons
- No comments
- No other databases
- No INFORMATION_SCHEMA
"""

# ---------------------------
# Basic helpers
# ---------------------------
def is_nsfw(q: str) -> bool:
    s = q.lower()
    return any(t in s for t in NSFW_TERMS)

def is_off_topic(q: str) -> bool:
    s = q.lower()
    # allow greetings and city/cities (we will clarify later)
    if any(x in s for x in ["hi", "hello", "yo", "hey", "cities", "city"]):
        return False
    return not any(t in s for t in ALLOWED_TOPICS)

# ---------------------------
# Snowflake Connection
# ---------------------------
def get_conn():
    return snowflake.connector.connect(
        account=st.secrets["SNOWFLAKE_ACCOUNT"],
        user=st.secrets["SNOWFLAKE_USER"],
        password=st.secrets["SNOWFLAKE_PASSWORD"],
        warehouse=st.secrets["SNOWFLAKE_WAREHOUSE"],
        database=st.secrets["SNOWFLAKE_DATABASE"],
        schema=st.secrets["SNOWFLAKE_SCHEMA"],
        role=st.secrets["SNOWFLAKE_ROLE"],
    )

def run_query(sql: str):
    with get_conn() as conn:
        cur = conn.cursor()
        cur.execute(sql)
        rows = cur.fetchall()
        cols = [c[0] for c in cur.description]
    return [dict(zip(cols, r)) for r in rows]

# ---------------------------
# Cortex JSON helpers
# ---------------------------
def extract_first_json(text: str) -> dict:
    if text is None:
        raise ValueError("Empty Cortex response")

    s = text.strip()
    m = re.search(r"\{.*\}", s, flags=re.DOTALL)
    if not m:
        raise ValueError(f"No JSON object found in: {s[:300]}")

    j = m.group(0)
    j = re.sub(r"[\x00-\x1F]", " ", j)  # remove control chars

    try:
        return json.loads(j)
    except json.JSONDecodeError:
        j2 = re.sub(r'\\(?!["\\/bfnrtu])', r'\\\\', j)
        return json.loads(j2)



def cortex_complete_json(model: str, prompt: str) -> dict:
    sql = f"""
    SELECT SNOWFLAKE.CORTEX.COMPLETE(
      '{model}',
      $$ {prompt} $$
    ) AS OUT
    """
    with get_conn() as conn:
        cur = conn.cursor()
        cur.execute(sql)
        out = cur.fetchone()[0]
    return extract_first_json(out)

# ---------------------------
# SQL validator (hard guardrail)
# ---------------------------
_ALLOWED_UPPER = set(v.upper() for v in ALLOWED_VIEWS)

def normalize_sql(sql: str) -> str:
    if not sql:
        return ""

    s = sql.strip()

    # Remove any non-ascii chars (kills weird quotes/symbols)
    s = s.encode("ascii", "ignore").decode()

    # Collapse whitespace/newlines
    s = re.sub(r"\s+", " ", s).strip()

    # If model prefixed text like "Show ..." before SELECT, cut to first SELECT
    m = re.search(r"\bselect\b", s, flags=re.I)
    if m:
        s = s[m.start():].strip()

    # Drop trailing semicolons (common model mistake)
    s = s.rstrip(";").strip()

    return s


def validate_sql(sql: str) -> tuple[bool, str]:
    sql = normalize_sql(sql)
    if not sql:
        return False, "Empty SQL"

    s = sql.strip()
    s_low = s.lower()

    # Disallow CTEs for stability
    if s_low.startswith("with "):
        return False, "CTEs are not allowed (please use a direct SELECT)"

    # Must be SELECT only
    if not s_low.startswith("select"):
        return False, "Only SELECT queries are allowed"

    if ";" in s or "--" in s or "/*" in s or "*/" in s:
        return False, "No semicolons or comments allowed"

    banned_words = [
        "insert","update","delete","merge","drop","alter","create","grant","revoke",
        "call","execute","show","use","information_schema"
    ]

    for w in banned_words:
        if re.search(rf"\b{re.escape(w)}\b", s_low):
            return False, f"Disallowed SQL keyword: {w}"

    referenced = set(re.findall(r"APP_DB\.APP_SCHEMA\.V_[A-Z0-9_]+", s, flags=re.I))
    if not referenced:
        return False, "Query must use approved views"

    for r in referenced:
        if r.upper() not in _ALLOWED_UPPER:
            return False, f"Unapproved view referenced: {r}"

    return True, "ok"

# ---------------------------
# QuerySpec compiler
# ---------------------------

ALLOWED_SCHEMA = {
  "APP_DB.APP_SCHEMA.V_RENT_BURDEN_AVG_COUNTY_NAMED": ["state_abbrev","county_name","renter_total_computed","avg_rent_pct"],
  "APP_DB.APP_SCHEMA.V_RENT_BURDEN_COUNTY_NAMED": ["state_abbrev","county_name","renter_total_computed","renter_over_30","pct_rent_over_30"],
  "APP_DB.APP_SCHEMA.V_COMMUTE_STATE_NAMED": ["state_abbrev","total_workers","avg_commute_minutes"],
  "APP_DB.APP_SCHEMA.V_MIGRATION_COUNTY_NAMED": ["state_abbrev","county_name","total_population","migrants","migration_rate"],
  "APP_DB.APP_SCHEMA.V_MIGRATION_STATE_NAMED": ["state_abbrev","total_population","migrants","migration_rate"],
  "APP_DB.APP_SCHEMA.V_LANGUAGE_COUNTY_NAMED": ["state_abbrev","county_name","total_population","non_english_population","non_english_rate"],
  "APP_DB.APP_SCHEMA.V_LANGUAGE_STATE_NAMED": ["state_abbrev","total_population","non_english_population","non_english_rate"]
}

ALLOWED_JOIN_PAIRS = {
  ("APP_DB.APP_SCHEMA.V_RENT_BURDEN_COUNTY_NAMED", "APP_DB.APP_SCHEMA.V_MIGRATION_COUNTY_NAMED"),
  ("APP_DB.APP_SCHEMA.V_MIGRATION_COUNTY_NAMED", "APP_DB.APP_SCHEMA.V_RENT_BURDEN_COUNTY_NAMED"),

  ("APP_DB.APP_SCHEMA.V_RENT_BURDEN_COUNTY_NAMED", "APP_DB.APP_SCHEMA.V_LANGUAGE_COUNTY_NAMED"),
  ("APP_DB.APP_SCHEMA.V_LANGUAGE_COUNTY_NAMED", "APP_DB.APP_SCHEMA.V_RENT_BURDEN_COUNTY_NAMED"),

  ("APP_DB.APP_SCHEMA.V_MIGRATION_COUNTY_NAMED", "APP_DB.APP_SCHEMA.V_LANGUAGE_COUNTY_NAMED"),
  ("APP_DB.APP_SCHEMA.V_LANGUAGE_COUNTY_NAMED", "APP_DB.APP_SCHEMA.V_MIGRATION_COUNTY_NAMED"),
}

def coerce_number(v):
    if isinstance(v, str):
        vv = v.strip()
        # "0.7" or "10000"
        if re.fullmatch(r"-?\d+(\.\d+)?", vv):
            return float(vv) if "." in vv else int(vv)
    return v

def compile_joinspec(j: dict) -> str:
    if not isinstance(j, dict):
        raise ValueError("join_query must be an object")

    left_view = j.get("left_view")
    right_view = j.get("right_view")

    if not left_view or not right_view:
        raise ValueError("left_view and right_view are required")

    # normalize short names if needed
    left_view = VIEW_ALIASES.get(left_view.upper(), left_view)
    right_view = VIEW_ALIASES.get(right_view.upper(), right_view)

    if (left_view, right_view) not in ALLOWED_JOIN_PAIRS:
        raise ValueError("Unapproved join pair")

    left_cols = set(ALLOWED_SCHEMA[left_view])
    right_cols = set(ALLOWED_SCHEMA[right_view])

    join_on = j.get("join_on") or []
    if join_on != ["state_abbrev", "county_name"]:
        raise ValueError("join_on must be ['state_abbrev','county_name']")

    # SELECT
    select_items = j.get("select") or []
    if not isinstance(select_items, list) or not select_items:
        raise ValueError("select must be a non-empty list")

    select_sql = []
    for it in select_items:
        side = it.get("view")
        col = it.get("col")
        if side not in ("left", "right"):
            raise ValueError("select.view must be left or right")
        if side == "left":
            if col not in left_cols: raise ValueError(f"Bad left col: {col}")
            select_sql.append(f"l.{col} AS l_{col}")
        else:
            if col not in right_cols: raise ValueError(f"Bad right col: {col}")
            select_sql.append(f"r.{col} AS r_{col}")

    # FILTERS
    def fmt_val(v):
        if isinstance(v, bool):
            return "TRUE" if v else "FALSE"
        if isinstance(v, (int, float)):
            return str(v)
        if isinstance(v, list):
            return "(" + ",".join(fmt_val(x) for x in v) + ")"
        s = str(v).replace("'", "''")
        return f"'{s}'"

    allowed_ops = {"=","!=","<",">","<=",">=","LIKE","IN"}
    where = []
    for f in (j.get("filters") or []):
        side = f.get("view")
        col = f.get("col")
        op = f.get("op")
        val = f.get("val")
        OP_ALIAS = {
        "GT": ">",
        "GTE": ">=",
        "LT": "<",
        "LTE": "<=",
        "EQ": "=",
        "NE": "!=",
        }

        val = coerce_number(val)

        if isinstance(op, str):
            op = op.strip().upper()
            op = OP_ALIAS.get(op, op)  # map aliases
        if op not in allowed_ops:
            raise ValueError(f"Bad op: {op}")
        if side == "left":
            if col not in left_cols: raise ValueError(f"Bad left filter col: {col}")
            prefix = "l"
        elif side == "right":
            if col not in right_cols: raise ValueError(f"Bad right filter col: {col}")
            prefix = "r"
        else:
            raise ValueError("filter.view must be left or right")
        if op == "IN" and not isinstance(val, list):
            raise ValueError("IN requires list")
        where.append(f"{prefix}.{col} {op} {fmt_val(val)}")

    where_clause = (" WHERE " + " AND ".join(where)) if where else ""

    # ORDER BY
    order_by = j.get("order_by") or []
    order_clause = ""
    if order_by:
        parts = []
        for o in order_by:
            side = o.get("view")
            col = o.get("col")
            direction = (o.get("dir") or "DESC").upper()
            if direction not in ("ASC","DESC"):
                raise ValueError("Bad order dir")
            if side == "left":
                if col not in left_cols: raise ValueError(f"Bad left order col: {col}")
                parts.append(f"l.{col} {direction}")
            elif side == "right":
                if col not in right_cols: raise ValueError(f"Bad right order col: {col}")
                parts.append(f"r.{col} {direction}")
            else:
                raise ValueError("order_by.view must be left or right")
        order_clause = " ORDER BY " + ", ".join(parts)

    limit = j.get("limit", 10)
    try:
        limit = int(limit)
    except Exception:
        limit = 10
    limit = max(1, min(limit, 50))

    sql = (
        f"SELECT {', '.join(select_sql)} "
        f"FROM {left_view} l "
        f"JOIN {right_view} r "
        f"ON l.state_abbrev = r.state_abbrev AND l.county_name = r.county_name"
        f"{where_clause}"
        f"{order_clause}"
        f" LIMIT {limit}"
    )
    return sql


VIEW_ALIASES = {
  "V_RENT_BURDEN_AVG_COUNTY_NAMED": "APP_DB.APP_SCHEMA.V_RENT_BURDEN_AVG_COUNTY_NAMED",
  "V_RENT_BURDEN_COUNTY_NAMED": "APP_DB.APP_SCHEMA.V_RENT_BURDEN_COUNTY_NAMED",
  "V_COMMUTE_STATE_NAMED": "APP_DB.APP_SCHEMA.V_COMMUTE_STATE_NAMED",
  "V_MIGRATION_COUNTY_NAMED": "APP_DB.APP_SCHEMA.V_MIGRATION_COUNTY_NAMED",
  "V_MIGRATION_STATE_NAMED": "APP_DB.APP_SCHEMA.V_MIGRATION_STATE_NAMED",
  "V_LANGUAGE_COUNTY_NAMED": "APP_DB.APP_SCHEMA.V_LANGUAGE_COUNTY_NAMED",
  "V_LANGUAGE_STATE_NAMED": "APP_DB.APP_SCHEMA.V_LANGUAGE_STATE_NAMED",
}
def compile_queryspec(q: dict) -> str:
    if not isinstance(q, dict):
        raise ValueError("query must be an object")

    view = q.get("view")
    if not view:
        raise ValueError("view is required")

    # normalize short view name -> fully qualified
    view_norm = VIEW_ALIASES.get(view.upper(), view)
    q["view"] = view_norm  # overwrite so later logic uses full name
    view = view_norm

    if "," in view:
        raise ValueError("Joins not enabled: query.view must be a single view (no commas)")

    view = q.get("view")
    if view not in ALLOWED_SCHEMA:
        raise ValueError(f"Unapproved view: {view}")

    allowed_cols = set(c.lower() for c in ALLOWED_SCHEMA[view])

    select_cols = q.get("select") or []
    if not isinstance(select_cols, list) or not select_cols:
        raise ValueError("select must be a non-empty list")
    for c in select_cols:
        if c.lower() not in allowed_cols:
            raise ValueError(f"Unapproved column in select: {c}")

    def fmt_val(v):
        if isinstance(v, bool):
            return "TRUE" if v else "FALSE"
        if isinstance(v, (int, float)):
            return str(v)
        if isinstance(v, list):
            return "(" + ",".join(fmt_val(x) for x in v) + ")"
        s = str(v).replace("'", "''")
        return f"'{s}'"

    allowed_ops = {"=","!=","<",">","<=",">=","LIKE","IN"}

    filters = q.get("filters") or []
    if not isinstance(filters, list):
        raise ValueError("filters must be a list")

    where_clauses = []
    for f in filters:
        if not isinstance(f, dict):
            raise ValueError("each filter must be an object")
        col, op, val = f.get("col"), f.get("op"), f.get("val")
        if col not in allowed_cols:
            raise ValueError(f"Unapproved filter col: {col}")
        op = f.get("op")
        OP_ALIAS = {
        "GT": ">",
        "GTE": ">=",
        "LT": "<",
        "LTE": "<=",
        "EQ": "=",
        "NE": "!=",
        }

        val = coerce_number(val)

        if isinstance(op, str):
            op = op.strip().upper()
            op = OP_ALIAS.get(op, op)
        if op not in allowed_ops:
            raise ValueError(f"Unapproved op: {op}")
        if op == "IN" and not isinstance(val, list):
            raise ValueError("IN requires list value")
        where_clauses.append(f"{col} {op} {fmt_val(val)}")

    order_by = q.get("order_by") or []
    if not isinstance(order_by, list):
        raise ValueError("order_by must be a list")
    
    # auto-order: if filtering on avg_rent_pct or pct_rent_over_30 and ordering ASC, flip to DESC
    metric_cols = {"avg_rent_pct", "pct_rent_over_30", "migration_rate", "migrants", "non_english_rate", "non_english_population", "avg_commute_minutes"}
    if order_by:
        for o in order_by:
            if o.get("col") in metric_cols and (o.get("dir") or "").upper() == "ASC":
                o["dir"] = "DESC"

    order_clause = ""
    if order_by:
        parts = []
        for o in order_by:
            if not isinstance(o, dict):
                raise ValueError("each order_by item must be an object")
            col = o.get("col")
                # If avg_rent_pct and val looks like fraction (<=1), convert to percent
            if col == "avg_rent_pct" and isinstance(val, (int, float)) and val <= 1:
                val = val * 100
            direction = (o.get("dir") or "DESC").upper()
            if col not in allowed_cols:
                raise ValueError(f"Unapproved order col: {col}")
            if direction not in ("ASC","DESC"):
                raise ValueError("Bad order dir")
            parts.append(f"{col} {direction}")
        order_clause = " ORDER BY " + ", ".join(parts)

    limit = q.get("limit", 10)
    try:
        limit = int(limit)
    except Exception:
        limit = 10
    limit = max(1, min(limit, 50))

    where_clause = (" WHERE " + " AND ".join(where_clauses)) if where_clauses else ""
    return f"SELECT {', '.join(select_cols)} FROM {view}{where_clause}{order_clause} LIMIT {limit}"


# ---------------------------
# Planner (Cortex)
# ---------------------------

PROMPT_TEMPLATE = """
You are "Census Agent", a structured query planner.

You MUST return valid JSON only.
Do NOT generate SQL.

Allowed modes:
["chat","clarify","sql","join_sql","refuse"]

Hard Rules:
- UNITED STATES (and territories like PR) ONLY.
- No general knowledge.
- If not answerable from schema, mode="refuse".
- If greeting/small talk, mode="chat".
- If unavailable geography level (e.g. cities), mode="clarify".
- Do NOT ask the user to confirm view names or columns.
- limit max 50.
- Use join_sql ONLY if the question contains constraints from TWO different topics/views.
- If only one topic is mentioned, ALWAYS use sql.

JOIN TRIGGER (MUST FOLLOW):
For example : If the question includes BOTH a rent metric (avg_rent_pct OR pct_rent_over_30 OR renter_over_30) AND a migration metric (migrants OR migration_rate),
you MUST set mode="join_sql" and fill join_query.
Do NOT output mode="sql" for such questions.

For the join example "ranked by migrants", migrants comes from V_MIGRATION_COUNTY_NAMED (right_view).
pct_rent_over_30 comes from V_RENT_BURDEN_COUNTY_NAMED (left_view).


If the question requires data from ONE view → mode="sql".
If the question requires data from TWO views → mode="join_sql".

RETURN FORMAT (MUST MATCH EXACTLY)
(Use these keys exactly.)

{{
  "mode": "chat|clarify|sql|join_sql|refuse",
  "message": "string",
  "query": {{
      "view": "string",
      "select": ["string"],
      "filters": [
          {{"col": "string", "op": "string", "val": "any"}}
      ],
      "order_by": [
          {{"col": "string", "dir": "ASC|DESC"}}
      ],
      "limit": 10
  }} | null,
  "join_query": {{
      "left_view": "string",
      "right_view": "string",
      "join_on": ["state_abbrev","county_name"],
      "select": [
          {{"view":"left|right","col":"string"}}
      ],
      "filters": [
          {{"view":"left|right","col":"string","op":"string","val":"any"}}
      ],
      "order_by": [
          {{"view":"left|right","col":"string","dir":"ASC|DESC"}}
      ],
      "limit": 10
  }} | null
}}

If mode != "sql", query must be null.
If mode != "join_sql", join_query must be null.

AVAILABLE VIEWS
{schema_context}

UNITS
avg_rent_pct → percent (0-100)
pct_rent_over_30 → fraction (0-1)

DEFAULTS
Migration county: state_abbrev, county_name, migrants, migration_rate
Migration state: state_abbrev, migrants, migration_rate
Rent average: state_abbrev, county_name, avg_rent_pct
Commute: state_abbrev, avg_commute_minutes
Language: state_abbrev, non_english_population, non_english_rate

If the phrase "on average" appears, you MUST use V_RENT_BURDEN_AVG_COUNTY_NAMED and avg_rent_pct (0-100).
Never use pct_rent_over_30 for "on average".

If filtering for "over X" and returning "top areas", order DESC.

Previous result context:
{context}

Conversation so far:
{chat_history}

User question:
{question}
"""
def agent_plan(question: str, chat_history: list, context: str) -> dict:
    prompt = PROMPT_TEMPLATE.format(
        schema_context=SCHEMA_CONTEXT,
        context=context,
        chat_history=chat_history,
        question=question
    )
    return cortex_complete_json("mistral-large", prompt)


# ---------------------------
# UI
# ---------------------------
st.title("🧠 US Census Chat Agent")

PRESET_QUESTIONS = [
    "In which areas of the country do residents spend, on average, over 30% of their income on rent?",
    "Which states have the longest average commutes?",
    "Which counties have the highest amount of migration (people moving in)? (county level)",
    "What are the top states with non-English speaking populations?",
    "Show the top 15 counties where percent rent over 30 is greater than 0.60 and migration rate is greater than 0.14 ranked by migrants?"
]

show_sql = st.toggle("Show SQL (last)", value=False, key="show_sql_toggle")
if show_sql and "last_sql" in st.session_state:
    st.code(st.session_state["last_sql"], language="sql")

if "messages" not in st.session_state:
    st.session_state.messages = []

# Render history
for msg in st.session_state.messages:
    with st.chat_message(msg["role"]):
        content = msg["content"]
        if isinstance(content, list):
            if msg.get("narrative"):
                st.write(msg["narrative"])
            st.dataframe(content)
        else:
            st.write(content)

with st.sidebar:
    debug = st.toggle("Debug (show planner + SQL)", value=False)
    st.header("Quick Questions")

    for i, q in enumerate(PRESET_QUESTIONS):
        if st.button(q, key=f"preset_{i}"):
            st.session_state["chat_box"] = q
            st.rerun()

    st.markdown("---")
    st.caption("Click a question to prefill it.")


user_input = st.chat_input(
    "Ask about rent burden, commute times, migration, or language...",
    key="chat_box"
)

GENERIC_FOLLOWUPS = [
    "so what's the answer", "so whats the answer", "what's the answer",
    "whats the answer", "so the answer", "answer?", "so which one", "which one"
]

if user_input and any(p in user_input.lower() for p in GENERIC_FOLLOWUPS):
    last_ans = st.session_state.get("last_answer")
    if last_ans:
        st.session_state.messages.append({"role": "assistant", "content": last_ans})
        with st.chat_message("assistant"):
            st.write(last_ans)
        st.stop()

# if is_off_topic(user_input):
#     assistant_text = "I can only answer using the US Census views in this app (rent burden, commute, migration, language)."
#     st.session_state.messages.append({"role":"assistant","content":assistant_text})
#     with st.chat_message("assistant"): st.write(assistant_text)
#     st.stop()


if user_input:
    st.session_state.messages.append({"role": "user", "content": user_input})
    with st.chat_message("user"):
        st.write(user_input)

    # quick local safety (cheap)
    if is_nsfw(user_input):
        assistant_text = "I can’t help with NSFW content. Ask me about US census topics like rent burden, commutes, migration, or language."
        st.session_state.messages.append({"role": "assistant", "content": assistant_text})
        with st.chat_message("assistant"):
            st.write(assistant_text)
        st.stop()

    # Build compact history for planner
    history = []
    for m in st.session_state.messages[-10:]:
        role = m["role"]
        content = m["content"]
        if isinstance(content, list):
            content = "TABLE_RESULT"
        history.append({"role": role, "content": str(content)})

    # Attach last table context for follow-ups
    last_table = None
    for m in reversed(st.session_state.messages):
        if isinstance(m["content"], list):
            last_table = m["content"][:5]
            break
    context = f"Last shown table (top rows): {last_table}" if last_table else "No prior table."

    # Plan
    try:
        plan = agent_plan(user_input, history, context)
    except Exception as e:
        assistant_text = f"Planner error: {e}"
        st.session_state.messages.append({"role": "assistant", "content": assistant_text})
        with st.chat_message("assistant"):
            st.write(assistant_text)
        st.stop()

    if debug:
        st.write("Planner output (plan):")
        st.json(plan)

    mode = (plan.get("mode") or "refuse").lower()
    if mode == "query":
        mode = "sql"
    msg = (plan.get("message") or "").strip()

    if mode == "chat":
        assistant_text = msg or "Hi — I’m Census Agent. Ask me about rent burden, commutes, migration, or language demographics."
        st.session_state.messages.append({"role": "assistant", "content": assistant_text})
        with st.chat_message("assistant"):
            st.write(assistant_text)

    elif mode == "refuse":
        assistant_text = msg or "I can only help with US census population questions (rent burden, commutes, migration, language)."
        st.session_state.messages.append({"role": "assistant", "content": assistant_text})
        with st.chat_message("assistant"):
            st.write(assistant_text)

    elif mode == "clarify":
        assistant_text = msg or "Can you clarify what you want to know?"
        st.session_state.messages.append({"role": "assistant", "content": assistant_text})
        with st.chat_message("assistant"):
            st.write(assistant_text)

    elif mode == "join_sql":
        joinspec = plan.get("join_query")
        k = extract_ordinal_k(user_input)
        if k and isinstance(joinspec, dict):
            joinspec["limit"] = max(int(joinspec.get("limit", 10)), k)
        sql = compile_joinspec(joinspec)
        # validate_sql(sql) then run_query(sql) same as normal
        ok, reason = validate_sql(sql)
        if not ok:
            if debug:
                st.write("Validator reason:", reason)
            assistant_text = f"I couldn't run that query safely ({reason})."
            st.session_state.messages.append({"role": "assistant", "content": assistant_text})
            with st.chat_message("assistant"):
                st.write(assistant_text)
        else:
            try:
                results = run_query(sql)
                st.session_state["last_question"] = user_input
                st.session_state["last_results"] = results

                final_answer = derive_final_answer(user_input, results)
                st.session_state["last_answer"] = final_answer

                narrative = msg or "Here are the results:"
                if not results:
                    narrative = (msg or "No results found.") + " (No rows matched the filter in this dataset.)"
                st.session_state.messages.append({"role": "assistant", "content": results, "narrative": narrative})

                with st.chat_message("assistant"):
                    st.write(narrative)
                    if final_answer:
                        st.write(final_answer)
                    st.dataframe(results)

            except Exception as e:
                assistant_text = f"SQL execution error: {e}"
                st.session_state.messages.append({"role": "assistant", "content": assistant_text})
                with st.chat_message("assistant"):
                    st.write(assistant_text)


    elif mode == "sql":
            
        queryspec = plan.get("query")
        k = extract_ordinal_k(user_input)
        if k and isinstance(queryspec, dict):
            queryspec["limit"] = max(int(queryspec.get("limit", 10)), k)
        try:
            sql = compile_queryspec(queryspec)
        except Exception as e:
            if debug:
                st.write("Compilation error:", str(e))
                st.write("QuerySpec was:")
                st.json(queryspec)
            assistant_text = f"Query compilation error: {e}"
            st.session_state.messages.append({"role": "assistant", "content": assistant_text})
            with st.chat_message("assistant"):
                st.write(assistant_text)
            st.stop()
        
        if debug:
            st.write("Compiled SQL:")
            st.code(sql, language="sql")

        ok, reason = validate_sql(sql)
        if not ok:
            if debug:
                st.write("Validator reason:", reason)
            assistant_text = f"I couldn't run that query safely ({reason})."
            st.session_state.messages.append({"role": "assistant", "content": assistant_text})
            with st.chat_message("assistant"):
                st.write(assistant_text)
        else:
            try:
                results = run_query(sql)
                st.session_state["last_question"] = user_input
                st.session_state["last_results"] = results

                final_answer = derive_final_answer(user_input, results)
                st.session_state["last_answer"] = final_answer
                if not results:
                    narrative = (msg or "No results found.") + " (No rows matched the filter in this dataset.)"

                st.session_state["last_sql"] = sql

                narrative = msg or "Here are the results:"
                st.session_state.messages.append({"role": "assistant", "content": results, "narrative": narrative})

                with st.chat_message("assistant"):
                    st.write(narrative)
                    if final_answer:
                        st.write(final_answer)
                    st.dataframe(results)


            except Exception as e:
                assistant_text = f"SQL execution error: {e}"
                st.session_state.messages.append({"role": "assistant", "content": assistant_text})
                with st.chat_message("assistant"):
                    st.write(assistant_text)


    else:
        assistant_text = "I can only help with US census population questions (rent burden, commutes, migration, language)."
        st.session_state.messages.append({"role": "assistant", "content": assistant_text})
        with st.chat_message("assistant"):
            st.write(assistant_text)
