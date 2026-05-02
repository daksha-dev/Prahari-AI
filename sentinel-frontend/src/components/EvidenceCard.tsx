import type { EvidenceCard as EvidenceType } from '../lib/types';
import { cn } from '../lib/utils';
import { useLanguage } from '../lib/language';

export default function EvidenceCard({ evidence }: { evidence: EvidenceType }) {
  const { t } = useLanguage();

  return (
    <div className="rounded-sm border border-border bg-bg-elevated p-6 space-y-6">
      <div className="font-caption text-text-secondary uppercase tracking-widest">{t('evidence')}</div>

      <div className="space-y-4">
        <div className="font-caption text-[10px] text-text-tertiary uppercase tracking-widest">{t('top_deviations')}</div>
        <div className="space-y-3">
          {evidence.topDeviations.map((d, i) => (
            <div key={i} className="flex items-center justify-between">
              <span className="mr-4 truncate font-sans text-body text-text-primary uppercase">{d.feature}</span>
              <span className={cn('font-mono text-xs font-bold', Math.abs(d.zScore) > 2 ? 'text-severity-critical' : 'text-severity-watch')}>
                {d.zScore > 0 ? '+' : ''}{d.zScore.toFixed(3)}
              </span>
            </div>
          ))}
        </div>
      </div>

      <div className="h-px bg-border" />

      <div className="space-y-4">
        <div className="font-caption text-[10px] text-text-tertiary uppercase tracking-widest">{t('drift_signals')}</div>
        <div className="flex flex-wrap gap-2">
          {evidence.driftSignals.map((s, i) => (
            <span key={i} className="rounded-sm border border-accent/30 px-2 py-0.5 font-mono text-[10px] uppercase text-accent">
              {s}
            </span>
          ))}
          {evidence.driftSignals.length === 0 && <span className="font-caption text-[10px] uppercase italic text-text-tertiary">{t('none_fired')}</span>}
        </div>
      </div>

      <div className="h-px bg-border" />

      <div className="grid grid-cols-2 gap-4">
        <div>
          <div className="mb-1 font-caption text-[10px] text-text-tertiary uppercase tracking-widest">{t('window')}</div>
          <div className="font-mono text-xs uppercase text-text-primary">W-{evidence.windowId}</div>
        </div>
        <div className="text-right">
          <div className="mb-1 font-caption text-[10px] text-text-tertiary uppercase tracking-widest">{t('timestamp')}</div>
          <div className="font-mono text-xs uppercase text-text-primary">{evidence.time}</div>
        </div>
      </div>
    </div>
  );
}
