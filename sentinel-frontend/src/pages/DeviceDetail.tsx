import { useEffect, useState } from 'react';
import { useParams, Link, useNavigate } from 'react-router-dom';
import { fetchAlerts, fetchDeviceDetail, fetchEvidenceCard } from '../lib/api';
import type { DeviceDetail, EvidenceCard as EvidenceType } from '../lib/types';
import TrustTimeline from '../components/TrustTimeline';
import DriftSignalStack from '../components/DriftSignalStack';
import BehavioralHeatmap from '../components/BehavioralHeatmap';
import EvidenceCard from '../components/EvidenceCard';
import { ArrowLeft, RotateCcw, ShieldAlert, FileText } from 'lucide-react';
import { motion, useReducedMotion } from 'framer-motion';
import { cn } from '../lib/utils';
import { useLanguage } from '../lib/language';

export default function DeviceDetailView() {
  const { id } = useParams<{ id: string }>();
  const navigate = useNavigate();
  const reduceMotion = useReducedMotion();
  const { language, t } = useLanguage();
  const [device, setDevice] = useState<DeviceDetail | null>(null);
  const [evidence, setEvidence] = useState<EvidenceType | null>(null);
  const [aiSummary, setAiSummary] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    async function loadData() {
      if (!id) return;
      try {
        const [deviceData, evidenceData, alerts] = await Promise.all([
          fetchDeviceDetail(id, language),
          fetchEvidenceCard(id),
          fetchAlerts(),
        ]);
        const alert = alerts.find(item => item.deviceId === id);
        setDevice(deviceData);
        setEvidence(evidenceData);
        setAiSummary(deviceData.summary || alert?.aiSummary || null);
      } catch (error) {
        console.error('Failed to load device details', error);
      } finally {
        setLoading(false);
      }
    }
    loadData();
    const interval = setInterval(loadData, 2000);
    window.addEventListener('sentinel:refresh', loadData);

    const handleEsc = (e: KeyboardEvent) => {
      if (e.key === 'Escape') navigate('/');
    };
    window.addEventListener('keydown', handleEsc);

    return () => {
      clearInterval(interval);
      window.removeEventListener('sentinel:refresh', loadData);
      window.removeEventListener('keydown', handleEsc);
    };
  }, [id, navigate, language]);

  if (loading && !device) {
    return (
      <div className="px-8 py-6 space-y-8">
        <div className="h-32 rounded-sm bg-elevated animate-pulse" />
        <div className="grid grid-cols-12 gap-8">
          <div className="col-span-8 space-y-8">
            <div className="h-[300px] rounded-sm bg-elevated animate-pulse" />
            <div className="h-[150px] rounded-sm bg-elevated animate-pulse" />
            <div className="h-[400px] rounded-sm bg-elevated animate-pulse" />
          </div>
          <div className="col-span-4 space-y-8">
            <div className="h-[250px] rounded-sm bg-elevated animate-pulse" />
            <div className="h-[350px] rounded-sm bg-elevated animate-pulse" />
          </div>
        </div>
      </div>
    );
  }

  if (!device) return <div className="p-12 text-center font-display text-title text-text-tertiary">{t('device_not_found')}</div>;

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

  const severityColor = getSeverityColor(device.trustScore);

  return (
    <div className="flex min-h-full flex-col">
      <div className="h-32 border-b border-border bg-bg-base px-8 py-6 flex items-end justify-between">
        <div className="space-y-4">
          <Link
            to="/"
            className="group flex cursor-pointer items-center gap-2 font-caption text-text-tertiary transition-colors duration-150 hover:text-text-primary focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent focus-visible:ring-offset-2 focus-visible:ring-offset-base"
          >
            <ArrowLeft size={14} className="transition-transform duration-150 group-hover:-translate-x-1" />
            <span className="group-hover:underline">{t('back_to_fleet')}</span>
          </Link>
          <div>
            <h1 className="font-sans text-hero leading-none text-text-primary">{device.name}</h1>
            <div className="mt-2 flex items-center gap-3 font-mono text-caption text-text-tertiary">
              <span>{device.ip}</span>
              <span className="h-1 w-1 rounded-full bg-border" />
              <span>{device.type.toUpperCase()}</span>
              <span className="h-1 w-1 rounded-full bg-border" />
              <span className="text-severity-healthy">{t('baseline_locked')}</span>
            </div>
          </div>
        </div>

        <div className="flex items-end gap-12">
          <div className="text-right">
            <motion.div
              initial={reduceMotion ? { opacity: 0 } : { scale: 0.9, opacity: 0 }}
              animate={reduceMotion ? { opacity: 1 } : { scale: 1, opacity: 1 }}
              className={`font-sans text-hero leading-none ${severityColor}`}
            >
              {device.trustScore}
            </motion.div>
            <div className={`mt-1 font-caption text-[10px] uppercase tracking-[0.2em] ${severityColor}`}>
              {getSeverityLabel(device.trustScore)}
            </div>
          </div>

          <div className="h-12 w-px bg-border" />

          <div className="flex flex-col items-end gap-1">
            <span className="font-caption text-[10px] text-text-tertiary uppercase tracking-widest">{t('drift_status')}</span>
            <div className="flex items-center gap-2">
              <div className={cn('h-2 w-2 rounded-full', device.driftConfirmed ? 'bg-accent' : 'bg-severity-healthy')} />
              <span className={cn('font-mono text-caption', device.driftConfirmed ? 'text-accent' : 'text-severity-healthy')}>
                {device.driftConfirmed ? t('drift_confirmed') : t('stable')}
              </span>
            </div>
          </div>
        </div>
      </div>

      <div className="grid grid-cols-12 gap-8 px-8 py-6">
        <div className="col-span-12 xl:col-span-8 space-y-8">
          <TrustTimeline data={device.history} trustScore={device.trustScore} />
          <DriftSignalStack signals={device.driftSignals} />
          <BehavioralHeatmap data={device.behavioralHeatmap} featureNames={device.featureNames} />
        </div>

        <div className="col-span-12 xl:col-span-4 flex flex-col gap-8">
          <div className="rounded-sm border border-border bg-bg-soft p-6">
            <div className="mb-6 font-caption text-accent text-[10px] tracking-[0.2em] uppercase">{t('analyst_note')}</div>
            <div className="font-sans text-body leading-[1.6] text-text-primary">
              {aiSummary || t('default_summary')}
            </div>
            <div className="mt-8 flex flex-wrap gap-2">
              <button className="h-8 cursor-pointer rounded-md border border-border bg-bg-elevated px-3 font-caption text-[10px] text-text-tertiary transition-colors duration-150 hover:border-accent hover:text-text-primary focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent focus-visible:ring-offset-2 focus-visible:ring-offset-base">{t('ask_followup')}</button>
              <button className="h-8 cursor-pointer rounded-md border border-border bg-bg-elevated px-3 font-caption text-[10px] text-text-tertiary transition-colors duration-150 hover:border-accent hover:text-text-primary focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent focus-visible:ring-offset-2 focus-visible:ring-offset-base">{t('translate')}</button>
              <button className="h-8 cursor-pointer rounded-md border border-border bg-bg-elevated px-3 font-caption text-[10px] text-text-tertiary transition-colors duration-150 hover:border-accent hover:text-text-primary focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent focus-visible:ring-offset-2 focus-visible:ring-offset-base flex items-center gap-1.5">
                <RotateCcw size={10} /> {t('regenerate')}
              </button>
            </div>
          </div>

          {evidence && <EvidenceCard evidence={evidence} />}

          <div className="sticky bottom-6 mt-auto space-y-2">
            <button className="h-10 w-full cursor-pointer rounded-md bg-accent text-bg-base font-sans text-sm font-semibold uppercase tracking-widest transition-colors duration-150 hover:bg-accent/90 flex items-center justify-center gap-3 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent focus-visible:ring-offset-2 focus-visible:ring-offset-base">
              <ShieldAlert size={18} />
              {t('generate_block_script')}
            </button>
            <button className="h-10 w-full cursor-pointer rounded-md border border-accent bg-bg-base text-accent font-sans text-xs font-semibold uppercase tracking-widest transition-colors duration-150 hover:bg-accent/10 flex items-center justify-center gap-3 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent focus-visible:ring-offset-2 focus-visible:ring-offset-base">
              <FileText size={16} />
              {t('generate_playbook')}
            </button>
            <button className="h-8 w-full cursor-pointer rounded-md text-center font-caption text-[10px] uppercase tracking-widest text-text-tertiary transition-colors duration-150 hover:text-text-primary hover:underline focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent focus-visible:ring-offset-2 focus-visible:ring-offset-base">
              {t('mark_investigated')}
            </button>
          </div>
        </div>
      </div>
    </div>
  );
}
