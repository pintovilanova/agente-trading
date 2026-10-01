# Solution Design Document (SDD): Autonomous Trading System ("Predador de Breakouts")

## 1. Architectural Overview

The system operates on a hybrid orchestration model, where **Google Apps Script** acts as the dynamic state manager and data source, while a **Unified GitHub Actions Pipeline** serves as the cloud execution server. The tactical "brain" is powered by the **Google Gemini API**, which enforces configured mathematical and risk management rules, orchestrating data through a fail-safe ephemeral file system.

### Technology Stack

| Component | Technology / Service | System Function |
| :--- | :--- | :--- |
| **Database & UI** | Google Sheets | Stores watchlists, historical logs via the "Diário de Bordo", control panel (Configs), and data visualization. |
| **Data Orchestrator** | Google Apps Script | Serves the active watchlists (US and EU) dynamically via Webhook and manages system state flags. |
| **Market Data (API)** | yfinance / Twelve Data | Provides technical metrics: Price, ADX, RSI, ATR, RVOL, Momentum, and SMA200. |
| **Cloud Engine (CI/CD)** | GitHub Actions | Autonomous unified execution environment (Ubuntu) running both the mathematical engines and the AI agent sequentially. |
| **Processing & AI** | Python 3 + Gemini API | Executes the Math Engines (`01_extrator_us.py`, `01_extrator_europa.py`) and AI Agent (`02_agente_gemini.py`), utilizing ephemeral local files (`comboio_us.txt`, `comboio_europa.txt`) for instant data handoffs. |
| **Security** | GitHub Secrets | Encrypted storage for API keys, email credentials, and webhook URLs. |

---

## 2. Execution Phases

### Phase 1: Mathematical Engine & Data Extraction (GitHub Actions - Step 1)
* **04:30 AM (US) / 08:30 AM (EU) - Cloud Awakening:** The scheduled workflows are triggered.
* **Market Separation:** The system uses dedicated scripts (`01_extrator_us.py` and `01_extrator_europa.py`) to handle specific market hours and distinct watchlists.
* **Watchlist Ingestion & Veto:** The script pulls the daily watchlist from Google Sheets via Webhook. It immediately checks the SPY Macro Filter (SMA200 and crash thresholds) to authorize or veto the daily run.
* **Calculation & Ephemeral Storage:** The script calculates ATR, Distance to SMA20, Momentum, RVOL, RSI, and ADX. It processes the mathematical targets (Stop Loss, Take-Profit, Trailing) and writes the resulting data "train" into local ephemeral files on the GitHub runner. A backup copy is emailed to the user for historical auditing.
* **Data Integrity Protocol:** An active filter (`dropna`) drops "ghost days" from pre-market polling, and an `anti-NaN` function sanitizes corrupt API math values, ensuring 100% JSON compliance before pushing to Google Sheets.

### Phase 2: Artificial Intelligence & Execution (GitHub Actions - Step 2)
* **Zero-Latency Handoff:** The `02_agente_gemini.py` script starts on the exact same virtual machine. It instantly reads the ephemeral text files, entirely bypassing external IMAP server connections and potential network blocks. (IMAP remains strictly as a local-PC fallback).
* **Gemini Processing (Strict Mode):** The AI acts as the ultimate Risk Manager. It evaluates the "train" data against strict parametric rules (zero fundamental bias). If the overall market lacks volume (RVOL) or trend strength (ADX), the AI applies the **Guillotine** and vetoes all trades, issuing a `[MERCADO ESTAGNADO - POSTURA DEFENSIVA]` alert.
* **Report Delivery:** If high-probability setups exist, the system dispatches the final, formatted tactical report highlighting the top 3 assets, their exact mathematical targets, flags (e.g., Earnings danger, Compression potential), and dynamic profit-management rules (Fixed TP vs. Trailing).

---

## 3. Business Logic & Risk Management (Math.Max Matrix)

The core of the system is built on a rigid capital preservation algorithm. The mathematical engine identifies anomalies, and the AI validates institutional commitment.

* **Qualification Filters (Mandatory):**
  * Price action above the SMA200 (SPY Macro Filter).
  * ADX > 25 (Strong trend).
  * RVOL > 1.0 (Volume anomaly / institutional interest).
  * RSI between 50 and 75 (Bullish momentum without being critically overbought).

* **Exclusion Filters (The AI Guillotine):**
  * **Earnings Danger:** Assets reporting earnings within 3 days are sumariamente rejected.
  * **Market Context Veto:** If the majority of the watchlist exhibits ADX < 25 and low RVOL, the AI assumes a choppy environment and blocks all trades to protect capital.
  * **Erratic Assets:** If the Volatility percentage (ATR vs. Price) exceeds 5%, the system flags the asset as high risk.

* **Risk Ratio & Mathematical Targets:**
  * Unit Risk = Entry Price - Stop Loss (calculated via ATR multiplier, safeguarded by the SMA20 Shield).
  * `Take-Profit = Entry + (Unit Risk * 1.2)`
  * `Break-Even = Entry + ((Take-Profit - Entry) / 2)`

* **Dynamic Profit Management (AI Ruleset):**
  * If ADX > 35: "[TENDÊNCIA EXTREMA] Ignora TP, gere pelo Trailing."
  * If ADX < 30: "[TENDÊNCIA MODERADA] Respeita o TP fixo."

---

## 4. Resilience & Fault Tolerance (Error Handling)

The architecture is designed to be fault-tolerant across multiple critical vectors:

1. **AI Traffic Spikes & Model Fallback (503/429 Errors):** The AI agent utilizes a robust `try/except` block with an exponential backoff algorithm. If the primary VIP model (`gemini-3.6-flash`) hits its strict daily free-tier quota (Error 429) or experiences server overload (Error 503), the system automatically downgrades to the high-availability fallback model (`gemini-2.5-flash`) to guarantee the tactical report delivery without interruption.
2. **IMAP & Network Block Bypass (Hybrid Handoff):** To prevent cloud-server IMAP timeouts or Google security blocks, data passing between the mathematical engines and the AI agent occurs via localized ephemeral files.
3. **JSON Payload Sanitization:** The `limpa()` function guarantees that missing market data (`NaN` or `np.float64(nan)`) is caught and converted to `"N/A"`, preventing critical communication crashes with the Google Sheets API.
4. **Cloud Scheduling Protection (Cron Jobs):** Integrated CI/CD workflows guarantee daily continuity perfectly aligned with morning delivery windows, preventing private repositories from pausing automated schedules due to inactivity.

---

## 5. Execution Pipeline (Chronological Flow)

```mermaid
sequenceDiagram
    autonumber
    participant Sheets as Google Sheets
    participant GH as GitHub Actions (Ubuntu)
    participant Phase1 as Math Engines<br/>(01_extrator_*)
    participant Phase2 as AI Agent<br/>(02_agente_gemini.py)
    participant AI as Gemini API

    GH->>Phase1: Trigger Workflow (Market Open)
    Phase1->>Sheets: Fetch EU/US Watchlists via Webhook
    Phase1->>Phase1: Drop Ghost Days & Sanitize Data (Anti-NaN)
    Phase1->>Phase1: Calculate Indicators & Risk Targets
    Phase1->>Sheets: Push Clean Data Array to UI
    Phase1->>GH: Write comboio_temp.txt (Ephemeral)
    Phase1-->>User Email: Send raw historical backup
    GH->>Phase2: Trigger AI Engine
    Phase2->>GH: Read comboio_temp.txt (Bypass IMAP)
    Phase2->>AI: Send Prompt + Asset Data
    
    alt VIP Model Execution (Gemini 3.6)
        AI-->>Phase2: Returns tactical selection or Defense Veto
    else Quota Exceeded / Server Full (Error 429 / 503)
        AI--xPhase2: Response Failure
        Note over Phase2,AI: Exponential Backoff & Tactic Switch
        Phase2->>AI: Fallback to High-Availability Model (Gemini 2.5)
        AI-->>Phase2: Returns tactical selection or Defense Veto
    end
    
    Phase2->>User Email: Dispatch Final "Predador" Report
