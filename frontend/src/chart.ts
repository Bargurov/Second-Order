// Display-only helpers: scales and tick positions. No scoring happens in the browser.

export type Scale = (value: number) => number;

export function linear(domain: [number, number], range: [number, number]): Scale {
  const [d0, d1] = domain;
  const [r0, r1] = range;
  const span = d1 - d0 || 1;
  return (value) => r0 + ((value - d0) / span) * (r1 - r0);
}

export function niceTicks(min: number, max: number, count = 5): number[] {
  const span = max - min || Math.abs(max) || 1;
  const magnitude = 10 ** Math.floor(Math.log10(span / count));
  const step = [1, 2, 2.5, 5, 10].map((m) => m * magnitude).find((s) => span / s <= count) ?? 10 * magnitude;
  const ticks: number[] = [];
  for (let value = Math.ceil(min / step) * step; value <= max + step * 1e-9; value += step) {
    ticks.push(Number(value.toFixed(10)));
  }
  return ticks;
}

/** First instants of each UTC month inside [start, end]. */
export function monthStarts(start: number, end: number): number[] {
  const first = new Date(start);
  const ticks: number[] = [];
  for (let month = first.getUTCMonth() + 1, year = first.getUTCFullYear(); ; month += 1) {
    const time = Date.UTC(year + Math.floor(month / 12), month % 12, 1);
    if (time > end) return ticks;
    ticks.push(time);
  }
}

/** Padded [min, max] that always contains every value. */
export function paddedExtent(values: number[], padding = 0.1): [number, number] {
  const min = Math.min(...values);
  const max = Math.max(...values);
  const span = max - min || Math.abs(max) || 1;
  return [min - span * padding, max + span * padding];
}
