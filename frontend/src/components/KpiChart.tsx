/**
 * The KPI against its counterfactual — the chart the product's whole claim rests on.
 *
 * Two series in the SAME unit on ONE axis, which is the only honest way to draw
 * "what happened" beside "what we expected": a second axis would let a reader find
 * any relationship they liked between two arbitrary scales. The detection window is
 * shaded because it was *held out of the baseline fit*, so the counterfactual there is
 * a genuine prediction rather than a line fitted through the thing it is judging — and
 * a reader cannot know that from the marks alone.
 *
 * Hand-rolled SVG rather than a chart library: the shaded held-out window and the
 * crosshair readout are the two things that carry the meaning here, and both are
 * easier to state directly than to coax out of a general-purpose API.
 *
 * Every chart in this app carries a table view, per the design rules. A line is a
 * summary; some readers want the numbers, and a chart that cannot be read as a table
 * is a chart that has to be trusted rather than checked.
 */

import { useMemo, useState } from 'react';

import { day, inr } from '@/lib/format';
import { trailingMean, WEEK } from '@/lib/series';
import type { KpiSeries } from '@/lib/types';

const VIEW_WIDTH = 720;
const VIEW_HEIGHT = 220;
const PAD_LEFT = 62;
/**
 * A gutter wide enough for a rupee tick, so axis labels sit BESIDE the plot rather
 * than inside it. At the previous 8px the line was drawn straight through them.
 */
const PAD_RIGHT = 8;
const PAD_TOP = 12;
const PAD_BOTTOM = 22;
const GRID_LINES = 4;

interface Point {
  date: string;
  actual: number;
  counterfactual: number;
}

interface Geometry {
  x: (index: number) => number;
  y: (value: number) => number;
  low: number;
  high: number;
}

/**
 * Zip the three parallel arrays into one row per day.
 *
 * The API sends three arrays of equal length; indexing them in parallel is how they
 * silently drift apart. One pass, one shape, and the compiler's strict index checking
 * then has something real to check.
 */
function toPoints(series: KpiSeries, smooth: boolean): Point[] {
  const actuals: (number | null | undefined)[] = smooth
    ? trailingMean(series.actual)
    : series.actual;
  const counterfactuals: (number | null | undefined)[] = smooth
    ? trailingMean(series.counterfactual)
    : series.counterfactual;
  // Days without a full window drop out of the line AND out of the scale, together
  // with their dates, so the x-axis stays aligned with what is drawn.
  return series.dates.flatMap((date, index) => {
    const actual = actuals[index];
    const counterfactual = counterfactuals[index];
    return actual == null || counterfactual == null ? [] : [{ date, actual, counterfactual }];
  });
}

export function KpiChart({ series }: { series: KpiSeries }) {
  const [table, setTable] = useState(false);
  const [hover, setHover] = useState<number | null>(null);

  const points = useMemo(() => toPoints(series, true), [series]);

  const geometry = useMemo<Geometry>(() => {
    const all = points.flatMap((point) => [point.actual, point.counterfactual]);
    const low = Math.min(...all);
    const high = Math.max(...all);
    const span = high - low || 1;
    const plotWidth = VIEW_WIDTH - PAD_LEFT - PAD_RIGHT;
    const plotHeight = VIEW_HEIGHT - PAD_TOP - PAD_BOTTOM;
    const lastIndex = Math.max(points.length - 1, 1);
    return {
      x: (index) => PAD_LEFT + (index / lastIndex) * plotWidth,
      y: (value) => PAD_TOP + (1 - (value - low) / span) * plotHeight,
      low,
      high,
    };
  }, [points]);

  const windowBand = useMemo(() => {
    const start = series.window_start;
    const end = series.window_end;
    if (!start || !end) return null;
    const from = points.findIndex((point) => point.date >= start);
    let to = -1;
    for (let index = points.length - 1; index >= 0; index -= 1) {
      if ((points[index]?.date ?? '') <= end) {
        to = index;
        break;
      }
    }
    if (from < 0 || to <= from) return null;
    return { left: geometry.x(from), width: geometry.x(to) - geometry.x(from) };
  }, [series, points, geometry]);

  const path = (pick: (point: Point) => number) =>
    points
      .map((point, index) => `${index ? 'L' : 'M'}${geometry.x(index)},${geometry.y(pick(point))}`)
      .join(' ');

  const active = hover === null ? undefined : points[hover];
  const first = points[0];
  const last = points[points.length - 1];
  if (points.length < 2 || !first || !last) return null;

  return (
    <div className="space-y-2">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <Legend />
        <button
          type="button"
          onClick={() => setTable(!table)}
          aria-pressed={table}
          className="rounded border border-hairline-border px-2 py-1 text-xs text-ink-secondary"
        >
          {table ? 'Chart view' : 'Table view'}
        </button>
      </div>

      {table ? (
        <SeriesTable series={series} />
      ) : (
        <figure className="m-0">
          <svg
            viewBox={`0 0 ${VIEW_WIDTH} ${VIEW_HEIGHT}`}
            className="w-full"
            role="img"
            aria-label={`${series.kpi_id} against its counterfactual over ${points.length} days`}
            onMouseLeave={() => setHover(null)}
            onMouseMove={(event) => {
              const box = event.currentTarget.getBoundingClientRect();
              const ratio = (event.clientX - box.left) / box.width;
              const index = Math.round(ratio * (points.length - 1));
              setHover(Math.min(Math.max(index, 0), points.length - 1));
            }}
          >
            {Array.from({ length: GRID_LINES + 1 }, (_, step) => {
              const y = PAD_TOP + (step / GRID_LINES) * (VIEW_HEIGHT - PAD_TOP - PAD_BOTTOM);
              // Ticks read top-down, so step 0 is the maximum.
              const value = geometry.high - (step / GRID_LINES) * (geometry.high - geometry.low);
              return (
                <g key={step}>
                  <line
                    x1={PAD_LEFT}
                    x2={VIEW_WIDTH - PAD_RIGHT}
                    y1={y}
                    y2={y}
                    stroke="var(--hairline-grid)"
                    strokeWidth={1}
                    vectorEffect="non-scaling-stroke"
                  />
                  <text
                    x={PAD_LEFT - 6}
                    y={y + 3}
                    fontSize={9}
                    textAnchor="end"
                    className="tnum"
                    fill="var(--ink-muted)"
                  >
                    {inr(value)}
                  </text>
                </g>
              );
            })}

            {windowBand ? (
              <rect
                x={windowBand.left}
                y={PAD_TOP}
                width={windowBand.width}
                height={VIEW_HEIGHT - PAD_TOP - PAD_BOTTOM}
                fill="var(--ink-primary)"
                opacity={0.06}
              />
            ) : null}

            <path
              d={path((point) => point.counterfactual)}
              fill="none"
              stroke="var(--series-2)"
              strokeWidth={2}
              strokeDasharray="5 4"
              vectorEffect="non-scaling-stroke"
            />
            <path
              d={path((point) => point.actual)}
              fill="none"
              stroke="var(--series-1)"
              strokeWidth={2}
              strokeLinejoin="round"
              vectorEffect="non-scaling-stroke"
            />

            {hover !== null && active !== undefined ? (
              <g>
                <line
                  x1={geometry.x(hover)}
                  x2={geometry.x(hover)}
                  y1={PAD_TOP}
                  y2={VIEW_HEIGHT - PAD_BOTTOM}
                  stroke="var(--hairline-axis)"
                  strokeWidth={1}
                  vectorEffect="non-scaling-stroke"
                />
                <circle
                  cx={geometry.x(hover)}
                  cy={geometry.y(active.actual)}
                  r={3.5}
                  fill="var(--series-1)"
                />
                <circle
                  cx={geometry.x(hover)}
                  cy={geometry.y(active.counterfactual)}
                  r={3.5}
                  fill="var(--series-2)"
                />
              </g>
            ) : null}

            <text x={PAD_LEFT} y={VIEW_HEIGHT - 6} fontSize={10} fill="var(--ink-muted)">
              {day(first.date)}
            </text>
            <text
              x={VIEW_WIDTH - PAD_RIGHT}
              y={VIEW_HEIGHT - 6}
              fontSize={10}
              textAnchor="end"
              fill="var(--ink-muted)"
            >
              {day(last.date)}
            </text>
          </svg>

          <figcaption className="mt-1 text-xs text-ink-muted">
            {active === undefined ? (
              <>
                {WEEK}-day trailing mean — the table view carries every daily value. Shaded: the
                window held out of the baseline fit, so the counterfactual there is a prediction
                rather than a line fitted through what it is judging.
              </>
            ) : (
              <span className="tnum">
                {day(active.date)} · actual {inr(active.actual)} · counterfactual{' '}
                {inr(active.counterfactual)}
              </span>
            )}
          </figcaption>
        </figure>
      )}
    </div>
  );
}

function Legend() {
  return (
    <div className="flex items-center gap-4 text-xs text-ink-secondary">
      <span className="flex items-center gap-1.5">
        <svg width="16" height="8" aria-hidden>
          <line x1="0" y1="4" x2="16" y2="4" stroke="var(--series-1)" strokeWidth="2" />
        </svg>
        Actual
      </span>
      <span className="flex items-center gap-1.5">
        <svg width="16" height="8" aria-hidden>
          <line
            x1="0"
            y1="4"
            x2="16"
            y2="4"
            stroke="var(--series-2)"
            strokeWidth="2"
            strokeDasharray="4 3"
          />
        </svg>
        Counterfactual
      </span>
    </div>
  );
}

function SeriesTable({ series }: { series: KpiSeries }) {
  // Untouched daily values. The chart smooths to a weekly mean; this is where a
  // reader checks what was actually measured.
  const points = toPoints(series, false);
  return (
    <div className="max-h-72 overflow-auto">
      <table className="w-full text-left text-xs">
        <thead className="sticky top-0 bg-card text-ink-muted">
          <tr>
            <th className="py-1 font-normal">Date</th>
            <th className="py-1 text-right font-normal">Actual</th>
            <th className="py-1 text-right font-normal">Counterfactual</th>
            <th className="py-1 text-right font-normal">Difference</th>
          </tr>
        </thead>
        <tbody className="tnum">
          {points.map((point) => (
            <tr
              key={point.date}
              className="border-t"
              style={{ borderColor: 'var(--hairline-grid)' }}
            >
              <td className="py-1 text-ink-secondary">{day(point.date)}</td>
              <td className="py-1 text-right text-ink">{inr(point.actual)}</td>
              <td className="py-1 text-right text-ink-secondary">{inr(point.counterfactual)}</td>
              <td className="py-1 text-right text-ink-secondary">
                {inr(point.actual - point.counterfactual)}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
