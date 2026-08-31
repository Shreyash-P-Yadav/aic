/**
 * Series shaping for display. The values themselves are never altered — only how
 * densely they are drawn.
 *
 * Revenue here carries a strong weekly cycle (the day-of-week autocorrelation is
 * measurable in the data), so 180 raw daily points draw a sawtooth in which the
 * movement being reported competes with Tuesday. Since every insight on this screen is
 * about a *weekly* period, a 7-day trailing mean is the mark that matches the claim.
 *
 * This is a presentation choice and it is labelled as one wherever it is used: the
 * table view beside every chart carries the untouched daily values, so smoothing hides
 * nothing — it just stops the chart arguing with itself.
 */

export const WEEK = 7;

/**
 * Trailing mean over `window` points, with the leading partial windows returned as
 * `null` rather than as averages of one or two days.
 *
 * That distinction matters more than it looks. Averaging "what exists so far" makes the
 * first value a single raw day - an outlier in a series with this much daily variance -
 * which then sets the top of the y-scale and draws a vertical spike at the left edge
 * that no reader can interpret. Measured on the demo insight it put the axis maximum at
 * around 4.29 cr against a typical 2.2 cr. `null` says "not enough history yet", which
 * is true, and the caller drops those points from both the line and the scale.
 */
export function trailingMean(values: number[], window: number = WEEK): (number | null)[] {
  if (window <= 1) return [...values];
  const out: (number | null)[] = [];
  let sum = 0;
  for (let index = 0; index < values.length; index += 1) {
    sum += values[index] ?? 0;
    if (index >= window) sum -= values[index - window] ?? 0;
    out.push(index >= window - 1 ? sum / window : null);
  }
  return out;
}
