"""
triage.py — Task 1: Intelligent ticket triage agent.

Pipeline:
  raw ticket text/JSON
    -> LLM classification (product area, category, urgency + reasoning)
    -> KB retrieval keyed off the ticket + the model's own error-code guess
    -> routing decision (rule table, not LLM — see README)
    -> LLM draft first-response, grounded in whatever KB chunk we retrieved

Why routing is a rule table and not another LLM call: routing team assignment
is a deterministic business rule ("Billing category -> Billing Ops", "P1 ->
on-call"), not a judgment call. Asking an LLM to reinvent that mapping every
time is slower, costs money, and can drift. Classification and drafting are
genuinely open-ended language tasks, so those stay LLM-driven.
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from pathlib import Path

from kb_retrieval import get_index
from llm_client import call_llm, call_llm_json

VALID_CATEGORIES = [
    "Bug", "Feature Request", "How-To", "Performance",
    "Billing", "Integration", "Onboarding", "Data Loss",
]
VALID_URGENCY = ["P1", "P2", "P3", "P4"]

# Deterministic routing table: category -> responder team.
# Urgency P1 always adds on-call regardless of category.
ROUTING_TABLE = {
    "Bug": "Tier-2 Engineering",
    "Feature Request": "Product Team (backlog triage)",
    "How-To": "Tier-1 Support",
    "Performance": "Tier-2 Engineering (Performance Squad)",
    "Billing": "Billing Ops",
    "Integration": "Tier-2 Engineering (Integrations Squad)",
    "Onboarding": "Customer Success / Onboarding",
    "Data Loss": "Tier-2 Engineering + Incident Response",
}


@dataclass
class TriageResult:
    ticket_id: str | None
    product_area_guess: str
    category: str
    urgency: str
    reasoning: str
    kb_match: dict | None
    responder_team: str
    draft_response: str
    warnings: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return asdict(self)


CLASSIFY_PROMPT_VERSION = "triage-classify-v2"
DRAFT_PROMPT_VERSION = "triage-draft-v1"

CLASSIFY_SYSTEM = """You are a support-ticket triage classifier for a B2B SaaS company \
with five products: DataBridge Pro, CloudSync, AnalyticsHub, SecureVault, WorkflowEngine.

Classify the ticket into:
- "product": best-guess product name from the five above, or "Unknown"
- "product_area_guess": the module/feature area affected, in a few words
- "category": exactly one of Bug, Feature Request, How-To, Performance, Billing, Integration, Onboarding, Data Loss
- "urgency": exactly one of P1, P2, P3, P4, using this rubric:
    P1 = business-stopping, production down, data loss, security breach
    P2 = major functionality broken, significant workaround required, many users affected
    P3 = moderate impact, workaround exists, limited user impact
    P4 = cosmetic, low impact, or a general question/feature request with no urgency
- "error_codes_mentioned": array of any literal error codes/strings quoted in the ticket (empty array if none)
- "reasoning": 2-3 sentences explaining the category and urgency call, referencing specific \
details from the ticket text (user counts, environment, whether it's a workaround-available \
situation, etc.)

Be conservative with P1 — most tickets are not P1. If the ticket is ambiguous, say so explicitly \
in "reasoning" and pick the most defensible single label rather than hedging with multiple labels."""


def _classify(ticket_text: str) -> dict:
    prompt = f"Ticket:\n\n{ticket_text}"
    result = call_llm_json(CLASSIFY_SYSTEM, prompt, max_tokens=600)

    if result.get("category") not in VALID_CATEGORIES:
        result["category"] = "Bug"
        result.setdefault("reasoning", "")
        result["reasoning"] += " [fallback: model returned an out-of-enum category, defaulted to Bug]"
    if result.get("urgency") not in VALID_URGENCY:
        result["urgency"] = "P3"
        result.setdefault("reasoning", "")
        result["reasoning"] += " [fallback: model returned an out-of-enum urgency, defaulted to P3]"
    return result


DRAFT_SYSTEM = """You are drafting the first response a support agent will send to a customer. \
Tone: professional, empathetic, concise. Do not promise specific fix timelines you don't know. \
If a knowledge-base excerpt is provided, ground your suggested next steps in it and reference it \
naturally (don't say "according to document chunk 3"). If no relevant KB excerpt was found, \
acknowledge the issue and say a specialist from the responder team will follow up — don't invent \
a fix. Sign off as "Support Team", 120-180 words."""


def _draft_response(ticket_text: str, classification: dict, kb_excerpt: str | None) -> str:
    context = f"Ticket:\n{ticket_text}\n\nClassified as: {classification['category']} / {classification['urgency']}"
    if kb_excerpt:
        context += f"\n\nRelevant knowledge-base excerpt:\n{kb_excerpt}"
    else:
        context += "\n\nNo matching knowledge-base article was found for this issue."
    return call_llm(DRAFT_SYSTEM, context, max_tokens=400, redact=False)


def triage_ticket(ticket: dict | str) -> TriageResult:
    """
    Accepts either a raw string (subject+body concatenated) or a dict with at
    least subject/body keys (matching tickets.json's shape, minus the labels
    -- this function does not look at ground-truth category/urgency/product
    fields even if they're present, since the whole point is to classify
    without human labelling).
    """
    warnings: list[str] = []

    if isinstance(ticket, str):
        ticket_id = None
        ticket_text = ticket
    else:
        ticket_id = ticket.get("ticket_id")
        subject = ticket.get("subject", "")
        body = ticket.get("body", "")
        if not subject and not body:
            warnings.append("Ticket has no subject or body text; classification will be low-confidence.")
        ticket_text = f"Subject: {subject}\n\n{body}"

    classification = _classify(ticket_text)

    # Retrieval query combines the ticket text with any literal error codes
    # the model spotted, since those are the highest-signal search terms.
    error_codes = classification.get("error_codes_mentioned") or []
    retrieval_query = ticket_text + " " + " ".join(error_codes)
    hits = get_index().retrieve(retrieval_query, top_k=1)
    kb_match = None
    kb_excerpt = None
    if hits:
        chunk, score = hits[0]
        if score >= 0.05:  # below this, treat as "no confident match"
            kb_match = {
                "doc": chunk.doc_path,
                "section": chunk.heading_trail,
                "relevance_score": round(score, 3),
            }
            kb_excerpt = chunk.text
        else:
            warnings.append(f"Best KB match scored below confidence threshold ({score:.3f}); treated as no match.")

    urgency = classification["urgency"]
    category = classification["category"]
    responder_team = ROUTING_TABLE.get(category, "Tier-1 Support")
    if urgency == "P1":
        responder_team = f"On-call Engineer + {responder_team}"

    draft = _draft_response(ticket_text, classification, kb_excerpt)

    return TriageResult(
        ticket_id=ticket_id,
        product_area_guess=classification.get("product_area_guess", classification.get("product", "Unknown")),
        category=category,
        urgency=urgency,
        reasoning=classification.get("reasoning", ""),
        kb_match=kb_match,
        responder_team=responder_team,
        draft_response=draft,
        warnings=warnings,
    )


if __name__ == "__main__":
    sample = json.loads(Path(__file__).resolve().parent.parent.joinpath("data/tickets.json").read_text())[3]
    result = triage_ticket(sample)
    print(json.dumps(result.to_dict(), indent=2))
