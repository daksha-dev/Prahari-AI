---
marp: true
theme: default
class: lead
backgroundColor: #111827
color: #F9FAFB
---

# 🛡️ Prahari AI
**Intelligent IoT Network Trust & Anomaly Monitoring**
*Powered by Sarvam AI*

Vibe-a-thon 2026 · Track: AI and Automation
Team: The Night's Watch (IIT Madras)

---

## 📌 The Problem
- **Blind Spots:** Consumers deploy dozens of smart devices with zero visibility into their behavior.
- **Gradual Compromise:** Botnets like Mirai take over devices slowly (drift), not instantly.
- **Alert Fatigue:** Existing firewalls flag packets, leaving analysts to parse logs for 20+ minutes.

---

## 💡 The Solution: Prahari AI
Prahari AI is a continuous behavioral monitoring and autonomous response system.
- Profiles every device and assigns a **0-100 Trust Score**.
- Detects **behavioral drift** in real time (using online Machine Learning).
- Includes an **Agentic AI Analyst** (powered by Sarvam) to narrate, investigate, and remediate in 5 Indian languages.

---

## 🛠️ Architecture & Tech Stack
- **Backend Engine:** FastAPI (Python), handling real-time telemetry.
- **Machine Learning:** 
  - *Anomaly:* Isolation Forest & River Half-Space Trees
  - *Drift:* ADWIN & Chi-Squared test across 22 network features
- **AI Agent:** Sarvam AI (`sarvam-m`) with 7 autonomous tool functions.
- **Frontend:** React 19 + Vite, Tailwind CSS, Recharts for dynamic heatmaps.

---

## 🚀 Key Features
1. **Trust Engine:** Strict policies penalize risky behavior quadratically.
2. **Explainability:** Generates z-score heatmaps and plain-text evidence cards.
3. **Multilingual Analyst:** English, Hindi, Kannada, Tamil, Telugu support.
4. **Data Sovereignty:** Sarvam on Indian infra keeps telemetry domestic (DPDP/CERT-In compliant).
5. **Interactive Dashboard:** Live telemetry injection and 4 built-in threat scenarios.

---

## 📊 The "Slow Drift" Threat Scenario
- **Normal:** Smart Thermostat communicates with cloud API.
- **Drift Starts:** Slight increase in internal connection attempts and packet entropy.
- **Detection:** ADWIN flags concept drift, Isolation Forest scores drop.
- **Action:** Trust score decays gracefully, moving from NORMAL to AT_RISK, finally CRITICAL.

---

## 👥 The Team
- **R Daksha Subramanya:** ML Lead & Backend
- **Sachidanand N C:** Integration & QA
- **Vaishnavi J:** Frontend & Dashboard
- **K Kusuma Komali Priya:** Content & AI Demo

**Thank You!** Check out our live demo at the booth.
