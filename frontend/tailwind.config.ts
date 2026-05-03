import type { Config } from "tailwindcss";
import tailwindcssAnimate from "tailwindcss-animate";

export default {
  darkMode: "class",
  content: ["./index.html", "./src/**/*.{ts,tsx}"],
  theme: {
    extend: {
      fontFamily: {
        sans: ['"Inter"', "ui-sans-serif", "system-ui", "-apple-system", "sans-serif"],
        headline: ['"Manrope"', "sans-serif"],
        body: ['"Inter"', "sans-serif"],
        label: ['"Inter"', "sans-serif"],
        mono: ['"JetBrains Mono"', "ui-monospace", '"Cascadia Code"', '"Fira Code"', "monospace"],
      },
      fontSize: {
        "2xs": ["0.6875rem", { lineHeight: "1rem" }],
      },
      colors: {
        /* ---- shadcn/ui semantic tokens (kept for non-overview pages) ---- */
        border: "hsl(var(--border))",
        input: "hsl(var(--input))",
        ring: "hsl(var(--ring))",
        background: "hsl(var(--background))",
        foreground: "hsl(var(--foreground))",
        primary: {
          DEFAULT: "hsl(var(--primary))",
          foreground: "hsl(var(--primary-foreground))",
        },
        secondary: {
          DEFAULT: "hsl(var(--secondary))",
          foreground: "hsl(var(--secondary-foreground))",
        },
        destructive: {
          DEFAULT: "hsl(var(--destructive))",
          foreground: "hsl(var(--destructive-foreground))",
        },
        muted: {
          DEFAULT: "hsl(var(--muted))",
          foreground: "hsl(var(--muted-foreground))",
        },
        accent: {
          DEFAULT: "hsl(var(--accent))",
          foreground: "hsl(var(--accent-foreground))",
        },
        popover: {
          DEFAULT: "hsl(var(--popover))",
          foreground: "hsl(var(--popover-foreground))",
        },
        card: {
          DEFAULT: "hsl(var(--card))",
          foreground: "hsl(var(--card-foreground))",
        },
        sidebar: {
          DEFAULT: "hsl(var(--sidebar-background))",
          foreground: "hsl(var(--sidebar-foreground))",
          primary: "hsl(var(--sidebar-primary))",
          "primary-foreground": "hsl(var(--sidebar-primary-foreground))",
          accent: "hsl(var(--sidebar-accent))",
          "accent-foreground": "hsl(var(--sidebar-accent-foreground))",
          border: "hsl(var(--sidebar-border))",
          ring: "hsl(var(--sidebar-ring))",
        },
        /* ---- Stitch design-system tokens ---- */
        "error-container": "#7f2927",
        "on-error-container": "#ff9993",
        "surface-container": "#191922",
        "on-surface": "#e6e3f7",
        "on-surface-variant": "#aba9bc",
        "surface-container-high": "#1e1f2a",
        "surface-container-highest": "#242533",
        "surface-container-low": "#13131a",
        "surface-container-lowest": "#000000",
        "surface-variant": "#242533",
        "surface-bright": "#2a2b3b",
        "outline-variant": "#474656",
        outline: "#757485",
        "primary-container": "#004f51",
        "primary-dim": "#85c3c5",
        "primary-fixed": "#afeef0",
        "primary-fixed-dim": "#a1dfe1",
        "on-primary": "#00484a",
        "on-primary-container": "#9ddbdd",
        "secondary-container": "#2d3c51",
        "secondary-dim": "#8f9fb7",
        "secondary-fixed": "#d3e4fe",
        "secondary-fixed-dim": "#c5d6f0",
        "on-secondary-container": "#b0c0da",
        "tertiary": "#ffbfba",
        "tertiary-dim": "#ed9f99",
        "tertiary-container": "#fdaca7",
        "error-dim": "#bb5551",
        error: "#ee7d77",
        "surface-tint": "#93d1d3",
      },
      borderRadius: {
        // shadcn-aligned semantic radii — drive everything off --radius.
        lg: "var(--radius)",
        md: "calc(var(--radius) - 1px)",
        sm: "calc(var(--radius) - 2px)",
        // Stitch / DESIGN.md cap card radius at 0.5rem (8px); override
        // Tailwind's built-in larger radii so existing rounded-xl /
        // rounded-2xl class users land at the institutional ceiling
        // instead of the consumer-grade 12-16px default.
        xl: "0.5rem",
        "2xl": "0.5rem",
      },
    },
  },
  plugins: [tailwindcssAnimate],
} satisfies Config;
