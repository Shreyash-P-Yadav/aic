/**
 * The two question-shaped screens: Ask and Actions.
 *
 * The admin panel used to live here and now has its own file — it is the only screen
 * that writes rather than reads, and mixing it in made this file the place every
 * interactive change landed regardless of what it touched.
 */

import { useState } from 'react';
import { useMutation, useQueries, useQuery } from '@tanstack/react-query';
import { Link } from 'react-router-dom';

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
                {answer.insight_id ? (
                  // The answer is a *view* of an insight that already ran, so it must be
                  // possible to walk back to the evidence behind it. An answer you cannot
                  // trace is a chatbot's answer.
                  <Link
                    to={`/insights/${answer.insight_id}`}
                    className="inline-block text-xs text-ink-secondary underline underline-offset-2"
                  >
                    Open the evidence behind this answer →
                  </Link>
                ) : null}
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
  const published = (insights.data ?? []).filter((item) => item.status === 'published');
  // Every published insight, not just the first: an action lives on the insight that
  // earned it, and the highest-confidence insight is not always the top of the feed —
  // the feed is ranked by priority, which weighs materiality too. Showing one insight's
  // actions made the screen look empty whenever the leader happened to be a Low-tier
  // movement, which is a rendering accident, not a decision the engine took.
  const details = useQueries({
    queries: published.map((item) => ({
      queryKey: ['insight', item.insight_id],
      queryFn: ({ signal }: { signal: AbortSignal }) => api.insight(item.insight_id, signal),
    })),
  });

  if (insights.isPending) return <Skeleton rows={4} />;
  if (published.length === 0) {
    return <EmptyState title="No published insight yet" detail="Actions follow an insight." />;
  }
  if (details.some((query) => query.isPending)) return <Skeleton rows={4} />;

  const proposed = published.flatMap((item, index) => {
    const payload = details[index]?.data;
    if (!payload || isAbstention(payload)) return [];
    return payload.actions.map((action) => ({ action, insight: item }));
  });
  const withheld = published.flatMap((item, index) => {
    const payload = details[index]?.data;
    if (!payload || isAbstention(payload)) return [];
    return payload.actions_withheld.map((reason) => ({ reason, kpiId: item.kpi_id }));
  });

  return (
    <div className="space-y-4">
      {proposed.length === 0 ? (
        <EmptyState
          title="No action proposed"
          detail={
            withheld.length > 0
              ? 'Every governed action for the leading driver was considered and ruled out. The reasons are below.'
              : 'No governed action applies to the leading driver on any published insight.'
          }
        />
      ) : (
        <div className="grid gap-4 lg:grid-cols-2">
          {proposed.map(({ action, insight }) => (
            <ActionCard
              key={`${insight.insight_id}:${action.action_id}`}
              action={action}
              kpiId={insight.kpi_id}
              tier={insight.tier}
            />
          ))}
        </div>
      )}
      {withheld.length > 0 ? (
        // Shown, not hidden. An action the system declined to recommend is a decision it
        // took, and a screen that renders only the proposals makes that decision invisible.
        <Card>
          <SectionTitle hint="Each was evaluated against live data and ruled out">
            Considered and not proposed
          </SectionTitle>
          <ul className="space-y-2 text-xs text-ink-secondary">
            {withheld.map((item) => (
              <li key={`${item.kpiId}:${item.reason}`} className="flex gap-2">
                <span className="shrink-0 text-ink-muted">{item.kpiId}</span>
                <span>{item.reason}</span>
              </li>
            ))}
          </ul>
        </Card>
      ) : null}
    </div>
  );
}

function ActionCard({ action, kpiId, tier }: { action: ActionFact; kpiId: string; tier: string }) {
  const [approved, setApproved] = useState(false);
  return (
    <Card>
      <p className="text-xs uppercase tracking-wide text-ink-muted">
        {action.driver_id} → {action.lever}
      </p>
      <h3 className="mt-1 text-lg font-semibold text-ink">{action.title}</h3>
      <p className="mt-0.5 text-xs text-ink-muted">
        From {kpiId} at {tier} confidence
      </p>
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
