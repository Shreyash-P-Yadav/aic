/**
 * A shape, not a chart.
 *
 * No axis, no ticks, no labels — a sparkline's whole job is to say "this is roughly
 * what the last two months looked like" in the width of a card. It is drawn from raw
 * values rather than an index precisely because it carries no scale: rescaling would
 * imply a precision the mark is not making.
 *
 * Smoothed to a weekly mean for the same reason the full chart is: this KPI has a
 * strong day-of-week cycle, and at 120px wide the raw daily series draws static rather
 * than shape.
 *
 * Decorative, so it is hidden from assistive technology. The card states the movement
 * and the impact in text; the line adds nothing a screen reader needs to hear.
 */

import { trailingMean } from '@/lib/series';

const VIEW_WIDTH = 120;
const VIEW_HEIGHT = 28;
const STROKE = 1.5;

export function Sparkline({ values, muted = false }: { values: number[]; muted?: boolean }) {
  if (values.length < 2) return null;
  const smoothed = trailingMean(values).filter((value): value is number => value !== null);
  if (smoothed.length < 2) return null;
  const low = Math.min(...smoothed);
  const high = Math.max(...smoothed);
  const span = high - low || 1;
  // Inset by the stroke so the extremes are not clipped at the viewBox edge.
  const y = (value: number) =>
    VIEW_HEIGHT - STROKE - ((value - low) / span) * (VIEW_HEIGHT - STROKE * 2);
  const step = VIEW_WIDTH / (smoothed.length - 1);
  const points = smoothed.map((value, index) => `${index * step},${y(value)}`).join(' ');

  return (
    <svg
      viewBox={`0 0 ${VIEW_WIDTH} ${VIEW_HEIGHT}`}
      preserveAspectRatio="none"
      className="h-7 w-full"
      aria-hidden
      focusable="false"
    >
      <polyline
        points={points}
        fill="none"
        strokeWidth={STROKE}
        strokeLinejoin="round"
        strokeLinecap="round"
        vectorEffect="non-scaling-stroke"
        stroke={muted ? 'var(--ink-muted)' : 'var(--series-1)'}
      />
    </svg>
  );
}
