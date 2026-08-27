# Support & TAM Tooling — Technical Task Submission

Production-grade(ish) AI tooling for Technical Support and TAM teams, built
against the provided mock dataset (500 tickets, 50 accounts, and the product
knowledge base).

## What's here

| Task | File | What it does |
|---|---|---|
| 1 — Triage agent | `src/triage.py`, `src/api.py` | Classifies a raw ticket, retrieves a matching KB article, routes it, drafts a first response |
| 2 — Account brief | `src/account_brief.py` | Rule-based risk detection + LLM-written QBR brief, quote-justified |
| 3 — Eval harness | `eval/eval_harness.py` | 13 test cases (7 for Task 1, 6 for Task 2), rule-based scoring, JSON + Markdown reports |
| 4 — Design note | this file, below | Failure modes, latency/quality trade-off, data sensitivity, scaling |
| Bonus | `app.py`, `.github/workflows/eval.yml`, `PROMPTS.md` | Streamlit demo UI, CI eval run, prompt versioning changelog |

Shared infrastructure: `src/kb_retrieval.py` (TF-IDF retrieval over the
markdown KB) and `src/llm_client.py` (single choke point for all model calls
— caching, temperature=0, PII scrubbing).

---

## Setup

```bash
git clone <this-repo>
cd <this-repo>
pip install -r requirements.txt
cp .env.example .env   # then paste your real ANTHROPIC_API_KEY into .env
export $(cat .env | xargs)   # or use direnv / your shell's preferred method
```

Requires Python 3.11+.

## Sample run — Task 1 (triage)

```bash
cd src
python triage.py   # runs triage on data/tickets.json[3] and prints the result
```

Or hit the REST endpoint:

```bash
uvicorn api:app --reload --app-dir src
curl -X POST localhost:8000/triage -H "Content-Type: application/json" -d '{
  "subject": "Production pipeline timing out",
  "body": "Our DataBridge Pro ingestion pipeline has been failing since this morning with ERR_CONNECTION_TIMEOUT after 30s. About 40 users affected. No workaround found yet."
}'
```

Representative output shape (field values will vary slightly run to run
since this hits a live model, though category/urgency are stable for a
clear-cut case like the one above):

```json
{
  "ticket_id": null,
  "product_area_guess": "Data Ingestion",
  "category": "Bug",
  "urgency": "P2",
  "reasoning": "Production ingestion pipeline is failing with a timeout error affecting ~40 users; no workaround exists, but a single team is impacted rather than the whole customer base.",
  "kb_match": {
    "doc": "products/databridge-pro.md",
    "section": "DataBridge Pro — Product Reference > Common Support Scenarios > Pipeline stopped processing",
    "relevance_score": 0.151
  },
  "responder_team": "Tier-2 Engineering",
  "draft_response": "Hi there, thanks for flagging this...",
  "warnings": []
}
```

## Sample run — Task 2 (account brief)

```bash
cd src
python account_brief.py   # auto-picks an At Risk/Churning account and prints the brief
```

Or via the API: `GET /account-brief/{account_id}`.

## Running the evals

```bash
python eval/eval_harness.py           # live, hits the real API, needs ANTHROPIC_API_KEY
python eval/eval_harness.py --mock    # offline, canned responses, no key needed — what CI runs
```

Writes `eval/eval_report.json` and `eval/eval_report.md`. The version
checked into this repo was generated with `--mock` (see the top of that file
for the mode used) purely so the report is reviewable without an API key —
re-run without `--mock` for a live grading pass.

## Running unit tests

```bash
PYTHONPATH=src pytest tests/ -v
```

These cover the deterministic pieces (KB chunking/retrieval, routing rules,
risk-signal detection) directly, without needing a live API key.

## Bonus demo UI

```bash
streamlit run app.py
```

---

## Design note

### Failure modes

**1. Misclassification on genuinely ambiguous tickets.** A ticket that reads
as both a bug report and a feature request (see eval case
`t1-07-ADVERSARIAL-mixed-signals`) can get a defensible-but-wrong label.
Mitigation: the classifier prompt was tuned (v1→v2, see `PROMPTS.md`) to
force a single best-guess label plus visible reasoning rather than a hedge,
so a human reviewing the queue can catch and correct it quickly — the
`reasoning` field exists specifically so triage decisions are auditable, not
a black box. In production I'd add a confidence field and route anything
below a threshold to a human-review queue instead of auto-routing it.

**2. KB retrieval returning a plausible-but-wrong article.** TF-IDF over ~10
docs works well for this dataset, but a near-miss (e.g. matching "timeout"
in an unrelated product's doc) is possible. Mitigation: a relevance-score
floor (0.05) below which the pipeline reports "no confident match" instead of
forcing a wrong citation — visible in `triage.py`'s `_chk_kb_match_found`
logic and covered by the eval harness. I'd want real query logs before
tuning that threshold further; right now it's a reasonable guess, not a
measured optimum.

**3. The account-brief LLM pass inventing a risk not backed by data.** This
already happened once during development — an early prompt draft let the
model describe a "declining NPS trend" when `nps_score` was simply `null`.
Fixed by splitting risk *detection* (rule-based, deterministic) from risk
*narration* (LLM, but only allowed to describe what pass 1 already found) —
see the module docstring in `account_brief.py`. Detection: the eval harness's
`flagged_quotes_verifiable` check would catch this class of failure by
verifying every quoted excerpt actually appears in the source ticket.

### Latency vs. quality

The clearest trade-off is Task 1's KB retrieval: I used TF-IDF instead of an
embedding-based vector search. Embeddings would retrieve better semantic
matches (e.g. "the app fell over" matching "outage"), but require an
embedding API call, an index build/refresh pipeline, and infra to host a
vector store. TF-IDF is instant, needs no extra network call, and for a
~10-document KB with fairly literal error-code vocabulary, it gets close
enough. If latency were the hard constraint I'd go further: pre-classify
common ticket patterns into a lookup table (skip the LLM call entirely for
known-shape tickets) and only fall through to the full LLM pipeline for
novel phrasing.

### Data sensitivity

Tickets and accounts can contain PII (contact names, emails embedded in
ticket bodies). `llm_client.py`'s `call_llm()` is the single choke point all
model calls go through, and it regex-scrubs email addresses and phone
numbers from prompts *before* they're sent to the model. This is intentionally
naive regex, not an NER-based PII detector — good enough to catch the two
most common leak vectors in this dataset, not a substitute for a real DLP
layer in production. I'd also want prompt/response logging to go to a
retention-limited, access-controlled store rather than wherever
`.llm_cache/` currently sits (which is fine for a local dev cache, not for
production).

### Scaling

At 10x ticket volume (5,000 tickets), the KB retrieval step is the first
thing that would need to change — TF-IDF cosine similarity over a growing
corpus is still cheap at this scale, but a KB that's *also* grown 10x
(hundreds of docs) would start returning noisier top-1 matches and I'd want
to move to embeddings + a real vector index (see latency section above). The
LLM calls themselves parallelize trivially (each ticket is independent), so
the real bottleneck becomes API rate limits and cost — at that point I'd
batch triage runs, add request queuing/backoff, and seriously consider a
cheaper/faster model for the classification step (keeping the stronger model
only for response drafting, where quality matters more).
