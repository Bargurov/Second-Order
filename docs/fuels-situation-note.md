# Drafting the fuels page's "situation now" note

The note on `/fuels` is short prose written from public agency material and bound to the price snapshot and observation
date it was written for. This is the procedure.

Until SPEC 0.5.39 the prices came from FRED, whose terms bar AI and software development, so a session never saw a
price: it read only `fuels status`. The prices now come from EIA's open data API, and an analysis (fuels-note-0.2,
SPEC 0.5.41) is written from the verified EIA snapshot itself. One limit stays: a FRED-era snapshot
(`fuels-snapshot-0.1`, provider `fred`) is never opened for its values; the page withholds its prices too.

1. **The owner runs `python -m second_order fuels refresh`.** It uses `EIA_API_KEY` when set, else the key the owner
   stored once with `fuels key set` (Windows Credential Manager), and appends one snapshot under
   `data/fuels/snapshots/`. It prints no price. A session never reads the key, in either place, never runs
   `fuels key` and never runs a refresh.
   - Snapshots are per checkout, and a note binds only where its snapshot file is present. From a worktree, run
     `fuels refresh` and `fuels status` with `--snapshots <main checkout>/data/fuels/snapshots`
     (the main checkout's folder), so the snapshot is not lost with the worktree. A snapshot file can be copied between
     checkouts as is: its name is its hash, so a copy verifies itself.
2. **The session runs `python -m second_order fuels status`** and reads `snapshot_id` and `barrel_date` from its report
   (`latest`): the snapshot is `verified` and its provider is `eia`. To read the values, it serves a byte-identical copy
   of that snapshot through the review server (`tests/review_browser_server.py`, no `--fuels`) and reads `/api/fuels`:
   the barrel, the series and Situation Now's windows, as the page shows them. It reads no unverified or FRED-era file.
3. **Draft `content/fuels/notes/situation-NNNN.json`** (the next number, from 0001, no gaps).
   - Common fields: `note_version`, `number`, `written_on`, `covers_through` (the latest source date), `snapshot_id`
     and `observation_date` (= `barrel_date`) from step 2, `author`, `review`
     `{"state": "unreviewed", "reviewed_on": null}`, `headline`, `lede` and `sources`.
   - The session always writes `author` "Claude (AI-drafted)" and never marks a note reviewed. "Owner" is only for
     prose the owner wrote.
   - Cite each source with its title, publisher, date, https URL and a locator (a section or page). Cite only what was
     read in the source itself, on the date given; prefer a stable archive URL to a page that is replaced each release.
   - The refused phrases (SPEC, "Fuels page", Text rules: "caused", "due to", "driven by", "expects", "forecast",
     "will rise" and the rest) are refused in every text, even inside an attribution: write "EIA's November STEO says
     stocks may build", not "EIA expects stocks to build".
   - No figures in the prose: a digit is refused except inside a year. Every figure, date and direction is a
     placeholder that the page fills from the bound snapshot.
4. **A fuels-note-0.2 analysis** (the form for new notes) replaces the columns with `analysis`:
   - `lede` is the visible summary: twenty-five to seventy words as written, forty to seventy once filled. The headline
     and summary say what moved and what it may mean, in a reader's half-minute.
   - Four sections of statements, `what_happened` (one to four), `meaning` (one to six), `relevance` (one or two) and
     `watch` (two or three), then `caveats` (one to six texts, no placeholders): what this cannot tell and what is
     missing.
   - Each statement is `{"kind", "text", "sources", "mechanism"}`. The kind is one of `observation` (a price as
     published), `computed` (from the engine), `hypothesis` (a reading or a general mechanism, never a finding about
     this move), `sourced` (what a cited source says) or `source_projection` (a source's view of the future, attributed
     to it). `sources` lists indexes into `sources`: a sourced statement or projection names at least one; an
     observation or computed figure names none. Every source is cited at least once.
   - `mechanism` is null, `drivers:<id>` or `transmission:<id>`, naming one of the page's committed mechanisms (the
     page refuses an unknown one). A `relevance` statement names a transmission mechanism and says the conditions that
     change the effect.
   - Placeholders: `{brent}`, `{basket}`, `{crack}`, `{brent_change}` (the barrel), and for `week` and `month`:
     `{week_from}` and `{week_to}` (the dates compared), `{week_split}` (the accounting split of the basket's change,
     as words), `{week_gasoline_part}` and `{week_diesel_part}` (each product's part, per barrel of crude), and for
     each of `brent`, `gasoline`, `diesel`, `basket`, `crack`: `{week_brent_move}` ("rose", "fell", "was unchanged"),
     `{week_brent_change}` (the size, with its unit) and, except the crack, `{week_brent_pct}`. If a window is not
     computed for the bound snapshot, the note is not shown as a reading and the page says why.
   - Keep observation, calculation, hypothesis and attributed projection apart. A split of the basket's change between
     Brent and the crack is accounting, not a cause. The crack is a benchmark gross margin, not a refinery's profit.
     Prices alone show no stocks, demand or supply. Few conclusions, each founded; say what is missing.
   - fuels-note-0.1 (headline, lede and three `columns`: `supply`, `demand`, `stocks`, with the four barrel
     placeholders) still reads, unchanged.
5. **Run `fuels status` again** and confirm the note is listed with state `current` (its `snapshot_id` is the latest).
   A refusal names the file and field; fix that and run again. Then read the page at desktop and phone width.
6. **The owner reads the page and commits the note.** Setting `review` to `reviewed` with a `reviewed_on` date is the
   owner's act.
7. **To review or revise, copy the note to the next number** with the changed fields and a new `written_on`; never edit
   an earlier file. A copy bound to the same snapshot leaves both notes bound, and the page shows the highest number.
   A note shows as `earlier`, with its prices then and now, only after a later refresh; without its verified snapshot
   it is never shown as a reading.
