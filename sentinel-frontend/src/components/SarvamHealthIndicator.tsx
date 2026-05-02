import { useEffect, useState } from 'react';
import { getSarvamHealth, subscribeSarvamHealth, type SarvamHealth } from '../lib/sarvamHealth';
import { useLanguage } from '../lib/language';
import { cn } from '../lib/utils';

export default function SarvamHealthIndicator() {
  const { t } = useLanguage();
  const [health, setHealth] = useState<SarvamHealth>(getSarvamHealth().health);

  useEffect(() => {
    return subscribeSarvamHealth(next => setHealth(next.health));
  }, []);

  const label = health === 'on' ? t('sarvam_on') : health === 'degraded' ? t('sarvam_degraded') : t('sarvam_offline');
  const dot = health === 'on' ? 'bg-severity-healthy' : health === 'degraded' ? 'bg-severity-watch' : 'bg-severity-critical';

  return (
    <div className="fixed bottom-4 right-4 z-40 pointer-events-none flex items-center gap-2 font-mono text-[10px] text-text-tertiary uppercase">
      <span className={cn('h-1.5 w-1.5 rounded-full', dot)} />
      <span>{label}</span>
    </div>
  );
}
