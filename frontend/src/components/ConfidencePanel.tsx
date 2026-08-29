/**
 * The six confidence signals, with the softmin marked.
 *
 * The weakest signal is highlighted because that is what the composite is: a chain is
 * as strong as its weakest link, and a reader who sees only the total learns nothing
 * about why it is what it is.
 */

import { share } from '@/lib/format';
import type { ConfidenceFact } from '@/lib/types';
import { TierChip } from './primitives';

const SIGNAL_LABEL: Record<string, string> = {
  c1_detection: 'c1 detection',
  c2_attribution: 'c2 attribution',
  c3_statistical: 'c3 statistics',
  c4_data_trust: 'c4 data trust',
  c5_evidence: 'c5 evidence',
  c6_narrative: 'c6 narrative',
};

export function ConfidencePanel({ confidence }: { confidence: ConfidenceFact }) {
  const entries = Object.entries(confidence.signals).sort(([a], [b]) => a.localeCompare(b));
  return (
    <div className="space-y-3">
      <div className="flex items-center justify-between gap-2">
        <TierChip tier={confidence.tier} />
        <span className="tnum text-sm text-ink">
          {confidence.calibrated.toFixed(2)}
          {confidence.calibration_fitted ? '' : ' (uncalibrated)'}
        </span>
      </div>
      <ul className="space-y-1.5">
        {entries.map(([name, value]) => {
          const weakest = name === confidence.weakest_signal;
          return (
            <li key={name} className="grid grid-cols-[7rem_1fr_2.5rem] items-center gap-2">
              <span className={`text-xs ${weakest ? 'text-ink' : 'text-ink-secondary'}`}>
                {SIGNAL_LABEL[name] ?? name}
              </span>
              <span
                className="h-2 rounded-full"
                style={{ backgroundColor: 'var(--hairline-grid)' }}
              >
                <span
                  className="block h-2 rounded-full"
                  style={{
                    width: `${Math.max(value, 0.01) * 100}%`,
                    backgroundColor: weakest ? 'var(--status-serious)' : 'var(--series-1)',
                  }}
                  title={confidence.signal_detail[name]}
                />
              </span>
              <span className="tnum text-right text-xs text-ink-secondary">{share(value, 0)}</span>
            </li>
          );
        })}
      </ul>
      <p className="text-xs text-ink-muted">
        Composite is a softmin (p = −4) over the six, so it sits near the weakest — here{' '}
        {SIGNAL_LABEL[confidence.weakest_signal] ?? confidence.weakest_signal}.{' '}
        {confidence.signal_detail[confidence.weakest_signal]}
      </p>
      {confidence.hard_gate_failures.length > 0 ? (
        <ul className="space-y-1 text-xs" style={{ color: 'var(--status-critical)' }}>
          {confidence.hard_gate_failures.map((failure) => (
            <li key={failure}>Hard gate: {failure}</li>
          ))}
        </ul>
      ) : null}
    </div>
  );
}
