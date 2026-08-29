/**
 * The price-volume-mix waterfall: expected → price → volume → mix → unexplained → actual.
 *
 * Custom SVG rather than a chart library, because a waterfall is a sequence of
 * *connected* bars and every library that offers one draws the connectors wrong — or
 * not at all. The connectors are the whole point: they are what shows that the parts
 * sum to the whole, which is the Bennet identity the backend asserts to 1e-6.
 *
 * Colour carries direction (a fall is red, a rise is green) and is always paired with
 * a sign and a label, so identity is never colour alone.
 */

import { inr } from '@/lib/format';

export interface WaterfallStep {
  label: string;
  value: number;
  kind: 'anchor' | 'delta';
}

interface Props {
  steps: WaterfallStep[];
  height?: number;
}

const BAR_GAP = 2;
const RADIUS = 4;
const PADDING = { top: 24, right: 12, bottom: 44, left: 12 };

export function Waterfall({ steps, height = 260 }: Props) {
  if (steps.length === 0) return null;

  // Running positions: an anchor sits on the baseline, a delta floats from wherever
  // the running total had reached.
  let running = 0;
  const placed = steps.map((step) => {
    if (step.kind === 'anchor') {
      running = step.value;
      return { ...step, from: 0, to: step.value };
    }
    const from = running;
    running += step.value;
    return { ...step, from, to: running };
  });

  const values = placed.flatMap((step) => [step.from, step.to]);
  const max = Math.max(...values, 0);
  const min = Math.min(...values, 0);
  const span = max - min || 1;
  const plotHeight = height - PADDING.top - PADDING.bottom;
  const scale = (value: number) => PADDING.top + ((max - value) / span) * plotHeight;

  const columnWidth = 100 / placed.length;

  return (
    <figure className="w-full overflow-x-auto">
      <svg
        viewBox={`0 0 100 ${height}`}
        preserveAspectRatio="none"
        className="h-[260px] w-full min-w-[520px]"
        role="img"
        aria-label="Price, volume and mix decomposition of the revenue change"
      >
        {/* Recessive baseline. */}
        <line
          x1={0}
          x2={100}
          y1={scale(0)}
          y2={scale(0)}
          stroke="var(--hairline-axis)"
          strokeWidth={0.3}
          vectorEffect="non-scaling-stroke"
        />
        {placed.map((step, index) => {
          const x = index * columnWidth + columnWidth * 0.18;
          const width = columnWidth * 0.64;
          const top = scale(Math.max(step.from, step.to));
          const bottom = scale(Math.min(step.from, step.to));
          const barHeight = Math.max(bottom - top - BAR_GAP, 1);
          const colour =
            step.kind === 'anchor'
              ? 'var(--series-1)'
              : step.value >= 0
                ? 'var(--status-good)'
                : 'var(--status-critical)';
          const previous = placed[index - 1];
          return (
            <g key={step.label}>
              {previous ? (
                <line
                  x1={(index - 1) * columnWidth + columnWidth * 0.82}
                  x2={x}
                  y1={scale(previous.to)}
                  y2={scale(previous.to)}
                  stroke="var(--hairline-axis)"
                  strokeWidth={0.25}
                  strokeDasharray="1 1"
                  vectorEffect="non-scaling-stroke"
                />
              ) : null}
              <rect x={x} y={top} width={width} height={barHeight} rx={RADIUS / 4} fill={colour}>
                <title>{`${step.label}: ${inr(step.kind === 'anchor' ? step.value : step.value)}`}</title>
              </rect>
            </g>
          );
        })}
      </svg>
      <figcaption className="mt-1 grid grid-cols-2 gap-x-4 gap-y-1 text-xs sm:grid-cols-3 lg:grid-cols-6">
        {placed.map((step) => (
          <span key={step.label} className="text-ink-secondary">
            <span className="block text-ink-muted">{step.label}</span>
            <span className="tnum">{inr(step.value)}</span>
          </span>
        ))}
      </figcaption>
    </figure>
  );
}
