import { createContext, useContext, useEffect, useMemo, useState, type ReactNode } from 'react';
import { type Language, t as translate, type StringKey } from './strings';

interface LanguageContextValue {
  language: Language;
  setLanguage: (language: Language) => void;
  t: (key: StringKey, vars?: Record<string, string | number>) => string;
}

const LanguageContext = createContext<LanguageContextValue | null>(null);
const STORAGE_KEY = 'sentinel.language';

const isLanguage = (value: string | null): value is Language => {
  return value === 'en' || value === 'hi' || value === 'kn' || value === 'ta' || value === 'te';
};

export function LanguageProvider({ children }: { children: ReactNode }) {
  const [language, setLanguageState] = useState<Language>(() => {
    const stored = localStorage.getItem(STORAGE_KEY);
    return isLanguage(stored) ? stored : 'en';
  });

  const setLanguage = (next: Language) => {
    setLanguageState(next);
    localStorage.setItem(STORAGE_KEY, next);
  };

  useEffect(() => {
    document.documentElement.lang = language;
  }, [language]);

  const value = useMemo<LanguageContextValue>(() => ({
    language,
    setLanguage,
    t: (key, vars) => translate(language, key, vars),
  }), [language]);

  return <LanguageContext.Provider value={value}>{children}</LanguageContext.Provider>;
}

export function useLanguage() {
  const value = useContext(LanguageContext);
  if (!value) {
    throw new Error('useLanguage must be used within LanguageProvider');
  }
  return value;
}
