export type Severity = 'healthy' | 'watch' | 'risk' | 'critical';

export interface Device {
  id: string;
  name: string;
  type: string;
  ip: string;
  trustScore: number;
  severity: Severity;
  history: number[];
  driftConfirmed: boolean;
  icon?: string;
}

export interface EvidenceCard {
  windowId: number;
  time: string;
  duration: string;
  topDeviations: { feature: string; zScore: number }[];
  driftSignals: string[];
  policyViolations: string[];
}

export interface DeviceDetail extends Device {
  baselineLocked: boolean;
  anomalyScores: number[];
  driftSignals: {
    adwin: boolean[];
    chiSquared: boolean[];
    modelDisagreement: boolean[];
  };
  behavioralHeatmap: number[][]; // [featureIndex][windowIndex]
  featureNames: string[];
  summary: string;
}

export interface NetworkSummary {
  meanTrust: number;
  deviceCount: number;
  activeAlerts: number;
  driftConfirmed: number;
  trustHistory: number[];
}

export interface ChatMessage {
  id: string;
  role: 'user' | 'assistant';
  content: string;
  timestamp: string;
  toolCalls?: { id: string; name: string; status: 'pending' | 'complete' }[];
  citations?: { type: 'device' | 'evidence'; id: string; label: string }[];
}

export interface Alert {
  incidentId: string;
  deviceId: string;
  name: string;
  ip: string;
  severity: string;
  trust: number;
  timestampIso: string;
  windowId: number;
  aiSummary: string | null;
}

export type ScenarioName = 'live' | 'slow_drift' | 'sudden_ddos' | 'recon_scan';

export type ChatStreamEvent =
  | { type: 'tool_call'; name: string; args: Record<string, unknown> }
  | { type: 'tool_result'; name: string; snippet: string }
  | { type: 'token'; content: string }
  | { type: 'error'; error_class: string; message: string }
  | { type: 'done' };
