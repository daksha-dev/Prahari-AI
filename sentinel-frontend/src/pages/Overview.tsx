import { useEffect, useMemo, useState } from 'react';
import { fetchDevices, fetchNetworkSummary } from '../lib/api';
import type { Device, NetworkSummary, ScenarioName } from '../lib/types';
import DeviceCard from '../components/DeviceCard';
import { AnimatePresence, motion, useReducedMotion } from 'framer-motion';
import { AlertCircle, TrendingUp } from 'lucide-react';
import { useLanguage } from '../lib/language';

interface OverviewProps {
  scenario: ScenarioName;
  onScenarioChange: (name: ScenarioName) => void;
}

export default function Overview({ scenario, onScenarioChange }: OverviewProps) {
  const { t } = useLanguage();
  const reduceMotion = useReducedMotion();
  const [devices, setDevices] = useState<Device[]>([]);
  const [summary, setSummary] = useState<NetworkSummary | null>(null);
  const [loading, setLoading] = useState(true);
  const [lastUpdated, setLastUpdated] = useState(new Date());

  useEffect(() => {
    async function loadData() {
      try {
        const [devicesData, summaryData] = await Promise.all([fetchDevices(), fetchNetworkSummary()]);
        setDevices(devicesData);
        setSummary(summaryData);
        setLastUpdated(new Date());
      } catch (error) {
        console.error('Failed to load overview data', error);
      } finally {
        setLoading(false);
      }
    }
    loadData();

    const interval = setInterval(loadData, 3000);
    window.addEventListener('sentinel:refresh', loadData);
    return () => {
      clearInterval(interval);
      window.removeEventListener('sentinel:refresh', loadData);
    };
  }, []);

  const counts = useMemo(() => ({
    healthy: devices.filter(d => d.trustScore >= 70).length,
    watch: devices.filter(d => d.trustScore >= 50 && d.trustScore < 70).length,
    risk: devices.filter(d => d.trustScore >= 30 && d.trustScore < 50).length,
    critical: devices.filter(d => d.trustScore < 30).length,
  }), [devices]);

  const networkTrustScore = useMemo(() => {
    if (devices.length === 0) return 0;
    return Math.round(devices.reduce((acc, d) => acc + d.trustScore, 0) / devices.length);
  }, [devices]);

  const getSeverityColor = (score: number) => {
    if (score >= 70) return 'text-severity-healthy';
    if (score >= 50) return 'text-severity-watch';
    if (score >= 30) return 'text-severity-risk';
    return 'text-severity-critical';
  };

  const getSeverityLabel = (score: number) => {
    if (score >= 70) return t('healthy');
    if (score >= 50) return t('watch');
    if (score >= 30) return t('at_risk');
    return t('critical');
  };

  const scenarioLabels: Record<ScenarioName, string> = {
    live: t('scenario_live'),
    slow_drift: t('scenario_slow_drift'),
    sudden_ddos: t('scenario_sudden_ddos'),
    recon_scan: t('scenario_recon_scan'),
  };

  if (loading && !summary) {
    return (
      <div className="px-8 py-6 space-y-12">
        <div className="grid h-48 grid-cols-3 gap-8">
          <div className="rounded-sm bg-elevated animate-pulse" />
          <div className="rounded-sm bg-elevated animate-pulse" />
          <div className="rounded-sm bg-elevated animate-pulse" />
        </div>
        <div className="grid grid-cols-4 gap-4">
          {Array.from({ length: 8 }).map((_, i) => (
            <div key={i} className="h-[180px] w-[240px] rounded-sm bg-elevated animate-pulse" />
          ))}
        </div>
      </div>
    );
  }

  return (
    <div className="flex min-h-full flex-col">
      <div className="grid h-48 grid-cols-3 gap-8 border-b border-border bg-bg-base px-8 py-6">
        <div className="flex h-full flex-col justify-between">
          <div className="space-y-3">
            <div className="font-caption text-text-secondary uppercase">{t('network_trust')}</div>
            <motion.div
              initial={reduceMotion ? { opacity: 0 } : { opacity: 0, y: 10 }}
              animate={reduceMotion ? { opacity: 1 } : { opacity: 1, y: 0 }}
              className={`flex items-baseline font-display text-display leading-none ${getSeverityColor(networkTrustScore)}`}
            >
              {networkTrustScore}
            </motion.div>
          </div>
          <div className="flex flex-col gap-2">
            <div className="flex items-center gap-2 font-mono text-caption text-text-tertiary">
              <TrendingUp size={12} className="text-severity-healthy" />
              <span>+2.4%</span>
            </div>
            <div className="h-10 w-full rounded-sm bg-bg-soft/50 relative overflow-hidden">
              <svg className="absolute inset-0 h-full w-full" preserveAspectRatio="none">
                <path d="M0 30 Q 50 10, 100 25 T 200 15 T 300 35 T 400 20" fill="none" stroke="currentColor" strokeWidth="1" className="text-accent/30" />
              </svg>
            </div>
          </div>
        </div>

        <div className="flex h-full flex-col justify-between border-l border-border pl-8">
          <div className="space-y-3">
            <div className="font-caption text-text-secondary uppercase">{t('devices_monitored')}</div>
            <div className="flex items-baseline font-sans text-hero leading-none text-text-primary">{devices.length}</div>
          </div>
          <div className="space-y-1">
            <div className="flex items-center gap-2">
              <div className="h-1.5 w-1.5 rounded-full bg-severity-healthy" />
              <span className="font-mono text-caption text-text-secondary">{counts.healthy}</span>
              <span className="font-caption text-text-tertiary uppercase">{t('healthy')}</span>
            </div>
            <div className="flex items-center gap-2">
              <div className="h-1.5 w-1.5 rounded-full bg-severity-watch" />
              <span className="font-mono text-caption text-text-secondary">{counts.watch}</span>
              <span className="font-caption text-text-tertiary uppercase">{t('watch')}</span>
            </div>
            <div className="flex items-center gap-2">
              <div className="h-1.5 w-1.5 rounded-full bg-severity-critical" />
              <span className="font-mono text-caption text-text-secondary">{counts.critical + counts.risk}</span>
              <span className="font-caption text-text-tertiary uppercase">{t('critical')}</span>
            </div>
          </div>
        </div>

        <div className="flex h-full flex-col justify-between border-l border-border pl-8">
          <div className="space-y-3">
            <div className="font-caption text-text-secondary uppercase">{t('active_incidents')}</div>
            <div className={`flex items-baseline font-sans text-hero leading-none ${counts.critical > 0 ? 'text-severity-critical' : 'text-text-primary'}`}>
              {counts.critical + counts.risk}
            </div>
          </div>
          {counts.critical > 0 ? (
            <div className="flex cursor-pointer items-start gap-3 rounded-sm border border-severity-critical/20 bg-severity-critical/10 p-3 transition-colors duration-150 hover:bg-severity-critical/20">
              <AlertCircle size={16} className="mt-0.5 text-severity-critical" />
              <div>
                <div className="font-sans text-xs font-semibold text-text-primary">{t('anomalous_behavior')}</div>
                <div className="font-mono text-[10px] uppercase text-text-secondary">10.0.2.15 · {new Date().toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })}</div>
              </div>
            </div>
          ) : (
            <div className="font-caption uppercase italic text-text-tertiary">{t('no_active_threats')}</div>
          )}
        </div>
      </div>

      <div className="sticky top-[56px] z-50 flex h-14 items-center justify-between border-b border-border bg-bg-soft px-8">
        <div className="flex items-center gap-4">
          <span className="font-caption uppercase tracking-widest text-text-primary">{t('fleet')}</span>
          <div className="font-mono text-[10px] uppercase text-text-tertiary">
            {t('updated_n_ago', { n: Math.floor((new Date().getTime() - lastUpdated.getTime()) / 1000) })}
          </div>
        </div>

        <div className="flex items-center gap-3">
          <span className="font-caption text-[10px] uppercase text-text-secondary">{t('scenario')}</span>
          <select
            value={scenario}
            onChange={(e) => onScenarioChange(e.target.value as ScenarioName)}
            className="h-8 cursor-pointer rounded-md border border-border bg-bg-elevated px-3 font-mono text-[11px] text-text-primary transition-colors duration-150 focus:border-accent focus:outline-none focus-visible:ring-2 focus-visible:ring-accent focus-visible:ring-offset-2 focus-visible:ring-offset-base"
          >
            {(Object.keys(scenarioLabels) as ScenarioName[]).map(key => (
              <option key={key} value={key}>{scenarioLabels[key]}</option>
            ))}
          </select>
        </div>
      </div>

      <div className="px-8 py-6">
        <div className="grid grid-cols-4 justify-start gap-4">
          <AnimatePresence mode="popLayout">
            {devices.map(device => (
              <DeviceCard key={device.id} device={device} severityLabel={getSeverityLabel(device.trustScore)} />
            ))}
          </AnimatePresence>
        </div>
      </div>
    </div>
  );
}
