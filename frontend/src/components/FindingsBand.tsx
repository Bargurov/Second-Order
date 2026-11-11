import { useLoad } from "../api";
import { EVENT_STATE, fetchBand, occasionHref, occasionStatus } from "../insights";
import { Link } from "../router";
import "../insights.css";

/** The event overview's findings band: the stored state of this event's occasion, read only, with a link. */
export function FindingsBand({ kind, id }: { kind: string; id: string }) {
  const [band] = useLoad((signal) => fetchBand(kind, id, signal), `band:${kind}:${id}`);
  let body;
  if (band.state === "loading") body = <p role="status">Reading stored findings…</p>;
  else if (band.state !== "ready") body = <p>Findings could not be read: {band.message}</p>;
  else if (band.data.state === "not_checked") {
    body = <p>Not checked yet. A check of retained evidence is an explicit, local action on the
      {" "}<Link to="/findings">Findings</Link> page.</p>;
  } else if (band.data.occasion) {
    const occasion = band.data.occasion;
    body = <p><Link to={occasionHref(occasion.date)}>{occasion.date}</Link>: {occasionStatus({
      state: (occasion.state ?? "unavailable") as "checked", findings: occasion.findings, detail: occasion.detail ?? null,
    })}.</p>;
  } else {
    const event = band.data.event;
    body = <p>{event ? `${EVENT_STATE[event.state]}${event.detail ? `: ${event.detail}` : ""}` : "Not measured."}</p>;
  }
  return (
    <section id="overview-findings" className="card event-context-section overview-section findings-band"
             aria-labelledby="overview-findings-title">
      <h2 id="overview-findings-title">Treasury findings</h2>
      {body}
      <p className="findings-note">A retrospective, single-market pilot: Treasury yields around this release's date,
        from retained H.15 data. Not a verdict on the release and not a forecast.</p>
    </section>
  );
}
