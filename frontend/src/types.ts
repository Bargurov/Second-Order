// Shapes of the prepared, read-only Dossier views (view_version "dossier-view-0.3").

export type LegVerdict = "supported" | "contradicted" | "inconclusive" | "unavailable" | "excluded" | "pending";
export type DossierVerdict = LegVerdict | "mixed" | "incomplete";

export type DossierState = "evaluated" | "not_evaluated";

export interface DossierSummary {
  id: string;
  headline: string;
  published_at: string;
  label: string;
  source: "fixture" | "store";
  state: DossierState;
  evidence_class: "prospective" | "replay";
  usage: "showcase" | "research";
  evaluation_id: string | null;
  verdict: DossierVerdict | null;
  rules_version: string | null;
  as_of: string | null;
}

export interface DossierIndex {
  view_version: string;
  fixture_as_of: string;
  active_rules_version: string;
  dossiers: DossierSummary[];
}

export interface SnapshotSummary {
  snapshot_id: string;
  /** A FRED real-time date; null for the Board's H.15 release package, which has no historical vintage. */
  vintage_date: string | null;
  retrieved_at: string;
  adapter_version: string;
}

export interface DataProvenance {
  provider: string;
  attribution: string;
  measurement_convention: string;
  baseline: SnapshotSummary;
  outcome: SnapshotSummary | null;
}

export type AnchorKey = "event_anchor" | "reference_end" | "score_anchor" | "target_at";

export interface MapNode {
  id: string;
  label: string;
  kind: "event" | "channel" | "observable" | "explanatory";
}

export interface MapEdge {
  source: string;
  target: string;
}

export interface LegDefinition {
  id: string;
  node_id: string;
  primary: boolean;
  channel: string;
  observable_id: string;
  link: "direct" | "proxy";
  expected: "up" | "down";
  horizon: 1 | 5 | 20;
  falsifier: string;
  rationale: string;
  headline_reports_move: boolean;
}

export interface Hypothesis {
  event: { headline: string; source_url: string; published_at: string };
  frozen_at: string;
  replay_as_of: string | null;
  evidence_class: "prospective" | "replay";
  usage: "showcase" | "research";
  story_id: string;
  engine: { provider: string; model: string; prompt_hash: string; schema_version: string };
  summary: string;
  nodes: MapNode[];
  edges: MapEdge[];
  legs: LegDefinition[];
  supersedes: string | null;
}

export type OutcomeRates = Record<"supported" | "contradicted" | "inconclusive", number | null>;

export interface Placebo {
  requested: number;
  selected: number;
  eligible: number;
  unavailable: number;
  rates: OutcomeRates;
  selected_dates: string[];
}

export interface LegResult {
  leg_id: string;
  primary: boolean;
  observable_id: string;
  horizon: number;
  unit: string;
  verdict: LegVerdict;
  measured_change: number | null;
  signed_move: number | null;
  percentile_rank: number | null;
  reference_windows: number;
  non_overlapping_reference_windows: number;
  reason: string;
  event_anchor?: string;
  score_anchor?: string;
  reference_end?: string;
  target_at?: string;
  anchor_policy?: string;
  placebo?: Placebo;
}

export interface Rules {
  version: string;
  upper: number;
  lower: number;
  reference_days: number;
  min_windows: number;
  estimation_days: number;
  estimation_gap: number;
  placebo_dates: number;
}

export interface Evaluation {
  hypothesis_id: string;
  as_of: string;
  rules: Rules;
  rules_hash: string;
  verdict: DossierVerdict;
  legs: LegResult[];
  data_hash: string;
}

export interface ReferenceView {
  values: number[];
  event_signed_move: number;
  below: number;
  equal: number;
  above: number;
  histogram: { edges: number[]; counts: number[] };
}

/** Provenance of a fixture showcase series: FICTIONAL demonstration series and the generator that invented them. */
export interface SeriesProvenance {
  provider: string;
  ticker: string;
  price_basis: string;
  description: string;
  version: string;
  generator: string;
  timestamp_basis: string;
  timestamp_note: string;
}

export interface SeriesView {
  label: string;
  quote_unit: string;
  /** "daily_date": points carry New York observation dates (YYYY-MM-DD), never a time of day. */
  time_basis: "timestamp" | "daily_date";
  points: [string, number | null][];
  provenance: SeriesProvenance | null;
  caption: string | null;
  attribution: string | null;
}

export interface LegView {
  leg_id: string;
  unit: string;
  measurement: string;
  reference: ReferenceView | null;
  series: SeriesView | null;
  /** New York dates of the recorded anchors, present for the daily convention. */
  anchor_dates: Partial<Record<AnchorKey, string>> | null;
}

export interface Dossier {
  view_version: string;
  id: string;
  label: string;
  state: DossierState;
  hypothesis: Hypothesis;
  evaluation: Evaluation | null;
  evaluation_id: string | null;
  legs: LegView[];
  research: { enters_research_scores: boolean; reason: string };
  limitations: { title: string; text: string }[];
  data_provenance: DataProvenance | null;
  published_date: string | null;
}

/** One leg with its frozen definition, recorded result (absent before evaluation) and prepared view. */
export interface JoinedLeg {
  definition: LegDefinition;
  result: LegResult | null;
  view: LegView;
  node: MapNode;
}
