import streamlit as st
import snowflake.connector
import re

st.set_page_config(page_title="US Census Chat Agent", page_icon="🧠")

ALLOWED_TOPICS = [
    "rent", "renter", "commute", "travel time", "migration", "moving",
    "language", "non-english", "english only", "census", "population",
    "county", "state"
]

NSFW_TERMS = [
    "porn", "sex", "nude", "xxx", "onlyfans", "fetish", "blowjob", "anal",
    "rape", "incest", "child porn", "cp"
]

def is_nsfw(q: str) -> bool:
    s = q.lower()
    return any(t in s for t in NSFW_TERMS)

def is_off_topic(q: str) -> bool:
    s = q.lower()
    # If none of the allowed topic keywords appear, treat as off-topic
    return not any(t in s for t in ALLOWED_TOPICS)

def format_answer(question: str, rows: list[dict]):
    q = question.lower()

    if not rows:
        return "No results found."

    # COMMUTE
    if "commute" in q:
        return "Top states by average commute time (minutes):"

    # RENT
    if "rent" in q:
        return "Areas with the highest share of renters spending ≥ threshold of income on rent:"

    # MIGRATION
    if "migration" in q or "moving" in q:
        return "Top areas by number of people who moved in the past year:"

    # LANGUAGE
    if "language" in q or "non-english" in q:
        return "Top areas by share of residents speaking a non-English language at home:"

    return "Here are the results:"

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

def run_query(sql):
    with get_conn() as conn:
        cur = conn.cursor()
        cur.execute(sql)
        rows = cur.fetchall()
        cols = [c[0] for c in cur.description]
    return [dict(zip(cols, r)) for r in rows]


# ---------------------------
# Intent Router (Version A)
# ---------------------------
STATE_MAP = {
    "alabama":"AL","alaska":"AK","arizona":"AZ","arkansas":"AR","california":"CA","colorado":"CO",
    "connecticut":"CT","delaware":"DE","district of columbia":"DC","florida":"FL","georgia":"GA",
    "hawaii":"HI","idaho":"ID","illinois":"IL","indiana":"IN","iowa":"IA","kansas":"KS","kentucky":"KY",
    "louisiana":"LA","maine":"ME","maryland":"MD","massachusetts":"MA","michigan":"MI","minnesota":"MN",
    "mississippi":"MS","missouri":"MO","montana":"MT","nebraska":"NE","nevada":"NV","new hampshire":"NH",
    "new jersey":"NJ","new mexico":"NM","new york":"NY","north carolina":"NC","north dakota":"ND","ohio":"OH",
    "oklahoma":"OK","oregon":"OR","pennsylvania":"PA","rhode island":"RI","south carolina":"SC","south dakota":"SD",
    "tennessee":"TN","texas":"TX","utah":"UT","vermont":"VT","virginia":"VA","washington":"WA",
    "west virginia":"WV","wisconsin":"WI","wyoming":"WY","puerto rico":"PR"
}

def extract_top_n(q: str, default=10):
    m = re.search(r'\btop\s+(\d+)\b', q.lower())
    if m:
        n = int(m.group(1))
        return max(1, min(n, 50))
    return default

def extract_state_abbrev(q: str):
    s = q.lower()

    # direct "in CA"
    m = re.search(r'\bin\s+([a-z]{2})\b', s)
    if m:
        return m.group(1).upper()

    # full name "in california"
    for name, ab in STATE_MAP.items():
        if name in s:
            return ab
    return None

def route_question(question: str):
    q = question.lower()
    top_n = extract_top_n(question, default=10)
    state = extract_state_abbrev(question)

    state_filter = f"WHERE state_abbrev = '{state}'" if state else ""
    and_state_filter = f"AND state_abbrev = '{state}'" if state else ""

    # RENT
    if "rent" in q:
        threshold = 0.30
        match = re.search(r'(\d+)%', q)
        if match:
            threshold = float(match.group(1)) / 100.0

        sql = f"""
        SELECT state_abbrev, county_name, pct_rent_over_30
        FROM APP_DB.APP_SCHEMA.V_RENT_BURDEN_COUNTY_NAMED
        WHERE pct_rent_over_30 >= {threshold}
        {and_state_filter}
        ORDER BY pct_rent_over_30 DESC
        LIMIT {top_n};
        """
        return sql

    # COMMUTE
    if "commute" in q:
        sql = f"""
        SELECT state_abbrev, total_workers, avg_commute_minutes
        FROM APP_DB.APP_SCHEMA.V_COMMUTE_STATE_NAMED
        {state_filter}
        ORDER BY avg_commute_minutes DESC
        LIMIT {top_n};
        """
        return sql

    # MIGRATION
    if "migration" in q or "moving" in q:
        wants_state = ("state" in q) or ("states" in q)

        if wants_state:
            sql = f"""
            SELECT state_abbrev, migrants, migration_rate
            FROM APP_DB.APP_SCHEMA.V_MIGRATION_STATE_NAMED
            ORDER BY migrants DESC
            LIMIT {top_n};
            """
        else:
            sql = f"""
            SELECT state_abbrev, county_name, migrants, migration_rate
            FROM APP_DB.APP_SCHEMA.V_MIGRATION_COUNTY_NAMED
            {state_filter}
            ORDER BY migrants DESC
            LIMIT {top_n};
            """
        return sql

    # LANGUAGE
    if "language" in q or "non-english" in q:
        wants_state = ("state" in q) or ("states" in q)

        if wants_state:
            sql = f"""
            SELECT state_abbrev, non_english_population, non_english_rate
            FROM APP_DB.APP_SCHEMA.V_LANGUAGE_STATE_NAMED
            ORDER BY non_english_rate DESC
            LIMIT {top_n};
            """
        else:
            sql = f"""
            SELECT state_abbrev, county_name, non_english_rate
            FROM APP_DB.APP_SCHEMA.V_LANGUAGE_COUNTY_NAMED
            {state_filter}
            ORDER BY non_english_rate DESC
            LIMIT {top_n};
            """
        return sql

    return None


# ---------------------------
# Streamlit Chat UI
# ---------------------------
st.title("🧠 US Census Chat Agent")

if "messages" not in st.session_state:
    st.session_state.messages = []

for msg in st.session_state.messages:
    with st.chat_message(msg["role"]):
        st.write(msg["content"])

user_input = st.chat_input("Ask a question about US population data...")

if user_input:
    st.session_state.messages.append({"role": "user", "content": user_input})
    with st.chat_message("user"):
        st.write(user_input)

    if "city" in user_input.lower() or "cities" in user_input.lower():
        st.session_state.messages.append({
            "role": "assistant",
            "content": "This dataset is organized by state/county/block-group, not city names. I’ll answer using counties (closest available)."
        })
        with st.chat_message("assistant"):
            st.write("This dataset is organized by state/county/block-group, not city names. I’ll answer using counties (closest available).")

    if is_nsfw(user_input):
        response = "I can’t help with NSFW content. Ask me about US census population topics like rent burden, commutes, migration, or language."
    else:
        sql = route_question(user_input)

        if sql is None or is_off_topic(user_input):
            response = "I can answer questions about US census population data focused on rent burden, commute times, migration, and language demographics."
        else:
            try:
                results = run_query(sql)
                response = results
            except Exception as e:
                response = f"Error: {e}"


    st.session_state.messages.append({"role": "assistant", "content": response})
    with st.chat_message("assistant"):
        if isinstance(response, list):
            st.write(format_answer(user_input, response))
            st.dataframe(response)
        else:
            st.write(response)


