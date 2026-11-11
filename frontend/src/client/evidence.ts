// The evidence of a recorded analysis, as the Client shows it: where each quote sits in the captured source text (the
// server's code-point offsets, already checked by the contract's reader) and the text split into marked and unmarked
// passages. The quotes are the publisher's words; nothing here rewrites them.
import type { EvidencePart, LocatedQuote, ResearchContent } from "../contracts/user.ts";

const range = (numbers: number[]) => {
  const sorted = [...new Set(numbers)].sort((a, b) => a - b);
  if (sorted.length === 0) return "";
  const first = sorted[0];
  const last = sorted[sorted.length - 1];
  return first === last ? `Paragraph ${first}` : `Paragraphs ${first}–${last}`;
};

const PART: Record<EvidencePart, string> = {
  headline: "its headline", excerpt: "its feed excerpt", text: "its publication text",
};

/** "Paragraph 3, characters 120–198", with a note when the match needed plain quotation marks or spacing. A Go deeper
 * source's quote also names where it comes from: "Report 2, Synthetic Ledger, its feed excerpt". */
export function locator(quote: LocatedQuote): string {
  const where = `${range(quote.paragraphs)}, characters ${quote.start + 1}–${quote.end}`;
  const from = quote.evidence ? `; Report ${quote.evidence.report}, ${quote.evidence.publisher}, ` +
    `${PART[quote.evidence.part]}` : "";
  const match = quote.match === "normalized" ? "; matched after making quotation marks, dashes and spacing plain" : "";
  const among = quote.evidence ? "in the publishers' words" : "in the source";
  const repeated = quote.occurrences > 1 ? `; this passage occurs ${quote.occurrences} times ${among}` : "";
  return `${where}${from}${match}${repeated}`;
}

export interface Segment { text: string; statements: number[] }

/** The source text as consecutive segments; a segment inside one or more quotes lists the statements quoting it. */
export function markedSource(source: string, content: ResearchContent | null): Segment[] {
  const characters = Array.from(source);
  const owners: number[][] = characters.map(() => []);
  for (const item of content?.established ?? []) {
    for (const quote of item.quotes) {
      for (let index = quote.start; index < Math.min(quote.end, characters.length); index++) {
        if (!owners[index].includes(item.number)) owners[index].push(item.number);
      }
    }
  }
  const segments: Segment[] = [];
  characters.forEach((character, index) => {
    const statements = owners[index];
    const last = segments.at(-1);
    if (last && last.statements.join() === statements.join()) last.text += character;
    else segments.push({ text: character, statements: [...statements] });
  });
  return segments;
}
