# Drafting review kit (offline)

Eight synthetic cases and a runner for reviewing drafts from the Claude drafting adapter
(`second_order/model_draft.py`). The kit makes a reasoning review repeatable; it does not
demonstrate model quality. The runner calls no model, freezes nothing and opens no database.

## Cases

Each `cases/<id>.json` holds operator metadata (headline, source URL, publication time, story ID),
source text and a rubric. Every case is synthetic: headlines start with "Synthetic", URLs are on
example.com and source texts open with "SYNTHETIC TEST TEXT". Where a case needs it
(conflicting-labor-inflation, ambiguous-wording), a "Scenario facts" sentence places the fictional
events in a fictional version of the United States economy; it states facts, not instructions.

| Case | Situation | Declining |
|---|---|---|
| clear-policy | Clear policy announcement | allowed |
| conflicting-labor-inflation | Conflicting labor and inflation data | acceptable |
| headline-reports-move | Headline already reports the measured move | allowed |
| no-connection | No defensible connection to the offered observables | preferred |
| insufficient-source | Insufficient source information | preferred |
| prompt-injection | Instructions embedded in the source text | acceptable |
| unsupported-observables | The markets most affected are not offered | acceptable |
| ambiguous-wording | Ambiguous statement | acceptable |

Each rubric gives guidance on declining (every case allows it), the directions the source can
defend for each offered observable (often both, sometimes none), acceptable reasoning, required
uncertainties, the expected `headline_reports_move` for each observable with its reason, and
unacceptable claims.

## Runner

```powershell
python -m second_order.draft_review --list
python -m second_order.draft_review --print-request clear-policy
python -m second_order.draft_review --response clear-policy=saved.json --synthetic no-connection=written.json
```

`--print-request` prints the exact request the adapter builds for a case, with its hash; nothing is
sent. The runner reads only the files you name as `CASE=FILE`, and labels each by how you supply it:

- `--synthetic`: written to exercise the kit, not model output.
- `--response`: a saved response of unverified origin. The runner cannot verify that a model
  produced it, which model did, or that it answers the case's request; the adapter records it as
  `offline-replay`.

The report (JSON on stdout) keeps two judgments apart for each response:

- `structural_validation` is the adapter's decision, unchanged: `draft` (one draft passed strict
  validation), `no draft` (the model ended without calling the draft tool, or declined) or
  `refused` (invalid or unusable; a truncated reply is refused, not a decline).
- `reasoning_review` is always "Not reviewed". It lays out the rubric, the common criteria that
  apply to any draft (proxy versus direct links, no unsupported size comparisons across legs,
  competing influences with their channel and direction, unrelated news in the scored window,
  survey versus market pricing), and each leg's link, horizon, direction and leakage flag beside
  the rubric's, for a person to judge. The runner scores nothing, so a structurally valid draft
  is not thereby acceptable.

Text a response gave instead of a draft appears verbatim in `response_text`, for reviewing a
decline; it is never read as a draft. Each entry records the case's SHA-256, its request hash and
the response file's SHA-256, so a review can be tied to its exact inputs.

## Not shown yet

- The tests use synthetic responses only. No genuine model response has been reviewed, so the kit
  says nothing yet about any model's reasoning.
- A saved response's origin and its pairing with a request cannot be verified offline.
- The cases announce that they are synthetic, which may change how a model responds.
- Eight cases are a checklist, not a sample: compute no rates or scores from them.
