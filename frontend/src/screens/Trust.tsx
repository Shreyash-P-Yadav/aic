/**
 * Trust & calibration — the backtest, exactly as it was measured.
 *
 * Split out of the other read-only screens because it is the only one that argues:
 * the rest report state, this one reports whether the system earned the right to be
 * believed, FAILs included.
 */

import { ReliabilityChart } from '@/components/ReliabilityChart';
import {
  Card,
  EmptyState,
  ErrorState,
  SectionTitle,
  SimulatedLabel,
  Skeleton,
} from '@/components/primitives';
import { api } from '@/lib/api';
import type { EvalMeasurement } from '@/lib/types';
import { useQuery } from '@tanstack/react-query';
import { Fragment } from 'react';

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
