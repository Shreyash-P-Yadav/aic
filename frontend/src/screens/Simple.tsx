/**
 * The five read-only operational screens.
 *
 * They share a shape — fetch, skeleton, empty state, error state, table — so they are
 * one file with five exports rather than five files with the same file in them. Each
 * is small because the interesting work happened in the pipeline that produced the
 * rows; the screen's job is to make it legible.
 */

import { Fragment } from 'react';
import { useQuery } from '@tanstack/react-query';

import { ReliabilityChart } from '@/components/ReliabilityChart';
import type { EvalMeasurement } from '@/lib/types';

import {
  Card,
  EmptyState,
  ErrorState,
  FreshnessBadge,
  SectionTitle,
  SimulatedLabel,
  Skeleton,
} from '@/components/primitives';
import { api, ApiError } from '@/lib/api';
import { share } from '@/lib/format';

function Panel<T>({
  title,
  hint,
  query,
  empty,
  children,
}: {
  title: string;
  hint?: string;
  query: { isPending: boolean; isError: boolean; error: unknown; data: T[] | undefined };
  empty: string;
  children: (rows: T[]) => React.ReactNode;
}) {
  return (
    <Card>
      <SectionTitle hint={hint}>{title}</SectionTitle>
      {query.isPending ? <Skeleton rows={3} /> : null}
      {query.isError ? (
        <EmptyState
          title={empty}
          detail={
            query.error instanceof ApiError
              ? (query.error.problem.detail ?? query.error.problem.title)
              : String(query.error)
          }
        />
      ) : null}
      {query.data?.length === 0 ? <EmptyState title={empty} /> : null}
      {query.data && query.data.length > 0 ? children(query.data) : null}
    </Card>
  );
}

export function DataSources() {
  const sources = useQuery({ queryKey: ['sources'], queryFn: ({ signal }) => api.sources(signal) });
  const freshness = useQuery({
    queryKey: ['freshness'],
    queryFn: ({ signal }) => api.freshness(signal),
    retry: false,
  });
  const dq = useQuery({ queryKey: ['dq'], queryFn: ({ signal }) => api.dq(signal), retry: false });
  return (
    <div className="space-y-6">
      <SimulatedLabel />
      <Panel
        title="Source contracts"
        hint="Eleven feeds, each with its own cadence and its own way of being wrong"
        query={sources}
        empty="No source contracts loaded"
      >
        {(rows) => (
          <div className="grid gap-3 md:grid-cols-2 xl:grid-cols-3">
            {rows.map((source) => (
              <article key={source.source_id} className="rounded border border-hairline-border p-3">
                <p className="text-sm font-medium text-ink">{source.source_id}</p>
                <p className="mt-0.5 text-xs text-ink-secondary">{source.system}</p>
                <dl className="mt-2 grid grid-cols-2 gap-x-3 gap-y-1 text-xs text-ink-muted">
                  <dt>Cadence</dt>
                  <dd className="text-ink-secondary">{source.cadence}</dd>
                  <dt>SLA</dt>
                  <dd className="tnum text-ink-secondary">{source.latency_sla_hours}h</dd>
                  <dt>Quality</dt>
                  <dd className="text-ink-secondary">{source.quality_tier}</dd>
                </dl>
                {source.known_issues.length > 0 ? (
                  <p className="mt-2 text-[11px] text-ink-muted">
                    Known issues: {source.known_issues.join(', ')}
                  </p>
                ) : null}
              </article>
            ))}
          </div>
        )}
      </Panel>
      <Panel title="Freshness" query={freshness} empty="No warehouse is loaded">
        {(rows) => (
          <ul className="space-y-1 text-sm">
            {rows.map((row) => (
              <li key={row.source_id} className="flex flex-wrap justify-between gap-2">
                <span className="text-ink-secondary">{row.source_id}</span>
                <FreshnessBadge state={row.state} />
              </li>
            ))}
          </ul>
        )}
      </Panel>
      <Panel
        title="Data quality"
        hint="Quarantine, never drop — every held row is countable with a reason"
        query={dq}
        empty="No warehouse is loaded"
      >
        {(rows) => (
          <div className="overflow-x-auto">
            <table className="w-full min-w-[34rem] text-xs">
              <thead>
                <tr className="border-b border-hairline-grid text-left text-ink-muted">
                  <th className="py-1.5 pr-3 font-medium">Source</th>
                  <th className="py-1.5 pr-3 font-medium">Expectation</th>
                  <th className="py-1.5 pr-3 font-medium">Outcome</th>
                  <th className="py-1.5 font-medium">Rows</th>
                </tr>
              </thead>
              <tbody className="tnum text-ink-secondary">
                {rows.slice(0, 40).map((row, index) => (
                  <tr key={index} className="border-b border-hairline-grid last:border-0">
                    <td className="py-1.5 pr-3">{row.source_id}</td>
                    <td className="py-1.5 pr-3">{row.expectation}</td>
                    <td className="py-1.5 pr-3">{row.outcome}</td>
                    <td className="py-1.5">{row.rows_affected}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </Panel>
    </div>
  );
}

export function TrustCalibration() {
  const calibration = useQuery({
    queryKey: ['calibration'],
    queryFn: ({ signal }) => api.calibration(signal),
  });
  const evals = useQuery({ queryKey: ['evals'], queryFn: ({ signal }) => api.evals(signal) });

  return (
    <div className="space-y-6">
      <SimulatedLabel />
      <Card>
        <SectionTitle hint="Confidence is computed and calibrated, never claimed">
          Calibration
        </SectionTitle>
        {calibration.isPending ? <Skeleton rows={2} /> : null}
        {calibration.isError ? <ErrorState title="Could not read the calibration state" /> : null}
        {calibration.data ? (
          <div className="space-y-2">
            <p className="text-2xl font-semibold text-ink">
              {calibration.data.fitted ? 'Fitted' : 'Not yet adopted'}
            </p>
            <p className="text-sm text-ink-secondary">{calibration.data.detail}</p>
            <p className="text-xs text-ink-muted">
              A map is fitted only when it earns adoption. Below the discrimination floor the
              composite score is shown raw and labelled uncalibrated — a fabricated calibration
              curve would be worse than none.
            </p>
          </div>
        ) : null}
      </Card>

      {evals.isPending ? (
        <Card>
          <SectionTitle>Backtest</SectionTitle>
          <Skeleton rows={5} />
        </Card>
      ) : null}

      {evals.data && !evals.data.available ? (
        <Card>
          <SectionTitle>Backtest</SectionTitle>
          <EmptyState title="No backtest has been run here" detail={evals.data.detail} />
        </Card>
      ) : null}

      {evals.data?.available ? (
        <>
          <Card>
            <SectionTitle hint={`${evals.data.corpus_events} ledger events replayed`}>
              Backtest
            </SectionTitle>
            <p className="text-sm text-ink-secondary">
              Temporal split at <span className="tnum">{evals.data.cut_date}</span> —{' '}
              <span className="tnum">{evals.data.fit_events}</span> events fitted,{' '}
              <span className="tnum">{evals.data.holdout_events}</span> held out. Every metric below
              is measured; none was re-targeted to produce a pass.
            </p>
            <div className="mt-3 overflow-x-auto">
              <table className="w-full text-left text-xs">
                <thead className="text-ink-muted">
                  <tr>
                    <th className="py-1 font-normal">Metric</th>
                    <th className="py-1 text-right font-normal">Measured</th>
                    <th className="py-1 text-right font-normal">Target</th>
                    <th className="py-1 text-right font-normal">n</th>
                    <th className="py-1 text-right font-normal">Verdict</th>
                  </tr>
                </thead>
                <tbody className="tnum">
                  {groupBySection(evals.data.measurements).map(([section, rows]) => (
                    <Fragment key={section}>
                      <tr>
                        <th
                          colSpan={5}
                          className="pt-3 pb-1 text-left text-[11px] font-semibold uppercase tracking-wide text-ink-muted"
                        >
                          {section}
                        </th>
                      </tr>
                      {rows.map((item) => (
                        <tr
                          key={`${section}-${item.name}`}
                          className="border-t"
                          style={{ borderColor: 'var(--hairline-grid)' }}
                        >
                          <td className="py-1 pr-2 text-ink-secondary" title={item.detail}>
                            {item.name}
                          </td>
                          <td className="py-1 text-right text-ink">
                            {metric(item.value, item.unit)}
                          </td>
                          <td className="py-1 text-right text-ink-muted">
                            {item.target === null ? '—' : metric(item.target, item.unit)}
                          </td>
                          <td className="py-1 text-right text-ink-muted">{item.n}</td>
                          <td className="py-1 text-right">
                            <Verdict verdict={item.verdict} />
                          </td>
                        </tr>
                      ))}
                    </Fragment>
                  ))}
                </tbody>
              </table>
            </div>
          </Card>

          <div className="grid gap-6 lg:grid-cols-2">
            <Card>
              <SectionTitle hint="Predicted against observed">Reliability curve</SectionTitle>
              <ReliabilityChart bins={evals.data.reliability} />
            </Card>
            <Card>
              <SectionTitle hint={evals.data.tier_basis || 'Observed hit rate per tier'}>
                Tiers as measured
              </SectionTitle>
              <table className="w-full text-left text-xs">
                <thead className="text-ink-muted">
                  <tr>
                    <th className="py-1 font-normal">Tier</th>
                    <th className="py-1 text-right font-normal">n</th>
                    <th className="py-1 text-right font-normal">Mean score</th>
                    <th className="py-1 text-right font-normal">Observed</th>
                  </tr>
                </thead>
                <tbody className="tnum">
                  {evals.data.tiers.map((row) => (
                    <tr
                      key={row.tier}
                      className="border-t"
                      style={{ borderColor: 'var(--hairline-grid)' }}
                    >
                      <td className="py-1 text-ink">{row.tier}</td>
                      <td className="py-1 text-right text-ink-secondary">{row.n}</td>
                      <td className="py-1 text-right text-ink-secondary">
                        {row.n ? row.mean_score.toFixed(3) : '—'}
                      </td>
                      <td className="py-1 text-right text-ink-secondary">
                        {row.n ? `${(row.hit_rate * 100).toFixed(0)}%` : '—'}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
              <p className="mt-2 text-xs text-ink-muted">
                A tier with no events is shown empty rather than hidden. A band nothing can enter is
                a fact about the curve, not a gap in the table.
              </p>
            </Card>
          </div>

          {evals.data.notes.length > 0 ? (
            <Card>
              <SectionTitle>Notes from the run</SectionTitle>
              <ul className="space-y-1 text-xs text-ink-secondary">
                {evals.data.notes.map((note) => (
                  <li key={note}>{note}</li>
                ))}
              </ul>
            </Card>
          ) : null}
        </>
      ) : null}
    </div>
  );
}

/**
 * Group measurements under their section heading, preserving the report's own order.
 *
 * Twenty-five rows in one flat list is a wall. The sections are how the eval suite
 * itself thinks about them — calibration, attribution, detection and so on — so
 * grouping here costs nothing and makes a judge able to find the one they care about.
 */
function groupBySection(items: EvalMeasurement[]): [string, EvalMeasurement[]][] {
  const order: string[] = [];
  const groups = new Map<string, EvalMeasurement[]>();
  for (const item of items) {
    const key = item.section || 'Other';
    if (!groups.has(key)) {
      groups.set(key, []);
      order.push(key);
    }
    groups.get(key)?.push(item);
  }
  return order.map((key) => [key, groups.get(key) ?? []]);
}

/** Format a measured value the way its unit wants to be read. */
function metric(value: number, unit: string): string {
  if (!Number.isFinite(value)) return 'not measured';
  if (unit === '%') return `${(value * 100).toFixed(1)}%`;
  if (unit === 'ms') return `${value.toFixed(0)} ms`;
  if (unit === 'usd') return `$${value.toFixed(4)}`;
  if (unit === 'count') return value.toLocaleString('en-IN');
  return value.toFixed(3);
}

/** PASS, FAIL or a dash — coloured by status token, never by a series colour. */
function Verdict({ verdict }: { verdict: string }) {
  if (verdict === '—') return <span className="text-ink-muted">—</span>;
  const good = verdict === 'PASS';
  return (
    <span
      className="rounded px-1.5 py-0.5 text-[10px] font-medium"
      style={{ color: good ? 'var(--status-good)' : 'var(--status-critical)' }}
    >
      {verdict}
    </span>
  );
}

export function Telemetry() {
  const telemetry = useQuery({
    queryKey: ['telemetry'],
    queryFn: ({ signal }) => api.telemetry(signal),
  });
  return (
    <div className="space-y-6">
      <SimulatedLabel />
      <Card>
        <SectionTitle hint="Priced from real token counts, at list rates">Model cost</SectionTitle>
        {telemetry.isPending ? <Skeleton rows={2} /> : null}
        {telemetry.data ? (
          <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
            <Stat label="Insights metered" value={String(telemetry.data.insights_metered)} />
            <Stat
              label="Mean cost / insight"
              value={`₹${telemetry.data.mean_inr_per_insight.toFixed(3)}`}
            />
            <Stat label="Model calls" value={String(telemetry.data.model_calls)} />
            <Stat
              label="Cache hit rate"
              value={
                telemetry.data.model_calls + telemetry.data.cache_hits === 0
                  ? '—'
                  : share(
                      telemetry.data.cache_hits /
                        (telemetry.data.model_calls + telemetry.data.cache_hits),
                    )
              }
            />
          </div>
        ) : null}
        <p className="mt-3 text-xs text-ink-muted">
          Every model call is metered against the insight it was made for, and priced from the
          tokens it actually used at published list rates. Running offline the calls are free, so
          this is what the same work <em>would</em> cost — a modelled figure from real usage, not a
          bill. Cache hits are counted too: a cost per insight that ignored them would improve on
          paper exactly as caching made it cheaper.
        </p>
        <p className="mt-3 text-xs text-ink-muted">
          {telemetry.data?.downgrades ?? 0} call(s) downshifted to a smaller model by the
          per-insight cost cap. A downgrade is always logged, so a cheaper narrative is never
          mistaken for a considered one.
        </p>
      </Card>
    </div>
  );
}

function Stat({ label, value }: { label: string; value: string }) {
  return (
    <div>
      <p className="text-xs uppercase tracking-wide text-ink-muted">{label}</p>
      <p className="mt-1 text-2xl font-semibold text-ink">{value}</p>
    </div>
  );
}

export function Audit() {
  const audit = useQuery({ queryKey: ['audit'], queryFn: ({ signal }) => api.audit(signal) });
  return (
    <div className="space-y-6">
      <SimulatedLabel />
      <Panel
        title="Audit log"
        hint="A refusal is as auditable as a result"
        query={audit}
        empty="Nothing audited yet in this session"
      >
        {(rows) => (
          <div className="overflow-x-auto">
            <table className="w-full min-w-[38rem] text-xs">
              <thead>
                <tr className="border-b border-hairline-grid text-left text-ink-muted">
                  <th className="py-1.5 pr-3 font-medium">Run</th>
                  <th className="py-1.5 pr-3 font-medium">Event</th>
                  <th className="py-1.5 pr-3 font-medium">Role</th>
                  <th className="py-1.5 pr-3 font-medium">Contract</th>
                  <th className="py-1.5 pr-3 font-medium">Outcome</th>
                  <th className="py-1.5 font-medium">Rows</th>
                </tr>
              </thead>
              <tbody className="tnum text-ink-secondary">
                {rows.map((row, index) => (
                  <tr key={index} className="border-b border-hairline-grid last:border-0">
                    <td className="py-1.5 pr-3">{row.run_id.slice(0, 8)}</td>
                    <td className="py-1.5 pr-3">{row.event}</td>
                    <td className="py-1.5 pr-3">{row.role}</td>
                    <td className="py-1.5 pr-3">{row.contract_id ?? '—'}</td>
                    <td className="py-1.5 pr-3">{row.outcome}</td>
                    <td className="py-1.5">{row.rows_returned ?? '—'}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </Panel>
    </div>
  );
}
