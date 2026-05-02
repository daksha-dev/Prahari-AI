import { MOCK_DEVICES, getMockDeviceDetail, getMockEvidenceCard, getMockNetworkSummary } from './mockData';
import type { Alert, ChatStreamEvent, Device, DeviceDetail, EvidenceCard, NetworkSummary, ScenarioName, Severity } from './types';
import { reportSarvamFailure, reportSarvamSuccess } from './sarvamHealth';

const API_URL = import.meta.env.VITE_API_URL || 'mock';
const FEATURE_NAMES = [
  'total_bytes', 'total_packets', 'total_flows', 'packets_per_sec', 'bytes_per_sec',
  'flows_per_sec', 'unique_dst_ips', 'unique_dst_ports', 'dst_ip_entropy', 'port_entropy',
  'tcp_ratio', 'udp_ratio', 'icmp_ratio', 'mean_iat', 'mean_flow_duration',
  'syn_ack_ratio', 'rst_rate', 'flow_symmetry', 'burstiness', 'new_dst_count',
  'avg_payload_size', 'connection_failure_rate'
];

const severityFromTrust = (score: number): Severity => {
  if (score >= 70) return 'healthy';
  if (score >= 50) return 'watch';
  if (score >= 35) return 'risk';
  return 'critical';
};

const iconForType = (type: string) => {
  const icons: Record<string, string> = {
    camera: 'Camera',
    doorbell: 'Bell',
    bulb: 'Lightbulb',
    lock: 'Lock',
    plug: 'Zap',
    thermostat: 'Thermometer',
    tv: 'Tv',
    speaker: 'Speaker',
    esp32: 'Cpu',
  };
  return icons[type] || 'Cpu';
};

const assertOk = async (response: Response) => {
  if (!response.ok) {
    throw new Error(`API request failed: ${response.status} ${response.statusText}`);
  }
  return response;
};

const toDevice = (raw: any): Device => ({
  id: raw.device_id,
  name: raw.name,
  type: raw.device_type,
  ip: raw.ip,
  trustScore: raw.current_trust,
  severity: severityFromTrust(raw.current_trust),
  history: raw.trust_sparkline || [],
  driftConfirmed: Boolean(raw.drift_confirmed),
  icon: iconForType(raw.device_type),
});

const transpose = (rows: number[][]): number[][] => {
  if (!rows.length) return FEATURE_NAMES.map(() => []);
  return FEATURE_NAMES.map((_, featureIndex) => rows.map(row => Number(row[featureIndex] || 0)));
};

export const fetchDevices = async (): Promise<Device[]> => {
  if (API_URL === 'mock') return Promise.resolve(MOCK_DEVICES);
  const response = await assertOk(await fetch(`${API_URL}/api/devices`));
  const raw = await response.json();
  return raw.map(toDevice);
};

export const fetchDeviceDetail = async (id: string, language = 'en'): Promise<DeviceDetail> => {
  if (API_URL === 'mock') return Promise.resolve(getMockDeviceDetail(id));
  const [detailResponse, alerts] = await Promise.all([
    assertOk(await fetch(`${API_URL}/api/devices/${id}?language=${encodeURIComponent(language)}`)),
    fetchAlerts().catch(() => []),
  ]);
  const raw = await detailResponse.json();
  const device = raw.device;
  const history = (raw.trust_history || []).map((point: any) => point.trust);
  const driftRows = raw.drift_status || [];
  const alert = alerts.find(item => item.deviceId === id);
  return {
    id: device.device_id,
    name: device.name,
    type: device.device_type,
    ip: device.ip,
    trustScore: raw.current_trust,
    severity: severityFromTrust(raw.current_trust),
    history,
    driftConfirmed: Boolean(device.drift_confirmed),
    icon: iconForType(device.device_type),
    baselineLocked: true,
    anomalyScores: driftRows.map((row: any) => Number(row.factor || 1)),
    driftSignals: {
      adwin: driftRows.map((row: any) => Boolean(row.adwin)),
      chiSquared: driftRows.map((row: any) => Boolean(row.chi_squared)),
      modelDisagreement: driftRows.map((row: any) => Boolean(row.model_disagreement)),
    },
    behavioralHeatmap: transpose(raw.behavioral_heatmap || []),
    featureNames: FEATURE_NAMES,
    summary: alert?.aiSummary || '',
  };
};

export const fetchEvidenceCard = async (id: string): Promise<EvidenceCard> => {
  if (API_URL === 'mock') return Promise.resolve(getMockEvidenceCard(id));
  const response = await assertOk(await fetch(`${API_URL}/api/devices/${id}/evidence`));
  const raw = await response.json();
  return {
    windowId: raw.window_id,
    time: raw.timestamp_iso ? new Date(raw.timestamp_iso).toLocaleTimeString() : '',
    duration: '60s',
    topDeviations: (raw.top_deviating_features || []).map((item: any) => ({
      feature: item.name,
      zScore: Number(item.z_score || 0),
    })),
    driftSignals: raw.drift_signals_fired || [],
    policyViolations: (raw.policy_violations || []).map((item: any) => item.detail || item.rule || String(item)),
  };
};

export const fetchNetworkSummary = async (): Promise<NetworkSummary> => {
  if (API_URL === 'mock') return Promise.resolve(getMockNetworkSummary());
  const [summaryResponse, devices] = await Promise.all([
    assertOk(await fetch(`${API_URL}/api/network-summary`)),
    fetchDevices(),
  ]);
  const raw = await summaryResponse.json();
  return {
    meanTrust: raw.mean_trust,
    deviceCount: raw.total_devices,
    activeAlerts: raw.watch_count + raw.at_risk_count + raw.critical_count,
    driftConfirmed: raw.drift_confirmed_count,
    trustHistory: devices.map(device => device.trustScore),
  };
};

export const fetchAlerts = async (): Promise<Alert[]> => {
  if (API_URL === 'mock') return Promise.resolve([]);
  const response = await assertOk(await fetch(`${API_URL}/api/alerts`));
  const raw = await response.json();
  return raw.map((item: any) => ({
    incidentId: item.incident_id,
    deviceId: item.device_id,
    name: item.name,
    ip: item.ip,
    severity: item.severity,
    trust: item.trust,
    timestampIso: item.timestamp_iso,
    windowId: item.window_id,
    aiSummary: item.ai_summary,
  }));
};

export const switchScenario = async (name: ScenarioName) => {
  if (API_URL === 'mock') return { ok: true, scenario: name };
  const response = await assertOk(await fetch(`${API_URL}/api/scenario`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ name }),
  }));
  return response.json();
};

export const resetDemo = async () => {
  if (API_URL === 'mock') return { ok: true, scenario: 'live' };
  const response = await assertOk(await fetch(`${API_URL}/api/reset`, { method: 'POST' }));
  return response.json();
};

export async function streamChat(
  messages: { role: 'user' | 'assistant'; content: string }[],
  onEvent: (event: ChatStreamEvent) => void,
  language = 'en',
) {
  if (API_URL === 'mock') {
    onEvent({ type: 'token', content: 'Mock mode is active. Set VITE_API_URL to your Railway backend for live Sentinel analysis.' });
    onEvent({ type: 'done' });
    reportSarvamSuccess();
    return;
  }
  let hadError = false;
  try {
    const response = await assertOk(await fetch(`${API_URL}/api/chat`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ messages, language }),
    }));
    const reader = response.body?.getReader();
    if (!reader) throw new Error('SSE response body is not readable.');
    const decoder = new TextDecoder();
    let buffer = '';
    while (true) {
      const { value, done } = await reader.read();
      if (done) break;
      buffer += decoder.decode(value, { stream: true });
      const events = buffer.split('\n\n');
      buffer = events.pop() || '';
      for (const event of events) {
        const line = event.split('\n').find(part => part.startsWith('data: '));
        if (!line) continue;
        const parsed = JSON.parse(line.slice(6)) as ChatStreamEvent;
        if (parsed.type === 'error') hadError = true;
        onEvent(parsed);
      }
    }
    if (hadError) reportSarvamFailure();
    else reportSarvamSuccess();
  } catch (error) {
    reportSarvamFailure();
    throw error;
  }
}
