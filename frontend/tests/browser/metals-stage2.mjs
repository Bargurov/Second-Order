// The Stage 2 part of the metals browser check (metals-check.mjs): what each metal's snapshot, supply chain,
// concentration, industrial uses, geopolitical exposure and economic transmission show, read off the page in one pass
// per metal (`PAGE`) and compared with the reply (`verifyMetal`), in any state of the sources; and the controls the new
// parts add (folds, About notes, the uses selects, the overview's Concentration switch). Nothing here trusts the page's
// own code: every expected string is written again from the reply.
import { same } from "./metals-kit.mjs";

const n = (text) => String(text ?? "").replace(/\s+/g, " ").trim();
const grouped = (digits) => digits.replace(/\B(?=(\d{3})+(?!\d))/g, ",");
export const hhiRange = (low, high) => (low === high ? grouped(low) : `${grouped(low)}–${grouped(high)}`);
export const coverage = (share, over) => (over === true ? `named countries ${share}%, over the printed total`
  : `named countries ${share}% of the world total`);
const importCoverage = (share) => `named sources ${share}% of US imports`;
export const WRITTEN_BY = "Written by the assistant from the figures on this page and retained sources; not reviewed by the owner.";
export const NO_EVENT = "No verified event is retained for this metal. Events appear here only from a retained primary source (an official publication or a filing), dated.";
export const FINAL = "Final products: no retained source covers this stage.";
export const BADGES = { measured: "Measured", stated: "Stated by a source",
  hypothesis: "Hypothesis — not measured or stated by a retained source" };
export const NEW_FOLDS = ["supply-chain", "concentration", "uses", "exposure", "transmission"];
const QUOTED_NOTE = "Passages chosen by the assistant; each quote is checked against its retained source on this read, and withheld when it cannot be.";
/** The events block's note: past events, dated as their sources date them, not a news feed. */
export const EVENTS_NOTE = `${QUOTED_NOTE} Each event is a past one, dated as its source dates it, from the report named under it; this is not a news feed.`;
/** The IEA uses block's note: what the table covers. */
export const USES_SCOPE = "Demand from energy technologies only, as the IEA scopes them; other industrial uses of this metal are not in this table.";
/** Each chain's label over the lists that follow its links. */
export const READING = "The assistant's readingWho is exposed, who may gain or lose and what could soften it: not measured, and not stated by a retained source.";

/** One expression, run per metal with every fold open: the new parts as the page shows them. */
export const PAGE = `(() => {
  const panel = document.getElementById("mt-metal-panel");
  const t = (e) => (e?.innerText ?? "").replace(/\\s+/g, " ").trim();
  const all = (e) => (e?.textContent ?? "").replace(/\\s+/g, " ").trim();
  const fold = (part) => panel.querySelector('details[data-part="' + part + '"]');
  const withheld = (e) => [...(e?.querySelectorAll("[data-withheld-part]") ?? [])].map(all);
  const hhi = (h) => (h ? { range: t(h.querySelector(".mt-share")), coverage: t(h.querySelector(".mt-sub")) } : null);
  const snap = panel.querySelector("[data-snapshot]");
  const sf = fold("supply-chain"), cf = fold("concentration"), uf = fold("uses"), ef = fold("exposure"), tf = fold("transmission");
  const blocks = (f) => [...f.querySelectorAll(":scope > .mt-fold-body > [data-block]")];
  const sb = blocks(sf);
  return {
    folds: Object.fromEntries(["supply-chain", "concentration", "uses", "exposure", "transmission"]
      .map((p) => [p, { teaser: all(fold(p)?.querySelector(".mt-fold-teaser")), title: all(fold(p)?.querySelector(".mt-fold-title")) }])),
    snapshot: snap && { inFold: !!snap.closest("details"), shown: snap.offsetHeight > 0, heading: all(snap.querySelector("h4")),
      items: [...snap.querySelectorAll("[data-snap]")].map((e) => ({ id: e.dataset.snap, value: t(e.querySelector(".mt-snap-value")),
        source: t(e.querySelector(".mt-snap-source")), withheld: withheld(e) })) },
    supply: { ladder: [...sf.querySelectorAll("ol.mt-ladder > li")].map((li) => ({ stage: li.dataset.stage,
        missing: li.classList.contains("is-missing"), name: t(li.querySelector(".mt-step-name")), body: t(li.querySelector(".mt-step-body")) })),
      final: t(sf.querySelector("p.mt-step-final")), withheld: withheld(sf),
      blocks: sb.map((b) => ({ source: b.dataset.block, label: all(b.querySelector(".mt-src-label")), note: all(b.querySelector(".mt-src-note")),
        withheld: withheld(b), ieaStages: b.querySelectorAll(".mt-step-iea").length })),
      apart: sb.every((a) => sb.every((b) => a === b || !a.contains(b))), facts: t(sf.querySelector(".mt-facts")),
      scope: t(sf.querySelector(".mt-series-scope")) },
    conc: { tables: cf.querySelectorAll("table").length, withheld: withheld(cf), none: t(cf.querySelector("p.mt-none")),
      rows: [...cf.querySelectorAll("table.mt-conc-detail tbody tr")].map((tr) => { const td = [...tr.querySelectorAll("td")];
        return { series: tr.dataset.series, cr1: t(td[0]), cr3: t(td[1]), hhi: hhi(td[2]?.querySelector(".mt-hhi")), hhiText: t(td[2]) }; }),
      imports: [...cf.querySelectorAll("table.mt-conc-imports tbody tr")].map((tr) => ({ head: t(tr.querySelector("th")),
        cells: [...tr.querySelectorAll("td")].map(t), hhi: hhi(tr.querySelector(".mt-hhi")) })) },
    uses: { withheld: withheld(uf), missing: t(uf.querySelector("[data-missing]")), selects: [...uf.querySelectorAll("select")].map((s) => s.id),
      share: t(uf.querySelector("[data-energy-share]")), note: t(uf.querySelector('[data-note="importance"]')),
      blocks: blocks(uf).map((b) => ({ source: b.dataset.block, withheld: withheld(b), note: all(b.querySelector(":scope > .mt-src-note")) })),
      tables: [...uf.querySelectorAll(".mt-use")].map((u) => ({ name: u.dataset.use, key: u.querySelector("table")?.dataset.uses,
        scope: t(u.querySelector("[data-use-scope]")), none: t(u.querySelector("p.mt-none")),
        rows: [...u.querySelectorAll("tbody tr")].map((tr) => [t(tr.querySelector("th")), ...[...tr.querySelectorAll("td")].map(t)]),
        total: [...u.querySelectorAll("tfoot td")].map(t) })) },
    exposure: { withheld: withheld(ef), noEvent: t(ef.querySelector("[data-no-event]")), differs: ef.querySelector("[data-leaders-differ]")?.dataset.leadersDiffer ?? null,
      events: [...ef.querySelectorAll("[data-events] [data-passage]")].map((p) => ({ id: p.dataset.passage, state: p.dataset.state,
        kind: all(p.querySelector(".mt-quote-kind")), when: all(p.querySelector("[data-when]")), quote: t(p.querySelector("blockquote")),
        source: t(p.querySelector(".mt-quote-source")) })),
      quotedNote: all(ef.querySelector('[data-block="quoted"] > .mt-src-note')),
      head: all(ef.querySelector("[data-unverified] h4")),
      unverified: [...ef.querySelectorAll("[data-unverified] [data-passage]")].map((p) => ({ id: p.dataset.passage, state: p.dataset.state, text: all(p),
        dated: !!p.querySelector("[data-when]") })) },
    transmission: { written: t(tf.querySelector("[data-written-by]")), withheld: withheld(tf), none: t(tf.querySelector("p.mt-none")),
      thesisLink: !!tf.querySelector("[data-thesis-link]"),
      chains: [...tf.querySelectorAll("article[data-chain]")].map((a) => ({ id: a.dataset.chain, count: t(a.querySelector(".mt-chain-count")),
        reading: all(a.querySelector("[data-reading]")),
        learned: t(a.querySelector("[data-learned] p")), assumed: t(a.querySelector("[data-assumed] p")),
        links: [...a.querySelectorAll("li.mt-link")].map((li) => { const m = li.querySelector("[data-measured]"); let own = null, cov = null;
          if (m) { const c = m.cloneNode(true), v = c.querySelector("[data-coverage]"); cov = v ? v.textContent.trim() : null; v?.remove(); own = c.textContent.trim(); }
          const p = li.querySelector("[data-passage]");
          return { kind: li.dataset.kind, badge: all(li.querySelector(".mt-badge")), text: t(li.querySelector(".mt-link-text")), measured: own,
            coverage: cov, all: all(li), passage: p && { state: p.dataset.state, quote: t(p.querySelector("blockquote")), source: t(p.querySelector(".mt-quote-source")) } }; }) })) },
  };
})()`;

/** The reply's pieces for one metal. */
const piece = (reply, id) => ({
  risk: reply.risk.state === "available" ? reply.risk.chapters.find((c) => c.id === id) : null,
  chapter: reply.usgs.state === "available" ? reply.usgs.chapters.find((c) => c.id === id) : null,
  uses: reply.uses.state === "available" ? reply.uses.entries.filter((e) => e.chapter === id) : null,
  frame: reply.iea.minerals.find((m) => m.chapter === id) ?? null,
  research: reply.research.state === "available" ? (reply.research.metals[id] ?? null) : undefined,
});
const verifiedPassage = (cited) => cited.evidence.state === "verified" && cited.evidence.quote !== null;
/** A passage's source and place as the page must write them: the source's title, publisher and edition, never its id. */
const placed = (e) => n(`${e.title} · ${e.publisher}, ${e.edition} · ${e.where}`);
/** US net import reliance as the page must write it: named by its commodity, and "one of N", where the chapter prints
 * more than one 2025 figure. */
export const relianceWords = (chapter, reliance) => {
  const count = chapter.reliance.filter((row) => row.year === "2025").length;
  const value = /^(?:\d{1,3}(?:,\d{3})+|\d+)(?:\.\d+)?$/.test(reliance.value.trim()) ? `${reliance.value}%` : reliance.value;
  return { count, figure: count > 1 ? `${reliance.commodity} ${value}` : value,
    oneOf: count > 1 ? `One of ${count} 2025 figures USGS prints for this chapter` : null };
};

/** The problems (strings, by part) found comparing one metal's page, every fold open, with the reply; none means it matches. */
export function verifyMetal(reply, id, page) {
  const bad = { snapshot: [], supply: [], conc: [], uses: [], exposure: [], transmission: [] };
  let part = "snapshot";
  const need = (ok, what) => { if (!ok) bad[part].push(`${id}: ${what}`); };
  const { risk, chapter, uses, frame, research } = piece(reply, id);
  const ieaOn = reply.iea.state === "available" && frame !== null;
  const withheldWith = (list, problem) => list.length > 0 && list.every((text) => text.includes(`Withheld: ${problem}`));

  // The snapshot: open on arrival, every item with its source line.
  const snap = page.snapshot;
  need(snap && !snap.inFold && snap.shown && snap.heading === "Snapshot", "the snapshot is always shown, outside every fold");
  const hasUnit = chapter !== null && chapter.series.some((s) => typeof s.unit_issue === "string" && s.unit_issue !== "");
  const wantItems = risk ? ["leaders", "concentrated", "reserves", "reliance", "critical", ...(hasUnit ? ["unit"] : []), "iea"]
    : ["usgs", "iea"];
  need(same(snap?.items.map((i) => i.id), wantItems), `snapshot items ${JSON.stringify(snap?.items.map((i) => i.id))}`);
  need(snap?.items.every((i) => i.source.length > 12), "every snapshot item names its source");
  const item = (key) => snap?.items.find((i) => i.id === key);
  if (risk) {
    for (const stage of risk.stages) {
      if (stage.leader.shown !== null) need(item("leaders")?.value.includes(`${stage.leader.countries[0]} ${stage.leader.shown}%`), `snapshot leader of ${stage.detail}`);
    }
    if (risk.stages.length === 0) need(item("leaders")?.value.includes("USGS's file has no 2025 production table for this metal"), "snapshot says no production table");
    if (risk.us.reliance !== null && chapter) {
      const want = relianceWords(chapter, risk.us.reliance), shown = item("reliance")?.value ?? "";
      need(shown.startsWith(want.figure) && (want.oneOf === null ? !shown.includes("2025 figures USGS prints")
        : shown.includes(want.oneOf)), `snapshot reliance "${shown}"`);
    }
  } else need(withheldWith(item("usgs")?.withheld ?? [], reply.risk.problem), "snapshot's USGS item gives the withheld problem");
  if (uses) {
    for (const entry of uses) need(item("iea")?.value.includes(entry.name) && item("iea").value.includes(`${entry.total["2025"]} kt`), `snapshot IEA total of ${entry.name}`);
    if (uses.length === 0) need(item("iea")?.value.includes("The IEA's energy-technology table has no entry for this metal"), "snapshot says the IEA has no entry");
  } else need(withheldWith(item("iea")?.withheld ?? [], reply.uses.problem), "snapshot's IEA item gives the withheld problem");

  // Supply chain.
  part = "supply";
  const s = page.supply;
  need(s.final === FINAL, "the Final products sentence, exactly");
  const wantSources = ["usgs", ...(frame ? ["iea"] : []), "quoted"];
  need(same(s.blocks.map((b) => b.source), wantSources) && s.apart, `supply-chain blocks ${JSON.stringify(s.blocks.map((b) => b.source))}`);
  need(s.blocks[0]?.label.startsWith("USGS · Mineral Commodity Summaries 2026"), "the USGS block is labelled");
  if (frame) {
    const b = s.blocks.find((x) => x.source === "iea");
    need(b.label.startsWith("IEA · Critical Minerals Dataset 2026") && b.note.startsWith("A separate source"), "the IEA block is labelled apart");
    if (ieaOn) need(b.ieaStages === frame.supply.length && b.ieaStages > 0, "the IEA stages are the reply's");
    else need(withheldWith(b.withheld, reply.iea.problem), "the IEA block gives the withheld problem");
  }
  if (risk) {
    const named = (stage) => risk.stages.filter((x) => x.stage === stage);
    const want = [...["mining", "refining"].flatMap((stage) => named(stage).length > 0
      ? named(stage).map((x) => ({ stage, missing: false, x }))
      : risk.missing_stages.includes(stage) ? [{ stage, missing: true }] : []),
      ...named("other").map((x) => ({ stage: "other", missing: false, x }))];
    need(same(s.ladder.map((l) => [l.stage, l.missing]), want.map((w) => [w.stage, w.missing])), `stage ladder ${JSON.stringify(s.ladder.map((l) => [l.stage, l.missing]))}`);
    want.forEach((w, at) => {
      const row = s.ladder[at];
      if (!row) return;
      if (w.missing) need(row.body.endsWith(`USGS's file has no ${w.stage} table for this metal`) && row.body.length < 120, `missing ${w.stage} sentence`);
      else {
        need(row.name === w.x.detail, `stage name ${w.x.detail}`);
        if (w.x.leader.shown !== null) need(row.body.includes(`${w.x.leader.countries[0]} ${w.x.leader.shown}%`), `${w.x.detail} leader`);
        if (w.x.top3.shown !== null) need(row.body.includes(`${w.x.top3.shown}%`), `${w.x.detail} top three`);
      }
    });
    if (risk.us.reliance !== null && chapter) {
      const want = relianceWords(chapter, risk.us.reliance);
      need(s.facts.includes(want.figure) && (want.oneOf === null || s.facts.includes(want.oneOf)), "US net import reliance as printed, named where the chapter prints several");
    }
    need(risk.stages.length === 0 || (s.scope.includes("CR1") && s.scope.includes("CR3")), "the CR1 and CR3 line");
  } else {
    need(s.ladder.length === 0 && withheldWith(s.blocks[0].withheld, reply.risk.problem) && page.folds["supply-chain"].teaser === "USGS part withheld",
      "supply chain's USGS block gives the withheld problem");
  }

  // Concentration & risk.
  part = "conc";
  const c = page.conc;
  if (risk && chapter) {
    const wantRows = Object.keys(risk.series).filter((sid) => chapter.series.some((x) => x.id === sid));
    need(same(c.rows.map((r) => r.series), wantRows), `concentration rows ${JSON.stringify(c.rows.map((r) => r.series))}`);
    for (const row of c.rows) {
      const series = chapter.series.find((x) => x.id === row.series), ind = risk.series[row.series];
      if (!series || !ind) continue;
      need(series.leader.shown !== null ? row.cr1 === n(`${series.leader.countries[0]} ${series.leader.shown}%`) : !row.cr1.includes("%"), `${row.series} CR1`);
      need(series.top3.shown !== null ? row.cr3.startsWith(`${series.top3.shown}%`) && series.top3.countries.every((x) => row.cr3.includes(x))
        : !row.cr3.includes("%"), `${row.series} CR3`);
      const full = ind.hhi_low !== null && ind.hhi_high !== null && ind.named_share !== null;
      need(full ? same(row.hhi, { range: hhiRange(ind.hhi_low, ind.hhi_high), coverage: coverage(ind.named_share, ind.over_total) })
        : row.hhi === null, `${row.series} HHI ${JSON.stringify(row.hhi)}`);
    }
    const groups = risk.us.imports;
    need(c.imports.length === groups.length, "one import row per source table");
    groups.forEach((g, at) => {
      const row = c.imports[at];
      if (!row) return;
      if (g.reason !== null) return need(row.cells.length === 1 && !row.cells[0].includes("%"), `import row ${at} gives only its reason`);
      need(row.cells[0] === (g.leader === null ? "No named source" : n(`${g.leader.country} ${g.leader.value}%`)), `import row ${at} leader`);
      need(row.cells[1] === (g.top3 === null ? "Fewer than three named" : `${g.top3}%`), `import row ${at} top three`);
      need(g.hhi_low === null ? row.hhi === null : same(row.hhi, { range: hhiRange(g.hhi_low, g.hhi_high), coverage: importCoverage(g.named_share) }), `import row ${at} HHI`);
    });
    if (groups.length === 0) need(c.none.includes("USGS prints no US import sources for this metal"), "no import sources sentence");
  } else need(c.tables === 0 && withheldWith(c.withheld, reply.risk.problem) && page.folds.concentration.teaser === "USGS part withheld",
    "concentration gives the withheld problem and no table");

  // Industrial uses.
  part = "uses";
  const u = page.uses;
  if (uses) {
    need(same(u.tables.map((t) => t.name), uses.map((e) => e.name)), `uses tables ${JSON.stringify(u.tables.map((t) => t.name))}`);
    for (const table of u.tables) {
      const entry = uses.find((e) => e.name === table.name);
      if (!entry) continue;
      need(table.key === "cps-2030" && table.scope === (entry.scope_note ?? ""), `${entry.name} key and scope`);
      need(same(table.total, [entry.total["2025"], "the base of each share", entry.total["cps-2030"]]), `${entry.name} totals`);
      if (entry.technologies === null) need(table.rows.length === 0 && table.none.startsWith("The IEA gives this entry's total only"), `${entry.name} has no split`);
      else need(same(table.rows, entry.technologies.map((x) => [x.label, x.values["2025"], x.share_2025 === null ? table.rows[0]?.[2] : `${x.share_2025}%`, x.values["cps-2030"]])),
        `${entry.name} technology rows`);
    }
    if (uses.length === 0) need(u.missing.includes("The IEA's energy-technology table has no entry for this metal"), "uses says no IEA entry");
    if (uses.length > 0 || ieaOn) need(same(u.selects, [`mt-${id}-uses-scenario`, `mt-${id}-uses-year`]), "uses has its own scenario and year");
  } else {
    need(u.tables.length === 0 && withheldWith(u.blocks.find((b) => b.source === "iea")?.withheld ?? [], reply.uses.problem) &&
      page.folds.uses.teaser.startsWith("IEA part withheld"), "uses' IEA block gives the withheld problem");
  }
  if (ieaOn) need(u.share.includes(`${frame.demand.energy_share["2025"]}%`), "the energy-technology share of demand");
  need(u.blocks.find((b) => b.source === "iea")?.note === USES_SCOPE, "the IEA block says it covers energy technologies only");
  need(u.note.includes("Industrial importance"), "the industrial-importance note");

  // Geopolitical exposure.
  part = "exposure";
  const e = page.exposure;
  if (research === undefined) need(withheldWith(page.exposure.withheld.slice(-1), reply.research.problem), "exposure gives the research problem");
  else {
    const events = research?.events ?? [];
    const shown = events.filter(verifiedPassage), apart = events.filter((x) => !verifiedPassage(x));
    need(same(e.events.map((x) => x.id), shown.map((x) => x.evidence.id)), `verified events ${JSON.stringify(e.events.map((x) => x.id))}`);
    shown.forEach((x, at) => need(e.events[at]?.quote === n(x.evidence.quote) && e.events[at].kind === `${x.kind} · ${x.when}` &&
      e.events[at].when === x.when && x.evidence.quote.includes(x.when) && e.events[at].source === placed(x.evidence) &&
      e.events[at].state === "verified", `event ${x.evidence.id} quoted, dated and placed`));
    need(e.quotedNote === EVENTS_NOTE, "the events block says they are past events, dated, and not a news feed");
    need(shown.length === 0 ? e.noEvent === NO_EVENT : e.noEvent === "", "the no-event sentence exactly when no event is verified");
    need(same(e.unverified.map((x) => x.id), apart.map((x) => x.evidence.id)) && (apart.length === 0 ? e.head === "" : e.head === "Cited, not verified on this read"), "unverified events listed apart");
    apart.forEach((x, at) => need(e.unverified[at]?.state === x.evidence.state && e.unverified[at].text.includes(x.evidence.problem) &&
      !e.unverified[at].text.includes(x.kind) && !e.unverified[at].dated, `unverified ${x.evidence.id} gives its reason, no kind and no date`));
  }
  if (risk) need(e.differs === String(risk.leaders_differ), "one country largest at several stages");
  else need(withheldWith(e.withheld.slice(0, 1), reply.risk.problem), "exposure's USGS block gives the withheld problem");

  // Economic transmission.
  part = "transmission";
  const tr = page.transmission;
  need(tr.written === WRITTEN_BY && reply.research.written_by === WRITTEN_BY, "the written-by sentence, exactly");
  if (research === undefined) need(withheldWith(tr.withheld, reply.research.problem) && tr.chains.length === 0, "transmission gives the research problem");
  else {
    const chains = research?.chains ?? [];
    need(same(tr.chains.map((x) => x.id), chains.map((x) => x.id)), "the chains are the reply's");
    need(chains.length > 0 || tr.none === "No transmission chain is written for this metal.", "no-chain sentence");
    need(tr.thesisLink === (research?.thesis === "copper"), "the copper thesis link");
    chains.forEach((chain, at) => {
      const shown = tr.chains[at];
      if (!shown) return;
      const counts = { measured: 0, stated: 0, withheld: 0, hypothesis: 0 };
      for (const link of chain.links) counts[link.kind === "stated" && !verifiedPassage(link) ? "withheld" : link.kind] += 1;
      const k = chain.links.length;
      need(shown.count === `${k} ${k === 1 ? "link" : "links"}: ${counts.measured} measured, ${counts.stated} stated by a source${counts.withheld > 0
        ? `, ${counts.withheld} ${counts.withheld === 1 ? "quote" : "quotes"} withheld on this read` : ""}, ${counts.hypothesis} ${counts.hypothesis === 1 ? "hypothesis" : "hypotheses"}`,
      `${chain.id} link counts "${shown.count}"`);
      need(shown.learned === n(chain.learned) && shown.assumed === n(chain.assumed), `${chain.id} learned and assumed`);
      need(shown.reading === READING, `${chain.id} labels the lists after its links as the assistant's reading`);
      need(shown.links.length === k, `${chain.id} links`);
      chain.links.forEach((link, i) => {
        const p = shown.links[i];
        if (!p) return;
        const label = `${chain.id}/${i}`;
        need(p.kind === link.kind && p.badge === BADGES[link.kind] && p.text === n(link.text), `${label} kind, label and text`);
        if (link.kind === "measured") {
          need(link.shown !== null ? p.measured === n(link.shown) : p.measured === null && p.all.includes(n(link.unavailable)), `${label} measured value or reason`);
          if (link.shown !== null && "stage" in link.ref && link.ref.figure === "hhi" && risk) {
            const match = Object.values(risk.series).find((ind) => ind.hhi_low !== null && hhiRange(ind.hhi_low, ind.hhi_high) === link.shown);
            need(match && p.coverage === coverage(match.named_share, match.over_total), `${label} HHI coverage ${p.coverage}`);
          }
        } else if (link.kind === "stated") {
          if (verifiedPassage(link)) need(p.passage?.state === "verified" && p.passage.quote === n(link.evidence.quote) &&
            p.passage.source === placed(link.evidence), `${label} verified quote`);
          else need(p.passage?.state === link.evidence.state && p.passage.quote === "" && p.all.includes(n(link.evidence.problem)), `${label} withheld quote gives its reason`);
        } else need(p.measured === null && p.passage === null, `${label} hypothesis shows no value or quote`);
      });
    });
  }
  return bad;
}

/** A series' expected HHI as the page shows it ({ range, coverage }), or null when it is not shown. */
export const hhiOf = (ind) => (ind && ind.hhi_low !== null && ind.hhi_high !== null && ind.named_share !== null
  ? { range: hhiRange(ind.hhi_low, ind.hhi_high), coverage: coverage(ind.named_share, ind.over_total) } : null);
