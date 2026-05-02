import { cn } from '../lib/utils';
import { useLanguage } from '../lib/language';

interface DriftSignals {
  adwin: boolean[];
  chiSquared: boolean[];
  modelDisagreement: boolean[];
}

export default function DriftSignalStack({ signals }: { signals: DriftSignals }) {
  const { t } = useLanguage();
  const windowSize = 30;
  const adwin = signals.adwin.slice(-windowSize);
  const chiSquared = signals.chiSquared.slice(-windowSize);
  const modelDisagreement = signals.modelDisagreement.slice(-windowSize);

  const rows = [
    { label: 'ADWIN', data: adwin },
    { label: 'CHI-SQUARED', data: chiSquared },
    { label: 'MODEL DISAGREEMENT', data: modelDisagreement },
  ];

  const isConfirmed = (colIndex: number) => {
    const count = [adwin[colIndex], chiSquared[colIndex], modelDisagreement[colIndex]].filter(Boolean).length;
    return count >= 2;
  };

  return (
    <section className="rounded-sm border border-border bg-bg-elevated p-6 space-y-6">
      <div className="flex items-center justify-between">
        <h3 className="font-caption text-text-secondary uppercase tracking-widest">{t('drift_signal_stack')}</h3>
        <div className="font-mono text-[10px] text-text-tertiary uppercase">{t('last_30_windows')}</div>
      </div>

      <div className="flex flex-col gap-3">
        {rows.map((row, i) => (
          <div key={i} className="grid grid-cols-[140px_1fr] items-center gap-4">
            <span className="font-caption text-[10px] text-text-tertiary uppercase">{row.label}</span>
            <div className="flex gap-[2px]">
              {row.data.map((active, j) => (
                <div key={j} className="relative group">
                  <div
                    className={cn(
                      'h-[14px] w-[14px] rounded-[1px] transition-colors duration-150',
                      active ? 'bg-severity-watch' : 'bg-bg-soft',
                    )}
                  />
                  {i === 0 && isConfirmed(j) && (
                    <div className="absolute -top-[4px] left-0 right-0 h-[2px] bg-accent z-10" />
                  )}
                </div>
              ))}
            </div>
          </div>
        ))}
      </div>

      <div className="flex items-center gap-4 pt-2">
        <div className="flex items-center gap-2">
          <div className="h-[8px] w-[8px] rounded-[1px] bg-bg-soft" />
          <span className="font-caption text-[9px] text-text-tertiary uppercase">{t('inactive')}</span>
        </div>
        <div className="flex items-center gap-2">
          <div className="h-[8px] w-[8px] rounded-[1px] bg-severity-watch" />
          <span className="font-caption text-[9px] text-text-tertiary uppercase">{t('active')}</span>
        </div>
        <div className="flex items-center gap-2">
          <div className="h-[2px] w-4 bg-accent" />
          <span className="font-caption text-[9px] text-text-tertiary uppercase">{t('drift_confirmed')} (2-OF-3)</span>
        </div>
      </div>
    </section>
  );
}
