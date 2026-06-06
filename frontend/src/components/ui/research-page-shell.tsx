import type { CSSProperties, ReactNode } from "react";
import { cn } from "@/lib/utils";

/**
 * ResearchPageShell — shared chrome harmonizer for the older app pages.
 *
 * The "new" surfaces (Market Overview, Inbox Workbench, Analysis View) are
 * styled to the Direction-C ``--so-*`` palette; the older pages are still on
 * the shadcn ``.dark`` theme (navy-black / teal).  Rather than hand-edit each
 * old page's chrome, this shell sets two things on one root element:
 *
 *   1. the full ``--so-*`` Direction-C palette — so any chrome that is
 *      migrated explicitly can use ``--so-*`` classes; and
 *   2. a remap of the shadcn theme tokens (``--card`` / ``--foreground`` /
 *      ``--primary`` / …) to the SAME Direction-C values — so a page's
 *      existing shadcn-token chrome (``bg-card``, ``text-muted-foreground``,
 *      ``border-border`` …) inherits the new look with no per-element edits.
 *
 * It is deliberately **layout-neutral**: CSS variables and base text colour
 * only, no width / flex / overflow that could fight the wrapped page.  Pure
 * presentation — no data, no logic.  Grayscale surfaces convert exactly
 * (``#121212`` → ``0 0% 7%``); the citrine primary (vs the old teal) is the
 * one deliberately visible differentiator.
 */

const RESEARCH_SHELL_VARS = {
  // ---- Direction-C palette (verbatim from Market Overview's SO_VARS) ----
  "--so-bg-1": "#121212",
  "--so-bg-2": "#181818",
  "--so-ink-0": "#efeadb",
  "--so-ink-1": "#c6c1b3",
  "--so-ink-2": "#908b7f",
  "--so-ink-3": "#5e5a52",
  "--so-ink-4": "#383631",
  "--so-rule": "rgba(232,227,209,0.10)",
  "--so-rule-hi": "rgba(232,227,209,0.18)",
  "--so-citrine": "#d4b343",
  "--so-jade": "#6e9c87",
  "--so-jade-ink": "#98c2ad",
  "--so-rust": "#c97064",
  "--so-rust-ink": "#e0978c",
  "--so-amber": "#c89759",
  "--so-slate": "#7a8694",
  "--so-bd-rust": "rgba(201,112,100,0.40)",
  "--so-bd-amber": "rgba(200,151,89,0.40)",
  "--so-bd-jade": "rgba(110,156,135,0.45)",
  "--so-display": "'Manrope','Inter',sans-serif",
  "--so-serif": "'Inter','Manrope',sans-serif",

  // ---- shadcn theme-token remap → Direction-C (HSL triples) ----
  // Surfaces are grayscale → exact conversions; inks are the warm so-ink
  // ramp; the accent flips from teal to citrine.  bg/fg pairs are kept so
  // contrast holds.  ``--background`` is intentionally left untouched so the
  // page sits on the same dark base as Market Overview.
  "--card": "0 0% 7%", // #121212 so-bg-1
  "--card-foreground": "45 14% 74%", // #c6c1b3 so-ink-1
  "--foreground": "45 38% 90%", // #efeadb so-ink-0
  "--popover": "0 0% 9%", // #181818 so-bg-2
  "--popover-foreground": "45 14% 74%",
  "--muted": "0 0% 9%",
  "--muted-foreground": "42 7% 53%", // #908b7f so-ink-2
  "--secondary": "0 0% 9%",
  "--secondary-foreground": "45 14% 74%",
  "--accent": "0 0% 9%",
  "--accent-foreground": "45 14% 74%",
  "--primary": "46 63% 55%", // #d4b343 citrine
  "--primary-foreground": "0 0% 7%", // dark text on citrine
  "--border": "40 5% 14%", // opaque approximation of the warm so-rule hairline
  "--input": "40 5% 14%",
  "--ring": "46 63% 55%", // citrine focus ring
} as CSSProperties;

export interface ResearchPageShellProps {
  children: ReactNode;
  className?: string;
}

export function ResearchPageShell({ children, className }: ResearchPageShellProps) {
  return (
    <div className={cn("text-foreground", className)} style={RESEARCH_SHELL_VARS}>
      {children}
    </div>
  );
}
