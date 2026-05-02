<h1 align="center">Prahari AI</h1>

<p align="center">
  <strong>Intelligent IoT Network Trust & Anomaly Monitoring — Powered by Sarvam AI</strong>
</p>

<p align="center">
  <em>Hindi: प्रहरी — "sentinel / guardian"</em>
</p>

<p align="center">
  <a href="#-problem-statement">Problem</a> •
  <a href="#-features">Features</a> •
  <a href="#-demo">Demo</a> •
  <a href="#-architecture">Architecture</a> •
  <a href="#-tech-stack">Tech Stack</a> •
  <a href="#-getting-started">Getting Started</a> •
  <a href="#-api-reference">API</a> •
  <a href="#-team">Team</a>
</p>

<p align="center">
  <em>Built for Vibe-a-thon 2026 · Nitte Meenakshi Institute of Technology · Track: AI and Automation</em>
</p>

---

## 📌 Problem Statement

As smart homes and IoT ecosystems grow, so do the attack surfaces. Consumers deploy cameras, locks, thermostats, and smart speakers — but have **zero visibility** into whether those devices are behaving normally or have been compromised. Traditional firewalls only see packets; they can't tell you *"your thermostat just started scanning 40 internal IP addresses at 3 AM."*

In 2016, the Mirai botnet took down half the internet using IoT devices nobody knew were compromised. Every one of them had drifted from normal to malicious behavior over days. Existing security tools rely on signature matching — they catch known attacks but miss gradual drift entirely. And when alerts do fire, a security analyst spends 20+ minutes reading logs to understand what changed and why.

**Prahari AI** solves both halves of that problem. It continuously profiles every device on the network, detects behavioral drift in real time using online ML, and lets users investigate anomalies through a conversational AI analyst that speaks English, Hindi, Kannada, Tamil, and Telugu.

---

## 🎯 Demo

| Resource | Link |
|----------|------|
| 🎥 Demo Video | *Coming soon* |
| 🌐 Live Frontend | *Coming soon (Vercel)* |
| 🔧 Live Backend | *Coming soon (Railway)* |
| 📂 GitHub Repo | [daksha-dev/Prahari-AI](https://github.com/daksha-dev/Prahari-AI) |

---

## ✨ Features

### 🔍 Real-Time Anomaly Detection
- **Dual-model scoring** using Isolation Forest (batch) + Half-Space Trees (online/streaming) from the [River](https://riverml.xyz/) library
- 22-feature network behavioral fingerprint per device (bytes/sec, packet rates, entropy, SYN/ACK ratio, burstiness, etc.)
- Exponential smoothing to reduce false positives

### 📊 Statistical Drift Detection
- **ADWIN** (Adaptive Windowing) for concept drift on anomaly score streams
- **Chi-squared test** across feature distributions (burn-in baseline vs. recent 10 windows)
- **Model disagreement tracking** (Isolation Forest vs Half-Space Trees divergence streaks)
- Drift is "confirmed" when ≥2 of the 3 signals fire simultaneously

### 🛡️ Trust Scoring Engine
- Continuous 0–100 trust score per device, starting at 95
- Trust decays via quadratic penalty: `15 × (anomaly × drift_factor)²`
- Recovery when anomaly subsides and no drift is confirmed
- Hard policy penalties for forbidden ports (Telnet/23, backdoors), traffic spikes, and SYN floods
- Severity tiers: `NORMAL` → `WATCH` → `AT_RISK` → `CRITICAL`

### 🧠 Sarvam AI-Powered Analyst Chat (Agentic)
- SSE-streamed conversational interface powered by **Sarvam AI** (`sarvam-m` model)
- **7 tool functions** the AI can autonomously call to investigate:
  - `list_flagged_devices` — find devices below trust threshold
  - `get_device_trust` — deep device context (history, z-scores, peer comparison)
  - `explain_drift` — evidence breakdown + attack pattern classification
  - `get_network_summary` — aggregate network health
  - `get_recent_activity` — alert timeline + score deltas
  - `compare_devices` — side-by-side analysis of 2–5 devices
  - `system_remediation` — generate firewall block scripts (iptables/PowerShell) for human approval
- **Attack pattern classifier**: data exfiltration, lateral scanning, DDoS participation, C2 beaconing, frozen sensor
- **Multilingual**: full system prompts in English, Hindi (हिंदी), Kannada (ಕನ್ನಡ), Tamil (தமிழ்), Telugu (తెలుగు)
- **Sovereign by design**: Sarvam runs on Indian infrastructure, keeping telemetry within Indian data jurisdiction (relevant under DPDP Act and CERT-In guidelines for critical infrastructure deployments)

### 📈 Explainability & Evidence Cards
- Per-window evidence cards with top-5 deviating features by z-score
- Deterministic plain-English explanations + AI-generated incident narrations
- Full z-score heatmap visualization across all 22 features over the last 30 windows

### 🎮 Scenario Simulator
- Built-in synthetic device simulator with 12 realistic IoT device profiles
- 4 demo scenarios:
  - **Live** — all devices behave normally
  - **Slow Drift** — thermostat gradually compromised over 30 windows
  - **Sudden DDoS** — camera floods the network instantly
  - **Recon Scan** — smart lock starts port-scanning with forbidden ports

### 🖥️ Interactive Dashboard
- Real-time device cards with trust gauges, severity badges, and drift indicators
- Behavioral heatmap (z-scores across 22 features × 30 windows)
- Trust timeline with anomaly score overlay
- Drift signal stack visualization (ADWIN / Chi² / Model Disagreement)
- Animated intro sequence and dark-mode-first UI
- Language selector for multilingual support

---

## 🏗️ Architecture

```
┌─────────────────────────────────────────────────────────────────────┐
│                        PRAHARI AI SYSTEM                            │
├─────────────────────────────────────────────────────────────────────┤
│                                                                     │
│  ┌──────────────┐     REST / SSE      ┌──────────────────────────┐ │
│  │   React +    │ ◄─────────────────► │    FastAPI Backend       │ │
│  │   Vite +     │    polling +        │                          │ │
│  │   Tailwind   │    event stream     │  ┌────────────────────┐  │ │
│  │   Dashboard  │                     │  │   ML Engine        │  │ │
│  └──────────────┘                     │  │  ┌──────────────┐  │  │ │
│                                       │  │  │IsolationForest│  │  │ │
│                                       │  │  │HalfSpaceTrees │  │  │ │
│                                       │  │  │ADWIN Drift    │  │  │ │
│                                       │  │  │Chi² Test      │  │  │ │
│                                       │  │  │Trust Engine   │  │  │ │
│                                       │  │  │Policy Checker │  │  │ │
│                                       │  │  └──────────────┘  │  │ │
│                                       │  └────────────────────┘  │ │
│  ┌──────────────┐                     │                          │ │
│  │  IoT Devices │  telemetry ────────►│  ┌────────────────────┐  │ │
│  │  (simulated  │  (or real ingest)   │  │   Sarvam AI Chat   │  │ │
│  │   or real)   │                     │  │  (agentic, tools,  │  │ │
│  └──────────────┘                     │  │   multilingual)    │  │ │
│                                       │  └────────────────────┘  │ │
│                                       └──────────────────────────┘ │
└─────────────────────────────────────────────────────────────────────┘
```

---

## 🛠️ Tech Stack

| Layer | Technology | Purpose |
|-------|-----------|---------|
| **Frontend** | React 19, TypeScript, Vite 8 | SPA dashboard |
| **Styling** | Tailwind CSS 3, Framer Motion | UI design + animations |
| **Charts** | Recharts | Trust timeline, heatmaps |
| **Icons** | Lucide React | UI icons |
| **Backend** | FastAPI, Uvicorn, Python 3.12 | REST API + SSE streaming |
| **ML (Batch)** | scikit-learn (Isolation Forest) | Anomaly detection |
| **ML (Online)** | River (Half-Space Trees, ADWIN) | Streaming anomaly + drift |
| **Statistics** | SciPy (chi2_contingency) | Distribution drift test |
| **Data** | NumPy, Pandas | Feature engineering |
| **AI** | Sarvam AI API (`sarvam-m`) | Agentic chat analyst, narration |
| **Validation** | Pydantic v2 | Request/response schemas |
| **Testing** | pytest, pytest-asyncio, respx | Unit + integration tests |

---

## 🚀 Getting Started

### Prerequisites

- **Python 3.12+**
- **Node.js 20+** and npm
- A **Sarvam AI API key** ([get one here](https://dashboard.sarvam.ai/))

### 1. Clone the Repository

```bash
git clone https://github.com/daksha-dev/Prahari-AI.git
cd Prahari-AI
```

### 2. Backend Setup

```bash
cd sentinel-backend

# Create a virtual environment
python -m venv venv

# Activate it
# Windows PowerShell:
.\venv\Scripts\Activate.ps1
# macOS/Linux:
source venv/bin/activate

# Install dependencies
pip install -r requirements.txt

# Configure environment
cp .env.example .env
# Edit .env and add your SARVAM_API_KEY
```

### 3. Frontend Setup

```bash
cd sentinel-frontend

# Install dependencies
npm install

# Configure environment (defaults to localhost:8000)
cp .env.example .env.local
```

### 4. Run Both Servers

**Option A — Use the convenience script (Windows PowerShell):**

```powershell
.\start-dev.ps1
```

**Option B — Run manually in two terminals:**

```bash
# Terminal 1: Backend
cd sentinel-backend
uvicorn app.main:app --reload --host 0.0.0.0 --port 8000

# Terminal 2: Frontend
cd sentinel-frontend
npm run dev
```

### 5. Open the Dashboard

Navigate to **http://localhost:5173** in your browser.

### 6. Verify Everything Works

```powershell
.\smoke-test.ps1    # Checks all API endpoints
.\demo-check.ps1    # Walks through a full demo scenario
```

---

## 📡 API Reference

| Method | Endpoint | Description |
|--------|----------|-------------|
| `GET` | `/healthz` | Health check |
| `GET` | `/api/devices` | List all devices with trust scores |
| `GET` | `/api/devices/{id}` | Device detail (trust history, heatmap, drift, evidence) |
| `GET` | `/api/devices/{id}/evidence` | Latest evidence card for a device |
| `GET` | `/api/network/summary` | Aggregate network health counts |
| `GET` | `/api/alerts` | All alerts (trust drops below threshold) |
| `POST` | `/api/chat` | SSE-streamed AI analyst chat |
| `POST` | `/api/scenario` | Switch simulator scenario (`live`, `slow_drift`, `sudden_ddos`, `recon_scan`) |
| `POST` | `/api/reset` | Reset demo to live scenario |
| `POST` | `/api/ingest` | Ingest real device telemetry |

---

## 🧪 Testing

```bash
cd sentinel-backend
pytest -v
```

Test suite covers:
- Health endpoint
- Device listing and detail APIs
- Ingest pipeline
- ML engine (anomaly scoring, drift detection, trust updates)
- Simulator scenario switching
- Sarvam AI integration (mocked)
- Chat SSE streaming
- Narrator fallback behavior

---

## 🤖 AI Tools & Transparency

### AI Tools Used During Development

| Tool | How It Was Used | What We Modified |
|------|----------------|-----------------|
| **Claude (Anthropic)** | Architecture planning, PRD authoring, debugging async issues, system prompt engineering, README drafting | Heavily customized all generated test cases, fixed edge cases in SSE streaming, rewrote system prompts for 5 Indian languages |
| **Codex (OpenAI)** | FastAPI scaffolding, test suite generation, refactoring | Reviewed and edited every generated function; rewrote ML engine logic, trust scoring algorithm, and tool dispatch from scratch based on our domain understanding |
| **Gemini CLI + ui-ux-pro-max skill** | React component scaffolding, design system generation, Tailwind theming | Refined visual hierarchy, typography, and color palette manually |

### AI in the Product Itself

- **Sarvam AI** is used at runtime for the conversational analyst chat and incident narration
- The AI is given 7 tool functions and autonomously decides which to call based on user queries
- All system prompts were hand-written in 5 languages (English, Hindi, Kannada, Tamil, Telugu)
- The AI never fabricates data — every claim is grounded in tool output from the ML engine

### What We Built vs What AI Helped With

| Component | Built by Team | AI-Assisted |
|-----------|:---:|:---:|
| ML anomaly detection pipeline (Isolation Forest + HST) | ✅ | — |
| Statistical drift detection (ADWIN + Chi² + disagreement) | ✅ | — |
| Trust scoring engine with policy rules | ✅ | — |
| 22-feature network behavioral fingerprint design | ✅ | — |
| Attack pattern classifier | ✅ | — |
| Sarvam AI integration (agentic tool-calling) | ✅ | — |
| System prompts in 5 Indian languages | ✅ | — |
| React dashboard components | ✅ | Boilerplate |
| FastAPI routing/middleware | ✅ | Scaffolding |
| Test suite | ✅ | Initial generation |
| Device simulator with 4 scenarios | ✅ | — |

---

## 📁 Project Structure

```
Prahari-AI/
├── sentinel-backend/           # FastAPI + ML engine
│   ├── app/
│   │   ├── ai/                 # Sarvam AI integration
│   │   │   ├── narrator.py     # Incident narration (multilingual)
│   │   │   ├── sarvam_client.py# Sarvam API wrapper
│   │   │   ├── system_prompts.py# Prompts in 5 languages
│   │   │   └── tools.py        # 7 agentic tool functions
│   │   ├── api/                # REST endpoints
│   │   │   ├── alerts.py
│   │   │   ├── chat.py         # SSE-streamed chat
│   │   │   ├── devices.py
│   │   │   └── ingest.py       # Real device telemetry intake
│   │   ├── engine/             # Core ML pipeline
│   │   │   ├── anomaly_detector.py  # Isolation Forest + HST
│   │   │   ├── drift_detector.py    # ADWIN + Chi² + disagreement
│   │   │   ├── explainability.py    # Evidence cards + z-scores
│   │   │   ├── feature_engineer.py  # 22-feature fingerprint
│   │   │   ├── policy_checker.py    # Hard rule violations
│   │   │   └── trust_engine.py      # Trust scoring (0-100)
│   │   ├── models/             # Pydantic schemas
│   │   ├── simulator/          # Synthetic IoT simulator
│   │   └── store/              # In-memory data store
│   ├── tests/                  # pytest test suite
│   ├── requirements.txt
│   └── .env.example
├── sentinel-frontend/          # React + Vite dashboard
│   ├── src/
│   │   ├── components/         # UI components
│   │   │   ├── AnalystChat.tsx      # AI chat panel
│   │   │   ├── BehavioralHeatmap.tsx # Z-score heatmap
│   │   │   ├── DeviceCard.tsx       # Device trust card
│   │   │   ├── DriftSignalStack.tsx # Drift signal viz
│   │   │   ├── EvidenceCard.tsx     # Evidence breakdown
│   │   │   ├── IntroSequence.tsx    # Animated intro
│   │   │   ├── TrustTimeline.tsx    # Trust score chart
│   │   │   └── TopBar.tsx           # Navigation bar
│   │   ├── pages/
│   │   │   ├── Overview.tsx         # Dashboard home
│   │   │   └── DeviceDetail.tsx     # Per-device deep dive
│   │   └── lib/                # Utilities, API client, types
│   └── package.json
├── archive/                    # Pre-hackathon prototype (gitignored)
├── start-dev.ps1               # Launch both servers
├── smoke-test.ps1              # API endpoint verification
├── demo-check.ps1              # Full demo walkthrough
└── README.md
```

---

## 🔐 Security

- **No API keys in code** — all secrets are loaded from `.env` files
- `.env` and `.env.local` are gitignored
- `.env.example` files contain only placeholder values
- The AI chat never executes remediation actions — it only generates scripts for **human approval**
- CORS is restricted to `localhost:5173` and `*.vercel.app`

---

## 🧑💻 Third-Party APIs & Libraries

| Service / Library | Usage | License |
|-------------------|-------|---------|
| [Sarvam AI](https://www.sarvam.ai/) | Conversational AI analyst + incident narration | Commercial API |
| [scikit-learn](https://scikit-learn.org/) | Isolation Forest anomaly detection | BSD-3 |
| [River](https://riverml.xyz/) | Half-Space Trees (online anomaly) + ADWIN (drift) | BSD-3 |
| [SciPy](https://scipy.org/) | Chi-squared contingency test for drift | BSD-3 |
| [FastAPI](https://fastapi.tiangolo.com/) | Backend REST framework | MIT |
| [React](https://react.dev/) | Frontend UI library | MIT |
| [Recharts](https://recharts.org/) | Data visualization charts | MIT |
| [Framer Motion](https://www.framer.com/motion/) | UI animations | MIT |
| [Tailwind CSS](https://tailwindcss.com/) | Utility-first CSS | MIT |

---

## 👥 Team — The Night's Watch

| Name | Role | Contributions |
|------|------|---------------|
| **R Daksha Subramanya** | ML Lead & Backend | ML pipeline architecture, trust engine design, Sarvam AI integration, FastAPI service layer, system prompt engineering |
| **Sachidanand N C** | Integration & QA | End-to-end integration, deployment configuration, test suite, smoke tests, demo path verification |
| **Vaishnavi J** | Frontend & Dashboard | React dashboard design, component architecture, charts and visualizations, animation work |
| **K Kusuma Komali Priya** | Content & AI Demo | System prompt translations across 5 Indian languages, demo script, content review, AI behavior tuning |

> *All members from IIT Madras*

---

## 📜 License

This project was built for **Vibe-a-thon 2026** at Nitte Meenakshi Institute of Technology. All rights reserved by the team.
