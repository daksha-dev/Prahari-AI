import { Link } from 'react-router-dom';
import { motion, useReducedMotion } from 'framer-motion';
import LanguageSelector from './LanguageSelector';
import { useLanguage } from '../lib/language';

interface TopBarProps {
  onAskSentinel: () => void;
}

export default function TopBar({ onAskSentinel }: TopBarProps) {
  const reduceMotion = useReducedMotion();
  const { t } = useLanguage();

  return (
    <header className="h-[56px] bg-bg-base border-b border-border flex items-center justify-between px-8 sticky top-0 z-[60]">
      <div className="flex items-center gap-6">
        <Link to="/" className="font-display text-2xl text-text-primary hover:opacity-80 transition-opacity">
          Sentinel<span className="text-accent">.</span>
        </Link>
        
        <div className="h-4 w-[1px] bg-border" />
        
        <div className="flex items-center gap-2">
          <motion.div 
            animate={reduceMotion ? { opacity: 1 } : { opacity: [1, 0.5, 1] }}
            transition={{ duration: 2, repeat: Infinity }}
            className="w-2 h-2 rounded-full bg-severity-healthy"
          />
          <span className="font-caption text-text-secondary uppercase">{t('all_systems_operational')}</span>
        </div>
      </div>

      <div className="flex items-center gap-6">
        <LanguageSelector />

        <div className="h-4 w-[1px] bg-border" />

        <button 
          onClick={onAskSentinel}
          className="h-10 cursor-pointer bg-accent text-bg-base px-4 rounded-md font-sans text-sm font-semibold hover:bg-accent/90 transition-colors duration-150 flex items-center gap-3 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent focus-visible:ring-offset-2 focus-visible:ring-offset-base"
        >
          {t('ask_sentinel')}
          <span className="opacity-50 font-mono text-xs px-1.5 py-0.5 border border-bg-base/20 rounded-sm">/</span>
        </button>
      </div>
    </header>
  );
}
