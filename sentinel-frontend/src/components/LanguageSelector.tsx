import { useState } from 'react';
import { ChevronDown } from 'lucide-react';
import { LANGUAGE_LABELS, MORE_LANGUAGES, PRIMARY_LANGUAGES, type Language } from '../lib/strings';
import { useLanguage } from '../lib/language';
import { cn } from '../lib/utils';

export default function LanguageSelector({ compact = false }: { compact?: boolean }) {
  const { language, setLanguage, t } = useLanguage();
  const [open, setOpen] = useState(false);

  const choose = (next: Language) => {
    setLanguage(next);
    setOpen(false);
  };

  const optionClass = (value: Language) => cn(
    compact ? 'h-7 px-2 text-[10px]' : 'h-8 px-2.5 text-[11px]',
    'font-caption uppercase rounded-md cursor-pointer transition-colors duration-150',
    'focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent focus-visible:ring-offset-2 focus-visible:ring-offset-base',
    language === value ? 'text-accent bg-accent/10' : 'text-text-secondary hover:text-text-primary hover:bg-bg-elevated',
  );

  return (
    <div className="relative flex items-center gap-1">
      <div className="flex items-center gap-1">
        {PRIMARY_LANGUAGES.map(value => (
          <button key={value} type="button" onClick={() => choose(value)} className={optionClass(value)}>
            {LANGUAGE_LABELS[value]}
          </button>
        ))}
      </div>
      <div className="h-4 w-[1px] bg-border" />
      <button
        type="button"
        onClick={() => setOpen(prev => !prev)}
        className={cn(
          compact ? 'h-7 px-2 text-[10px]' : 'h-8 px-2.5 text-[11px]',
          'flex items-center gap-1 rounded-md font-caption text-text-secondary cursor-pointer transition-colors duration-150 hover:text-text-primary hover:bg-bg-elevated',
          'focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent focus-visible:ring-offset-2 focus-visible:ring-offset-base',
        )}
        aria-label={t('more_languages')}
      >
        {compact ? '+' : t('more_languages')}
        <ChevronDown size={12} />
      </button>
      {open && (
        <div className="absolute right-0 top-full z-[90] mt-2 min-w-32 rounded border border-border bg-bg-soft p-1">
          {MORE_LANGUAGES.map(value => (
            <button key={value} type="button" onClick={() => choose(value)} className={cn(optionClass(value), 'w-full text-left')}>
              {LANGUAGE_LABELS[value]}
            </button>
          ))}
        </div>
      )}
    </div>
  );
}
