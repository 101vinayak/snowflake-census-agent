import os
import requests
import streamlit as st

API_URL = os.getenv("API_URL", "http://127.0.0.1:8000")

st.set_page_config(page_title="US Census Chat Agent", page_icon="🗺️", layout="centered")

st.title("🗺️ US Census Chat Agent")
st.caption("Ask about rent burden (≥30%), commute time, migration, or non-English speaking populations.")

with st.sidebar:
    st.header("Settings")
    api_url = st.text_input("Backend API URL", API_URL)
    st.markdown("---")
    st.write("Example questions:")
    st.code("In which areas do renters spend over 30% of income on rent?")
    st.code("Which states have the longest average commutes?")
    st.code("Which counties have the highest migration (moving in)?")
    st.code("What are the top counties with non-English speaking populations?")

if "messages" not in st.session_state:
    st.session_state.messages = []

# chat history
for m in st.session_state.messages:
    with st.chat_message(m["role"]):
        st.markdown(m["content"])
        if m.get("rows"):
            st.dataframe(m["rows"], use_container_width=True)

q = st.chat_input("Type your question…")
if q:
    st.session_state.messages.append({"role": "user", "content": q})

    with st.chat_message("user"):
        st.markdown(q)

    with st.chat_message("assistant"):
        with st.spinner("Querying Census data in Snowflake…"):
            try:
                resp = requests.post(
                    f"{api_url}/chat",
                    json={"question": q},
                    timeout=30,
                )
                resp.raise_for_status()
                data = resp.json()

                st.markdown(data.get("message", ""))
                rows = data.get("rows", [])
                if rows:
                    st.dataframe(rows, use_container_width=True)

                st.session_state.messages.append({
                    "role": "assistant",
                    "content": data.get("message", ""),
                    "rows": rows
                })

            except Exception as e:
                st.error(f"Request failed: {e}")
                st.session_state.messages.append({
                    "role": "assistant",
                    "content": f"Request failed: {e}",
                    "rows": []
                })

