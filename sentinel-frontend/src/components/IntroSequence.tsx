import React, { useReducer, useEffect, useRef, useCallback, useState } from 'react';
import { motion } from 'framer-motion';

/*
  STATE MACHINE NOTES:
  - Stages: idle -> authenticating -> discovering -> locking -> ready -> complete
  - Reducer handles deterministic transitions and ensures content accumulates without duplication.
  - Stage authenticating: 3 lines resolve at 600ms intervals.
  - Stage discovering: 12 devices resolve at 120ms intervals.
  - Stage locking: 4 baseline lines resolve at 300ms intervals.
  - Stage ready: "SENTINEL READY" display, waits for final click to enter dashboard.
  - Stage complete: Intro fades out and unmounts.
  - StrictMode safety: Ref-tracked 'scheduled' flag prevents duplicate effect execution in dev.
*/

const RAILWAY_URL = "sentinel-api.railway.app";

const DEVICE_REGISTRY = [
  { ip: "192.168.50.04", name: "Living Room Camera" },
  { ip: "192.168.50.05", name: "Kitchen Camera" },
  { ip: "192.168.50.12", name: "Smart Thermostat" },
  { ip: "192.168.50.18", name: "Front Door Lock" },
  { ip: "192.168.50.21", name: "Garage Opener" },
  { ip: "192.168.50.24", name: "Bedroom Light" },
  { ip: "192.168.50.31", name: "Office Printer" },
  { ip: "192.168.50.33", name: "Home Assistant" },
  { ip: "192.168.50.40", name: "Media Server" },
  { ip: "192.168.50.42", name: "Backup Drive" },
  { ip: "192.168.50.45", name: "Nursery Monitor" },
  { ip: "192.168.50.50", name: "Solar Inverter" },
];

type Stage = "idle" | "authenticating" | "discovering" | "locking" | "ready" | "complete";

type Line = { text: string; resolved: boolean; showSpinner?: boolean };
type DeviceLine = { ip: string; name: string; resolved: boolean };

type State = {
  stage: Stage;
  authLines: Line[];
  deviceLines: DeviceLine[];
  baselineLines: Line[];
};

type Action =
  | { type: "advance" }
  | { type: "auth_line_complete"; index: number }
  | { type: "device_line_complete"; index: number }
  | { type: "baseline_line_complete"; index: number }
  | { type: "skip" };

const initialState: State = {
  stage: sessionStorage.getItem("sentinel.intro_complete") === "true" ? "complete" : "idle",
  authLines: [],
  deviceLines: [],
  baselineLines: [],
};

const isEditableTarget = (target: EventTarget | null) => {
  if (!(target instanceof HTMLElement)) return false;
  return (
    target.tagName === "INPUT" ||
    target.tagName === "TEXTAREA" ||
    target.tagName === "SELECT" ||
    target.isContentEditable
  );
};

function reducer(state: State, action: Action): State {
  switch (action.type) {
    case "advance": {
      if (state.stage === "idle") {
        return {
          ...state,
          stage: "authenticating",
          authLines: [
            { text: "Establishing secure channel", resolved: false },
            { text: `Authenticating with backend at ${RAILWAY_URL}`, resolved: false },
            { text: "Stream connection: ESTABLISHED", resolved: false },
          ],
        };
      }
      if (state.stage === "authenticating" && state.authLines.every(l => l.resolved)) {
        return {
          ...state,
          stage: "discovering",
          deviceLines: DEVICE_REGISTRY.map(d => ({ ...d, resolved: false })),
        };
      }
      if (state.stage === "discovering" && state.deviceLines.every(l => l.resolved)) {
        return {
          ...state,
          stage: "locking",
          baselineLines: [
            { text: "Computing baselines from 30 burn-in windows", resolved: false, showSpinner: true },
            { text: "Baseline locked · 22 features per device · 12 devices monitored", resolved: false },
            { text: "Detection engine: ARMED", resolved: false },
            { text: "AI Analyst: STANDBY", resolved: false },
          ],
        };
      }
      if (state.stage === "locking" && state.baselineLines.every(l => l.resolved)) {
        return { ...state, stage: "ready" };
      }
      if (state.stage === "ready") {
        return { ...state, stage: "complete" };
      }
      return state;
    }
    case "auth_line_complete": {
      const authLines = [...state.authLines];
      if (authLines[action.index]) authLines[action.index].resolved = true;
      return { ...state, authLines };
    }
    case "device_line_complete": {
      const deviceLines = [...state.deviceLines];
      if (deviceLines[action.index]) deviceLines[action.index].resolved = true;
      return { ...state, deviceLines };
    }
    case "baseline_line_complete": {
      const baselineLines = [...state.baselineLines];
      if (baselineLines[action.index]) baselineLines[action.index].resolved = true;
      return { ...state, baselineLines };
    }
    case "skip":
      return { ...state, stage: "complete" };
    default:
      return state;
  }
}

const IntroSequence: React.FC = () => {
  const [state, dispatch] = useReducer(reducer, initialState);
  const [isVisible, setIsVisible] = useState(state.stage !== "complete");
  const containerRef = useRef<HTMLDivElement>(null);
  const scheduledRef = useRef<Stage | null>(null);
  const advanceGuard = useRef(false);

  // Persistence handler
  useEffect(() => {
    if (state.stage === "complete") {
      sessionStorage.setItem("sentinel.intro_complete", "true");
      const timer = setTimeout(() => setIsVisible(false), 400);
      return () => clearTimeout(timer);
    }
  }, [state.stage]);

  // Stage: Authenticating
  useEffect(() => {
    if (state.stage !== "authenticating" || scheduledRef.current === "authenticating") return;
    scheduledRef.current = "authenticating";
    const timers = state.authLines.map((_, i) => 
      setTimeout(() => dispatch({ type: "auth_line_complete", index: i }), (i + 1) * 600)
    );
    return () => { timers.forEach(clearTimeout); scheduledRef.current = null; };
  }, [state.stage, state.authLines.length]);

  // Stage: Discovering
  useEffect(() => {
    if (state.stage !== "discovering" || scheduledRef.current === "discovering") return;
    scheduledRef.current = "discovering";
    const timers = state.deviceLines.map((_, i) => 
      setTimeout(() => dispatch({ type: "device_line_complete", index: i }), (i + 1) * 120)
    );
    return () => { timers.forEach(clearTimeout); scheduledRef.current = null; };
  }, [state.stage, state.deviceLines.length]);

  // Stage: Locking
  useEffect(() => {
    if (state.stage !== "locking" || scheduledRef.current === "locking") return;
    scheduledRef.current = "locking";
    const timers = state.baselineLines.map((_, i) => 
      setTimeout(() => dispatch({ type: "baseline_line_complete", index: i }), (i + 1) * 300)
    );
    return () => { timers.forEach(clearTimeout); scheduledRef.current = null; };
  }, [state.stage, state.baselineLines.length]);

  const handleAdvance = useCallback(() => {
    if (advanceGuard.current) return;
    
    const canAdvance = 
      state.stage === "idle" ||
      (state.stage === "authenticating" && state.authLines.every(l => l.resolved)) ||
      (state.stage === "discovering" && state.deviceLines.every(l => l.resolved)) ||
      (state.stage === "locking" && state.baselineLines.every(l => l.resolved)) ||
      state.stage === "ready";

    if (canAdvance) {
      advanceGuard.current = true;
      dispatch({ type: "advance" });
      setTimeout(() => { advanceGuard.current = false; }, 100);
    }
  }, [state]);

  useEffect(() => {
    if (!isVisible) return;

    const handleKeyDown = (e: KeyboardEvent) => {
      if (isEditableTarget(e.target)) return;

      if (e.key === " " || e.key === "Enter") {
        e.preventDefault();
        handleAdvance();
      } else if (e.key === "Escape") {
        dispatch({ type: "skip" });
      }
    };
    window.addEventListener("keydown", handleKeyDown);
    return () => window.removeEventListener("keydown", handleKeyDown);
  }, [handleAdvance, isVisible]);

  if (!isVisible) return null;

  const showPrompt = 
    state.stage === "idle" ||
    (state.stage === "authenticating" && state.authLines.every(l => l.resolved)) ||
    (state.stage === "discovering" && state.deviceLines.every(l => l.resolved)) ||
    (state.stage === "locking" && state.baselineLines.every(l => l.resolved)) ||
    state.stage === "ready";

  const getPromptText = () => {
    if (state.stage === "idle") return "PRESS [SPACE] OR CLICK TO INITIALIZE";
    if (state.stage === "authenticating") return "PRESS [SPACE] OR CLICK TO DISCOVER DEVICES";
    if (state.stage === "discovering") return "PRESS [SPACE] OR CLICK TO LOCK BASELINE";
    return "PRESS [SPACE] OR CLICK TO ENTER DASHBOARD";
  };

  return (
    <motion.div
      ref={containerRef}
      initial={{ opacity: 1 }}
      animate={{ opacity: state.stage === "complete" ? 0 : 1 }}
      transition={{ duration: 0.4 }}
      className="fixed inset-0 z-[200] bg-bg-base flex flex-col items-center justify-center cursor-default select-none overflow-hidden"
      onClick={handleAdvance}
    >
      {/* Brand Mark */}
      <motion.div
        layout
        className="font-display text-text-primary fixed z-[210]"
        style={{
          left: state.stage === "idle" ? "50%" : "48px",
          top: state.stage === "idle" ? "50%" : "48px",
          x: state.stage === "idle" ? "-50%" : "0%",
          y: state.stage === "idle" ? "-50%" : "0%",
          fontSize: state.stage === "idle" ? "56px" : "32px",
        }}
        transition={{ duration: 0.8, ease: [0.16, 1, 0.3, 1] }}
      >
        Sentinel<span className="text-accent">.</span>
      </motion.div>

      {/* Terminal Content */}
      {state.stage !== "idle" && (
        <div className="max-w-[640px] w-full mx-auto px-8 flex flex-col justify-center min-h-[400px]">
          <div className="w-full space-y-0" aria-live="polite">
            {state.authLines.map((line, i) => (
              <LogLine key={`auth-${i}`} text={`▸ ${line.text}`} resolved={line.resolved} />
            ))}
            {state.deviceLines.length > 0 && (
              <div className="pt-6 space-y-0">
                <div className="font-mono text-[14px] text-text-tertiary mb-2">▸ Scanning subnet 192.168.50.0/24...</div>
                {state.deviceLines.map((line) => (
                  <LogLine key={`dev-${line.ip}`} text={`▸ ${line.ip}`} subText={`— ${line.name}`} resolved={line.resolved} />
                ))}
              </div>
            )}
            {state.baselineLines.length > 0 && (
              <div className="pt-6 space-y-0">
                {state.baselineLines.map((line, i) => (
                  <LogLine key={`base-${i}`} text={`▸ ${line.text}`} resolved={line.resolved} showSpinner={line.showSpinner && !line.resolved} isStatus={i > 1} />
                ))}
              </div>
            )}
          </div>
          
          <div className="mt-12 h-32 flex flex-col justify-start">
            {showPrompt && (
              <div className="space-y-6">
                {(state.stage === "ready" || (state.stage === "locking" && state.baselineLines.every(l => l.resolved))) && (
                  <motion.div 
                    initial={{ opacity: 0, y: 10 }}
                    animate={{ opacity: 1, y: 0 }}
                    className="font-display text-4xl text-text-primary"
                  >
                    SENTINEL READY
                  </motion.div>
                )}
                <Prompt text={getPromptText()} />
              </div>
            )}
          </div>
        </div>
      )}

      {/* Stage 0 Prompt */}
      {state.stage === "idle" && (
        <div className="fixed top-[calc(50%+64px)] left-1/2 -translate-x-1/2">
          <Prompt text="PRESS [SPACE] OR CLICK TO INITIALIZE" />
        </div>
      )}

      {/* Skip Button */}
      <button
        onClick={(e) => { e.stopPropagation(); dispatch({ type: "skip" }); }}
        className="fixed bottom-12 right-12 font-caption text-[12px] text-text-secondary hover:text-text-primary hover:underline uppercase transition-colors outline-none border-none bg-transparent"
      >
        Skip intro
      </button>
    </motion.div>
  );
};

const LogLine = ({ text, subText, resolved, showSpinner, isStatus }: { text: string; subText?: string; resolved: boolean; showSpinner?: boolean; isStatus?: boolean }) => {
  const parts = text.split(":");
  return (
    <motion.div
      initial={{ opacity: 0, y: 4 }}
      animate={{ opacity: 1, y: 0 }}
      className="flex justify-between items-center w-full py-[6px] font-mono text-[14px]"
    >
      <div className="flex gap-2 truncate">
        <span className={resolved ? "text-text-primary" : "text-text-secondary"}>
          {parts[0]}
          {parts[1] && isStatus && (
            <span className={resolved ? "text-severity-healthy font-bold" : ""}>
              :{parts[1]}
            </span>
          )}
        </span>
        {subText && <span className="text-text-tertiary truncate">{subText}</span>}
        {showSpinner && (
          <motion.div
            animate={{ rotate: 360 }}
            transition={{ duration: 1, repeat: Infinity, ease: "linear" }}
            className="w-3 h-3 border-2 border-accent border-t-transparent rounded-full inline-block ml-2 self-center"
          />
        )}
      </div>
      <div className="flex items-center flex-shrink-0 ml-4">
        {resolved ? (
          <span className="text-severity-healthy font-bold">✓</span>
        ) : (
          !showSpinner && (
            <motion.div
              animate={{ opacity: [0.4, 1, 0.4] }}
              transition={{ duration: 1.5, repeat: Infinity }}
              className="w-1.5 h-1.5 rounded-full bg-accent"
            />
          )
        )}
      </div>
    </motion.div>
  );
};

const Prompt = ({ text }: { text: string }) => (
  <button
    className="font-caption text-[12px] uppercase text-text-secondary tracking-[0.04em] text-left cursor-default outline-none border-none bg-transparent block"
    aria-label={text}
  >
    <motion.span
      initial={{ opacity: 0.5 }}
      animate={{ opacity: [0.5, 1, 0.5] }}
      transition={{ duration: 2, repeat: Infinity, ease: "easeInOut" }}
    >
      {text}
    </motion.span>
  </button>
);

export default IntroSequence;
