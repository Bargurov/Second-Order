# Data provenance & honesty notes

Second Order is an **honest research dashboard** for geopolitical, macro, and
policy events. It is a quant-finance research craftsmanship project — **not a
trading or trade-recommendation tool**. Read this before reading any number in
the repo.

## What the evidence is — and is not

- **No buy / sell / trading-signal framing.** Findings are reported as
  *evidence*, never as a confirmed mechanism, a forecast, or a recommendation.
- **Representative cases are not proof.** The curated "case library" is selected
  to show the *range* of outcomes a reviewer should expect (including
  contradictions and unresolved reads), not a best-of and not a success record.
  Single-event readouts are `n = 1` descriptive reads, not generalisable results.
- **Phase 1 and Phase 2 are separate FDR pools.** They are never combined into a
  single q-value or a single denominator, and no cross-phase FDR statistic is
  computed. The closed evidence track preserves this separation everywhere it is
  surfaced (e.g. `GET /evidence/summary`).
- **Two kinds of denominator are kept distinct:** the *analysis / coverage*
  denominator (can the engine read the event) and the *thesis / track-record*
  denominator (was a directional outcome captured). They are not merged.
- **Synthetic / seed / test rows are flagged, not deleted.** Bootstrap seed rows
  live in the archive but are flagged in the `event_hygiene` sidecar
  (`override_class = 'synthetic_seed'`) and excluded from the accepted-corpus
  denominators. They remain retrievable by id for auditability (keep-and-flag).

## What is shipped — and what is not

- **The source code is shipped** under the MIT `LICENSE`.
- **The events archive (`events.db`) is NOT shipped.** It is gitignored, large,
  and carries seed/test rows. A clean clone starts with an **empty** archive, so
  every archive-derived figure quoted in `README.md` reflects the maintainer's
  local archive *as of the dates noted there*, not a fresh checkout. The
  read-only report scripts recompute all such figures from whatever `events.db`
  is present and are the source of truth.
- **No secrets are shipped.** `.env`, provider API keys (`ANTHROPIC_API_KEY`,
  etc.), and `backups/` are gitignored and have never been committed.
- **The closed Phase 1–4 evidence artifacts ARE shipped** under
  `evidence_artifacts/section_c_v2/` — real frozen, source-anchored research
  artifacts (see README), clean-clone reproducible via CI against a fixture
  database. (`evidence_artifacts/section_c_v1/` is a separate demo-walkthrough
  input bundle, labelled as such in its own README — not part of the frozen
  evidence pools.)

## Data sources

Saved headlines and source metadata are derived from public news / RSS feeds and
official sources (e.g. government press releases, regulatory filings); market
prices come from market-data providers (e.g. Polygon, yfinance) and are cached
locally. None of that third-party content is redistributed in this repository —
only the code that fetches, caches, and analyses it. Provider terms govern any
data you fetch yourself; this project makes no warranty about third-party data.
