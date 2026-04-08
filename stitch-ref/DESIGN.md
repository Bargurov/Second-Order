# Design System Strategy: The Analytical Monolith

## 1. Overview & Creative North Star
The "Creative North Star" for this design system is **The Quiet Authority**. 

In institutional finance, true power doesn't shout; it observes and calculates. We are moving away from the "SaaS-standard" look—characterized by bright blues and heavy borders—toward a bespoke editorial experience that feels like a Bloomberg Terminal reimagined for a high-end gallery. 

The aesthetic is driven by **intentional asymmetry** and **tonal depth**. By utilizing high information density balanced with generous, purposeful whitespace in the margins, we create a layout that feels both exhaustive and breathable. This system prioritizes the data as the primary "visual ornament," using precision-engineered components to frame complex insights.

## 2. Colors & Surface Architecture
The palette is rooted in the "Deep Dark" (#0a0a0f), utilizing a spectrum of slate grays and muted jewel tones to convey a sense of calm under pressure.

### The "No-Line" Rule
Standard 1px solid borders are prohibited for sectioning. They create visual noise and fragment the user’s focus. Instead, boundaries are defined through:
*   **Background Shifts:** Transitioning from `surface` to `surface-container-low` to define a sidebar.
*   **Tonal Transitions:** Using `surface-container-highest` to lift a primary data module from the background.

### Surface Hierarchy & Nesting
Think of the UI as a series of physical layers—stacked sheets of obsidian glass.
*   **Base:** `surface` (#0e0e13) - The desk on which everything sits.
*   **Sections:** `surface-container-low` (#13131a) - Used for broad content areas.
*   **Modules:** `surface-container-highest` (#242533) - Reserved for the most critical interactive data grids.
*   **Nesting:** An inner data table (`surface-container-highest`) should sit inside a panel (`surface-container-low`) to create a natural, "milled" look without a single stroke.

### The Glass & Gradient Rule
To prevent the UI from feeling "flat," floating elements (modals, dropdowns, popovers) must use **Glassmorphism**.
*   **Token:** Use `surface-container-high` at 80% opacity with a `20px` backdrop-blur.
*   **Signature Textures:** For main Call-to-Actions (CTAs), utilize a subtle linear gradient from `primary` (#93d1d3) to `primary-container` (#004f51) at a 135-degree angle. This provides a "lathe-cut" metallic finish rather than a flat plastic feel.

## 3. Typography
The system uses a dual-type scale to balance high-speed readability with authoritative headers.

*   **Display & Headlines (Manrope):** Chosen for its geometric precision and modern "tech-institutional" feel. Use `display-md` for high-level portfolio totals to create an editorial "hero" moment.
*   **Body & Labels (Inter):** The workhorse. Inter’s tall x-height ensures that even at `label-sm` (0.6875rem), financial digits remain legible.
*   **Analytical Hierarchy:** All numbers should use tabular lining (tnum) to ensure that columns of data align perfectly, reinforcing the brand's commitment to "precision."

## 4. Elevation & Depth
We reject traditional drop shadows. Depth is achieved through **Tonal Layering**.

*   **The Layering Principle:** Place a `surface-container-lowest` (#000000) card on a `surface-container-low` (#13131a) section to create a "recessed" effect, as if the data is carved into the interface.
*   **Ambient Shadows:** For floating elements, use a "Tinted Ambient" shadow: `0 20px 40px rgba(0, 0, 0, 0.4)`. Avoid gray shadows; let the shadow be a deeper version of the background.
*   **The Ghost Border Fallback:** If a border is required for accessibility (e.g., in a high-density data grid), use the "Ghost Border."
    *   **Token:** `outline-variant` at 15% opacity. It should be felt, not seen.

## 5. Components

### Buttons
*   **Primary:** Gradient of `primary` to `primary-container`. `md` radius (0.375rem). No border.
*   **Secondary:** `surface-container-highest` background with a `ghost border`.
*   **Tertiary:** Text-only using `primary` color, with a `surface-bright` hover state.

### Indicator Pills (The "Second Order" Signature)
*   **Positive/Calm:** `primary-container` background with `primary` text. No saturated greens.
*   **Negative/Stressed:** `error_container` background with `error_dim` (#bb5551) text.
*   Note: All pills use `full` roundedness (9999px) to contrast against the rigid 4-6px grid.

### Data Grids & Lists
*   **No Dividers:** Prohibit the use of horizontal lines between rows. Use `8px` of vertical white space or a subtle background hover shift (`surface-bright`) to separate content.
*   **Sparklines:** Rendered in `primary` (teal) or `error_dim` (coral). Stroke width: `1.5px`. No fill/area under the curve to keep the density high and clean.

### Input Fields
*   **State:** Default state is `surface-container-highest`.
*   **Focus:** Transition to a `ghost border` using `primary` at 40% opacity. 
*   **Density:** Use `body-sm` for input text to maintain high information density without sacrificing touch/click targets.

## 6. Do’s and Don’ts

### Do
*   **DO** use monochromatic shifts to indicate hierarchy.
*   **DO** lean into "Overlapping Elements." Allow a chart legend to slightly overlap a grid edge using a glassmorphic background.
*   **DO** use `label-sm` for metadata—embrace the "small print" aesthetic of high finance.
*   **DO** ensure all financial values are right-aligned in tables for mathematical clarity.

### Don't
*   **DON’T** use 100% opaque borders to separate sections.
*   **DON’T** use pure white (#ffffff) for text. Use `on_surface_variant` (#aba9bc) for secondary info to reduce eye strain in dark mode.
*   **DON’T** use standard "Material Design" shadows. They look "cheap" in an institutional context.
*   **DON’T** use rounded corners larger than `0.5rem` (8px). Anything rounder feels consumer-grade and "soft."