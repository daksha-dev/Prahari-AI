import type { Device, DeviceDetail, EvidenceCard, NetworkSummary } from './types';

const generateHistory = (length: number, start: number, trend: number = 0) => {
  const history = [];
  let current = start;
  for (let i = 0; i < length; i++) {
    current += (Math.random() - 0.5) * 5 + trend;
    current = Math.max(0, Math.min(100, current));
    history.push(Math.round(current));
  }
  return history;
};

const FEATURE_NAMES = [
  'packet_rate', 'byte_rate', 'tcp_syn_count', 'udp_pkt_count', 'dns_query_count',
  'avg_pkt_size', 'std_pkt_size', 'unique_ips', 'unique_ports', 'ttl_variation',
  'tcp_window_size', 'payload_entropy', 'conn_duration', 'outbound_ratio',
  'arp_request_rate', 'icmp_echo_rate', 'retransmission_rate', 'out_of_order_pkt',
  'http_error_rate', 'ssh_login_attempts', 'tls_cert_validation', 'dhcp_lease_freq'
];

export const MOCK_DEVICES: Device[] = [
  {
    id: '1',
    name: 'Smart Thermostat',
    type: 'ESP32',
    ip: '192.168.50.21',
    trustScore: 34,
    severity: 'risk',
    history: generateHistory(60, 95, -1.2), // Declining trust
    driftConfirmed: true,
    icon: 'Thermometer'
  },
  {
    id: '2',
    name: 'Security Camera N',
    type: 'IP Cam',
    ip: '192.168.50.45',
    trustScore: 92,
    severity: 'healthy',
    history: generateHistory(60, 92),
    driftConfirmed: false,
    icon: 'Camera'
  },
  {
    id: '3',
    name: 'Security Camera S',
    type: 'IP Cam',
    ip: '192.168.50.46',
    trustScore: 88,
    severity: 'healthy',
    history: generateHistory(60, 90),
    driftConfirmed: false,
    icon: 'Camera'
  },
  {
    id: '4',
    name: 'Living Room Bulb',
    type: 'Smart Bulb',
    ip: '192.168.50.10',
    trustScore: 98,
    severity: 'healthy',
    history: generateHistory(60, 98),
    driftConfirmed: false,
    icon: 'Lightbulb'
  },
  {
    id: '5',
    name: 'Kitchen Bulb',
    type: 'Smart Bulb',
    ip: '192.168.50.11',
    trustScore: 97,
    severity: 'healthy',
    history: generateHistory(60, 97),
    driftConfirmed: false,
    icon: 'Lightbulb'
  },
  {
    id: '6',
    name: 'Front Door Lock',
    type: 'Smart Lock',
    ip: '192.168.50.30',
    trustScore: 95,
    severity: 'healthy',
    history: generateHistory(60, 95),
    driftConfirmed: false,
    icon: 'Lock'
  },
  {
    id: '7',
    name: 'Back Door Lock',
    type: 'Smart Lock',
    ip: '192.168.50.31',
    trustScore: 94,
    severity: 'healthy',
    history: generateHistory(60, 94),
    driftConfirmed: false,
    icon: 'Lock'
  },
  {
    id: '8',
    name: 'Main Smart Plug',
    type: 'Smart Plug',
    ip: '192.168.50.60',
    trustScore: 65,
    severity: 'watch',
    history: generateHistory(60, 80, -0.2),
    driftConfirmed: false,
    icon: 'Zap'
  },
  {
    id: '9',
    name: 'TV Smart Plug',
    type: 'Smart Plug',
    ip: '192.168.50.61',
    trustScore: 91,
    severity: 'healthy',
    history: generateHistory(60, 91),
    driftConfirmed: false,
    icon: 'Zap'
  },
  {
    id: '10',
    name: 'Weather Station',
    type: 'Sensor',
    ip: '192.168.50.80',
    trustScore: 85,
    severity: 'healthy',
    history: generateHistory(60, 85),
    driftConfirmed: false,
    icon: 'Cloud'
  },
  {
    id: '11',
    name: 'Garage Opener',
    type: 'Controller',
    ip: '192.168.50.90',
    trustScore: 93,
    severity: 'healthy',
    history: generateHistory(60, 93),
    driftConfirmed: false,
    icon: 'Home'
  },
  {
    id: '12',
    name: 'Motion Sensor Hall',
    type: 'Sensor',
    ip: '192.168.50.101',
    trustScore: 89,
    severity: 'healthy',
    history: generateHistory(60, 89),
    driftConfirmed: false,
    icon: 'Activity'
  }
];

export const getMockDeviceDetail = (id: string): DeviceDetail => {
  const device = MOCK_DEVICES.find(d => d.id === id) || MOCK_DEVICES[0];
  const isDrifting = id === '1';

  return {
    ...device,
    baselineLocked: true,
    anomalyScores: Array.from({ length: 60 }, () => Math.random() * (isDrifting ? 0.8 : 0.2)),
    driftSignals: {
      adwin: Array.from({ length: 60 }, (_, i) => isDrifting && i > 40 && Math.random() > 0.3),
      chiSquared: Array.from({ length: 60 }, (_, i) => isDrifting && i > 35 && Math.random() > 0.4),
      modelDisagreement: Array.from({ length: 60 }, (_, i) => isDrifting && i > 45 && Math.random() > 0.2),
    },
    behavioralHeatmap: Array.from({ length: 22 }, (_, f) => 
      Array.from({ length: 30 }, (_, w) => {
        if (isDrifting && w > 15 && f < 5) return Math.random() * 2 + 1; // High deviation
        return (Math.random() - 0.5) * 2;
      })
    ),
    featureNames: FEATURE_NAMES,
    summary: isDrifting 
      ? "Significant behavioral drift detected in Smart Thermostat. Outbound connection patterns have deviated from the baseline, specifically in DNS query frequency and average packet size. This suggests a potential firmware compromise or data exfiltration attempt."
      : "Device behavior is consistent with the established baseline. No significant anomalies or drift signals detected."
  };
};

export const getMockEvidenceCard = (_deviceId: string): EvidenceCard => ({
  windowId: 542,
  time: new Date().toLocaleTimeString(),
  duration: '300s',
  topDeviations: [
    { feature: 'dns_query_count', zScore: 4.2 },
    { feature: 'avg_pkt_size', zScore: -3.8 },
    { feature: 'outbound_ratio', zScore: 2.5 },
    { feature: 'unique_ips', zScore: 2.1 },
    { feature: 'packet_rate', zScore: 1.8 }
  ],
  driftSignals: ['ADWIN confirmed', 'Chi-Squared threshold exceeded'],
  policyViolations: ['Unauthorized DNS server access', 'Unexpected peak-hour traffic']
});

export const getMockNetworkSummary = (): NetworkSummary => ({
  meanTrust: Math.round(MOCK_DEVICES.reduce((acc, d) => acc + d.trustScore, 0) / MOCK_DEVICES.length),
  deviceCount: MOCK_DEVICES.length,
  activeAlerts: MOCK_DEVICES.filter(d => d.trustScore < 70).length,
  driftConfirmed: MOCK_DEVICES.filter(d => d.driftConfirmed).length,
  trustHistory: generateHistory(60, 85)
});
