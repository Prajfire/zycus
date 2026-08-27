"""
Unit tests for the parts of the pipeline that don't require a live API key:
KB chunking/retrieval, routing table logic, and account risk-signal detection.
The eval harness (eval/eval_harness.py) covers the LLM-dependent behaviour,
either live or via --mock.

Run with: pytest tests/ -v
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from kb_retrieval import get_index, _split_on_headings_and_rules
from triage import ROUTING_TABLE, VALID_CATEGORIES, VALID_URGENCY
from account_brief import _detect_risk_signals, _extract_quote


def test_kb_index_loads_all_docs():
    idx = get_index()
    doc_paths = {c.doc_path.replace("\\", "/") for c in idx.chunks}
    assert "products/databridge-pro.md" in doc_paths
    assert "troubleshooting/performance-and-integrations.md" in doc_paths
    assert len(idx.chunks) > 20


def test_kb_retrieval_finds_relevant_error_code():
    idx = get_index()
    hits = idx.retrieve("RATE_LIMIT_EXCEEDED retry after 60s", top_k=1)
    assert hits
    chunk, score = hits[0]
    assert score > 0
    assert "RATE_LIMIT_EXCEEDED" in chunk.text or "rate" in chunk.text.lower()


def test_kb_retrieval_empty_query_returns_nothing():
    idx = get_index()
    assert idx.retrieve("") == []


def test_heading_split_preserves_hierarchy():
    md = "# Top\n\nintro text\n\n## Sub\n\nsub text that is long enough to survive the min-length filter\n\n---\n\n## Sub2\n\nmore text that is long enough to survive the min-length filter too"
    chunks = _split_on_headings_and_rules(md)
    trails = [c[0] for c in chunks]
    assert "Top" in trails
    assert "Top > Sub" in trails
    assert "Top > Sub2" in trails


def test_routing_table_covers_all_categories():
    for cat in VALID_CATEGORIES:
        assert cat in ROUTING_TABLE, f"{cat} has no routing rule"


def test_risk_signals_flag_declining_usage():
    account = {
        "health_status": "At Risk", "usage_trend": "Declining",
        "seats_licensed": 100, "seats_active": 90,
        "p1_tickets_last_30d": 0, "nps_score": 8, "last_login_days_ago": 3,
        "escalation_notes": [],
    }
    risks, flags = _detect_risk_signals(account, [])
    assert any("At Risk" in r for r in risks)
    assert any("Declining" in r for r in risks)


def test_risk_signals_flag_low_seat_utilization():
    account = {
        "health_status": "Healthy", "usage_trend": "Stable",
        "seats_licensed": 100, "seats_active": 20,
        "p1_tickets_last_30d": 0, "nps_score": 9, "last_login_days_ago": 1,
        "escalation_notes": [],
    }
    risks, flags = _detect_risk_signals(account, [])
    assert any("seats are active" in r for r in risks)


def test_risk_signals_healthy_account_has_no_forced_risks():
    account = {
        "health_status": "Healthy", "usage_trend": "Increasing",
        "seats_licensed": 100, "seats_active": 95,
        "p1_tickets_last_30d": 0, "nps_score": 9, "last_login_days_ago": 1,
        "escalation_notes": [],
    }
    risks, flags = _detect_risk_signals(account, [])
    assert risks == []
    assert flags == []


def test_ticket_flagged_for_churn_keyword_has_verifiable_quote():
    account = {
        "health_status": "Healthy", "usage_trend": "Stable",
        "seats_licensed": 10, "seats_active": 9,
        "p1_tickets_last_30d": 0, "nps_score": 8, "last_login_days_ago": 1,
        "escalation_notes": [],
    }
    ticket = {
        "ticket_id": "TKT-99999",
        "subject": "Considering switching",
        "body": "We are currently evaluating a competing vendor because of repeated outages.",
        "urgency": "P3", "satisfaction_score": None,
    }
    risks, flags = _detect_risk_signals(account, [ticket])
    assert len(flags) == 1
    quote = flags[0].quote
    full_text = f"{ticket['subject']}. {ticket['body']}".lower()
    assert quote.lower() in full_text


def test_extract_quote_never_exceeds_max_len():
    long_text = "This is a churn risk sentence about a competing vendor. " * 5
    quote = _extract_quote(long_text, max_len=50)
    assert len(quote) <= 50
