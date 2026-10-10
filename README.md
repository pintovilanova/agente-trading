# 🦅 Predador de Breakouts, Squeeze & Trend Following: Autonomous Trading Ecosystem

> **Solution Design Document (SDD)** — Autonomous institutional-grade trading ecosystem combining modular Python mathematical engines, cloud CI/CD execution via GitHub Actions, dynamic Google Sheets dashboard state management, and Google Gemini AI risk validation.

---

## 1. Architectural Overview

The system operates on a hybrid orchestration model, where **Google Apps Script** acts as the dynamic state manager and data source, while a **Unified GitHub Actions Pipeline** serves as the cloud execution server. The tactical "brain" is powered by the **Google Gemini API**, which enforces configured mathematical and risk management rules, orchestrating data through a fail-safe ephemeral file system.

### Technology Stack

| Component | Technology / Service | System Function |
| :--- | :--- | :--- |
| **Database & UI** | Google Sheets | Stores watchlists, historical logs via the "Diário de Bordo", state flags (`ATIVA_FAST`, `WIN`, `LOSS`), and control panels. |
| **Data Orchestrator** | Google Apps Script | Serves the active watchlists and active positions dynamically via Webhook and manages state transitions. |
| **Market Data (API)** | yfinance / Twelve Data | Provides technical metrics: Price, EMA, SMA, BBW, ADX, RSI, ATR, and RVOL. |
| **Cloud Engine (CI/CD)** | GitHub Actions | Autonomous unified execution environment (Ubuntu) running both the mathematical engines and the AI agent sequentially. |
| **Processing & AI** | Python 3 + Gemini API | Executes the Math Engines (`06_motor_fast_trend_carver.py`, `07_motor_vcp_breakout.py`, etc.) and AI Agent (`02_agente_gemini.py`), utilizing ephemeral local files (`comboio_carver_temp.txt`, `comboio_vcp_temp.txt`) for instant data handoffs. |
| **Security** | GitHub Secrets | Encrypted storage for API keys, email credentials, and webhook URLs. |

---

## 2. Execution Phases

### Phase 1: Mathematical Engine & Data Extraction (GitHub Actions - Step 1)
- **Post-Market Cloud Awakening:** Scheduled workflows are triggered automatically right after the US market close (or manually on demand).
- **Multi-Engine Specialization:** The system runs distinct specialized scripts (e.g., `06_motor_fast_trend_carver.py` for momentum trend following and `07_motor_vcp_breakout.py` for volatility compression/Squeeze).
- **Watchlist & State Ingestion:** The script pulls the daily watchlist and active positions (`ATIVA_FAST`) from Google Sheets via Webhook.
- **Calculation & Ephemeral Storage:** The script computes indicators (EMA 8/32, ATR 36, BBW, Volume SMA), evaluates dynamic multipliers, risk targets, or Trailing Stops, and writes the output train to local ephemeral files (`.txt`).
- **Data Integrity Protocol:** Active data cleaning sanitizes corrupt API math values, ensuring 100% JSON and string compliance before pushing logs.

### Phase 2: Artificial Intelligence & Execution (GitHub Actions - Step 2)
- **Zero-Latency Handoff:** The AI agent script starts immediately on the same virtual runner, reading ephemeral text files directly and bypassing external IMAP network restrictions.
- **Gemini Processing (Strict Mode):** The AI acts as the ultimate Risk Manager and Tactical Auditor, evaluating setups against institutional parameters. For Squeeze models, it enforces strict `Buy Stop` execution rules and structural Stop Losses.
- **State Transition Reminders:** The AI appends mandatory operational reminders to the reports, reminding the trader to update Google Sheets states to `ATIVA_FAST` upon trade execution, and `WIN`/`LOSS` upon trade closure for statistical tracking.
- **Report Delivery:** The system dispatches the final tactical report via email with customized subject flags (e.g., `🗜️ IA Predador: Relatório VCP Breakout Squeeze 🎯` or `🏄‍♂️ IA Predador: Relatório Carver Fast Trend 🚀`).

---

## 3. Business Logic & Risk Management (Math.Max Matrix)

The core of the system is built on a rigid capital preservation algorithm where mathematical engines identify high-probability setups and the AI validates institutional commitment.

- **Core Trading Engines:**
  - **Motor 06 (Fast Trend / Carver):** Focuses on long-term momentum using inertia (`Price > EMA8 > EMA32`) and daily ATR-based Trailing Stops with strict unidirectionality (stops never step down).
  - **Motor 07 (VCP / Breakout):** Focuses on volatility compression (BBW Squeeze + Volume Dry-up) for surgical entries via pending `Buy Stop` orders.

- **Dynamic Profit & Risk Management:**
  - **Volatility Parity:** Position sizing proportional to account volatility targets and forecast strength.
  - **Micro Risk:** Initial stop loss anchored firmly below consolidation structures (e.g., 5-day box low or 1.5x ATR).
  - **State Lifecycle:** `VCP_PENDING` (armed order) $\rightarrow$ `ATIVA_FAST` (open position under Carver management) $\rightarrow$ `WIN` / `LOSS` (closed for post-trade statistics).

---

## 4. Resilience & Fault Tolerance (Error Handling)

1. **AI Traffic Spikes & Model Fallback (503/429 Errors):** The AI agent utilizes a robust `try/except` block with an exponential backoff algorithm. If the primary model (`gemini-3.6-flash`) hits a quota limit (Error 429) or server overload (Error 503), the system automatically downgrades to the fallback model (`gemini-3.8-flash`) to guarantee tactical report delivery.
2. **IMAP & Network Block Bypass (Hybrid Handoff):** Data passing between mathematical engines and the AI agent occurs via localized ephemeral files, preventing cloud-server IMAP timeouts.
3. **Cloud Scheduling Protection (Cron Jobs):** Integrated CI/CD workflows guarantee daily continuity aligned perfectly with market trading calendars.

---

## 5. Execution Pipeline (Chronological Flow)

```mermaid
sequenceDiagram
    autonumber
    participant Sheets as Google Sheets
    participant GH as GitHub Actions (Ubuntu)
    participant Phase1 as Math Engines<br/>(06_motor_fast_trend / 07_motor_vcp)
    participant Phase2 as AI Agent / Dispatcher
    participant AI as Gemini API

    GH->>Phase1: Trigger Workflow (Post-Market Schedule / Manual)
    Phase1->>Sheets: Fetch Watchlists & Active Positions via Webhook
    Phase1->>Phase1: Calculate Indicators, ATR, BBW & State Flags
    Phase1->>GH: Write comboio_*_temp.txt (Ephemeral)
    Phase1-->>User Email: Send raw historical backup / Prompt
    GH->>Phase2: Trigger AI / Report Delivery
    Phase2->>GH: Read ephemeral text files (Bypass IMAP)
    Phase2->>AI: Send Prompt + Asset Data + State Instructions
    
    alt Primary Model Execution (Gemini 3.6 Flash)
        AI-->>Phase2: Returns audited tactical report
    else Quota Exceeded / Server Full (Error 429 / 503)
        AI--xPhase2: Response Failure
        Note over Phase2,AI: Exponential Backoff & Fallback Switch
        Phase2->>AI: Fallback to Contingency Model (Gemini 3.8 Flash)
        AI-->>Phase2: Returns audited tactical report
    end
    
    Phase2->>User Email: Dispatch Final Tactical Report (with State Reminders)
