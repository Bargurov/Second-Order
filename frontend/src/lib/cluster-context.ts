import type { NewsCluster } from "./api";

/** Build a compact context string from a news cluster for the analyze request. */
export function buildClusterContext(c: NewsCluster): string {
  const parts: string[] = [];
  if (c.source_count > 1) {
    const names = c.sources.map((s) => s.name).join(", ");
    parts.push(`Sources (${c.source_count}): ${names}`);
  }
  if (c.summary) parts.push(`Summary: ${c.summary}`);
  if (c.agreement) parts.push(`Agreement: ${c.agreement}`);
  if (c.consensus) {
    const con = c.consensus;
    const fields: string[] = [];
    if (con.actors) fields.push(`Actors: ${String(con.actors)}`);
    if (con.action) fields.push(`Action: ${String(con.action)}`);
    if (con.sector) fields.push(`Sector: ${String(con.sector)}`);
    if (con.geography) fields.push(`Geography: ${String(con.geography)}`);
    if (con.uncertainty) fields.push(`Uncertainty: ${String(con.uncertainty)}`);
    if (fields.length > 0) parts.push(fields.join(" | "));
  }
  return parts.join("\n");
}
