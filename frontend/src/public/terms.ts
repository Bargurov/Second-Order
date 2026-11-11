// The server's credit terms (GET /api/public/credit-terms) as the credits pages show them. Every rule, Effort, note
// and number is the server's, read at the time; nothing here copies, rounds or extends them. When the server has no
// credit terms, no number is shown at all.
import type { CreditTerms } from "../contracts/onboarding.ts";

export const EXAMPLES_CAPTION = "Quotes this server would issue now, under its current credit policy, for three " +
  "synthetic sources of plain English text. Your own source gets its own quote.";

export interface TermsView {
  configured: boolean;
  rules: string[];
  /** The server's reason when no terms are set. */
  detail: string | null;
  policy: string | null;
  efforts: string[];
  effortNote: string;
  sizeNote: string | null;
  validity: string | null;
  /** Column headings: the offered Efforts' labels, in the server's order. */
  columns: string[];
  examples: { key: string; label: string; characters: string; cells: string[] }[];
  /** Every example is quoted the same at each Effort, whatever its length: under these terms the Effort decides. */
  sizeNeutral: boolean;
  /** When sizeNeutral, the quote at each Effort (read from the examples); otherwise empty. */
  perEffort: { label: string; credits: string }[];
}

const unit = (count: number, one: string) => `${count} ${one}${count === 1 ? "" : "s"}`;

/** "15 minutes", "1 hour", "1 minute 30 seconds". */
export function validityText(seconds: number): string {
  if (seconds % 3600 === 0) return unit(seconds / 3600, "hour");
  if (seconds % 60 === 0) return unit(seconds / 60, "minute");
  return `${unit(Math.floor(seconds / 60), "minute")} ${unit(seconds % 60, "second")}`;
}

export function termsView(terms: CreditTerms): TermsView {
  const configured = terms.state === "configured";
  const first = terms.examples[0]?.quotes.map((quote) => quote.credits) ?? [];
  const sizeNeutral = configured && terms.examples.length > 0 && terms.examples.every((example) =>
    example.quotes.every((quote, index) => quote.credits === first[index]));
  return {
    sizeNeutral,
    perEffort: sizeNeutral ? terms.efforts.map((option, index) => ({ label: option.label, credits: String(first[index]) }))
      : [],
    configured, rules: terms.rules, detail: configured ? null : terms.detail,
    policy: terms.policy_version, efforts: terms.efforts.map((option) => option.label), effortNote: terms.effort_note,
    sizeNote: terms.size_note,
    validity: terms.quote_valid_seconds === null ? null : validityText(terms.quote_valid_seconds),
    columns: terms.efforts.map((option) => option.label),
    examples: terms.examples.map((example) => ({ key: example.example, label: example.label,
      characters: `${example.characters.toLocaleString("en")} characters`,
      cells: example.quotes.map((quote) => String(quote.credits)) })),
  };
}
