# Solution Design Document (SDD): Autonomous Trading System

## 1. Architectural Overview

The system operates on a hybrid orchestration model, where **Google Apps Script** acts as the dynamic state manager and data source, while a **Unified GitHub Actions Pipeline** serves as the cloud execution server. The tactical "brain" is powered by the **Google Gemini API**, which enforces configured mathematical and risk management rules, orchestrating data through a fail-safe ephemeral file system.

### Technology Stack

| Component | Technology / Service | System Function |
| :--- | :--- | :--- |
| **Database & UI** | Google Sheets | Stores watchlists, historical logs via the "Diário de Bordo", control panel (Configs), and data visualization. |
| **Data Orchestrator** | Google Apps Script | Serves the active watchlist dynamically via Webhook and manages system state flags. |
| **Market Data (API)** | yfinance / Twelve Data | Provides technical metrics: Price, ADX, RSI, ATR, RVOL, Momentum, and SMA200. |
| **Cloud Engine (CI/CD)** | GitHub Actions | Autonomous unified execution environment (Ubuntu) running both the mathematical engine and the AI agent sequentially. |
| **Processing & AI** | Python 3 + Gemini API | Executes the Math Engine (`v2`) and AI Agent (`git`), utilizing ephemeral local files (`comboio_temp.txt`) for instant, IMAP-free data handoffs. |
| **Security** | GitHub Secrets | Encrypted storage for API keys, email credentials, and webhook URLs. |

---

### Phase 1: Mathematical Engine & Data Extraction (GitHub Actions - Step 1)
*   **07:00 AM - Cloud Awakening:** The unified `.github/workflows/pipeline.yml` workflow is triggered.
*   **07:01 AM - Watchlist Ingestion & Veto:** The `agente_trading_v2.py` script pulls the daily watchlist from Google Sheets via Webhook. It immediately checks the SPY Macro Filter (SMA200 and crash thresholds) to authorize or veto the daily run.
*   **07:02 AM - Calculation & Ephemeral Storage:** The script calculates ATR, Distance to SMA20, Momentum, RVOL, RSI, and ADX. It processes the mathematical targets (Stop Loss, Take-Profit, Trailing) and writes the resulting data "train" into a local ephemeral file (`comboio_temp.txt`) on the GitHub runner. A backup copy is emailed to the user for historical auditing.

### Phase 2: Artificial Intelligence & Execution (GitHub Actions - Step 2)
*   **07:03 AM - Zero-Latency Handoff:** The `agente_trading_git.py` script starts on the exact same virtual machine. It instantly reads `comboio_temp.txt`, entirely bypassing external IMAP server connections and potential network blocks. (IMAP remains strictly as a local-PC fallback).
*   **07:04 AM - Gemini Processing:** The AI processes the data string following blind parametric rules (zero fundamental bias). 
*   **07:05 AM - Report Delivery:** The system dispatches the final, formatted tactical report to the user's email, highlighting the top 3 setups with their exact mathematical targets.

### Phase 3: Intraday Monitoring (Surgical Trigger)
*   **03:30 PM - Open Market Evaluation:** Scheduled Apps Script triggers perform a quick ping to check for high volume breakouts and update the `Diário de Bordo` tab with the Intraday status.

---

## 2. Business Logic & Risk Management (Math.Max Matrix)

The core of the system is built on a rigid capital preservation algorithm, where the AI acts strictly as an advanced calculator for predefined parameters.

*   **Qualification Filters (Mandatory):**
    *   Price action above the SMA200 (SPY Macro Filter).
    *   ADX > 25 (Strong trend).
    *   RVOL > 1.0 (Volume anomaly / institutional interest).
    *   RSI between 50 and 68 (Bullish momentum without being overbought).

*   **Exclusion Filters (Guillotine):**
    *   Severely negative Momentum (e.g., < -3.00). Automatically rejects "falling knives".
    *   RSI > 70. Rejects overbought assets at risk of imminent correction.
    *   RVOL > 2.0. Rejects volume climaxes and potential institutional dumping.

*   **Risk Ratio & Mathematical Targets:**
    *   Unit Risk = Entry Price - Stop Loss (calculated via ATR multiplier).
    *   `Take-Profit = Entry + (Unit Risk * 1.2)`
    *   `Break-Even = Entry + ((Take-Profit - Entry) / 2)`

*   **Trailing Stop (The Law of Risk):**
    *   Implements the formula `Math.max(Calculated Trailing, Previous Trailing)`. Ensures that the Stop Loss mechanically follows the price and never retreats, locking in profits as the trend advances.

---

## 3. Resilience & Fault Tolerance (Error Handling)

The architecture is designed to be fault-tolerant across four critical vectors:

1.  **IMAP & Network Block Bypass (Hybrid Handoff):** To prevent cloud-server IMAP timeouts or Google security blocks, the system passes data between the mathematical engine and the AI agent using a localized ephemeral file (`comboio_temp.txt`). External email fetching is retained solely as an automatic fallback for manual local executions.
2.  **AI Traffic Spikes & Rate Limits (503/429 Errors):** The AI agent utilizes a robust `try/except` block with an exponential backoff algorithm (Tenacity style). If the Gemini API hits rate limits or server overload, it retries up to 10 times, escalating wait periods up to a maximum of 300 seconds (5 minutes) per attempt.
3.  **Data API Limits:** Dynamic delays and error handling ensure that third-party financial data providers (like yfinance/Twelve Data) do not block the IP address due to high-frequency polling.
4.  **Cloud Scheduling Protection (Cron Jobs):** To prevent private repositories from pausing automated schedules due to inactivity (the 60-day rule), the integrated CI/CD workflow guarantees daily continuity perfectly aligned with the morning delivery window.

---

## 4. Execution Pipeline (Chronological Flow)

```mermaid
sequenceDiagram
    autonumber
    participant Sheets as Google Sheets
    participant GH as GitHub Actions (Ubuntu)
    participant Phase1 as Math Engine<br/>(agente_trading_v2.py)
    participant Phase2 as AI Agent<br/>(agente_trading_git.py)
    participant AI as Gemini API

    GH->>Phase1: Trigger Unified Workflow (Pass 1)
    Phase1->>Sheets: Fetch Watchlist via Webhook
    Phase1->>Phase1: Calculate Indicators & Targets
    Phase1->>GH: Write comboio_temp.txt (Ephemeral File)
    Phase1-->>User Email: Send historical backup email
    GH->>Phase2: Trigger Unified Workflow (Pass 2)
    Phase2->>GH: Read comboio_temp.txt (Bypass IMAP)
    Phase2->>AI: Send Prompt + Asset Data
    
    alt Normal Execution
        AI-->>Phase2: Returns top 3 asset selection
    else API Rate Limit / Spike (Error 429 / 503)
        AI--xPhase2: Response Failure
        Note over Phase2,AI: Exponential Backoff Retry (Max 10x)<br/>Waits 15s, 30s, 60s... up to 300s
        Phase2->>AI: Retries analysis
        AI-->>Phase2: Returns top 3 asset selection
    end
    
    Phase2->>User Email: Dispatch Final Tactical Report
