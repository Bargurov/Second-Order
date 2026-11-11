import type { LegDefinition, MapEdge, MapNode } from "../types";
import { CAPTION_H, PAD, edgePath, layout, useNarrow, type Orientation } from "./TransmissionMap";

const LINE_H = 17;
const CAPTION_CHAR = 6.9; // Advance of the 9.5px uppercase monospace caption, including letter spacing.
const LINE_CHAR = 6.95; // Advance of the 11px monospace proposal line.

/** Longest wording first; a narrow box (several nodes in one row on a phone) takes the first that fits. */
const CAPTIONS: Record<MapNode["kind"], string[]> = {
  event: ["Event"],
  channel: ["Channel · proposed", "Channel"],
  observable: ["Observable · proposed", "Observable"],
  explanatory: ["Explanatory · context", "Explanatory", "Context"],
};

function fitting(options: string[], width: number, advance: number): string {
  const room = Math.floor((width - 2 * PAD) / advance);
  const found = options.find((option) => option.length <= room);
  return found ?? `${options[options.length - 1].slice(0, Math.max(1, room - 1))}…`;
}

/**
 * The model's proposed map, drawn with the Dossier map's layout. Nothing on it is tested or evaluated: an
 * observable carries the proposed direction and horizon, never a verdict.
 */
export function DraftMap({ nodes, edges, legs }: { nodes: MapNode[]; edges: MapEdge[]; legs: LegDefinition[] }) {
  const orientation: Orientation = useNarrow() ? "tb" : "lr";
  const { boxes, width, height } = layout(nodes, edges, orientation);
  const legByNode = new Map(legs.map((leg) => [leg.node_id, leg]));
  const kindOf = new Map(nodes.map((node) => [node.id, node.kind]));
  const description = `Proposed map with ${nodes.length} nodes and ${edges.length} links; each leg is listed below.`;

  return (
    <svg className="map draft-map" viewBox={`0 0 ${width} ${height}`} role="img" aria-label={description}>
      <defs>
        <marker id="draft-map-arrow" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="7" markerHeight="7"
                orient="auto">
          <path d="M 0 0 L 10 5 L 0 10 z" className="map-arrowhead" />
        </marker>
      </defs>
      {edges.map((edge) => {
        const from = boxes.get(edge.source);
        const to = boxes.get(edge.target);
        if (!from || !to) return null;
        return (
          <path
            key={`${edge.source}->${edge.target}`}
            d={edgePath(from, to, orientation)}
            className={`map-edge${kindOf.get(edge.source) === "explanatory" ? " is-explanatory" : ""}`}
            markerEnd="url(#draft-map-arrow)"
          />
        );
      })}
      {[...boxes.values()].map((box) => {
        const leg = legByNode.get(box.node.id);
        const role = leg ? (leg.primary ? "Primary" : "Secondary") : null;
        const caption = fitting(role ? [`${role} · proposed`, role] : CAPTIONS[box.node.kind], box.w, CAPTION_CHAR);
        const arrow = leg?.expected === "up" ? "↑" : "↓";
        const proposal = leg && fitting(
          [`${arrow} ${leg.expected} · ${leg.horizon} obs`, `${arrow} ${leg.horizon} obs`, arrow], box.w, LINE_CHAR);
        return (
          <g key={box.node.id} transform={`translate(${box.x} ${box.y})`} className={`map-node kind-${box.node.kind}`}>
            <rect className="map-frame" width={box.w} height={box.h} rx={3} />
            <text className="map-caption" x={PAD} y={PAD + 9}>{caption.toUpperCase()}</text>
            {box.lines.map((line, i) => (
              <text key={i} className="map-label" x={PAD} y={PAD + CAPTION_H + 12 + i * LINE_H}>{line}</text>
            ))}
            {leg && (
              <text className="map-verdict draft-map-proposal" x={PAD} y={box.h - PAD + 1}>
                {proposal}
              </text>
            )}
          </g>
        );
      })}
    </svg>
  );
}
