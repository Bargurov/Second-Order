# Event intake and request preview (offline)

`python -m second_order.event_intake` lets an operator capture a published event and its source text
locally, then inspect the exact model request that would be sent for it. Every output says
**Nothing sent · Not frozen**. The tool creates no HTTP client, reads no API credentials, sends nothing,
generates no hypotheses, freezes nothing and opens no database.

This is manual intake by an operator, not automated ingestion: nothing is fetched, scheduled, clustered or
inferred. It works for any event, independently of the fixed synthetic pilot cases.

## Commands

```powershell
python -m second_order.event_intake capture --headline "..." --source-url https://... `
    --published-at 2026-01-15T14:00:00-05:00 --story-id my-story --source-file source.txt --model claude-sonnet-5-5
python -m second_order.event_intake list
python -m second_order.event_intake preview <capture-id>
```

All inputs are explicit: headline, source URL, timezone-aware publication time, story ID, one UTF-8 source-text
file and the model ID the request will name (there is no default model). `--root <dir>` selects another capture
directory; the default is `data/intake/`, which `.gitignore` already excludes.

The Tracker's form is stricter about the publication time than this command. It takes a date, a time of day and
an explicit UTC offset, and sends exactly `YYYY-MM-DDTHH:MM:SS±HH:MM`. The offset must lie between −12:00 and
+14:00 in 15-minute steps. `-00:00` is refused, because by convention it means the offset is unknown. Impossible
dates and times, missing offsets, `Z`, fractions, spaces and bare numbers are refused rather than adjusted.
The browser never converts the time, so the computer's time zone cannot change it. The capture keeps the
string as `published_at_as_supplied`; the request and `published_at` hold the same instant in UTC. Existing
captures, including those saved from the earlier form as converted UTC strings, are read and verified unchanged.

## What is checked before anything is written

Validation reuses the drafting adapter's operator check and request builder without changing them. A capture
is refused, and no record is created, when:

- the metadata is invalid (empty headline, invalid URL, naive or malformed time, blank story ID) or the
  publication time is in the future;
- the source file is missing, not a file, not valid UTF-8, empty or whitespace only, or longer than the
  adapter's 50,000-character limit. Nothing is truncated, decoded leniently or repaired;
- the model ID is not a plain lowercase identifier (letters, digits, `.` and `-`, at most 64 characters);
- the framing would be ambiguous: a line break or control character in the headline or story ID, a
  `<source_text>` or `</source_text>` tag in any field (any letter case or spacing), or a built request whose
  user message does not read back, through the draft-review reader, as exactly the supplied event and text.

## What a capture records

Each capture is a new directory, `<capture time>-<first 12 hex of the request hash>`, holding:

- `source.txt`: the supplied file's exact bytes (line endings, spacing and characters unchanged);
- `request.json`: the exact canonical request bytes the adapter would send. Their SHA-256 is the adapter's
  prompt hash;
- `capture.json`: the normalized event (publication time in UTC), the story ID, both SHA-256 hashes and byte
  counts, the prompt version, model, effort and token limit, the endpoint the request names (not contacted),
  and the SHA-256 of the request builder's and this module's code at capture time.

Two times are kept apart. The **publication time** is supplied by the operator and is not verified here (the
record also keeps it exactly as typed). The **capture time** is our clock when the record was written. It
shows possession from then on; capturing older material now is not evidence that we held it earlier.

## Immutability

A record is written to a staging directory and renamed into place, so it is either complete or absent; an
interrupted save leaves nothing behind. An existing record is never overwritten: a second capture with the same
time and content is refused, and capturing the same material later creates a separate record with its own
capture time. Record files are made read-only.

These are guards against accidents. The hashes sit beside the files they describe, so they detect accidental
change but cannot prove that nobody rewrote a whole record.

## Preview

`preview` works in two separate steps.

1. **Verify the stored record on its own terms.** Every manifest field that the stored bytes can confirm must
   match them: the source's SHA-256, byte count and character count (and valid UTF-8); the request's SHA-256,
   byte count and canonical form; the recorded model, effort and `max_tokens` against the stored request's own
   values (types included); the user message reading back as exactly the recorded event and source text; the
   recorded publication times agreeing; the capture ID matching the capture time and request hash; and the
   status "Nothing sent · Not frozen". Every manifest and request value that preview or `list` reads must
   be present with its exact type (non-empty text, whole numbers that are not true/false), or the capture
   is refused and the missing or mistyped field is named. A recorded prompt version is required but never
   compared with today's: an older prompt version is shown as recorded. Any mismatch refuses the capture with
   the reason, and nothing is shown.
   This step does not use today's request builder or its limits, or the draft-review reader, so a record
   is read the same way after those change. The labels preview prints (model, effort, token limit) are read
   from the verified request itself. Fields the bytes cannot confirm (story ID, prompt version, code identity,
   source file name, and the two times themselves) are listed as recorded only.
2. **Compare with today's code, as a diagnostic only.** Preview then asks whether today's builder would produce
   the same bytes: `identical`, `different` (for example after a prompt change), or `unavailable` when today's
   rules refuse the old inputs, such as a lower source limit. None of these outcomes affects the record's
   verification, and the verified original request is shown in each case.

`list` verifies every capture the same way; a capture that fails is listed as refused, without its labels.
Preview and list never write: a refusal leaves the record exactly as it was.

These checks compare the record with itself. They catch accidental or partial changes, not a consistent
rewrite of the whole record, and they do not establish who wrote it, when, or where the source came from.

## Limits

- The URL is not fetched and the source text is not compared with it; the publication time is not verified.
- No command in this module sends a captured request. The Tracker can copy a verified request into one explicit
  **local mock** attempt after confirming its hash; that path has no HTTP client, costs $0 and never retries.
  `second_order.paid_drafts` adds one **paid** path. It is off unless the server is started with
  `serve --enable-paid-drafts` and the key in `SECOND_ORDER_ANTHROPIC_API_KEY`. It posts exactly the saved, verified
  request bytes once, after an approval that names their SHA-256 and repeats the planning estimate. It never
  rebuilds or retries the request.
- The Tracker's preview reports `provider_called: false`, since previewing sends nothing, and the server's sending
  modes in `modes`. Paid sending being enabled there is not an approval.
- The Tracker's **Saved events** list reopens a capture after a reload, and **Refresh saved preview** re-reads the one
  shown (for example after the server is restarted with paid sending). Both use only `GET /api/intake/<capture>` and
  `GET /api/intake/<capture>/attempt`: the stored request is shown as verified, never recaptured or rebuilt, and
  approvals are cleared each time.
- The paid path has been exercised only through an injected fake provider with a dummy key, and through the
  production client over an in-process network (no retry; a 307 to any host is not followed). No real request has
  been sent from the Tracker, so the real API's acceptance of these exact bytes, authentication, network and timeout
  behavior, response formats and billed usage remain unverified.
- A capture has at most one attempt, mock or paid. `GET /api/intake/<capture>/attempt` reports, without writing or
  sending, whether none is recorded, an attempt was interrupted (kept, and still blocking another; for a paid
  attempt it also says whether the request was already sent and may have been billed), a recorded response awaits
  publication, or its result is ready. `POST /api/intake/<capture>/publish` publishes a recorded response from its
  saved files only; it never sends, regenerates or rebuilds anything.
- A preview shows inputs only. It says nothing about what a model would draft or whether a draft would be sound.
