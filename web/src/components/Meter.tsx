import type { ReactNode } from 'react';

export type Status = 'good' | 'warning' | 'critical';

const ICON: Record<Status, string> = { good: '✓', warning: '!', critical: '✕' };

export function StatusChip({ status, children }: { status: Status; children: ReactNode }) {
  return (
    <span className={`chip chip-${status}`}>
      <span className="chip-icon" aria-hidden="true">
        {ICON[status]}
      </span>
      {children}
    </span>
  );
}

interface MeterProps {
  label: string;
  value: number;
  cap: number;
  capLabel: string;
  format: (n: number) => string;
  // A reference value drawn as a labelled tick, e.g. the fleet before any efficiency settings.
  baseline?: number;
  baselineLabel?: string;
  note?: string;
}

export function Meter({ label, value, cap, capLabel, format, baseline, baselineLabel = 'baseline', note }: MeterProps) {
  const max = Math.max(value, cap, baseline ?? 0) * 1.06;
  const at = (n: number) => `${(n / max) * 100}%`;
  // Labels near either end of the track anchor inward instead of centering, so they never spill out.
  const edge = (n: number) => (n / max > 0.85 ? ' at-right' : n / max < 0.15 ? ' at-left' : '');
  const over = value > cap;
  const showBaseline = baseline !== undefined && Math.abs(baseline - value) / cap > 0.005;
  return (
    <div className="meter">
      <div className="meter-head">
        <span className="meter-label">{label}</span>
        <span className="meter-value">
          {format(value)} <span className="meter-of">of {format(cap)}</span>
        </span>
        <StatusChip status={over ? 'critical' : 'good'}>
          {over ? `${Math.round((value / cap - 1) * 100)}% over the cap` : `${format(cap - value)} headroom`}
        </StatusChip>
      </div>
      <div className="meter-track" role="img" aria-label={`${label}: ${format(value)} of ${format(cap)}`}>
        <div className={`meter-fill${over ? ' meter-fill-capped' : ''}`} style={{ width: at(Math.min(value, cap)) }} />
        {over && <div className="meter-over" style={{ left: at(cap), width: at(value - cap) }} />}
        <div className={`meter-cap${edge(cap)}`} style={{ left: at(cap) }}>
          <span>{capLabel}</span>
        </div>
        {showBaseline && (
          <div className={`meter-baseline${edge(baseline!)}`} style={{ left: at(baseline!) }}>
            <span>
              {baselineLabel} {format(baseline!)}
            </span>
          </div>
        )}
      </div>
      {note && <p className="meter-note">{note}</p>}
    </div>
  );
}
