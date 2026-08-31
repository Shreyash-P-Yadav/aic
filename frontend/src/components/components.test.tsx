/**
 * Component tests for the pieces that carry a claim.
 *
 * The chosen three are the ones where a rendering bug would misinform rather than
 * merely look wrong: a waterfall whose parts do not visibly sum, a confidence panel
 * that does not surface the weakest signal, and status that is communicated by colour
 * alone.
 */

import { render, screen } from '@testing-library/react';
import { describe, expect, it } from 'vitest';

import { ConfidencePanel } from './ConfidencePanel';
import { DriverChart } from './DriverChart';
import { FreshnessBadge, TierChip } from './primitives';

import { Waterfall } from './Waterfall';
import { isUnmapped } from '@/lib/segments';
import type { ConfidenceFact, DriverFact } from '@/lib/types';

const CONFIDENCE: ConfidenceFact = {
  signals: {
    c1_detection: 0.88,
    c2_attribution: 0.31,
    c3_statistical: 0.81,
    c4_data_trust: 0.94,
    c5_evidence: 0.75,
    c6_narrative: 1.0,
  },
  signal_detail: {
    c1_detection: 'conformal p = 0.0039',
    c2_attribution: 'bootstrap win rate 0.42 x coverage 0.74',
    c3_statistical: 'Ljung-Box p = 0.125',
    c4_data_trust: 'stale required sources: none',
    c5_evidence: 'corroboration 0.79',
    c6_narrative: 'verifier passed 100%',
  },
  composite: 0.41,
  calibrated: 0.41,
  calibration_fitted: false,
  tier: 'Low',
  weakest_signal: 'c2_attribution',
  hard_gate_failures: [],
};

describe('ConfidencePanel', () => {
  it('names the weakest signal, because that is what the composite is', () => {
    render(<ConfidencePanel confidence={CONFIDENCE} />);
    // Twice: once as the row label, once named in the softmin sentence.
    expect(screen.getAllByText(/c2 attribution/)).toHaveLength(2);
    expect(screen.getByText(/softmin/)).toBeInTheDocument();
  });

  it('says so when the calibration map is not fitted', () => {
    render(<ConfidencePanel confidence={CONFIDENCE} />);
    expect(screen.getByText(/uncalibrated/)).toBeInTheDocument();
  });

  it('surfaces a hard gate failure rather than folding it into the score', () => {
    render(
      <ConfidencePanel
        confidence={{
          ...CONFIDENCE,
          hard_gate_failures: ['a required source breaches its freshness SLA: martech_weekly'],
        }}
      />,
    );
    expect(screen.getByText(/Hard gate:/)).toBeInTheDocument();
  });
});

describe('Waterfall', () => {
  it('renders one labelled column per step', () => {
    render(
      <Waterfall
        steps={[
          { label: 'Counterfactual', value: 158_198_000, kind: 'anchor' },
          { label: 'Price', value: -926_696, kind: 'delta' },
          { label: 'Volume', value: 22_614_746, kind: 'delta' },
          { label: 'Mix', value: 2_338_307, kind: 'delta' },
          { label: 'Observed', value: 136_007_333, kind: 'anchor' },
        ]}
      />,
    );
    for (const label of ['Counterfactual', 'Price', 'Volume', 'Mix', 'Observed']) {
      expect(screen.getByText(label)).toBeInTheDocument();
    }
    expect(screen.getByRole('img')).toHaveAccessibleName(/decomposition/i);
  });
});

describe('status is never colour alone', () => {
  it('gives the tier chip a text label', () => {
    render(<TierChip tier="Insufficient" />);
    expect(screen.getByText('Insufficient')).toBeInTheDocument();
  });

  it('gives the freshness badge an icon and a label', () => {
    render(<FreshnessBadge state="red" />);
    expect(screen.getByText('red')).toBeInTheDocument();
  });
});

describe('DriverChart', () => {
  it('shows every estimate with its interval, and marks a grouped driver', () => {
    const drivers: DriverFact[] = [
      {
        driver_id: 'price_index',
        coefficient: -1.63,
        interval_low: -3.01,
        interval_high: -0.26,
        p_value: 0.02,
        agreement: 0.99,
        group: ['price_index'],
      },
      {
        driver_id: 'paid_social',
        coefficient: 0.04,
        interval_low: -0.02,
        interval_high: 0.1,
        p_value: 0.2,
        agreement: 0.8,
        group: ['display', 'paid_social'],
      },
    ];
    render(<DriverChart drivers={drivers} />);
    expect(screen.getByText('-1.630')).toBeInTheDocument();
    expect(screen.getByText(/grouped/)).toBeInTheDocument();
    expect(screen.getByText(/crossing the zero line/)).toBeInTheDocument();
  });
});

describe('unmapped segment detection', () => {
  it('flags the UNKNOWN member of any dimension', () => {
    expect(isUnmapped('category=UNKNOWN')).toBe(true);
    expect(isUnmapped('region=North x category=UNKNOWN')).toBe(true);
  });

  it('does not flag a real member that merely contains the word', () => {
    expect(isUnmapped('region=North')).toBe(false);
    expect(isUnmapped('channel=UNKNOWN_CHANNEL')).toBe(false);
    expect(isUnmapped('category=Unknown Brands Ltd')).toBe(false);
  });
});
