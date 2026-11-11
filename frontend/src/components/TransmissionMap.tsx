import { useEffect, useState, type KeyboardEvent } from "react";
import { verdictStatus } from "../format";
import type { JoinedLeg, MapEdge, MapNode } from "../types";

export type Orientation = "lr" | "tb";

interface Box {
  node: MapNode;
  lines: string[];
  x: number;
  y: number;
  w: number;
  h: number;
}

export const PAD = 12;
export const CAPTION_H = 17;
const LINE_H = 17;
const VERDICT_H = 22; // Also the proposed-direction line of a draft map (DraftMap).
const MARGIN = 8;
const NARROW_WIDTH = 360;
const VERDICT_CHAR = 6.95; // Advance of the 11px monospace verdict line, including letter spacing.

const CAPTION: Record<MapNode["kind"], string> = {
  event: "Event",
  channel: "Channel",
  observable: "Tested",
  explanatory: "Explanatory · unscored",
};

function wrap(text: string, maxChars: number, maxLines = 4): string[] {
  const lines: string[] = [];
  let line = "";
  for (const word of text.split(/\s+/)) {
    const next = line ? `${line} ${word}` : word;
    if (next.length > maxChars && line) {
      lines.push(line);
      line = word;
    } else {
      line = next;
    }
  }
  if (line) lines.push(line);
  return lines.length > maxLines ? [...lines.slice(0, maxLines - 1), `${lines[maxLines - 1]}…`] : lines;
}

/** Longest-path layers; an explanatory root sits one layer before the nodes it explains. */
function layers(nodes: MapNode[], edges: MapEdge[]): MapNode[][] {
  const parents = new Map(nodes.map((node) => [node.id, [] as string[]]));
  const children = new Map(nodes.map((node) => [node.id, [] as string[]]));
  for (const edge of edges) {
    parents.get(edge.target)?.push(edge.source);
    children.get(edge.source)?.push(edge.target);
  }
  const depth = new Map<string, number>();
  const visit = (id: string): number => {
    const known = depth.get(id);
    if (known !== undefined) return known;
    const value = Math.max(-1, ...(parents.get(id) ?? []).map(visit)) + 1;
    depth.set(id, value);
    return value;
  };
  nodes.forEach((node) => visit(node.id));
  for (const node of nodes) {
    const targets = children.get(node.id) ?? [];
    if (node.kind === "explanatory" && !(parents.get(node.id) ?? []).length && targets.length) {
      depth.set(node.id, Math.max(0, Math.min(...targets.map((id) => depth.get(id) ?? 0)) - 1));
    }
  }
  const grouped: MapNode[][] = Array.from({ length: Math.max(...depth.values()) + 1 }, () => []);
  [...nodes]
    .sort((a, b) => Number(a.kind === "explanatory") - Number(b.kind === "explanatory"))
    .forEach((node) => grouped[depth.get(node.id) ?? 0].push(node));
  return grouped.filter((layer) => layer.length);
}

const boxHeight = (node: MapNode, lines: string[]) =>
  PAD + CAPTION_H + lines.length * LINE_H + (node.kind === "observable" ? VERDICT_H : 0) + PAD - 2;

/** Box width: fixed columns side by side; on narrow screens a row shares the width (one node may be wider). */
const widthFor = (orientation: Orientation, rowSize: number) =>
  orientation === "lr" ? 204 : rowSize === 1 ? 250 : (NARROW_WIDTH - 2 * MARGIN - (rowSize - 1) * 12) / rowSize;

export function layout(nodes: MapNode[], edges: MapEdge[], orientation: Orientation) {
  const grouped = layers(nodes, edges);
  const boxes = new Map<string, Box>();
  const sized = grouped.map((layer) =>
    layer.map((node) => {
      const lines = wrap(node.label, Math.floor((widthFor(orientation, layer.length) - 2 * PAD) / 7.1));
      return { node, lines, h: boxHeight(node, lines) };
    }),
  );
  if (orientation === "lr") {
    const width = widthFor("lr", 1);
    const gapX = 64;
    const gapY = 18;
    const columns = sized.map((column) => column.reduce((sum, box) => sum + box.h, 0) + gapY * (column.length - 1));
    const height = Math.max(...columns);
    sized.forEach((column, c) => {
      let y = MARGIN + (height - columns[c]) / 2;
      for (const box of column) {
        boxes.set(box.node.id, { ...box, x: MARGIN + c * (width + gapX), y, w: width });
        y += box.h + gapY;
      }
    });
    return { boxes, width: 2 * MARGIN + sized.length * width + (sized.length - 1) * gapX, height: height + 2 * MARGIN };
  }
  const gapY = 30;
  let y = MARGIN;
  for (const row of sized) {
    const width = widthFor("tb", row.length);
    let x = (NARROW_WIDTH - (row.length * width + (row.length - 1) * 12)) / 2;
    for (const box of row) {
      boxes.set(box.node.id, { ...box, x, y, w: width });
      x += width + 12;
    }
    y += Math.max(...row.map((box) => box.h)) + gapY;
  }
  return { boxes, width: NARROW_WIDTH, height: y - gapY + MARGIN };
}

export function edgePath(from: Box, to: Box, orientation: Orientation): string {
  if (orientation === "lr") {
    const [x1, y1, x2, y2] = [from.x + from.w, from.y + from.h / 2, to.x - 7, to.y + to.h / 2];
    const dx = Math.max(24, (x2 - x1) / 2);
    return `M ${x1} ${y1} C ${x1 + dx} ${y1}, ${x2 - dx} ${y2}, ${x2} ${y2}`;
  }
  const [x1, y1, x2, y2] = [from.x + from.w / 2, from.y + from.h, to.x + to.w / 2, to.y - 7];
  const dy = Math.max(14, (y2 - y1) / 2);
  return `M ${x1} ${y1} C ${x1} ${y1 + dy}, ${x2} ${y2 - dy}, ${x2} ${y2}`;
}

export function useNarrow(query = "(max-width: 640px)"): boolean {
  const [narrow, setNarrow] = useState(() => window.matchMedia(query).matches);
  useEffect(() => {
    const media = window.matchMedia(query);
    const update = () => setNarrow(media.matches);
    media.addEventListener("change", update);
    return () => media.removeEventListener("change", update);
  }, [query]);
  return narrow;
}

interface Props {
  nodes: MapNode[];
  edges: MapEdge[];
  legs: JoinedLeg[];
  selectedLegId: string;
  onSelect: (legId: string) => void;
}

export function TransmissionMap({ nodes, edges, legs, selectedLegId, onSelect }: Props) {
  const orientation: Orientation = useNarrow() ? "tb" : "lr";
  const { boxes, width, height } = layout(nodes, edges, orientation);
  const legByNode = new Map(legs.map((leg) => [leg.definition.node_id, leg]));
  const kindOf = new Map(nodes.map((node) => [node.id, node.kind]));

  const choose = (leg: JoinedLeg | undefined) => leg && onSelect(leg.definition.id);
  const onKey = (event: KeyboardEvent<SVGGElement>, leg: JoinedLeg | undefined) => {
    if (event.key === "Enter" || event.key === " ") {
      event.preventDefault();
      choose(leg);
    }
  };

  return (
    <svg className="map" viewBox={`0 0 ${width} ${height}`} role="group" aria-label="Hypothesis map">
      <defs>
        <marker id="map-arrow" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="7" markerHeight="7" orient="auto">
          <path d="M 0 0 L 10 5 L 0 10 z" className="map-arrowhead" />
        </marker>
      </defs>
      {edges.map((edge) => {
        const from = boxes.get(edge.source);
        const to = boxes.get(edge.target);
        if (!from || !to) return null;
        const dashed = kindOf.get(edge.source) === "explanatory";
        return (
          <path
            key={`${edge.source}->${edge.target}`}
            d={edgePath(from, to, orientation)}
            className={`map-edge${dashed ? " is-explanatory" : ""}`}
            markerEnd="url(#map-arrow)"
          />
        );
      })}
      {[...boxes.values()].map((box) => {
        const leg = legByNode.get(box.node.id);
        const selected = leg?.definition.id === selectedLegId;
        const caption = leg ? `${CAPTION.observable} · ${leg.definition.primary ? "primary" : "secondary"}` : CAPTION[box.node.kind];
        const status = leg ? verdictStatus(leg.result?.verdict ?? null) : null;
        const mark = leg?.result ? "●" : "○";
        const fullVerdict = leg && status ? `${mark} ${status.label} · ${leg.definition.horizon}-session` : "";
        const verdictText = fullVerdict.length * VERDICT_CHAR <= box.w - 2 * PAD || !status
          ? fullVerdict
          : `${mark} ${status.label}`;
        return (
          <g
            key={box.node.id}
            transform={`translate(${box.x} ${box.y})`}
            className={`map-node kind-${box.node.kind}${leg ? " is-tested" : ""}${selected ? " is-selected" : ""}`}
            role={leg ? "button" : undefined}
            tabIndex={leg ? 0 : undefined}
            aria-pressed={leg ? selected : undefined}
            aria-label={leg && status ? `${box.node.label}: ${status.label.toLowerCase()}. Select this leg.` : undefined}
            onClick={() => choose(leg)}
            onKeyDown={(event) => onKey(event, leg)}
          >
            <rect className="map-frame" width={box.w} height={box.h} rx={3} />
            {status && <rect className={`map-stripe ${status.className}`} width={4} height={box.h} rx={1} />}
            <text className="map-caption" x={PAD} y={PAD + 9}>
              {caption.toUpperCase()}
            </text>
            {box.lines.map((line, i) => (
              <text key={i} className="map-label" x={PAD} y={PAD + CAPTION_H + 12 + i * LINE_H}>
                {line}
              </text>
            ))}
            {status && (
              <text className={`map-verdict ${status.className}`} x={PAD} y={box.h - PAD + 1}>
                {verdictText}
              </text>
            )}
          </g>
        );
      })}
    </svg>
  );
}
