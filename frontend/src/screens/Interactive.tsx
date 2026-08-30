/**
 * The three interactive screens: Ask, Actions and the admin panel.
 *
 * The admin panel shows what each control will do *before* doing it, because an
 * interactive control that misbehaves on stage is worse than no control, and the
 * cheapest defence is a presenter who can read the consequence before they click.
 */

import { useState } from 'react';
import { useMutation, useQuery } from '@tanstack/react-query';

import { Card, EmptyState, ErrorState, SectionTitle, Skeleton } from '@/components/primitives';
import { api, ApiError } from '@/lib/api';
import { day, inr } from '@/lib/format';
import { isAbstention, type ActionFact, type AskResponse } from '@/lib/types';

/**
 * Questions that demonstrate both paths.
 *
 * The first three resolve to a governed KPI and answer from a computation that already
 * happened. The last deliberately names none, so the system asks which KPI is meant
 * rather than guessing — which is the behaviour worth showing, and which nobody
 * discovers on a screen with a single empty box.
 */
const EXAMPLES = [
  'Why did net_revenue move last week?',
  'What happened to order_fill_rate?',
  'Explain the change in unit_volume',
  'What happened?',
];

export function Ask() {
  const [question, setQuestion] = useState(EXAMPLES[0] ?? '');
  const [answer, setAnswer] = useState<AskResponse | null>(null);
  const ask = useMutation({
    mutationFn: (text: string) => api.ask(text),
    onSuccess: setAnswer,
  });

  return (
    <div className="mx-auto max-w-3xl space-y-4">
      <Card>
        <SectionTitle hint="Answers from a computation that already happened">Ask</SectionTitle>
        <form
          className="flex flex-col gap-2 sm:flex-row"
          onSubmit={(event) => {
            event.preventDefault();
            ask.mutate(question);
          }}
        >
          <label className="sr-only" htmlFor="question">
            Question
          </label>
          <input
            id="question"
            value={question}
            onChange={(event) => setQuestion(event.target.value)}
            className="flex-1 rounded border border-hairline-border bg-card px-3 py-2 text-sm text-ink"
            placeholder="Ask about a governed KPI"
          />
          <button
            type="submit"
            className="rounded border border-hairline-axis px-4 py-2 text-sm text-ink"
          >
            Ask
          </button>
        </form>
        <div className="mt-3 flex flex-wrap items-center gap-2">
          <span className="text-xs text-ink-muted">Try:</span>
          {EXAMPLES.map((example) => (
            <button
              key={example}
              type="button"
              onClick={() => {
                setQuestion(example);
                ask.mutate(example);
              }}
              className="rounded-full border border-hairline-border px-3 py-1 text-xs text-ink-secondary transition hover:border-hairline-axis"
            >
              {example}
            </button>
          ))}
        </div>
        {ask.isPending ? <Skeleton rows={2} /> : null}
        {ask.isError ? (
          <ErrorState
            title="The question could not be answered"
            detail={ask.error instanceof ApiError ? ask.error.problem.detail : null}
          />
        ) : null}
        {answer ? (
          <div className="mt-4 space-y-2">
            {answer.kind === 'clarification' ? (
              <>
                <p className="text-sm font-medium text-ink">{answer.question}</p>
                <p className="text-xs text-ink-muted">
                  The system asks rather than guesses. Guessing is how a conversational tool answers
                  a question nobody asked.
                </p>
              </>
            ) : (
              <>
                <p className="text-base leading-relaxed text-ink">{answer.narrative}</p>
                <p className="text-xs text-ink-muted">{answer.detail}</p>
              </>
            )}
          </div>
        ) : null}
      </Card>
    </div>
  );
}

export function Actions() {
  const insights = useQuery({
    queryKey: ['insights', ''],
    queryFn: ({ signal }) => api.insights({}, signal),
  });
  const first = insights.data?.find((item) => item.status === 'published');
  const detail = useQuery({
    queryKey: ['insight', first?.insight_id],
    queryFn: ({ signal }) => api.insight(first!.insight_id, signal),
    enabled: Boolean(first),
  });

  if (insights.isPending) return <Skeleton rows={4} />;
  if (!first) {
    return <EmptyState title="No published insight yet" detail="Actions follow an insight." />;
  }
  if (detail.isPending) return <Skeleton rows={4} />;
  if (!detail.data || isAbstention(detail.data)) {
    return <EmptyState title="This insight abstained, so it carries no action." />;
  }
  const actions = detail.data.actions;
  if (actions.length === 0) {
    return (
      <EmptyState
        title="No action at this confidence tier"
        detail="Actions are suppressed entirely at Low or Insufficient confidence."
      />
    );
  }
  return (
    <div className="grid gap-4 lg:grid-cols-2">
      {actions.map((action) => (
        <ActionCard key={action.action_id} action={action} />
      ))}
    </div>
  );
}

function ActionCard({ action }: { action: ActionFact }) {
  const [approved, setApproved] = useState(false);
  return (
    <Card>
      <p className="text-xs uppercase tracking-wide text-ink-muted">
        {action.driver_id} → {action.lever}
      </p>
      <h3 className="mt-1 text-lg font-semibold text-ink">{action.title}</h3>
      <dl className="mt-3 space-y-1.5 text-sm">
        <div className="flex justify-between gap-3">
          <dt className="text-ink-muted">Expected impact</dt>
          <dd className="tnum text-ink">{inr(action.expected_impact_central)}</dd>
        </div>
        <div className="flex justify-between gap-3">
          <dt className="text-ink-muted">95% interval</dt>
          <dd className="tnum text-ink-secondary">
            {inr(action.expected_impact_low)} to {inr(action.expected_impact_high)}
          </dd>
        </div>
        <div className="flex justify-between gap-3">
          <dt className="text-ink-muted">Owner</dt>
          <dd className="text-ink-secondary">{action.owner_role}</dd>
        </div>
        <div className="flex justify-between gap-3">
          <dt className="text-ink-muted">Approval</dt>
          <dd className="text-ink-secondary">
            {action.needs_approval ? 'Required' : 'Within delegated authority'}
          </dd>
        </div>
        <div className="flex justify-between gap-3">
          <dt className="text-ink-muted">Earliest effect</dt>
          <dd className="text-ink-secondary">{day(action.earliest_effect)}</dd>
        </div>
      </dl>
      <div className="mt-4 border-t border-hairline-grid pt-3">
        <p className="text-xs uppercase tracking-wide text-ink-muted">Monitoring plan</p>
        <p className="mt-1 text-sm text-ink-secondary">
          {action.monitoring_kpi} at days {action.monitoring_checkpoints.join(', ')} against a{' '}
          {action.success_threshold_pct}% threshold.
        </p>
      </div>
      <button
        type="button"
        onClick={() => setApproved(true)}
        disabled={approved}
        className="mt-4 w-full rounded border border-hairline-axis px-4 py-2 text-sm text-ink disabled:text-ink-muted"
      >
        {approved ? 'Monitoring entry created' : 'Approve and monitor'}
      </button>
    </Card>
  );
}

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
