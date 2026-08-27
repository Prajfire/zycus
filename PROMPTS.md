# Prompt Versioning

Each prompt used in this repo has a version identifier defined next to it in
code (`src/triage.py`, `src/account_brief.py`) so a prompt change shows up in
`git blame`/PR diffs against a named version rather than as an anonymous
string edit. Cache keys in `llm_client.py` are based on the literal prompt
text, so bumping a version below also naturally invalidates stale cache
entries from the old wording.

## `triage-classify-v1` → `triage-classify-v2`
**Change:** added an explicit instruction to be conservative with P1 and to
pick one defensible label instead of hedging when a ticket is ambiguous.
**Why:** early manual testing on ambiguous tickets (see eval case
`t1-07-ADVERSARIAL-mixed-signals`) showed the model sometimes returned
multiple categories separated by "or", which broke the enum-membership check
downstream. v2 fixed this.

## `triage-draft-v1`
**Status:** initial version, no changes yet.
**Notes for next iteration:** consider adding a variable for the customer's
plan tier so Enterprise customers get a slightly more white-glove tone —
currently the draft tone doesn't vary by plan tier, which real support teams
usually do differ on.

## `account-brief-v1`
**Status:** initial version, no changes yet.
**Notes for next iteration:** the system prompt explicitly tells the model
not to invent risks beyond what the rule-based pass supplies. This was added
after the *first* draft of the prompt (not committed) let the model add a
plausible-sounding but unsupported risk ("declining NPS trend") when NPS was
simply `null`. Keeping risk detection out of the LLM's hands entirely fixed
that class of error — documented in README under Task 4 (Failure modes).
