"""
app.py — bonus Streamlit demo. A TAM or support agent shouldn't need to touch
JSON or curl to use this thing.

Run with: streamlit run app.py
"""

import json
import sys
from pathlib import Path

import streamlit as st

sys.path.insert(0, str(Path(__file__).resolve().parent / "src"))

from account_brief import AccountNotFoundError, build_account_brief
from triage import triage_ticket

st.set_page_config(page_title="Support & TAM Tooling", layout="wide")
st.title("Support & TAM Tooling — Demo")

tab1, tab2 = st.tabs(["Ticket Triage", "Account Brief"])

with tab1:
    st.subheader("Triage an incoming ticket")
    with st.form("triage_form"):
        subject = st.text_input("Subject", "Production pipeline timing out")
        body = st.text_area(
            "Body", height=150,
            value="Our DataBridge Pro ingestion pipeline has been failing since this morning with "
                  "ERR_CONNECTION_TIMEOUT after 30s. About 40 users on our Engineering team are affected. "
                  "No workaround found yet.",
        )
        submitted = st.form_submit_button("Triage ticket")

    if submitted:
        with st.spinner("Classifying, retrieving KB context, drafting response..."):
            try:
                result = triage_ticket({"subject": subject, "body": body}).to_dict()
            except Exception as e:
                st.error(f"Something went wrong: {e}")
                result = None

        if result:
            col1, col2, col3 = st.columns(3)
            col1.metric("Category", result["category"])
            col2.metric("Urgency", result["urgency"])
            col3.metric("Routed to", result["responder_team"])

            st.markdown("**Reasoning**")
            st.write(result["reasoning"])

            if result["kb_match"]:
                st.markdown("**Matched knowledge-base article**")
                st.info(f"{result['kb_match']['doc']} — {result['kb_match']['section']} "
                        f"(relevance {result['kb_match']['relevance_score']})")
            else:
                st.warning("No confident knowledge-base match found for this ticket.")

            st.markdown("**Draft first response**")
            st.text_area("draft", result["draft_response"], height=150, label_visibility="collapsed")

            if result["warnings"]:
                for w in result["warnings"]:
                    st.warning(w)

            with st.expander("Raw JSON output"):
                st.json(result)

with tab2:
    st.subheader("Generate a QBR account brief")
    accounts_path = Path(__file__).resolve().parent / "data" / "accounts.json"
    accounts = json.loads(accounts_path.read_text())
    options = {f"{a['company']} ({a['account_id']})": a["account_id"] for a in accounts}
    choice = st.selectbox("Account", list(options.keys()))

    if st.button("Generate brief"):
        account_id = options[choice]
        with st.spinner("Pulling account data, detecting risk signals, drafting brief..."):
            try:
                brief = build_account_brief(account_id).to_dict()
            except AccountNotFoundError as e:
                st.error(str(e))
                brief = None

        if brief:
            st.markdown(f"## {brief['company']}")
            st.markdown("**Executive summary**")
            st.write(brief["executive_summary"])

            st.markdown("**Open risks**")
            for r in brief["open_risks"]:
                st.markdown(f"- {r}")

            if brief["flagged_tickets"]:
                st.markdown("**Flagged tickets**")
                for f in brief["flagged_tickets"]:
                    st.markdown(f"- `{f['ticket_id']}` — {f['reason']}: *\"{f['quote']}\"*")

            st.markdown("**Talking points for the QBR**")
            for tp in brief["talking_points"]:
                st.markdown(f"- {tp}")

            if brief["data_gaps"]:
                st.caption("Data gaps: " + "; ".join(brief["data_gaps"]))

            with st.expander("Raw JSON output"):
                st.json(brief)
