import { useEffect, useRef, useState, type FocusEvent, type KeyboardEvent } from "react";
import { matching } from "../metalsPicks";

interface Frame { id: string; name: string }

/**
 * The metals picker: one button, closed by default, saying how many metals are picked; it opens a panel with a search
 * box and a checkbox per chapter (USGS order), plus Defaults, Clear and Done. Escape, Done or a click outside closes
 * it (Escape and Done return focus to the button). Arrow keys move from the search box through the visible checkboxes;
 * Space ticks. The picks themselves live in the page (and its address); this only reports each change.
 */
export function MetalPicker({ frames, picks, defaults, onChange }: {
  frames: readonly Frame[]; picks: readonly string[]; defaults: readonly string[];
  onChange: (next: string[]) => void;
}) {
  const [open, setOpen] = useState(false);
  const [query, setQuery] = useState("");
  const wrap = useRef<HTMLDivElement>(null);
  const button = useRef<HTMLButtonElement>(null);
  const search = useRef<HTMLInputElement>(null);
  const list = useRef<HTMLUListElement>(null);
  const shown = matching(frames, query);
  const names = picks.map((id) => frames.find((frame) => frame.id === id)?.name ?? id);

  const close = (focus: boolean) => {
    setOpen(false);
    setQuery("");
    if (focus) button.current?.focus();
  };
  useEffect(() => {  // Opened: the whole panel in view (its Done button included), and the search box focused.
    if (!open) return;
    document.getElementById("mt-picker-panel")?.scrollIntoView({ block: "nearest" });
    search.current?.focus({ preventScroll: true });
  }, [open]);
  useEffect(() => {
    if (!open) return undefined;
    const outside = (event: PointerEvent) => {
      if (wrap.current && !wrap.current.contains(event.target as Node)) close(false);
    };
    document.addEventListener("pointerdown", outside);
    return () => document.removeEventListener("pointerdown", outside);
  }, [open]);

  const toggle = (id: string, on: boolean) =>
    onChange(on ? [...picks.filter((item) => item !== id), id] : picks.filter((item) => item !== id));
  const keys = (event: KeyboardEvent<HTMLDivElement>) => {
    if (!open) return;
    if (event.key === "Escape") {
      event.preventDefault();
      close(true);
      return;
    }
    const boxes = [...(list.current?.querySelectorAll<HTMLInputElement>('input[type="checkbox"]') ?? [])];
    const at = boxes.indexOf(document.activeElement as HTMLInputElement);
    const fromSearch = document.activeElement === search.current;
    let next: HTMLElement | undefined;
    if (event.key === "ArrowDown" && (fromSearch || at >= 0)) next = boxes[fromSearch ? 0 : Math.min(at + 1, boxes.length - 1)];
    else if (event.key === "ArrowUp" && at >= 0) next = at === 0 ? search.current ?? undefined : boxes[at - 1];
    else if (event.key === "Home" && at >= 0) next = boxes[0];
    else if (event.key === "End" && at >= 0) next = boxes[boxes.length - 1];
    if (next) {
      event.preventDefault();
      next.focus();
    }
  };
  // Focus moving to something outside (Tab past the last control) closes the panel; a click inside never does.
  const leave = (event: FocusEvent<HTMLDivElement>) => {
    const to = event.relatedTarget as Node | null;
    if (open && to !== null && wrap.current && !wrap.current.contains(to)) close(false);
  };

  return (
    <div className="mt-picker" data-picker="" ref={wrap} onKeyDown={keys} onBlur={leave}>
      <button ref={button} type="button" className="mt-picker-button" aria-expanded={open}
              aria-controls="mt-picker-panel" onClick={() => (open ? close(true) : setOpen(true))}>
        <span className="mt-picker-label">Metals</span>
        <span className="mt-count" data-count="">{picks.length} of {frames.length}</span>
        <span className="mt-chevron" aria-hidden="true" />
      </button>
      <span className="mt-picker-names" data-picked-names="">{names.length > 0 ? names.join(", ") : "None picked"}</span>
      {open && (
        <div id="mt-picker-panel" className="mt-picker-panel" role="dialog" aria-label="Pick metals to compare">
          <label className="mt-picker-find">
            <span className="mt-sr">Find a metal</span>
            <input ref={search} type="search" value={query} placeholder="Find a metal" autoComplete="off"
                   spellCheck={false} aria-describedby="mt-picker-status"
                   onChange={(event) => setQuery(event.target.value)} />
          </label>
          <p id="mt-picker-status" className="mt-picker-status" aria-live="polite">
            {query.trim() === "" ? `${picks.length} of ${frames.length} picked · USGS chapter order`
              : `${shown.length} ${shown.length === 1 ? "match" : "matches"} · ${picks.length} picked`}</p>
          {shown.length === 0 ? <p className="mt-picker-empty">No metal matches “{query.trim()}”.</p> : (
            <fieldset className="mt-picker-fieldset">
              <legend className="mt-sr">Metals</legend>
              <ul ref={list} className="mt-picker-list">{shown.map((frame) => (
                <li key={frame.id}>
                  <label data-pick={frame.id}>
                    <input type="checkbox" name="metal" value={frame.id} checked={picks.includes(frame.id)}
                           onChange={(event) => toggle(frame.id, event.target.checked)} />
                    <span>{frame.name}</span>
                  </label>
                </li>))}
              </ul>
            </fieldset>)}
          <div className="mt-picker-actions">
            <button type="button" className="mt-text-button" onClick={() => onChange([...defaults])}>Defaults</button>
            <button type="button" className="mt-text-button" onClick={() => onChange([])}>Clear</button>
            <button type="button" className="mt-done" onClick={() => close(true)}>Done</button>
          </div>
        </div>)}
    </div>
  );
}
