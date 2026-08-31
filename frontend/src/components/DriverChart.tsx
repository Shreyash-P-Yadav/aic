/**
 * Driver coefficients as a dot with a confidence whisker.
 *
 * A bar chart of coefficients implies a magnitude read from a baseline, which an
 * elasticity does not have. A dot with its interval says the only two things that
 * matter: where the estimate is, and how much the data actually pins it down. An
 * interval that crosses zero is visible at a glance, which is the point.
 */

import { coefficient } from '@/lib/format';
import type { DriverFact } from '@/lib/types';

export function DriverChart({ drivers }: { drivers: DriverFact[] }) {
  if (drivers.length === 0) return null;
  const low = Math.min(...drivers.map((item) => item.interval_low), 0);
  const high = Math.max(...drivers.map((item) => item.interval_high), 0);
  const span = high - low || 1;
  const position = (value: number) => ((value - low) / span) * 100;

  return (
    <div className="space-y-3">
      {drivers.map((driver) => (
        <div key={driver.driver_id} className="grid grid-cols-[9rem_1fr_5rem] items-center gap-3">
          <span className="truncate text-xs text-ink-secondary" title={driver.driver_id}>
            {driver.driver_id}
            {driver.group.length > 1 ? (
              <span className="ml-1 text-ink-muted">(grouped)</span>
            ) : null}
          </span>
          <div className="relative h-6">
            <div
              className="absolute inset-y-1/2 h-px w-full"
              style={{ backgroundColor: 'var(--hairline-grid)' }}
            />
            <div
              className="absolute top-0 h-full w-px"
              style={{ left: `${position(0)}%`, backgroundColor: 'var(--hairline-axis)' }}
              aria-hidden
            />
            <div
              className="absolute inset-y-1/2 h-0.5 -translate-y-1/2"
              style={{
                left: `${position(driver.interval_low)}%`,
                width: `${position(driver.interval_high) - position(driver.interval_low)}%`,
                backgroundColor: 'var(--series-1)',
                opacity: 0.35,
              }}
            />
            <div
              className="absolute top-1/2 h-2.5 w-2.5 -translate-x-1/2 -translate-y-1/2 rounded-full"
              style={{
                left: `${position(driver.coefficient)}%`,
                backgroundColor: 'var(--series-1)',
              }}
              title={`${driver.driver_id}: ${coefficient(driver.coefficient)} (95% ${coefficient(driver.interval_low)} to ${coefficient(driver.interval_high)})`}
            />
          </div>
          <span className="tnum text-right text-xs text-ink">
            {coefficient(driver.coefficient)}
          </span>
        </div>
      ))}
      <p className="text-xs text-ink-muted">
        Dot is the estimate; the bar is its 95% interval. An interval crossing the zero line means
        the sign is not established.
      </p>
    </div>
  );
}
