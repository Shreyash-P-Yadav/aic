/**
 * The home screen: a freshness strip, then prioritised insight cards.
 *
 * Abstention cards are **visually distinct but not styled as errors**. An abstention
 * is a designed outcome — the system declining to guess — and painting it red would
 * teach a reader to read restraint as failure, which is the opposite of the point.
 */

import { useState } from 'react';
import { Link } from 'react-router-dom';
import { useQuery } from '@tanstack/react-query';

import { api, ApiError } from '@/lib/api';
import { Sparkline } from '@/components/Sparkline';
import { inr, pct, when } from '@/lib/format';
import type { InsightSummary } from '@/lib/types';
import {
  Card,
  EmptyState,
  ErrorState,
  FreshnessBadge,
  SectionTitle,
  Skeleton,
  TierChip,
} from '@/components/primitives';

export function InsightFeed() {
  const [status, setStatus] = useState<string>('');
  const insights = useQuery({
    queryKey: ['insights', status],
    queryFn: ({ signal }) => api.insights({ status: status || undefined }, signal),
  });

  return (
    <div className="space-y-6">
      <FreshnessStrip />
      <section>
        <SectionTitle hint="Prioritised by impact x tier x persistence">Insights</SectionTitle>
        <div className="mb-3 flex flex-wrap gap-2">
          {[
            { value: '', label: 'All' },
            { value: 'published', label: 'Published' },
            { value: 'abstained', label: 'Abstained' },
          ].map((option) => (
            <button
              key={option.value}
              type="button"
              onClick={() => setStatus(option.value)}
              aria-pressed={status === option.value}
              className={`rounded-full border px-3 py-1 text-xs transition ${
                status === option.value
                  ? 'border-hairline-axis bg-card text-ink'
                  : 'border-hairline-border text-ink-secondary'
              }`}
            >
              {option.label}
            </button>
          ))}
        </div>
        {insights.isPending ? <Skeleton rows={4} /> : null}
        {insights.isError ? (
          <ErrorState
            title="Could not load insights"
            detail={
              insights.error instanceof ApiError
                ? insights.error.problem.detail
                : String(insights.error)
            }
          />
        ) : null}
        {insights.data?.length === 0 ? (
          <EmptyState
            title="Nothing has been computed yet"
            detail="Run `make demo` to backfill, replay and scan."
          />
        ) : null}
        <div className="grid gap-3 lg:grid-cols-2">
          {(insights.data ?? []).map((insight) => (
            <InsightCard key={insight.insight_id} insight={insight} />
          ))}
        </div>
      </section>
    </div>
  );
}

function InsightCard({ insight }: { insight: InsightSummary }) {
  const abstained = insight.status === 'abstained';
  return (
    <Link
      to={`/insights/${insight.insight_id}`}
      className="block rounded-card border bg-card p-5 shadow-card transition hover:border-hairline-axis"
      style={{
        borderColor: 'var(--hairline-border)',
        borderLeftWidth: 3,
        borderLeftColor: abstained ? 'var(--ink-muted)' : 'var(--series-1)',
        borderLeftStyle: abstained ? 'dashed' : 'solid',
      }}
      data-status={insight.status}
    >
      <div className="flex flex-wrap items-baseline justify-between gap-2">
        <span className="text-sm font-semibold text-ink">{insight.kpi_id}</span>
        <TierChip tier={insight.tier} />
      </div>
      <div className="mt-2 flex items-end justify-between gap-4">
        <div>
          <p className="text-2xl font-semibold text-ink">
            {abstained ? 'Not attributed' : pct(insight.delta_pct)}
          </p>
          {insight.impact_inr !== null ? (
            <p className="tnum mt-0.5 text-sm text-ink-secondary">{inr(insight.impact_inr)}</p>
          ) : null}
        </div>
        {/* Shape only, and only when there is history to show. A sparkline drawn from
            two points is a straight line that says nothing. */}
        <div className="w-28 shrink-0">
          <Sparkline values={insight.spark} muted={abstained} />
        </div>
      </div>
      <p className="mt-2 text-sm text-ink-secondary">{insight.headline}</p>
      <div className="mt-3 flex flex-wrap items-center gap-x-3 gap-y-1 text-xs text-ink-muted">
        <span>{when(insight.created_at)}</span>
        {insight.top_segment ? (
          <>
            <span aria-hidden>·</span>
            <span>
              led by <span className="text-ink-secondary">{insight.top_segment}</span>
            </span>
          </>
        ) : null}
      </div>
    </Link>
  );
}

function FreshnessStrip() {
  const freshness = useQuery({
    queryKey: ['freshness'],
    queryFn: ({ signal }) => api.freshness(signal),
    retry: false,
  });
  return (
    <Card>
      <SectionTitle hint="Green means the drop that was due has arrived">Sources</SectionTitle>
      {freshness.isPending ? <Skeleton rows={2} /> : null}
      {freshness.isError ? (
        <EmptyState
          title="No warehouse is loaded"
          detail={
            freshness.error instanceof ApiError
              ? (freshness.error.problem.detail ?? '')
              : 'Run `make backfill` first.'
          }
        />
      ) : null}
      {/* A grid, not a wrapping flex row: `flex-1` stretches the final row's tiles to
          fill the width, so eight tiles on row one and three on row two rendered at
          wildly different widths. auto-fill keeps every tile on the same 9rem module. */}
      <div className="grid gap-2 [grid-template-columns:repeat(auto-fill,minmax(9rem,1fr))]">
        {(freshness.data ?? []).map((source) => (
          <div
            key={source.source_id}
            className="rounded border border-hairline-border p-2"
            title={source.detail}
          >
            <p className="truncate text-xs font-medium text-ink">{source.source_id}</p>
            <div className="mt-1 flex items-center justify-between gap-2">
              <FreshnessBadge state={source.state} />
              <span className="tnum text-[11px] text-ink-muted">
                {source.age_hours === null ? '—' : `${source.age_hours.toFixed(0)}h`}
              </span>
            </div>
          </div>
        ))}
      </div>
    </Card>
  );
}
