/**
 * The hero screen: narrative, the attribution ladder, and the right rail.
 *
 * The narrative is marked with its provenance because the distinction between "a
 * model wrote this" and "the engine computed this" is the whole governance claim, and
 * a reader should be able to see it rather than be told it.
 */

import { useParams } from 'react-router-dom';
import { useQuery } from '@tanstack/react-query';

import { AttributionLadder, ConfidenceRail } from '@/components/AttributionLadder';
import { ConfidencePanel } from '@/components/ConfidencePanel';
import {
  Card,
  EmptyState,
  ErrorState,
  ProvenanceTag,
  SectionTitle,
  Skeleton,
  TierChip,
} from '@/components/primitives';
import { api, ApiError } from '@/lib/api';
import { inr, pct } from '@/lib/format';
import { useUi } from '@/lib/store';
import { isAbstention, type Abstention, type InsightBundle } from '@/lib/types';

export function InsightDetail() {
  const { insightId = '' } = useParams();
  const { persona, showProvenance } = useUi();
  const insight = useQuery({
    queryKey: ['insight', insightId],
    queryFn: () => api.insight(insightId),
  });
  const narrative = useQuery({
    queryKey: ['narrative', insightId, persona],
    queryFn: () => api.narrative(insightId, persona),
  });

  if (insight.isPending) return <Skeleton rows={6} />;
  if (insight.isError) {
    return (
      <ErrorState
        title="Could not load this insight"
        detail={insight.error instanceof ApiError ? insight.error.problem.detail : null}
      />
    );
  }
  const payload = insight.data;

  return (
    <div className="grid gap-6 lg:grid-cols-[minmax(0,1fr)_20rem]">
      <div className="space-y-6">
        <Card>
          <div className="flex flex-wrap items-baseline justify-between gap-2">
            <SectionTitle>Narrative</SectionTitle>
            <div className="flex items-center gap-2">
              {showProvenance ? <ProvenanceTag kind="model" /> : null}
              {narrative.data ? <TierChip tier={narrative.data.tier} /> : null}
            </div>
          </div>
          {narrative.isPending ? <Skeleton rows={3} /> : null}
          {narrative.data ? (
            <>
              <p
                className="text-base leading-relaxed text-ink"
                data-provenance={
                  narrative.data.source.startsWith('template') ? 'computed' : 'model'
                }
              >
                {narrative.data.text}
              </p>
              <p className="mt-3 text-xs text-ink-muted">
                Rendered by {narrative.data.source} after {narrative.data.attempts} attempt(s);{' '}
                {narrative.data.numbers_checked} number(s) checked against the evidence bundle,{' '}
                {narrative.data.numbers_unsupported} unsupported.
              </p>
            </>
          ) : null}
        </Card>

        {isAbstention(payload) ? (
          <AbstentionBody artifact={payload} />
        ) : (
          <>
            <Headline bundle={payload} />
            <section>
              <SectionTitle hint="Each rung is a smaller, true answer">
                Attribution ladder
              </SectionTitle>
              <AttributionLadder bundle={payload} />
            </section>
          </>
        )}
      </div>

      {isAbstention(payload) ? (
        <aside className="space-y-4">
          <Card>
            <SectionTitle>Confidence</SectionTitle>
            <ConfidencePanel confidence={payload.confidence} />
          </Card>
        </aside>
      ) : (
        <ConfidenceRail bundle={payload} />
      )}
    </div>
  );
}

function Headline({ bundle }: { bundle: InsightBundle }) {
  return (
    <Card>
      <div className="grid gap-4 sm:grid-cols-3">
        <Metric label="Movement" value={pct(bundle.delta_pct)} />
        <Metric label="Impact" value={inr(bundle.delta)} />
        <Metric label="Counterfactual" value={inr(bundle.counterfactual)} />
      </div>
      <p className="mt-3 text-xs text-ink-muted">
        Period {bundle.period_start} to {bundle.period_end} · contract v{bundle.contract_version} ·
        detected by {bundle.detection_method}
      </p>
    </Card>
  );
}

function Metric({ label, value }: { label: string; value: string }) {
  return (
    <div>
      <p className="text-xs uppercase tracking-wide text-ink-muted">{label}</p>
      <p className="mt-1 text-2xl font-semibold text-ink">{value}</p>
    </div>
  );
}

function AbstentionBody({ artifact }: { artifact: Abstention }) {
  return (
    <Card>
      <SectionTitle hint="A designed outcome, not an error">Abstained</SectionTitle>
      <p className="text-base text-ink">
        {artifact.kpi_id} moved {artifact.observed_movement} and was not attributed.
      </p>
      <div className="mt-4 grid gap-4 sm:grid-cols-2">
        <Detail title="What is known" items={artifact.what_is_known} />
        <Detail title="Failed checks" items={artifact.failed_checks} />
        <Detail title="Missing evidence" items={artifact.missing_evidence} />
        <Detail title="Retry" items={[artifact.retry_trigger]} />
      </div>
    </Card>
  );
}

function Detail({ title, items }: { title: string; items: string[] }) {
  if (items.length === 0) {
    return <EmptyState title={title} detail="Nothing recorded." />;
  }
  return (
    <div>
      <p className="text-xs uppercase tracking-wide text-ink-muted">{title}</p>
      <ul className="mt-1 space-y-1 text-sm text-ink-secondary">
        {items.map((item) => (
          <li key={item}>{item}</li>
        ))}
      </ul>
    </div>
  );
}
