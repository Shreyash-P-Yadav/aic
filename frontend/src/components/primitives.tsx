/**
 * The small shared pieces: skeletons, empty states, error states, chips, cards.
 *
 * Skeletons rather than spinners, because a spinner tells a reader that something is
 * happening and a skeleton tells them what is about to appear. Every async panel in
 * this app has one, and an explicit empty state and error state besides — a panel
 * that renders nothing when it has nothing is indistinguishable from a broken panel.
 */

import type { ReactNode } from 'react';

import type { FreshnessState, Tier } from '@/lib/types';

export function Card({ children, className = '' }: { children: ReactNode; className?: string }) {
  return (
    <section
      className={`rounded-card border border-hairline-border bg-card p-5 shadow-card ${className}`}
    >
      {children}
    </section>
  );
}

export function SectionTitle({ children, hint }: { children: ReactNode; hint?: string }) {
  return (
    <header className="mb-3 flex items-baseline justify-between gap-3">
      <h2 className="text-sm font-semibold uppercase tracking-wide text-ink-secondary">
        {children}
      </h2>
      {hint ? <span className="text-xs text-ink-muted">{hint}</span> : null}
    </header>
  );
}

export function Skeleton({ rows = 3 }: { rows?: number }) {
  return (
    <div className="space-y-2" aria-busy="true" data-testid="skeleton">
      {Array.from({ length: rows }).map((_, index) => (
        <div
          key={index}
          className="h-4 animate-pulse rounded bg-hairline-grid"
          style={{ width: `${100 - index * 12}%` }}
        />
      ))}
    </div>
  );
}

export function EmptyState({ title, detail }: { title: string; detail?: string }) {
  return (
    <div className="rounded-card border border-dashed border-hairline-axis p-6 text-center">
      <p className="text-sm font-medium text-ink-secondary">{title}</p>
      {detail ? <p className="mt-1 text-xs text-ink-muted">{detail}</p> : null}
    </div>
  );
}

export function ErrorState({ title, detail }: { title: string; detail?: string | null }) {
  return (
    <div
      role="alert"
      className="rounded-card border border-hairline-border p-6"
      style={{ borderLeftWidth: 3, borderLeftColor: 'var(--status-critical)' }}
    >
      <p className="text-sm font-medium text-ink">{title}</p>
      {detail ? <p className="mt-1 text-xs text-ink-secondary">{detail}</p> : null}
    </div>
  );
}

const TIER_STYLE: Record<Tier, { colour: string; label: string }> = {
  High: { colour: 'var(--status-good)', label: 'High confidence' },
  Moderate: { colour: 'var(--status-warning)', label: 'Moderate confidence' },
  Low: { colour: 'var(--status-serious)', label: 'Low confidence' },
  Insufficient: { colour: 'var(--ink-muted)', label: 'Insufficient — abstained' },
};

/**
 * Status is never colour alone: every chip carries its label, because a reader with
 * a colour-vision deficiency and a reader glancing at a projector need the same thing.
 */
export function TierChip({ tier }: { tier: Tier }) {
  const style = TIER_STYLE[tier];
  return (
    <span
      className="inline-flex items-center gap-1.5 rounded-full border border-hairline-border px-2.5 py-0.5 text-xs font-medium text-ink-secondary"
      title={style.label}
    >
      <span
        aria-hidden
        className="h-2 w-2 rounded-full"
        style={{ backgroundColor: style.colour }}
      />
      {tier}
    </span>
  );
}

const FRESHNESS_STYLE: Record<FreshnessState, { colour: string; icon: string }> = {
  green: { colour: 'var(--status-good)', icon: '●' },
  amber: { colour: 'var(--status-warning)', icon: '◐' },
  red: { colour: 'var(--status-critical)', icon: '▲' },
  unknown: { colour: 'var(--ink-muted)', icon: '○' },
};

/** Icon *and* label, never colour alone. */
export function FreshnessBadge({ state }: { state: FreshnessState }) {
  const style = FRESHNESS_STYLE[state];
  return (
    <span className="inline-flex items-center gap-1 text-xs text-ink-secondary">
      <span aria-hidden style={{ color: style.colour }}>
        {style.icon}
      </span>
      {state}
    </span>
  );
}

/** Marks a region of the page as model-written rather than computed. */
export function ProvenanceTag({ kind }: { kind: 'computed' | 'model' }) {
  return (
    <span
      className="rounded border border-hairline-border px-1.5 py-0.5 text-[10px] uppercase tracking-wide text-ink-muted"
      data-provenance={kind}
    >
      {kind === 'model' ? 'LLM-written' : 'computed'}
    </span>
  );
}

/** The label the design requires on every panel of simulated data. */
export function SimulatedLabel() {
  return (
    <p className="text-[11px] uppercase tracking-wide text-ink-muted">
      Simulated data — Meridian Consumer Brands is a fictional company
    </p>
  );
}
