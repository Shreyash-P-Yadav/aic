/**
 * The admin panel: the four controls that change the simulated world, and the roles.
 *
 * Each control shows what it will do *before* doing it, because an interactive control
 * that misbehaves on stage is worse than no control, and the cheapest defence is a
 * presenter who can read the consequence before they click.
 */

import { useState } from 'react';
import { useMutation, useQuery } from '@tanstack/react-query';

import { Card, SectionTitle, Skeleton } from '@/components/primitives';
import { api, ApiError } from '@/lib/api';

const CONTROLS = [
  {
    id: 'inject-event' as const,
    title: 'Inject event',
    consequence:
      'Jumps the simulated clock to two days before a planted ledger event and replays through it. You choose when it breaks; the break itself is real, with a counterfactual the ground-truth ledger can vouch for.',
    placeholder: 'EV-2026-0306-OUTAGE',
  },
  {
    id: 'break-feed' as const,
    title: 'Break a feed',
    consequence:
      'Pauses a source and runs the simulated clock forward until it has actually gone stale. Freshness walks to red on that contract’s own schedule while every other feed keeps delivering, the c4 signal collapses, and the engine re-runs and abstains rather than explaining revenue from the feeds that are left.',
    placeholder: 'oms_orders',
  },
  {
    id: 'restore-feed' as const,
    title: 'Restore a feed',
    consequence:
      'Lets a paused source deliver again and runs the clock until its next drop lands. Freshness returns to green and the engine re-runs and publishes — so the abstention demo can be shown twice.',
    placeholder: 'oms_orders',
  },
];

export function Admin() {
  const roles = useQuery({ queryKey: ['roles'], queryFn: ({ signal }) => api.roles(signal) });
  return (
    <div className="space-y-6">
      <Card>
        <SectionTitle hint="Each control says what it will do before it does it">
          Demo controls
        </SectionTitle>
        <div className="grid gap-4 md:grid-cols-2">
          {CONTROLS.map((control) => (
            <ControlCard key={control.id} control={control} />
          ))}
          <ClockCard />
        </div>
      </Card>
      <Card>
        <SectionTitle hint="Switching role changes the data, not the label">Roles</SectionTitle>
        {roles.isPending ? <Skeleton rows={3} /> : null}
        <ul className="space-y-2 text-sm">
          {(roles.data ?? []).map((role) => (
            <li key={role.name} className="rounded border border-hairline-border p-3">
              <p className="font-medium text-ink">{role.display_name}</p>
              <p className="mt-0.5 text-xs text-ink-secondary">{role.description}</p>
              {Object.keys(role.bindings).length > 0 ? (
                <p className="mt-1 text-xs text-ink-muted">
                  Row-filter bindings:{' '}
                  {Object.entries(role.bindings)
                    .map(([key, value]) => `${key} = ${value}`)
                    .join(', ')}
                </p>
              ) : null}
            </li>
          ))}
        </ul>
      </Card>
    </div>
  );
}

/** Bounds mirrored from `MIN_ADVANCE_DAYS` / `MAX_ADVANCE_DAYS` in `harness/controls.py`.
 *  The server rejects anything outside them; these only keep the input honest. */
const MIN_DAYS = 1;
const MAX_DAYS = 30;

function ClockCard() {
  const [days, setDays] = useState(3);
  const run = useMutation({ mutationFn: () => api.advanceClock(days) });
  return (
    <article className="rounded border border-hairline-border p-4">
      <h3 className="text-sm font-semibold text-ink">Advance the clock</h3>
      <p className="mt-1 text-xs text-ink-secondary">
        Runs the simulated clock forward by whole days. Every scheduled drop in that window lands in
        order, freshness is re-measured against each contract&rsquo;s own SLA, and the engine
        re-runs. Forward only — going back would mean wiping the warehouse and reloading it, because
        it already holds rows for days that would not have happened yet.
      </p>
      <div className="mt-3 flex gap-2">
        <label className="sr-only" htmlFor="advance-days">
          Days to advance
        </label>
        <input
          id="advance-days"
          type="number"
          min={MIN_DAYS}
          max={MAX_DAYS}
          value={days}
          onChange={(event) => setDays(Number(event.target.value))}
          className="w-20 rounded border border-hairline-border bg-card px-2 py-1 text-xs text-ink"
        />
        <button
          type="button"
          onClick={() => run.mutate()}
          disabled={run.isPending}
          className="rounded border border-hairline-axis px-3 py-1 text-xs text-ink disabled:opacity-50"
        >
          {run.isPending ? 'Replaying…' : 'Run'}
        </button>
      </div>
      {run.isError ? (
        <p className="mt-2 text-xs" style={{ color: 'var(--status-serious)' }}>
          {run.error instanceof ApiError
            ? (run.error.problem.detail ?? run.error.problem.title)
            : 'The control is unavailable.'}
        </p>
      ) : null}
      {run.data ? <p className="mt-2 text-xs text-ink-secondary">{run.data.detail}</p> : null}
    </article>
  );
}

function ControlCard({ control }: { control: (typeof CONTROLS)[number] }) {
  const [target, setTarget] = useState(control.placeholder);
  const run = useMutation({ mutationFn: () => api.demo(control.id, target) });
  return (
    <article className="rounded border border-hairline-border p-4">
      <h3 className="text-sm font-semibold text-ink">{control.title}</h3>
      <p className="mt-1 text-xs text-ink-secondary">{control.consequence}</p>
      <div className="mt-3 flex gap-2">
        <label className="sr-only" htmlFor={`target-${control.id}`}>
          Target
        </label>
        <input
          id={`target-${control.id}`}
          value={target}
          onChange={(event) => setTarget(event.target.value)}
          className="flex-1 rounded border border-hairline-border bg-card px-2 py-1 text-xs text-ink"
        />
        <button
          type="button"
          onClick={() => run.mutate()}
          className="rounded border border-hairline-axis px-3 py-1 text-xs text-ink"
        >
          Run
        </button>
      </div>
      {run.isError ? (
        <p className="mt-2 text-xs" style={{ color: 'var(--status-serious)' }}>
          {run.error instanceof ApiError
            ? (run.error.problem.detail ?? run.error.problem.title)
            : 'The control is unavailable.'}
        </p>
      ) : null}
      {run.data ? <p className="mt-2 text-xs text-ink-secondary">{run.data.detail}</p> : null}
    </article>
  );
}
