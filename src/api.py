"""
api.py — lightweight FastAPI wrapper around triage_ticket() and build_account_brief().

Run with: uvicorn api:app --reload --app-dir src
"""

from __future__ import annotations

from typing import Optional

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel

from account_brief import AccountNotFoundError, build_account_brief
from triage import triage_ticket

app = FastAPI(title="Support & TAM Tooling API", version="0.1.0")


class TriageRequest(BaseModel):
    ticket_id: Optional[str] = None
    subject: str = ""
    body: str = ""


@app.post("/triage")
def triage_endpoint(req: TriageRequest):
    ticket = {"ticket_id": req.ticket_id, "subject": req.subject, "body": req.body}
    result = triage_ticket(ticket)
    return result.to_dict()


@app.get("/account-brief/{account_id}")
def account_brief_endpoint(account_id: str):
    try:
        brief = build_account_brief(account_id)
    except AccountNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))
    return brief.to_dict()


@app.get("/health")
def health():
    return {"status": "ok"}
