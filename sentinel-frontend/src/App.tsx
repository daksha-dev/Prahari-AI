import { BrowserRouter as Router, Routes, Route } from 'react-router-dom';
import Overview from './pages/Overview';
import DeviceDetailView from './pages/DeviceDetail';
import AnalystChat from './components/AnalystChat';
import TopBar from './components/TopBar';
import IntroSequence from './components/IntroSequence';
import { useState, useEffect } from 'react';
import { resetDemo, switchScenario } from './lib/api';
import type { ScenarioName } from './lib/types';
import { AnimatePresence, motion, useReducedMotion } from 'framer-motion';
import { LanguageProvider } from './lib/language';
import SarvamHealthIndicator from './components/SarvamHealthIndicator';

function App() {
  const [isChatOpen, setIsChatOpen] = useState(false);
  const [isDesktop, setIsDesktop] = useState(window.innerWidth >= 1280);
  const [scenario, setScenario] = useState<ScenarioName>('live');
  const [toast, setToast] = useState<string | null>(null);
  const reduceMotion = useReducedMotion();

  const showToast = (message: string) => {
    setToast(message);
    window.setTimeout(() => setToast(null), 2000);
  };

  const handleScenarioChange = async (name: ScenarioName) => {
    await switchScenario(name);
    setScenario(name);
    showToast(`Scenario: ${name.split('_').map(part => part[0].toUpperCase() + part.slice(1)).join(' ')}`);
    window.dispatchEvent(new Event('sentinel:refresh'));
  };

  useEffect(() => {
    const handleResize = () => setIsDesktop(window.innerWidth >= 1280);
    window.addEventListener('resize', handleResize);
    
    const handleKeyDown = async (e: KeyboardEvent) => {
      if (e.key === '/') {
        if (!isDesktop) {
          e.preventDefault();
          setIsChatOpen(true);
        } else {
          // On desktop, the input should just focus. Handled in AnalystChat.
        }
      }
      if ((e.metaKey || e.ctrlKey) && e.shiftKey && e.key.toLowerCase() === 'r') {
        e.preventDefault();
        await resetDemo();
        setScenario('live');
        showToast('Scenario: Live');
        window.dispatchEvent(new Event('sentinel:refresh'));
      }
      if (e.key === 'Escape') {
        setIsChatOpen(false);
      }
    };
    window.addEventListener('keydown', handleKeyDown);
    return () => {
      window.removeEventListener('resize', handleResize);
      window.removeEventListener('keydown', handleKeyDown);
    };
  }, [isDesktop]);

  return (
    <Router>
      <LanguageProvider>
      <div className="min-h-screen bg-bg-base text-text-primary flex flex-col font-sans selection:bg-accent/30">
        <IntroSequence />
        
        <TopBar
          onAskSentinel={() => {
            setIsChatOpen(true);
            window.dispatchEvent(new Event('sentinel:focus-chat'));
          }}
        />
        
        <div className="flex flex-1 overflow-hidden">
          <main className={`flex-1 overflow-y-auto ${isDesktop ? 'w-0' : 'w-full'}`}>
            <Routes>
              <Route path="/" element={<Overview scenario={scenario} onScenarioChange={handleScenarioChange} />} />
              <Route path="/device/:id" element={<DeviceDetailView />} />
            </Routes>
          </main>

          <AnalystChat 
            isOpen={isDesktop || isChatOpen} 
            isDesktop={isDesktop}
            onClose={() => setIsChatOpen(false)} 
          />
        </div>

        <AnimatePresence>
          {toast && (
            <motion.div 
              initial={reduceMotion ? { opacity: 0 } : { opacity: 0, y: 20 }}
              animate={reduceMotion ? { opacity: 1 } : { opacity: 1, y: 0 }}
              exit={reduceMotion ? { opacity: 0 } : { opacity: 0, y: 20 }}
              className="fixed bottom-8 left-8 z-[80] rounded border border-border-strong bg-bg-elevated px-4 py-3 text-caption text-text-primary"
            >
              <div className="flex items-center gap-3">
                <div className="w-1.5 h-1.5 rounded-full bg-accent animate-pulse" />
                {toast}
              </div>
            </motion.div>
          )}
        </AnimatePresence>
        
        <SarvamHealthIndicator />
      </div>
      </LanguageProvider>
    </Router>
  );
}

export default App;
