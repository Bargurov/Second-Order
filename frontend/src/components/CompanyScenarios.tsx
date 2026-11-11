import { useId, useRef, useState, type ReactNode } from "react";
import {
  BASE_VALUE, beyondOneStep, computeScenario, modeState, money, PRICE, priceProblem, priceText, SENSITIVITY, signedNumber, STEP,
  VOLUME, volumeProblem, volumeText, type Inputs, type Mode, type ScenarioAction, type ScenarioReply,
} from "../companyScenarios";
import { figureText, isFigure, type Block, type CompanyView } from "../companyResearch";
import { inputKey, Latest, latest } from "../copperRequests";
import { Figure, Fold, KindBadge, Line, Lines, SOURCE_SHORT, Stamp, useCompany, Withheld, Words } from "./CompanyBits";
import { TabList } from "./MetalsBits";

const RELEASE = "release-2026q3";
/** The hash part of each calculation: "#scenarios" and "#scenarios:cash-flow". */
export const CALC_HASH: Record<Mode, string | null> = { price_volume: null, cash_flow: "cash-flow" };
export const calcOf = (sub: string | null): Mode => (sub === "cash-flow" ? "cash_flow" : "price_volume");

/**
 * The Scenarios tab (stage 2): two separate calculations on the company's assumptions for Q4 2026, never added
 * together. Price × volume shows an approximate copper sales value, its change from the company's assumptions and the
 * change split in one fixed order; the published sensitivity applies the company's approximate cash flow figure
 * linearly to a price change. The server computes each one exactly on the records verified now
 * (POST /api/companies/fcx/scenario) and the page checks the reply again (companyScenarios.ts). A result is shown only
 * for the inputs it was computed for. A calculation whose records rest on a document that is not verified is not
 * offered, and its explanations are withheld with it.
 */
export function Scenarios({ mode, onMode }: { mode: Mode; onMode: (mode: Mode) => void }) {
  const { view } = useCompany();
  const texts = view.page.scenarios;
  return (
    <>
      <h2 className="co-h2">Scenarios</h2>
      <Stamp />
      <p className="co-plain"><Words block={texts.intro} /></p>
      <Marks />
      <TabList label="Calculation" className="mt-chooser co-chooser co-calc-tabs" active={mode} onSelect={onMode}
               tabs={[{ id: "price_volume" as Mode, label: texts.price_volume.short },
                 { id: "cash_flow" as Mode, label: texts.cash_flow.short }]}
               idFor={(id) => `co-calc-${id}`} panelFor={(id) => `co-calc-panel-${id}`} />
      <section role="tabpanel" id="co-calc-panel-price_volume" aria-labelledby="co-calc-price_volume" data-calc="price_volume"
               className="co-calc" hidden={mode !== "price_volume"}><PriceVolume /></section>
      <section role="tabpanel" id="co-calc-panel-cash_flow" aria-labelledby="co-calc-cash_flow" data-calc="cash_flow"
               className="co-calc" hidden={mode !== "cash_flow"}><CashFlow /></section>
    </>
  );
}

function Marks() {
  return (
    <p className="co-legend co-marks" data-marks="">
      <span><KindBadge kind="estimate" /> Company assumption</span>
      <span><span className="co-mark" data-mark="input">You</span> Your input</span>
      <span><KindBadge kind="computed" /> Computed by this project</span>
    </p>
  );
}

/** The company's assumptions a calculation starts from, with the document and its date. */
function Base({ items, extra }: { items: { label: string; record: string }[]; extra?: ReactNode }) {
  const { view } = useCompany();
  const release = view.sources.find((source) => source.id === RELEASE);
  return (
    <div className="co-calc-base" data-base="">
      <p className="co-badge" data-badge="estimate">Company assumptions for the fourth quarter of 2026 · {
        SOURCE_SHORT[RELEASE]}{release && release.state !== "verified" ? ` (${release.state})` : ""}</p>
      <dl className="co-estimates">{items.map((item) => (
        <div key={item.record}><dt>{item.label}</dt><dd><Figure id={item.record} /></dd></div>))}</dl>
      {extra}
    </div>
  );
}

function Blocked({ problem }: { problem: string | null }) {
  return <p className="co-calc-blocked" data-calc-blocked="" role="note">This calculation is not offered:{" "}
    <Withheld problem={problem} /></p>;
}

/** The base value of a record as it is entered: its printed form ("6.50", "875"). */
function entry(view: CompanyView, id: string): string {
  const record = view.records[id];
  return isFigure(record) && record.state === "available" && record.kind === "published" ? record.display ?? "" : "";
}

// ---------------------------------------------------------------- one calculation's inputs and reply

interface Calc {
  inputs: Inputs; set: (field: "price" | "volume", text: string) => void; reset: () => void; compute: () => void;
  problems: { price: string | null; volume: string | null }; tried: boolean; busy: boolean; action: ScenarioAction | null;
}

/** Inputs, their problems and the reply for exactly these inputs (the copper tools' tickets: a changed input
 * invalidates every reply in flight and removes the one on screen). A calculation the server blocks (a document it
 * rests on changed since the page was read) makes the page read everything again, so no figure or line from the
 * earlier read stays on screen; this holds for a late blocked reply too, sent for inputs that have changed since,
 * while a late result is still never shown. */
function useCalc(view: CompanyView, mode: Mode, initial: Inputs): Calc {
  const { reload } = useCompany();
  const [inputs, setInputs] = useState<Inputs>(initial);
  const [answer, setAnswer] = useState<{ key: string; action: ScenarioAction } | null>(null);
  const [busy, setBusy] = useState(false);
  const [tried, setTried] = useState(false);
  const gate = useRef(new Latest());
  const sent: Inputs = mode === "price_volume" ? { price: inputs.price.trim(), volume: (inputs.volume ?? "").trim() }
    : { price: inputs.price.trim() };
  const key = inputKey({ mode, ...sent });
  const current = useRef(key);
  current.current = key;
  const forget = () => { gate.current.invalidate(); setAnswer(null); setBusy(false); };
  const problems = { price: priceProblem(sent.price), volume: mode === "price_volume" ? volumeProblem(sent.volume ?? "") : null };
  return {
    inputs, problems, tried, busy,
    set: (field, text) => { setInputs((now) => ({ ...now, [field]: text })); forget(); },
    reset: () => { setInputs(initial); setTried(false); forget(); },
    compute: async () => {
      setTried(true);
      if (problems.price || problems.volume) { forget(); return; }
      setBusy(true);
      const outcome = await latest(gate.current, key, () => current.current, async () => {
        const action = await computeScenario(view, mode, sent)
          .catch((): ScenarioAction => ({ state: "failed", message: "The reply could not be read. Nothing was stored." }));
        // A blocked reply says a document changed after the page was read: the whole read is stale, whatever inputs
        // the request was sent for, so the page reads again before the ticket decides whether this reply is shown.
        if (action.state === "blocked") reload();
        return action;
      });
      if (!outcome.used) return;  // superseded, or sent for other inputs: never shown
      setAnswer({ key, action: outcome.value });
      setBusy(false);
    },
    action: answer !== null && answer.key === key ? answer.action : null,
  };
}

function Field({ calc, field, label, hint, mode }: {
  calc: Calc; field: "price" | "volume"; label: string; hint: string; mode: Mode;
}) {
  const id = useId();
  const text = field === "price" ? calc.inputs.price : calc.inputs.volume ?? "";
  const problem = calc.problems[field];
  const shown = problem !== null && (calc.tried || text.trim() !== "");
  return (
    <label className="co-field" htmlFor={`${id}-input`}>
      <span className="co-field-label"><span className="co-mark" data-mark="input">You</span> {label}</span>
      <input id={`${id}-input`} type="text" inputMode="decimal" autoComplete="off" spellCheck={false} value={text}
             data-input={field} aria-invalid={shown} aria-describedby={`${id}-hint ${id}-error`}
             onChange={(event) => calc.set(field, event.target.value)} name={`${mode}-${field}`} />
      <span id={`${id}-hint`} className="co-field-hint">{hint}</span>
      <span id={`${id}-error`} className="co-field-error" data-input-error={field} hidden={!shown}>{shown ? problem : ""}</span>
    </label>
  );
}

function Form({ calc, mode, children }: { calc: Calc; mode: Mode; children: ReactNode }) {
  return (
    <form className="co-calc-form" data-scenario-form="" noValidate
          onSubmit={(event) => { event.preventDefault(); calc.compute(); }}>
      <div className="co-calc-fields">{children}</div>
      <div className="co-calc-actions">
        <button type="submit" className="button co-compute" data-action="compute" disabled={calc.busy}>Compute</button>
        <button type="button" className="button co-reset" data-action="reset" onClick={calc.reset}>Reset to the company's
          assumptions</button>
      </div>
      <span className="co-sr" aria-live="polite">{calc.busy ? `Computing the ${mode === "price_volume" ? "price × volume"
        : "cash flow"} calculation` : ""}</span>
    </form>
  );
}

/** The result region: empty, computing, refused or blocked, or the reply for exactly the current inputs. */
function Result({ calc, children }: { calc: Calc; children: (data: ScenarioReply) => ReactNode }) {
  const action = calc.action;
  const state = action === null ? (calc.busy ? "computing" : "empty") : action.state === "ready" ? "ready"
    : action.state === "blocked" ? "blocked" : "error";
  const ready = action?.state === "ready" ? action.data : null;
  return (
    <section className="co-calc-result" data-result="" data-result-state={state} aria-live="polite"
             data-price={ready?.inputs.price} data-volume={ready?.inputs.volume} aria-label="Result">
      {ready && children(ready)}
      {action && action.state !== "ready" && <p role="alert" className="co-calc-error">{action.message}</p>}
      {!action && <p className="co-calc-empty">{calc.busy ? "Computing…"
        : "Press Compute: the result appears here, for the inputs it was computed for."}</p>}
    </section>
  );
}

const Row = ({ out, label, value }: { out: string; label: ReactNode; value: string }) => (
  <div data-row={out}><dt>{label}</dt><dd data-out={out}>{value}</dd></div>);

// ---------------------------------------------------------------- price × volume

function PriceVolume() {
  const { view } = useCompany();
  const texts = view.page.scenarios.price_volume;
  const state = modeState(view, "price_volume");
  const price = entry(view, PRICE), volume = entry(view, VOLUME);
  return (
    <>
      <h3 className="co-h3">{texts.title}</h3>
      <Base items={texts.base} extra={<p className="co-calc-base-value">{texts.base_value.label}:{" "}
        <Figure id={BASE_VALUE} /></p>} />
      {state.available ? <PriceVolumeCalc price={price} volume={volume} definition={texts.definition} />
        : <Blocked problem={state.problem} />}
      <Fold part="pv-formulas" title="Formulas" teaser="Price × volume, the change and its split">
        <Formulas lines={state.available ? [
          ["Price × volume", `price ($ a pound) × volume (million pounds) = US$ million`],
          ["At the company's assumptions", `${priceText(price)} × ${volumeText(volume)} = ${amount(view, BASE_VALUE)}`],
          ["Change", "your price × your volume − price × volume at the company's assumptions"],
          ["Volume effect", "(your volume − company volume) × company price"],
          ["Price effect", "(your price − company price) × your volume"],
          ["Check", "price effect + volume effect = change, exactly; nothing is rounded"],
        ] : [["Price × volume", "price × volume; the company's figures are not shown"]]} />
        <Lines blocks={texts.method} />
      </Fold>
      <Fold part="pv-sources" title="Sources and dates" teaser="The company's price and volume for the fourth quarter">
        <Lines blocks={texts.sources} />
      </Fold>
      <Fold part="pv-costs" title="Why a change in volume gives no cash flow figure here"
            teaser="Fixed and variable costs are not split in these documents">
        <Lines blocks={texts.costs} />
      </Fold>
    </>
  );
}

/** A shown record as a sentence reads it ("$0.10", "$75 million"), for the formula lines. */
const amount = (view: CompanyView, id: string) => {
  const record = view.records[id];
  return isFigure(record) && record.state === "available" ? figureText(record) : "not shown";
};
/** A signed price change to the cent: "+$0.10", "−$0.13". */
function signedPrice(value: string): string {
  const negative = value.startsWith("-");
  const body = value.replace(/^-/, "");
  return `${negative ? "−" : /^[0.]+$/.test(body) ? "" : "+"}${priceText(body)}`;
}

function Formulas({ lines }: { lines: [string, string][] }) {
  return <dl className="co-formulas">{lines.map(([name, text]) => (
    <div key={name}><dt>{name}</dt><dd><code>{text}</code></dd></div>))}</dl>;
}

function PriceVolumeCalc({ price, volume, definition }: { price: string; volume: string; definition: Block }) {
  const { view } = useCompany();
  const calc = useCalc(view, "price_volume", { price, volume });
  return (
    <div className="co-calc-work">
      <Form calc={calc} mode="price_volume">
        <Field calc={calc} mode="price_volume" field="price" label="Copper price, US$ per pound"
               hint={`The company assumes ${priceText(price)}`} />
        <Field calc={calc} mode="price_volume" field="volume" label="Copper sold, million pounds (sales, not production)"
               hint={`The company: ${volumeText(volume)}`} />
      </Form>
      <Result calc={calc}>{(data) => (
        <>
          <p className="co-calc-for">For {priceText(data.inputs.price)} a pound and {volumeText(data.inputs.volume ?? "")}
            {" "}<KindBadge kind="computed" /> <span className="co-sub">Computed by this project</span></p>
          <p className="co-calc-main"><span data-out="value">{money(data.result.value)}</span>
            <span className="co-calc-main-label"> price × volume</span></p>
          <p className="co-calc-definition" data-definition=""><Words block={definition} /></p>
          <dl className="co-calc-split">
            <Row out="change" label="Change from the company's assumptions" value={money(data.result.change, true)} />
            <Row out="price_effect" label="Price effect, on your volume" value={money(data.result.price_effect, true)} />
            <Row out="volume_effect" label="Volume effect, at the company's price"
                 value={money(data.result.volume_effect, true)} />
          </dl>
        </>)}
      </Result>
    </div>
  );
}

// ---------------------------------------------------------------- the published cash flow sensitivity

function CashFlow() {
  const { view } = useCompany();
  const texts = view.page.scenarios.cash_flow;
  const state = modeState(view, "cash_flow");
  const price = entry(view, PRICE);
  return (
    <>
      <h3 className="co-h3">{texts.title}</h3>
      <Base items={texts.base} />
      <div className="co-calc-notes"><Line block={texts.held} /><Line block={texts.linear} /></div>
      {state.available ? <CashFlowCalc price={price} /> : <Blocked problem={state.problem} />}
      <Fold part="cf-formula" title="Formula" teaser="The company's figure, applied linearly">
        <Formulas lines={state.available ? [
          ["Price change", `your price − ${priceText(price)}`],
          ["Steps", `price change ÷ ${amount(view, STEP)}`],
          ["Change in 2026 operating cash flows", `≈ steps × ${amount(view, SENSITIVITY)}`],
        ] : [["Change in operating cash flows", "≈ price change ÷ step × the company's figure; not shown"]]} />
      </Fold>
      <Fold part="cf-words" title="The company's figure, in its words" teaser="Results release, page ten">
        <Line block={texts.definition} />
      </Fold>
      <Fold part="cf-versus" title="Why this is not price × volume" teaser="Two measures of one price move">
        <Line block={texts.versus} />
      </Fold>
      <Fold part="cf-not-used" title="Not used here" teaser="Volume changes and the 10-K's older sensitivity">
        <Lines blocks={texts.not_used} />
      </Fold>
    </>
  );
}

function CashFlowCalc({ price }: { price: string }) {
  const { view } = useCompany();
  const calc = useCalc(view, "cash_flow", { price });
  return (
    <div className="co-calc-work">
      <Form calc={calc} mode="cash_flow">
        <Field calc={calc} mode="cash_flow" field="price" label="Average copper price in the fourth quarter, US$ per pound"
               hint={`The company assumes ${priceText(price)}`} />
      </Form>
      <Result calc={calc}>{(data) => (
        <>
          <p className="co-calc-for">For {priceText(data.inputs.price)} a pound <KindBadge kind="computed" />{" "}
            <span className="co-sub">Computed by this project from the company's figure</span></p>
          <p className="co-calc-main">≈ <span data-out="change">{money(data.result.change, true)}</span>
            <span className="co-calc-main-label"> change in consolidated operating cash flows for 2026</span></p>
          <dl className="co-calc-split">
            <Row out="price_change" label="Price change" value={`${signedPrice(data.result.price_change)} a pound`} />
            <Row out="steps" label={`Steps of ${amount(view, STEP)}`}
                 value={signedNumber(data.result.steps)} />
          </dl>
          {beyondOneStep(data.result.steps) && <p className="co-calc-steps" data-steps-note="">That is{" "}
            {data.result.steps.replace(/^-/, "")} steps of {amount(view, STEP)}. The company gives its figure for each step
            around {priceText(entry(view, PRICE))}; using it {data.result.steps.replace(/^-/, "")} times over is this
            project's arithmetic, not a range the company has confirmed.</p>}
          <p className="co-calc-definition" data-definition="">This project's linear use of the company's approximate
            figure, with volumes, costs and the company's other assumptions as the company states them. Not a range the
            company has confirmed.</p>
        </>)}
      </Result>
    </div>
  );
}
