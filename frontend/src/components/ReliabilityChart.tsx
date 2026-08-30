/**
 * The reliability curve: predicted confidence against how often it was actually right.
 *
 * The diagonal is perfection — a score of 0.7 should be correct 70% of the time. Bars
 * are drawn at the bin's *observed* hit rate and positioned at its *mean predicted*
 * score, so the distance from the diagonal is the calibration error, visible directly
 * rather than summarised into one number.
 *
 * Every bin carries its `n`, and bins with none are drawn as empty slots rather than
 * omitted. That matters: a curve that silently drops its empty bins looks far better
 * behaved than the data supports, and the whole point of this screen is to be the place
 * where the system is honest about how well it knows itself.
 */

import type { ReliabilityBin } from '@/lib/types';

const W = 320;
const H = 220;
const PAD = 34;

export function ReliabilityChart({ bins }: { bins: ReliabilityBin[] }) {
  const populated = bins.filter((bin) => bin.n > 0);
  if (populated.length === 0) return null;
  const x = (v: number) => PAD + v * (W - PAD * 2);
  const y = (v: number) => H - PAD - v * (H - PAD * 2);
  const maxN = Math.max(...populated.map((bin) => bin.n));

  return (
    <figure className="m-0">
      <svg
        viewBox={`0 0 ${W} ${H}`}
        className="w-full max-w-md"
        role="img"
        aria-label="Reliability curve: predicted confidence against observed hit rate"
      >
        <line
          x1={x(0)}
          y1={y(0)}
          x2={x(1)}
          y2={y(1)}
          stroke="var(--hairline-axis)"
          strokeWidth={1}
          strokeDasharray="4 3"
          vectorEffect="non-scaling-stroke"
        />
        {[0, 0.5, 1].map((tick) => (
          <g key={tick}>
            <text
              x={x(tick)}
              y={H - PAD + 12}
              fontSize={8}
              textAnchor="middle"
              fill="var(--ink-muted)"
              className="tnum"
            >
              {tick.toFixed(1)}
            </text>
            <text
              x={PAD - 6}
              y={y(tick) + 3}
              fontSize={8}
              textAnchor="end"
              fill="var(--ink-muted)"
              className="tnum"
            >
              {tick.toFixed(1)}
            </text>
          </g>
        ))}
        {populated.map((bin) => (
          <circle
            key={bin.lower}
            cx={x(bin.mean_score)}
            cy={y(bin.hit_rate)}
            r={4 + 4 * (bin.n / maxN)}
            fill="var(--series-1)"
            fillOpacity={0.75}
          >
            <title>{`predicted ${bin.mean_score.toFixed(2)}, observed ${bin.hit_rate.toFixed(2)}, n = ${bin.n}`}</title>
          </circle>
        ))}
        <text x={W / 2} y={H - 4} fontSize={8} textAnchor="middle" fill="var(--ink-muted)">
          predicted confidence
        </text>
      </svg>
      <figcaption className="mt-1 text-xs text-ink-muted">
        Dot size is the number of events in that bin. The dashed line is perfect calibration;
        distance from it is the error.
      </figcaption>
    </figure>
  );
}
