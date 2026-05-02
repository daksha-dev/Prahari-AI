import type { Device } from '../lib/types';
import { cn } from '../lib/utils';
import { LineChart, Line, ResponsiveContainer } from 'recharts';
import { useNavigate } from 'react-router-dom';
import * as Icons from 'lucide-react';
import { motion, useReducedMotion } from 'framer-motion';

export default function DeviceCard({ device, severityLabel }: { device: Device; severityLabel: string }) {
  const navigate = useNavigate();
  const reduceMotion = useReducedMotion();
  const Icon = (Icons as any)[device.icon || 'Cpu'] || Icons.Cpu;
  
  const getSeverityColor = (score: number) => {
    if (score >= 70) return 'text-severity-healthy';
    if (score >= 50) return 'text-severity-watch';
    if (score >= 30) return 'text-severity-risk';
    return 'text-severity-critical';
  };

  const getSeverityHex = (score: number) => {
    if (score >= 70) return '#4ade80';
    if (score >= 50) return '#facc15';
    if (score >= 30) return '#fb923c';
    return '#ef4444';
  };

  const severityColor = getSeverityColor(device.trustScore);
  const isCritical = device.trustScore < 50;

  return (
    <motion.div 
      layout={!reduceMotion}
      initial={reduceMotion ? { opacity: 0 } : { opacity: 0, scale: 0.95 }}
      animate={reduceMotion ? { opacity: 1 } : { opacity: 1, scale: 1 }}
      whileHover={reduceMotion || isCritical ? {} : { scale: 1.005, borderColor: '#525252' }}
      onClick={() => navigate(`/device/${device.id}`)}
      tabIndex={0}
      role="button"
      onKeyDown={(event) => {
        if (event.key === 'Enter' || event.key === ' ') {
          event.preventDefault();
          navigate(`/device/${device.id}`);
        }
      }}
      className={cn(
        "relative flex h-[180px] w-[240px] flex-none flex-col justify-between rounded-sm bg-bg-elevated p-5 cursor-pointer transition-colors duration-150 border focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent focus-visible:ring-offset-2 focus-visible:ring-offset-base",
        isCritical ? "border-accent border-2" : "border-border",
        "group"
      )}
    >
      <div className="h-12 flex flex-col gap-1">
        <div className="flex items-center gap-2">
          <Icon size={16} className="text-text-secondary" />
          <span className="font-sans text-body font-semibold text-text-primary truncate">{device.name}</span>
        </div>
        <div className="font-mono text-caption text-text-tertiary">{device.ip}</div>
      </div>
      
      <div className="absolute inset-x-5 top-1/2 flex -translate-y-1/2 flex-col items-center justify-center">
        <motion.span 
          initial={{ opacity: 0 }}
          animate={{ opacity: 1 }}
          className={cn("font-sans text-[36px] font-semibold leading-none", severityColor)}
        >
          {device.trustScore}
        </motion.span>
        <span className={cn("font-caption text-[10px] uppercase tracking-widest mt-1", severityColor)}>
          {severityLabel}
        </span>
      </div>

      <div className="h-10 w-full">
        <ResponsiveContainer width="100%" height="100%">
          <LineChart data={device.history.slice(-20).map(v => ({ v }))}>
            <Line 
              type="monotone" 
              dataKey="v" 
              stroke={getSeverityHex(device.trustScore)} 
              strokeWidth={2} 
              dot={false} 
              isAnimationActive={false} 
            />
          </LineChart>
        </ResponsiveContainer>
      </div>

      {device.driftConfirmed && (
        <motion.div 
          animate={reduceMotion ? { opacity: 1 } : { opacity: [1, 0.4, 1] }}
          transition={{ duration: 2, repeat: Infinity }}
          className="absolute top-3 right-3 w-2 h-2 bg-accent rounded-full" 
        />
      )}
      
      <div className="absolute top-3 right-8 opacity-0 group-hover:opacity-100 transition-opacity duration-150">
        <Icons.ChevronRight size={14} className="text-text-tertiary" />
      </div>
    </motion.div>
  );
}
