/**
 * Scale and tick helpers shared by the hand-rolled SVG charts.
 *
 * Axis conventions every chart follows: horizontal gridlines only, no
 * axis spines, 10px mono muted tick labels rendered with the shared
 * lib/format formatters, and the margins below so y labels line up
 * across cards.
 */

export const CHART_MARGIN = { top: 8, right: 8, bottom: 18, left: 36 } as const;

export function linearScale(
  domainMin: number,
  domainMax: number,
  rangeMin: number,
  rangeMax: number,
): (value: number) => number {
  const span = domainMax - domainMin || 1;
  return (value) => rangeMin + ((value - domainMin) / span) * (rangeMax - rangeMin);
}

/**
 * Round tick values from zero up to at least `max`, stepping by a
 * 1/2/5 multiple of a power of ten so labels stay readable.
 */
export function niceTicks(max: number, count = 3): number[] {
  if (max <= 0) {
    return [0];
  }
  const rawStep = max / count;
  const magnitude = 10 ** Math.floor(Math.log10(rawStep));
  const normalized = rawStep / magnitude;
  const multiplier = normalized <= 1 ? 1 : normalized <= 2 ? 2 : normalized <= 5 ? 5 : 10;
  const step = multiplier * magnitude;
  const ticks: number[] = [];
  const top = Math.ceil(max / step - 1e-9) * step;
  for (let tick = 0; tick <= top + step / 2; tick += step) {
    ticks.push(Number(tick.toPrecision(12)));
  }
  return ticks;
}
