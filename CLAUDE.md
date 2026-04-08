# Git & Workflow Rules
- ALWAYS make code changes directly to the current branch (`master`).
- NEVER create a new git branch. 
- NEVER initialize a new git repository.
- Modify the files in place and wait for my approval.
- Floating overlays only may use blur/glass treatment.
- Do not add new colors or extra surface levels.
- Do not use hard divider lines for sectioning unless necessary.
- Card boundaries must be obvious through tonal contrast.

## Color rules
- Primary accent = muted teal family only.
- Negative/stressed = muted coral family only.
- Neutral/monitoring = gray/slate family only.
- Avoid yellow unless the design explicitly calls for a watch state.
- Never let yellow dominate a page.

## Typography rules
- Manrope for headlines.
- Inter for body and labels.
- Use tabular numbers for prices, percentages, yields, and counts.
- Keep metadata quiet and secondary.

## Shape / spacing rules
- Tight radii, tight spacing, dense layouts.
- Normal cards max out around 8px radius.
- Pills may be fully rounded.
- Avoid oversized padding and soft consumer-style cards.



## Before finishing any UI task
Check:
- section/card contrast is obvious
- no accidental yellow flood
- no new arbitrary colors
- typography matches the system
- page still feels institutional, not SaaS
frontend/CLAUDE.md
# Frontend Claude Memory

See `DESIGN.md` for the full design philosophy.

## What this frontend should feel like
Second Order should feel like:
- quiet authority
- institutional intelligence
- dense, calm, precise
- premium but not flashy

## Hard design constraints
- Page background = darkest base only
- Major sections = `section-surface`
- Inner modules/cards = `raised-surface`
- Floating overlays only may use blur/glass
- No new colors or new surface levels
- No hard section borders by default
- No yellow-heavy pages

## Page priorities
### Market Overview
- command center first
- uncertainty and movers dominate
- headlines are secondary

### Headlines
- compact scanning worklist
- high density
- clear analyze affordance



## Visual constraints
- Use Manrope for headlines, Inter for body
- Use tabular numbers
- Keep corners tight
- Prefer tonal layering over border-heavy layout
- Major sections must read as distinct surfaces
- Inner cards must be visibly nested

## Working style
- For UI tasks, do not change backend logic unless explicitly asked
- For fidelity tasks, match the provided reference closely
- Do not invent extra widgets or decorative elements
- Solve problems through hierarchy, spacing, and tonal contrast first