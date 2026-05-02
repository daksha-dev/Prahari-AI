import { useState } from 'react';
import { motion, AnimatePresence } from 'framer-motion';
import { cn } from '../lib/utils';
import { useLanguage } from '../lib/language';

export default function BehavioralHeatmap({ data, featureNames }: { data: number[][], featureNames: string[] }) {
  const { t } = useLanguage();
  const [hoveredCell, setHoveredCell] = useState<{ row: number, col: number, val: number } | null>(null);

  const getHeatmapColor = (val: number) => {
    const absVal = Math.abs(val);
    if (absVal < 1.0) return '#1a1a1a';
    if (absVal < 2.0) return '#3a3a3a';
    if (absVal < 3.0) return '#facc15';
    return '#ef4444';
  };

  return (
    <section className="rounded-sm border border-border bg-bg-elevated p-6 space-y-6">
      <div className="flex items-center justify-between">
        <h3 className="font-caption text-text-secondary uppercase tracking-widest">{t('behavioral_heatmap')}</h3>
        <div className="font-mono text-[10px] text-text-tertiary uppercase">{t('z_score_deviations')}</div>
      </div>

      <div className="relative overflow-visible">
        <div className="flex flex-col gap-[1px]">
          {data.map((row, i) => (
            <div key={i} className="flex items-center gap-4 group">
              <span className="font-mono text-[10px] text-text-tertiary w-40 truncate uppercase group-hover:text-text-primary transition-colors duration-150">
                {featureNames[i]}
              </span>
              <div className="flex gap-[1px]">
                {row.slice(-30).map((val, j) => (
                  <div
                    key={j}
                    onMouseEnter={() => setHoveredCell({ row: i, col: j, val })}
                    onMouseLeave={() => setHoveredCell(null)}
                    className="h-3 w-3 cursor-crosshair transition-colors duration-150 hover:scale-125 hover:z-10"
                    style={{ backgroundColor: getHeatmapColor(val) }}
                  />
                ))}
              </div>
            </div>
          ))}
        </div>

        <AnimatePresence>
          {hoveredCell && (
            <motion.div
              initial={{ opacity: 0, scale: 0.95 }}
              animate={{ opacity: 1, scale: 1 }}
              exit={{ opacity: 0, scale: 0.95 }}
              className="absolute pointer-events-none z-50 rounded-sm border border-border bg-bg-soft p-3"
              style={{
                left: (hoveredCell.col * 13) + 160,
                top: (hoveredCell.row * 13) - 60,
              }}
            >
              <div className="space-y-1">
                <div className="font-caption text-[9px] text-text-tertiary uppercase tracking-wider">{t('feature')}</div>
                <div className="font-sans text-xs font-semibold text-text-primary uppercase">{featureNames[hoveredCell.row]}</div>
                <div className="flex justify-between gap-8 pt-2">
                  <div>
                    <div className="font-caption text-[9px] text-text-tertiary uppercase tracking-wider">{t('z_score')}</div>
                    <div className={cn('font-mono text-xs font-bold', Math.abs(hoveredCell.val) > 2 ? 'text-severity-critical' : 'text-text-primary')}>
                      {hoveredCell.val.toFixed(3)}
                    </div>
                  </div>
                  <div className="text-right">
                    <div className="font-caption text-[9px] text-text-tertiary uppercase tracking-wider">{t('window')}</div>
                    <div className="font-mono text-xs text-text-secondary">W-{30 - hoveredCell.col}</div>
                  </div>
                </div>
              </div>
            </motion.div>
          )}
        </AnimatePresence>
      </div>

      <div className="flex items-center gap-4 pt-2">
        <div className="flex items-center gap-2">
          <div className="h-2 w-2 rounded-[1px] bg-bg-soft" />
          <span className="font-caption text-[9px] text-text-tertiary uppercase">{t('nominal')}</span>
        </div>
        <div className="flex items-center gap-2">
          <div className="h-2 w-2 rounded-[1px] bg-border" />
          <span className="font-caption text-[9px] text-text-tertiary uppercase">{t('deviating')}</span>
        </div>
        <div className="flex items-center gap-2">
          <div className="h-2 w-2 rounded-[1px] bg-severity-watch" />
          <span className="font-caption text-[9px] text-text-tertiary uppercase">{t('high')}</span>
        </div>
        <div className="flex items-center gap-2">
          <div className="h-2 w-2 rounded-[1px] bg-severity-critical" />
          <span className="font-caption text-[9px] text-text-tertiary uppercase">{t('critical')}</span>
        </div>
      </div>
    </section>
  );
}
