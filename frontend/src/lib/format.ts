/**
 * Number formatting, in the units this business actually reads.
 *
 * A CFO reads crore, a regional manager reads lakh, an analyst reads the number. The
 * *value* is identical in all three — the backend's verifier matches any of them
 * against the same computed fact — so the choice here is presentational and safe.
 */

const CRORE = 10_000_000;
const LAKH = 100_000;

/** Rupees, at the largest Indian unit that keeps the number readable. */
export function inr(value: number): string {
  const magnitude = Math.abs(value);
  if (magnitude >= CRORE) return `₹${(value / CRORE).toFixed(2)} cr`;
  if (magnitude >= LAKH) return `₹${(value / LAKH).toFixed(1)} lakh`;
  return `₹${value.toLocaleString('en-IN', { maximumFractionDigits: 0 })}`;
}

/**
 * A quantity in its own unit.
 *
 * Only rupees get crore and lakh. A count of units rendered as "₹-21,082" is wrong, and
 * it is the same mistake the number verifier caught in the narration layer — a UI has
 * no way to avoid it unless the API tells it the unit.
 */
export function quantity(value: number, unit: string): string {
  if (unit === 'INR') return inr(value);
  if (unit === 'percent') return `${value.toFixed(2)}pp`;
  return `${value.toLocaleString('en-IN', { maximumFractionDigits: 0 })} ${unit}`;
}

/** A signed percentage, always with its direction visible. */
export function pct(value: number, digits = 2): string {
  return `${value >= 0 ? '+' : ''}${value.toFixed(digits)}%`;
}

/** A 0-1 fraction as a percentage, for shares and win rates. */
export function share(value: number, digits = 0): string {
  return `${(value * 100).toFixed(digits)}%`;
}

/** A coefficient or elasticity, at the precision an analyst reads them. */
export function coefficient(value: number): string {
  return value.toFixed(3);
}

/** An ISO timestamp as a short local string. */
export function when(iso: string): string {
  const parsed = new Date(iso);
  if (Number.isNaN(parsed.getTime())) return iso;
  return parsed.toLocaleString('en-IN', {
    day: '2-digit',
    month: 'short',
    hour: '2-digit',
    minute: '2-digit',
  });
}

/** An ISO date as a short local date. */
export function day(iso: string): string {
  const parsed = new Date(iso);
  if (Number.isNaN(parsed.getTime())) return iso;
  return parsed.toLocaleDateString('en-IN', { day: '2-digit', month: 'short', year: 'numeric' });
}
