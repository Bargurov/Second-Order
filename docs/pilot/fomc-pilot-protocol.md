# FOMC pilot protocol, version 1 (APPROVED: showcase pilot)

**Status: approved by the project owner on 2026-11-07, as a showcase pilot. It starts at 2026-12-01T00:00:00+00:00.**
The owner's approval covers:
- the start timestamp;
- the eight scheduled statements;
- the 2-year yield as the primary leg and the 10-year as the secondary, horizon 5 on both;
- one case per statement, by its first freeze;
- deviations kept and shown but out of the summary of valid results;
- outcome tracking continuing after the last statement.

The approval is for this showcase pilot only. Research intake stays closed, and INCLUSION.md is unchanged.

This protocol does not open research intake, change INCLUSION.md or add a research class. It defines a prospective
**showcase** pilot: its counts never enter research summaries and are never pooled with them. Background, checks and
the reasoning behind each choice are in `docs/research-pilot-protocol-draft-2026-11-04.md` (private; not in the public repository) (revised 2026-11-07).

## Start timestamp and approval

| Field | Value |
| --- | --- |
| Start timestamp (UTC) | `2026-12-01T00:00:00+00:00` (UTC, before 2026-12-09T19:00:00+00:00, the first statement's expected publication) |
| Approved by | The project owner |
| Approved on | 2026-11-07 |
| Commit of the approved text | Recorded in the activation report, `docs/pilot/fomc-pilot-activation-2026-11-07.md` (private; not in the public repository) (a commit cannot name its own ID) |

The same timestamp is in `content/pilot/fomc-pilot.json`, as `"start_utc"`, with `"status": "approved"`.

The ledger refuses a definition that:
- is approved without a start, or has a start while still proposed;
- gives the start in another offset than UTC;
- sets the start at or after 2:00 p.m. New York time on the first statement date.

The start is an exact instant. A case's stated publication time is compared with it as an instant, whatever the
offsets. A case published before it is "before start" and is never included afterwards.

## 1. The question

For each case: did the market observations after the freeze align with the measurable implications of a hypothesis
frozen before them? The answer is reported as observations consistent (or not) with the frozen hypothesis. It is never
a claim of causality, skill or a trading signal.

## 2. Event family and the fixed schedule

The family is **scheduled FOMC post-meeting policy statements**: the Board press release "Federal Reserve issues FOMC
statement", one per scheduled meeting.

The pilot covers exactly these eight statements (New York dates, from the Board's calendar of 2026-10-28). They are
fixed now and never changed, extended or shortened on the basis of results.

| # | Statement day | Story ID |
| --- | --- | --- |
| 1 | Wed 2026-12-09 | `fomc-2026-12-09` |
| 2 | Wed 2027-01-27 | `fomc-2027-01-27` |
| 3 | Wed 2027-03-17 | `fomc-2027-03-17` |
| 4 | Wed 2027-04-28 | `fomc-2027-04-28` |
| 5 | Wed 2027-06-09 | `fomc-2027-06-09` |
| 6 | Wed 2027-07-28 | `fomc-2027-07-28` |
| 7 | Wed 2027-09-15 | `fomc-2027-09-15` |
| 8 | Wed 2027-10-27 | `fomc-2027-10-27` |

- **Tentative dates.** The 2027 dates are tentative until the Board confirms each one at the preceding meeting.
- **A moved meeting.** It keeps its place in the schedule. The new date and story ID are written into the definition
  before the statement, with the old date in its `note`.
- **A cancelled statement.** It is marked `not_held` with the reason. It is never replaced, and the window never
  grows.
- **Unscheduled or intermeeting statements:** another family, never frozen.

## 3. Inclusion

A scheduled statement is included when all of these hold:

1. Its stated publication time is at or after the start timestamp, compared as instants.
2. Its official page states the publication time; the hypothesis records it with its UTC offset.
3. The case is frozen after publication and on the statement's **New York** date (section 4).
4. The freeze passes every check the code applies: freshness policy B, and enough reference windows for horizon 5.

An included statement with no valid case is **missed**, with its reason. It stays in every count.

## 4. Freeze window: set in New York time, converted per date to Israel time

- **Opens:** the Board posts H.15 on business days at 4:15 p.m. New York time, with the previous business day's
  values. A baseline that classifies the session before the statement day therefore exists only from 4:15 p.m. New
  York time on the statement day. This is the rule `second_order/h15_release.py` applies to baselines and outcomes
  alike.
- **Closes:** midnight New York time at the end of the statement day. A freeze after that falls on the next New York
  date and is not the case.
- **Writing:** the hypothesis can be written from publication (about 2:00 p.m. New York time); only the download,
  import, preview and freeze wait for the release.

The conversion is computed per date with the time-zone database (`pilot-ledger` prints it). The daylight-saving
changes differ between the two countries:

| Statement day | Statement (Israel, at 2:00 p.m. New York) | Freeze window in Israel time |
| --- | --- | --- |
| 2026-12-09 | 21:00 | 2026-12-09 23:15 to 2026-12-10 07:00 |
| 2027-01-27 | 21:00 | 2027-01-27 23:15 to 2027-01-28 07:00 |
| 2027-03-17 | 20:00 | 2027-03-17 22:15 to 2027-03-18 06:00 |
| 2027-04-28 | 21:00 | 2027-04-28 23:15 to 2027-04-29 07:00 |
| 2027-06-09 | 21:00 | 2027-06-09 23:15 to 2027-06-10 07:00 |
| 2027-07-28 | 21:00 | 2027-07-28 23:15 to 2027-07-29 07:00 |
| 2027-09-15 | 21:00 | 2027-09-15 23:15 to 2027-09-16 07:00 |
| 2027-10-27 | 21:00 | 2027-10-27 23:15 to 2027-10-28 07:00 |

If the Board's release is late (the Board is closed, or a holiday), a fresh baseline cannot exist inside the window,
and the statement is missed with that reason.

## 5. Legs and horizons (fixed for every case)

- **Primary leg:** the 2-year Treasury constant-maturity yield, Board H.15 (`yield:ust2y_cmt_h15`), horizon 5
  observations.
- **Secondary leg:** the 10-year Treasury constant-maturity yield, Board H.15 (`yield:ust10y_cmt_h15`), horizon 5
  observations.
- **Direction:** chosen by the author of each case, from their own reasoning.
- **Economic order:** declared in each leg's channel (`First order:`), with the mechanism in its rationale and a
  falsifier. Both legs are first order. No second-order observable is operational, and the second-order slot is
  reported as "not measured".
- **One case, not two.** The two maturities are two outcomes of one event. A case is counted once, by its primary leg;
  the secondary label is reported beside it and never added to the counts.

## 6. What is measured

The existing freeze and anchor rules (daily date convention) apply:

- **Event anchor E:** the last observation dated before the statement day.
- **Scoring anchor S:** the first observation dated after the New York freeze date, which for a same-day freeze is the
  session after the statement day.
- **Scored change:** 100 × (yield at S + 5 observations − yield at S), in basis points, signed by the frozen direction.
  It is ranked against the same-horizon changes of the windows that end by E, within the 250 observations up to E
  (120 needed).
- **Labels:**
  - *supported:* signed change > 0 and rank ≥ 0.80;
  - *contradicted:* signed change < 0 and rank ≤ 0.20;
  - *inconclusive:* otherwise;
  - *unavailable:* a session in the window is stated without a value.
- **Not measured:** the statement day's own change and the change from the statement day to S. H.15 gives one dated
  reading per day, not an observed time, and that date is never relabelled as an observed time.

| Statement | E | S | Target (h = 5) | Outcome obtainable from (New York) | (Israel) |
| --- | --- | --- | --- | --- | --- |
| 2026-12-09 | 12-08 | 12-10 | 2026-12-17 | Fri 2026-12-18 16:15 | 23:15 |
| 2027-01-27 | 01-26 | 01-28 | 2027-02-04 | Fri 2027-02-05 16:15 | 23:15 |
| 2027-03-17 | 03-16 | 03-18 | 2027-03-25 | Fri 2027-03-26 16:15 | 23:15 |
| 2027-04-28 | 04-27 | 04-29 | 2027-05-06 | Fri 2027-05-07 16:15 | 23:15 |
| 2027-06-09 | 06-08 | 06-10 | 2027-06-17 | Fri 2027-06-18 16:15 | 23:15 |
| 2027-07-28 | 07-27 | 07-29 | 2027-08-05 | Fri 2027-08-06 16:15 | 23:15 |
| 2027-09-15 | 09-14 | 09-16 | 2027-09-23 | Fri 2027-09-24 16:15 | 23:15 |
| 2027-10-27 | 10-26 | 10-28 | 2027-11-04 | Fri 2027-11-05 16:15 | 22:15 |

The dates are expected from the SIFMA calendar, not measured. Any later day is fine for the outcome download; the
outcome plan does not propose one earlier.

## 7. Counting: one case per statement, by its first freeze

`python -m second_order pilot-ledger` computes the ledger from the store and `content/pilot/fomc-pilot.json`. It only
reads.

- **The case:** a statement's story group is every hypothesis with its story ID. The case is the **first freeze**,
  ordered by freeze time and then hypothesis ID.
- **Later versions** (a changed direction, horizon or text) are kept and listed as extra freezes. They never add a
  case, never replace the first, and their assessments are listed but never counted. The code accepts such a freeze;
  the ledger decides what counts.
- **A first freeze outside the rules** (another publication date, frozen after New York midnight, not a prospective
  showcase) makes the statement missed; a later version cannot repair it.
- **A first freeze that does not conform** to the fixed legs is *nonconforming*. It must have exactly two legs: the
  2-year yield (`yield:ust2y_cmt_h15`) marked primary and the 10-year yield (`yield:ust10y_cmt_h15`) marked
  secondary, each with horizon 5. Legs are identified by these observable IDs, not by a record's primary flag
  alone, so a swapped primary, a missing or extra leg, or another horizon makes a case nonconforming.
  - It stays the case. It is frozen and covered, and the ledger shows it with its reasons and any assessment.
  - It never enters the summary of results.
  - A later conforming version does not replace it.
- **A mistyped story ID** on a statement date is listed as unmatched and not counted.
- **Labels:** an assessed conforming case is labelled by its **first** recorded evaluation; reassessments are
  listed. The primary label is the verdict of `yield:ust2y_cmt_h15` and the secondary label that of
  `yield:ust10y_cmt_h15`, whatever flags the record carries.
- **Before the start:** a statement whose first freeze states a publication time before the start is "before
  start". With no freeze, the expected publication (2:00 p.m. New York time) is compared with the start instead.

The ledger reports these counts:

| Count | Definition |
| --- | --- |
| Scheduled | Not held + Not started + Before start + Upcoming + Included (always the eight) |
| Not held | Marked `not_held`, with the reason |
| Not started | No start timestamp yet |
| Before start | The case's publication (or the expected one) is before the start instant |
| Upcoming | Scheduled, or open today, with no case yet |
| Included | Frozen + Missed |
| Missed | Included with no valid case, with the reason |
| Frozen | Pending + Assessed + Nonconforming |
| Nonconforming | Frozen cases whose legs, roles or horizons differ from the fixed legs; shown with the reasons |
| Extra freezes | Later versions, never counted |
| Primary labels | Among Assessed (conforming cases only) |
| Eligible | supported + contradicted + inconclusive (primary) |
| Secondary labels | Reported separately |
| Second order | "Not measured: no operational second-order observable" |

The headline figure is "*k* of *E* eligible primary legs had observations consistent with the frozen hypothesis".
It is built from the assessed, conforming cases only, and is always shown with Scheduled, Included, Missed,
Pending and Nonconforming. With eight statements, every count is descriptive. The scoring formula and the
labels' thresholds (section 6) are unchanged.

## 8. Intake ends; outcome tracking continues

- **Intake** ends with the eighth statement (2027-10-27); no case is added after it.
- **Outcome tracking** continues until every frozen case is assessed: the last case's outcome is obtainable from
  2027-11-05 16:15 New York time.
- **Assessment order:** cases are assessed in date order, each as soon as its outcome is held, never batched or chosen.
- **The ledger** is final when no case is pending.
- **Rules versions:** if the rules version changes during the pilot, each configuration is reported separately.

## 9. Data path and actions on each night

- **Source:** the Board's H.15 release package, `https://www.federalreserve.gov/releases/h15/data/FRB_h15_xml.zip`.
  It needs no key and has no charge. Each request is one approved download, kept privately and validated locally.
- **Baseline:** one download after the 4:15 p.m. New York release on the statement day, validated, then imported with
  start 2025-01-02. The Market context page's event plan does not apply the release time yet; the readiness check,
  not that page, says when to download.
- **Outcome:** one download from the outcome time in section 6, imported for the case. The outcome plan lists ended
  sessions the Board cannot have posted yet as "awaiting release" and does not request them. What a verified package
  holds always decides.
- **The step-by-step lists** for both nights are in Hebrew in `docs/pilot/fomc-night-checklist.he.md`. The journal
  with the eight dates is `docs/pilot/fomc-pilot-journal.he.md`.

## 10. Activation

Each step is explicit. Their execution and results are recorded in the activation report
(`docs/pilot/fomc-pilot-activation-2026-11-07.md` (private; not in the public repository)).

1. **Approve and record the start.** Done on 2026-11-07: the table above and `content/pilot/fomc-pilot.json`
   (`"start_utc": "2026-12-01T00:00:00+00:00"`, `"status": "approved"`).
2. **Merge.** Merge `research/h15-pilot-path` into the integration branch, then bring the main folder to it.
3. **Upgrade the store.** Back up `data/real/second-order.db`, then upgrade it:
   `python -m second_order store migrate --db data/real/second-order.db`. It only adds tables (checked on a copy on
   2026-11-07).
4. **Restart the server.** On statement nights and outcome days, run it with `--enable-market-retrieval` (and the
   flags it already uses).
5. **Check before the night.** `python -m second_order pilot-ledger --table` says the pilot starts at
   2026-12-01T00:00:00+00:00 and lists the eight statements as scheduled.
   `python -m second_order research-readiness --published 2026-12-09` says to wait until 2026-12-09 16:15 New York
   time.

## 11. Claims this pilot does not make

- It does not establish causality; a supported label does not confirm the stated mechanism.
- It produces no trading signal, recommendation or investment hit rate.
- It does not measure forecasting skill or calibration, and records no confidence or consensus forecast.
- Its counts are showcase counts, never research results.
- The two maturities are not two cases.
