# Eval Report

**9/13 test cases passed** (pass threshold: quality_score >= 0.7)

| Case ID | Task | Passed | Score | Description |
|---|---|---|---|---|
| t1-01-clear-p1-bug | task1 | ✅ | 0.71 | Clear P1: production down, data loss language, urgent tone. |
| t1-02-billing-question | task1 | ✅ | 0.8 | Clear low-urgency billing/how-to question. |
| t1-03-feature-request | task1 | ✅ | 1.0 | Clear feature request, no urgency. |
| t1-04-known-error-code | task1 | ✅ | 0.75 | References a specific documented error code — KB retrieval should find a match. |
| t1-05-onboarding | task1 | ✅ | 1.0 | New customer onboarding / setup question. |
| t1-06-ADVERSARIAL-sparse | task1 | ✅ | 1.0 | Adversarial: near-empty ticket body, should degrade gracefully rather than crash. |
| t1-07-ADVERSARIAL-mixed-signals | task1 | ✅ | 1.0 | Adversarial: ambiguous category (reads as both Bug and Feature Request) — tests that the model picks one defensible label instead of stalling. |
| t2-01-at-risk-account | task2 | ❌ | 0.5 | Real account with health_status=At Risk. |
| t2-02-churning-account | task2 | ❌ | 0.5 | Real account with health_status=Churning. |
| t2-03-healthy-account | task2 | ❌ | 0.5 | Real account with health_status=Healthy. |
| t2-04-new-account | task2 | ❌ | 0.5 | Real account with health_status=New. |
| t2-06-determinism-check | task2 | ✅ | 1.0 | Same account_id run twice must produce identical output. |
| t2-07-ADVERSARIAL-unknown-account | task2 | ✅ | 1.0 | Unknown account_id should raise AccountNotFoundError, not fabricate a brief. |

## Details

### t1-01-clear-p1-bug
_Clear P1: production down, data loss language, urgent tone._

- ✅ `category_in_enum` — Bug
- ✅ `urgency_in_enum` — P3
- ✅ `reasoning_present` — 169 chars
- ✅ `responder_team_assigned` — Tier-2 Engineering
- ❌ `draft_length_reasonable` — 14 words
- ❌ `classified_as_p1` — P3
- ✅ `kb_match_found` — {'doc': 'products\\databridge-pro.md', 'section': 'DataBridge Pro — Product Reference > Common Support Scenarios > Pipeline stopped processing', 'relevance_score': 0.151}

### t1-02-billing-question
_Clear low-urgency billing/how-to question._

- ✅ `category_in_enum` — Bug
- ✅ `urgency_in_enum` — P3
- ✅ `reasoning_present` — 169 chars
- ✅ `responder_team_assigned` — Tier-2 Engineering
- ❌ `draft_length_reasonable` — 14 words

### t1-03-feature-request
_Clear feature request, no urgency._

- ✅ `category_in_enum` — Bug
- ✅ `urgency_in_enum` — P3
- ✅ `reasoning_present` — 169 chars
- ✅ `responder_team_assigned` — Tier-2 Engineering

### t1-04-known-error-code
_References a specific documented error code — KB retrieval should find a match._

- ✅ `category_in_enum` — Bug
- ✅ `urgency_in_enum` — P3
- ✅ `kb_match_found` — {'doc': 'troubleshooting\\performance-and-integrations.md', 'section': 'Troubleshooting: Performance Issues > Error Reference', 'relevance_score': 0.189}
- ❌ `draft_length_reasonable` — 14 words

### t1-05-onboarding
_New customer onboarding / setup question._

- ✅ `category_in_enum` — Bug
- ✅ `urgency_in_enum` — P3
- ✅ `reasoning_present` — 169 chars

### t1-06-ADVERSARIAL-sparse
_Adversarial: near-empty ticket body, should degrade gracefully rather than crash._

- ✅ `degrades_gracefully` — warnings=[]
- ✅ `responder_team_assigned` — Tier-2 Engineering

### t1-07-ADVERSARIAL-mixed-signals
_Adversarial: ambiguous category (reads as both Bug and Feature Request) — tests that the model picks one defensible label instead of stalling._

- ✅ `category_in_enum` — Bug
- ✅ `urgency_in_enum` — P3
- ✅ `reasoning_present` — 169 chars

### t2-01-at-risk-account
_Real account with health_status=At Risk._

- ✅ `flagged_quotes_verifiable` — all quotes verified
- ❌ `executive_summary_length` — 0 sentences
- ❌ `talking_points_count` — 0 points
- ✅ `risks_field_populated` — ["Account health status is 'At Risk'.", "Usage trend is 'Inactive'.", 'Escalation note: Decision maker considering competing vendor evaluation']

### t2-02-churning-account
_Real account with health_status=Churning._

- ✅ `flagged_quotes_verifiable` — all quotes verified
- ❌ `executive_summary_length` — 0 sentences
- ❌ `talking_points_count` — 0 points
- ✅ `risks_field_populated` — ["Account health status is 'Churning'.", "Usage trend is 'Declining'.", '2 P1 tickets in the last 30 days.', 'Primary contact last logged in 41 days ago.', 'Escalation note: Champion left the company — no replacement identified yet', 'Escalation note: Customer expressed frustration with response times in last sync', 'Escalation note: Decision maker considering competing vendor evaluation']

### t2-03-healthy-account
_Real account with health_status=Healthy._

- ✅ `flagged_quotes_verifiable` — all quotes verified
- ❌ `executive_summary_length` — 0 sentences
- ❌ `talking_points_count` — 0 points
- ✅ `risks_field_populated` — ['Primary contact last logged in 57 days ago.']

### t2-04-new-account
_Real account with health_status=New._

- ✅ `flagged_quotes_verifiable` — all quotes verified
- ❌ `executive_summary_length` — 0 sentences
- ❌ `talking_points_count` — 0 points
- ✅ `risks_field_populated` — ['Only 58% of licensed seats are active (757/1314).']

### t2-06-determinism-check
_Same account_id run twice must produce identical output._

- ✅ `identical_repeat_run` — match

### t2-07-ADVERSARIAL-unknown-account
_Unknown account_id should raise AccountNotFoundError, not fabricate a brief._

- ✅ `raises_not_found` — raised as expected
