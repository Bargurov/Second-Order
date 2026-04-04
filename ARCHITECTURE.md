# Architecture Notes

This document explains the current V1 workflow in plain language. It is meant
to clarify how the project reasons about headlines without turning the design
into a large framework.

## V1 framing

The public V1.5 story is energy-focused. The intended use case is to take an
energy-related headline, classify it, extract the hidden economic mechanism,
and review whether a simple market check provides supporting evidence. The
current app works end to end, but the Streamlit layer is still a basic demo
rather than a polished product interface.

## Roadmap

- `V1.5`: backend engine plus a basic Streamlit demo
- `V2`: news ingestion plus an inbox-style review flow
- `V2.5`: UI/UX rework and polish for demo quality
- `V3`: OpenClaw and chat-style orchestration

## Workflow

### 1. Headline input

The workflow starts with one pasted headline. The system treats the headline
as a compact description of an event rather than a full article.

### 2. Event classification

The first pass assigns two labels:

- `stage`: where the event appears to sit in its lifecycle
- `persistence`: how durable the effects may be

These labels are simple heuristics. They help structure downstream reasoning,
but they are not meant to be a deep semantic model.

### 3. Hidden economic mechanism

The next step tries to identify the hidden economic mechanism behind the
headline. In practical terms, that means asking what changed, which actors or
assets may benefit, which may be hurt, and what belongs on a watchlist.

### 4. Watchlist generation

The mechanism step also produces a small list of assets to watch. The watchlist
is meant to make the output more concrete and easier to review.

### 5. Market validation

Market validation is a follow-up check on the watchlist. Its role is limited:
it is evidence, not proof. A supportive market read can strengthen the case
for a mechanism, but it does not confirm it. A weak or noisy read does not
necessarily invalidate the idea either.

### 6. Local persistence

The resulting record can be saved locally for later review. This keeps the
workflow inspectable and lightweight.

## Interpretation guidance

- Classification is heuristic and should be judged directionally.
- Mechanism output is provisional and should be reviewed critically.
- Market validation is evidence, not proof.
- The overall workflow is designed for practical review, not formal prediction.

## Out of scope

- No RAG
- No dashboards
- No OpenClaw in the current phase
- No full product-grade frontend beyond the current basic Streamlit demo
