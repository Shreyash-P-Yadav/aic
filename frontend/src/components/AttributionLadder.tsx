/**
 * The attribution ladder: four labelled rungs, each expandable.
 *
 * The order is the argument. WHERE narrows the movement to a segment, WHAT KIND says
 * whether that segment moved on price, volume or mix, WHY estimates the drivers behind
 * it, and WHAT EVENT points at the document that says it happened. A reader who stops
 * at any rung has a true, smaller answer rather than a partial one.
 */

import { useState } from 'react';

import { coefficient, day, inr, share } from '@/lib/format';
import { isUnmapped, UNMAPPED_NOTE } from '@/lib/segments';
import type { InsightBundle } from '@/lib/types';
import { ConfidencePanel } from './ConfidencePanel';
import { DriverChart } from './DriverChart';
import { EmptyState, SectionTitle } from './primitives';
import { Waterfall, type WaterfallStep } from './Waterfall';

type Rung = 'where' | 'kind' | 'why' | 'event';

const RUNG_TITLE: Record<Rung, string> = {
  where: 'Where',
  kind: 'What kind',
  why: 'Why',
  event: 'What event',
};

const RUNG_SUBTITLE: Record<Rung, string> = {
  where: 'Adtributor — explanatory power x surprise, with a bootstrap win rate',
  kind: 'Bennet price-volume-mix — the parts sum to the whole exactly',
  why: 'Driver estimates with their intervals, and the diagnostics behind them',
  event: 'Documents that survived the timing gate',
};

export function AttributionLadder({ bundle }: { bundle: InsightBundle }) {
  const [open, setOpen] = useState<Rung>('where');
  return (
    <div className="space-y-3">
      {(['where', 'kind', 'why', 'event'] as Rung[]).map((rung) => (
        <div key={rung} className="rounded-card border border-hairline-border bg-card">
          <button
            type="button"
            onClick={() => setOpen(open === rung ? ('where' as Rung) : rung)}
            aria-expanded={open === rung}
            className="flex w-full items-baseline justify-between gap-3 px-5 py-3 text-left"
          >
            <span className="text-sm font-semibold text-ink">{RUNG_TITLE[rung]}</span>
            <span className="hidden text-xs text-ink-muted sm:block">{RUNG_SUBTITLE[rung]}</span>
          </button>
          {open === rung ? (
            <div className="border-t border-hairline-border px-5 py-4">
              {rung === 'where' ? <WhereRung bundle={bundle} /> : null}
              {rung === 'kind' ? <KindRung bundle={bundle} /> : null}
              {rung === 'why' ? <WhyRung bundle={bundle} /> : null}
              {rung === 'event' ? <EventRung bundle={bundle} /> : null}
            </div>
          ) : null}
        </div>
      ))}
    </div>
  );
}

function WhereRung({ bundle }: { bundle: InsightBundle }) {
  if (bundle.segments.length === 0) {
    return <EmptyState title="No segment cleared the minimum explanatory-power floor." />;
  }
  const widest = Math.max(...bundle.segments.map((item) => Math.abs(item.explanatory_power)), 0.01);
  return (
    <div className="space-y-2">
      {bundle.segments.map((segment) => (
        <div key={segment.label} className="grid grid-cols-[10rem_1fr_7rem] items-center gap-3">
          <span
            className="truncate text-xs text-ink-secondary"
            title={
              isUnmapped(segment.label) ? `${segment.label} — ${UNMAPPED_NOTE}` : segment.label
            }
          >
            {segment.label}
            {isUnmapped(segment.label) ? (
              <span className="ml-1 rounded border border-hairline-border px-1 text-[10px] text-ink-muted">
                unmapped
              </span>
            ) : null}
          </span>
          <span className="h-3 rounded" style={{ backgroundColor: 'var(--hairline-grid)' }}>
            <span
              className="block h-3 rounded"
              style={{
                width: `${(Math.abs(segment.explanatory_power) / widest) * 100}%`,
                backgroundColor: 'var(--series-1)',
              }}
            />
          </span>
          <span className="tnum text-right text-xs text-ink-secondary">
            {share(segment.explanatory_power)} · win {share(segment.stability)}
          </span>
        </div>
      ))}
      <p className="text-xs text-ink-muted">
        A segment below a 90% bootstrap win rate is a ranked shortlist entry, never a named cause.
      </p>
    </div>
  );
}

function KindRung({ bundle }: { bundle: InsightBundle }) {
  if (
    bundle.price_effect === null ||
    bundle.volume_effect === null ||
    bundle.mix_effect === null ||
    bundle.pvm_reference === null ||
    bundle.pvm_comparison === null
  ) {
    return <EmptyState title="No price-volume-mix decomposition was computed for this window." />;
  }
  // Anchored on the two windows the decomposition ACTUALLY compares, not on the
  // counterfactual. This rung answers a different question from the headline — "of the
  // change from the previous window to this one, how much was price, volume and mix" —
  // and anchoring it on the counterfactual would leave a residual bar that is really
  // just the distance between two different comparisons. A reader would read that as
  // model error.
  const steps: WaterfallStep[] = [
    { label: 'Previous window', value: bundle.pvm_reference, kind: 'anchor' },
    { label: 'Price', value: bundle.price_effect, kind: 'delta' },
    { label: 'Volume', value: bundle.volume_effect, kind: 'delta' },
    { label: 'Mix', value: bundle.mix_effect, kind: 'delta' },
    { label: 'This window', value: bundle.pvm_comparison, kind: 'anchor' },
  ];
  return (
    <div className="space-y-2">
      <Waterfall steps={steps} />
      <p className="text-xs text-ink-muted">
        {bundle.pvm_label ? `${bundle.pvm_label}. ` : ''}
        The Bennet indicator is exact: price, volume and mix sum to the change between these two
        windows with no residual term. This is a different comparison from the headline, which is
        measured against the counterfactual rather than against the previous window.
      </p>
    </div>
  );
}

function WhyRung({ bundle }: { bundle: InsightBundle }) {
  if (bundle.drivers.length === 0) {
    return <EmptyState title="No driver estimate survived the contract's admissibility rules." />;
  }
  return (
    <div className="space-y-4">
      <DriverChart drivers={bundle.drivers} />
      <div className="overflow-x-auto">
        <table className="w-full min-w-[26rem] text-xs">
          <thead>
            <tr className="border-b border-hairline-grid text-left text-ink-muted">
              <th className="py-1.5 pr-3 font-medium">Driver</th>
              <th className="py-1.5 pr-3 font-medium">Coefficient</th>
              <th className="py-1.5 pr-3 font-medium">95% interval</th>
              <th className="py-1.5 pr-3 font-medium">p</th>
              <th className="py-1.5 font-medium">Agreement</th>
            </tr>
          </thead>
          <tbody className="tnum text-ink-secondary">
            {bundle.drivers.map((driver) => (
              <tr key={driver.driver_id} className="border-b border-hairline-grid last:border-0">
                <td className="py-1.5 pr-3">{driver.driver_id}</td>
                <td className="py-1.5 pr-3">{coefficient(driver.coefficient)}</td>
                <td className="py-1.5 pr-3">
                  {coefficient(driver.interval_low)} to {coefficient(driver.interval_high)}
                </td>
                <td className="py-1.5 pr-3">{driver.p_value.toFixed(4)}</td>
                <td className="py-1.5">{share(driver.agreement)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <p className="text-xs text-ink-muted">
        {share(bundle.explained_fraction)} of the variation is explained;{' '}
        {share(bundle.unexplained_fraction)} is not, and is labelled rather than allocated.
      </p>
    </div>
  );
}

function EventRung({ bundle }: { bundle: InsightBundle }) {
  if (bundle.evidence.length === 0) {
    return (
      <EmptyState
        title="No document cleared the evidence floor."
        detail={`${bundle.evidence_rejected_by_timing.length} candidate(s) were eliminated by the timing gate.`}
      />
    );
  }
  return (
    <div className="space-y-3">
      {bundle.evidence.map((item) => (
        <article key={item.doc_id} className="rounded border border-hairline-border p-3">
          <header className="flex flex-wrap items-baseline justify-between gap-2">
            <h3 className="text-sm font-medium text-ink">{item.title}</h3>
            <span className="text-xs text-ink-muted">
              tier {item.source_tier} · confidence {item.confidence.toFixed(2)}
            </span>
          </header>
          <p className="mt-1 text-xs text-ink-secondary">
            {item.kind} · published {day(item.publish_date)} · effective {day(item.effective_date)}{' '}
            · matched on {item.matched_on}
          </p>
        </article>
      ))}
      <p className="text-xs text-ink-muted">
        Corroboration {bundle.evidence_corroboration.toFixed(2)} by noisy-OR across independent
        sources; syndicated copies of one story count once.{' '}
        {bundle.evidence_rejected_by_timing.length} candidate(s) eliminated by the timing gate.
      </p>
    </div>
  );
}

export function ConfidenceRail({ bundle }: { bundle: InsightBundle }) {
  return (
    <aside className="space-y-4">
      <div className="rounded-card border border-hairline-border bg-card p-5">
        <SectionTitle>Confidence</SectionTitle>
        <ConfidencePanel confidence={bundle.confidence} />
      </div>
      <div className="rounded-card border border-hairline-border bg-card p-5">
        <SectionTitle hint={`watermark ${bundle.watermark ?? 'none'}`}>Freshness</SectionTitle>
        <ul className="space-y-1 text-xs text-ink-secondary">
          {bundle.freshness.map((item) => (
            <li key={item.source_id} className="flex justify-between gap-2">
              <span>{item.source_id}</span>
              <span className="tnum text-ink-muted">
                {item.age_hours === null ? '—' : `${item.age_hours.toFixed(1)}h`} / {item.sla_hours}
                h
              </span>
            </li>
          ))}
        </ul>
      </div>
      <div className="rounded-card border border-hairline-border bg-card p-5">
        <SectionTitle>Lineage</SectionTitle>
        <ol className="space-y-1 text-xs text-ink-secondary">
          {bundle.lineage.map((step) => (
            <li key={`${step.stage}-${step.to}`}>
              <span className="text-ink-muted">{step.stage}</span> {step.frm} → {step.to}
            </li>
          ))}
        </ol>
      </div>
      <div className="rounded-card border border-hairline-border bg-card p-5">
        <SectionTitle>Method</SectionTitle>
        <p className="text-xs text-ink-secondary">
          Detected by {bundle.detection_method} at p = {bundle.p_value.toFixed(4)}. Counterfactual{' '}
          {inr(bundle.counterfactual)} against an observed {inr(bundle.observed)}.
        </p>
      </div>
    </aside>
  );
}
