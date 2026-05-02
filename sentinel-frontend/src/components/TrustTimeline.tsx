import { AreaChart, Area, XAxis, YAxis, Tooltip, ResponsiveContainer, ReferenceLine } from 'recharts';
import { useLanguage } from '../lib/language';

export default function TrustTimeline({ data, trustScore }: { data: number[], trustScore: number }) {
  const { t } = useLanguage();
  const chartData = data.slice(-60).map((v, i) => ({ window: i, score: v }));
  
  const getSeverityHex = (score: number) => {
    if (score >= 70) return '#4ade80';
    if (score >= 50) return '#facc15';
    if (score >= 30) return '#fb923c';
    return '#ef4444';
  };

  const color = getSeverityHex(trustScore);

  return (
    <section className="rounded-sm border border-border bg-bg-elevated p-6 space-y-6">
      <div className="flex items-center justify-between">
        <h3 className="font-caption text-text-secondary uppercase tracking-widest">{t('trust_timeline')}</h3>
        <div className="font-mono text-[10px] text-text-tertiary uppercase">{t('last_60_windows')}</div>
      </div>
      
      <div className="h-[200px] w-full">
        <ResponsiveContainer width="100%" height="100%">
          <AreaChart data={chartData} margin={{ top: 0, right: 0, left: 0, bottom: 0 }}>
            <defs>
              <linearGradient id="areaFill" x1="0" y1="0" x2="0" y2="1">
                <stop offset="0%" stopColor="#ff7759" stopOpacity={0.08}/>
                <stop offset="100%" stopColor="#ff7759" stopOpacity={0}/>
              </linearGradient>
            </defs>
            <XAxis dataKey="window" hide />
            <YAxis domain={[0, 100]} hide />
            <Tooltip 
              content={({ active, payload }) => {
                if (active && payload && payload.length) {
                  return (
                    <div className="bg-bg-soft border border-border p-2 px-3">
                      <div className="font-mono text-[11px] text-text-primary">
                        SCORE: {payload[0].value}
                      </div>
                    </div>
                  );
                }
                return null;
              }}
            />
            <ReferenceLine y={70} stroke="#3a3a3a" strokeDasharray="4 4" />
            <ReferenceLine y={50} stroke="#3a3a3a" strokeDasharray="4 4" />
            <ReferenceLine y={30} stroke="#3a3a3a" strokeDasharray="4 4" />
            <Area 
              type="monotone" 
              dataKey="score" 
              stroke={color} 
              fill="url(#areaFill)" 
              strokeWidth={2} 
              isAnimationActive={false}
              connectNulls
            />
          </AreaChart>
        </ResponsiveContainer>
      </div>
    </section>
  );
}
