"""
account_brief.py — Task 2: TAM account health summariser.

Design choice worth flagging: churn/escalation flagging is done in two passes,
not one giant "summarize everything" prompt.

  Pass 1 (rule-based, deterministic, free): scan escalation_notes and recent
  ticket subjects/bodies for hard signals — P1 count, declining usage, low
  seat utilization, explicit competitor-evaluation language, negative CSAT.
  This is a keyword/threshold pass, not an LLM call, so it's exactly
  reproducible and doesn't hallucinate a quote that isn't there.

  Pass 2 (LLM, grounded): the LLM only writes prose *on top of* the flags
  pass 1 already found — it turns "3 tickets with category=Bug and urgency=P2
  in the last 90 days" into readable talking points. It is not asked to
  invent which tickets are risky; it's asked to explain risks it's handed.

This split is also why determinism is achievable: the risk *detection* never
touches the model, so re-running the same account_id always flags the same
tickets. Only the phrasing pass goes through the LLM, at temperature=0 with
response caching (see llm_client.py) so repeated runs return byte-identical
prose too.
"""

from __future__ import annotations

import json
import re
from dataclasses import asdict, dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path

from llm_client import call_llm_json

DATA_DIR = Path(__file__).resolve().parent.parent / "data"

CHURN_KEYWORDS = [
    "competing vendor", "competitor", "considering leaving", "evaluating alternatives",
    "cancel", "cancellation", "no replacement", "champion left", "budget cut",
    "frustrat", "unacceptable", "escalat", "downgrad",
]


class AccountNotFoundError(Exception):
    pass


@dataclass
class TicketFlag:
    ticket_id: str
    reason: str
    quote: str


@dataclass
class AccountBrief:
    account_id: str
    company: str
    executive_summary: str
    open_risks: list[str]
    flagged_tickets: list[TicketFlag]
    talking_points: list[str]
    data_gaps: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        d = asdict(self)
        return d


def _load_json(name: str) -> list[dict]:
    return json.loads((DATA_DIR / name).read_text())


def _recent_tickets(account_id: str, tickets: list[dict], days: int = 90) -> list[dict]:
    cutoff = datetime.now(timezone.utc) - timedelta(days=days)
    out = []
    for t in tickets:
        if t.get("account_id") != account_id:
            continue
        try:
            created = datetime.fromisoformat(t["created_at"].replace("Z", "+00:00"))
        except (KeyError, ValueError):
            continue
        if created > cutoff:
            out.append(t)
    return out


def _extract_quote(text: str, max_len: int = 160) -> str:
    """Grab the sentence most likely to justify a flag, trimmed to a safe length."""
    sentences = re.split(r"(?<=[.!?])\s+", text.strip())
    for kw in CHURN_KEYWORDS:
        for s in sentences:
            if kw in s.lower():
                return s.strip()[:max_len]
    return sentences[0].strip()[:max_len] if sentences else text[:max_len]


def _detect_risk_signals(account: dict, recent_tickets: list[dict]) -> tuple[list[str], list[TicketFlag]]:
    """Deterministic, rule-based. No LLM call here — see module docstring."""
    risks: list[str] = []
    flags: list[TicketFlag] = []

    if account.get("health_status") in ("At Risk", "Churning"):
        risks.append(f"Account health status is '{account['health_status']}'.")
    if account.get("usage_trend") in ("Declining", "Inactive"):
        risks.append(f"Usage trend is '{account['usage_trend']}'.")
    seats_licensed = account.get("seats_licensed") or 0
    seats_active = account.get("seats_active") or 0
    if seats_licensed and seats_active / seats_licensed < 0.6:
        pct = round(100 * seats_active / seats_licensed)
        risks.append(f"Only {pct}% of licensed seats are active ({seats_active}/{seats_licensed}).")
    if (account.get("p1_tickets_last_30d") or 0) >= 2:
        risks.append(f"{account['p1_tickets_last_30d']} P1 tickets in the last 30 days.")
    if account.get("nps_score") is not None and account["nps_score"] <= 6:
        risks.append(f"NPS score of {account['nps_score']} (detractor range).")
    last_login = account.get("last_login_days_ago")
    if last_login is not None and last_login > 30:
        risks.append(f"Primary contact last logged in {last_login} days ago.")

    for note in account.get("escalation_notes", []):
        if any(kw in note.lower() for kw in CHURN_KEYWORDS):
            risks.append(f"Escalation note: {note}")

    for t in recent_tickets:
        body = t.get("body", "") or ""
        subject = t.get("subject", "") or ""
        full_text = f"{subject}. {body}"
        hit_kw = next((kw for kw in CHURN_KEYWORDS if kw in full_text.lower()), None)
        is_p1 = t.get("urgency") == "P1"
        low_csat = (t.get("satisfaction_score") is not None and t["satisfaction_score"] <= 2)
        if hit_kw or is_p1 or low_csat:
            reason = (
                f"contains churn-signal language ('{hit_kw}')" if hit_kw else
                "P1 urgency" if is_p1 else
                f"low CSAT ({t['satisfaction_score']}/5)"
            )
            flags.append(TicketFlag(
                ticket_id=t["ticket_id"],
                reason=reason,
                quote=_extract_quote(full_text),
            ))

    return risks, flags


BRIEF_PROMPT_VERSION = "account-brief-v1"

BRIEF_SYSTEM = """You are helping a Technical Account Manager prepare for a QBR. You will be given \
structured account data, a list of already-identified risk signals, and flagged tickets with quotes. \
Do NOT invent new risks or tickets beyond what's given to you — your job is to turn the structured \
signals into a readable brief, not to discover new ones.

Return a JSON object with exactly these keys:
- "executive_summary": string, 3-5 sentences, plain prose covering account health, revenue context, \
and overall trajectory
- "talking_points": array of 3-6 short strings, each a concrete, specific talking point the TAM \
could raise in the QBR (not generic advice like "improve communication" — tie each to a fact given)

Be direct and factual. If the account looks healthy, say so plainly instead of manufacturing concern."""


def build_account_brief(account_id: str) -> AccountBrief:
    accounts = _load_json("accounts.json")
    tickets = _load_json("tickets.json")

    account = next((a for a in accounts if a["account_id"] == account_id), None)
    if account is None:
        raise AccountNotFoundError(
            f"No account found for account_id={account_id!r}. "
            f"This can happen because not every ticket's account_id has a matching "
            f"accounts.json record (see DATA_SCHEMA.md)."
        )

    recent = _recent_tickets(account_id, tickets)
    risks, flags = _detect_risk_signals(account, recent)

    data_gaps = []
    if not recent:
        data_gaps.append("No tickets found in the last 90 days for this account.")
    if account.get("nps_score") is None:
        data_gaps.append("No NPS score on file.")
    if not account.get("last_qbr_date"):
        data_gaps.append("No previous QBR date on file.")

    account_summary_for_llm = {
        k: v for k, v in account.items() if k != "account_id"
    }
    prompt = json.dumps({
        "account": account_summary_for_llm,
        "recent_ticket_count": len(recent),
        "identified_risks": risks,
        "flagged_tickets": [asdict(f) for f in flags],
        "data_gaps": data_gaps,
    }, indent=2)

    llm_out = call_llm_json(BRIEF_SYSTEM, prompt, max_tokens=800)

    return AccountBrief(
        account_id=account_id,
        company=account.get("company", "Unknown"),
        executive_summary=llm_out.get("executive_summary", ""),
        open_risks=risks if risks else ["No significant risk signals detected in the last 90 days."],
        flagged_tickets=flags,
        talking_points=llm_out.get("talking_points", []),
        data_gaps=data_gaps,
    )


if __name__ == "__main__":
    accounts = _load_json("accounts.json")
    at_risk = next((a for a in accounts if a["health_status"] in ("At Risk", "Churning")), accounts[0])
    brief = build_account_brief(at_risk["account_id"])
    print(json.dumps(brief.to_dict(), indent=2))
