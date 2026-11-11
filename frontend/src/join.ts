// Join each frozen leg with its recorded result and prepared view. Any gap or contradiction makes the
// prepared view unusable; nothing is inferred or filled in.

import type { Dossier, JoinedLeg } from "./types";

export function joinLegs(dossier: Dossier): JoinedLeg[] | null {
  const evaluation = dossier.evaluation;
  if ((dossier.state === "evaluated") !== (evaluation !== null)) return null;
  const joined = dossier.hypothesis.legs.map((definition) => ({
    definition,
    result: evaluation ? evaluation.legs.find((result) => result.leg_id === definition.id) : null,
    view: dossier.legs.find((view) => view.leg_id === definition.id),
    node: dossier.hypothesis.nodes.find((node) => node.id === definition.node_id),
  }));
  const consistent = joined.every(({ result, view, node }) => {
    if (!view || !node || result === undefined) return false;
    // Before evaluation nothing has been measured, so nothing may be drawn.
    if (result === null) return view.series === null && view.reference === null && view.anchor_dates === null;
    // A date-only series can be marked only by its recorded New York anchor dates.
    return view.series?.time_basis !== "daily_date" || view.anchor_dates !== null;
  });
  return consistent ? (joined as JoinedLeg[]) : null;
}
