# Solution Design Document (SDD): Autonomous Trading System

## 1. Architectural Overview

The system operates on a hybrid orchestration model, where **Google Apps Script** acts as the data extraction engine and state manager, while **GitHub Actions** serves as the cloud execution server (cron scheduling and heavy processing). The tactical "brain" is powered by the **Google Gemini API**, which enforces the configured mathematical and risk management rules.

### Technology Stack

| Component | Technology / Service | System Function |
| :--- | :--- | :--- |
| **Database & UI** | Google Sheets | Stores watchlists, historical logs via the "Diário de Bordo", control panel (Configs), and data visualization. |
| **Data Orchestrator** | Google Apps Script | Handles price/indicator extraction, state management via flags, and time-driven triggers. |
| **Market Data (API)** | Twelve Data & Yahoo Finance | Provides technical metrics: Price, ADX, RSI, ATR, RVOL, Momentum, and SMA200. |
| **Cloud Engine (CI/CD)** | GitHub Actions | Autonomous execution of the Python script in a virtualized Ubuntu environment, removing local hardware dependencies. |
| **Processing & AI** | Python 3 + Gemini API | Executes `agente_trading_git.py`, filters setups, calculates exact mathematical targets, and dispatches the final email report. |
| **Security** | GitHub Secrets | Encrypted storage for API keys, email credentials, and institutional access tokens. |

---
### Phase 1: Data Cleansing & Extraction (Apps Script)
*   **01:00 AM - State Reset:** The system clears all control checkboxes in the `Analise Compra` sheet to prevent duplicate processing.
*   **01:05 to 01:08 AM - Flag Activation:** Global configuration variables (`processarLoteItems_Short`, `processarTudo`, `enviarRelatorioIA`) are activated in the `Configs` tab.
*   **01:15 AM - Batch Extraction Engine:** The watchlist sweep (~160 assets) begins. The script makes calls to the Twelve Data API using an API Key rotation system to bypass volume blocks. ATR, Distance to SMA20, Momentum, RVOL, RSI, and ADX are calculated in real-time.
*   **05:30 AM - Consolidation & Dispatch:** Validated data is compiled into a standardized text format (the data "train") and sent via email to the system's inbox, bundled with the strict system prompt.
*   **06:00 AM - Apps Script Cycle Closure:** Configuration flags are reset to `false`.

### Phase 2: Artificial Intelligence & Execution (GitHub Actions)
*   **07:00 AM - Cloud Awakening:** The `.github/workflows/agente.yml` workflow is triggered by the internal GitHub UTC clock.
*   **07:01 AM - Gemini Processing:** The Python script reads the aggregated data received via email. The AI processes the triage following blind parametric rules (zero fundamental bias).
*   **07:02 AM - Report Delivery:** The system dispatches the final, perfectly formatted tactical report to the user's email. This includes the top 3 daily setups with exact calculations for Take-Profit, Stop Loss, Break-Even, and Position Sizing, appending the original data strings for auditing purposes.

### Phase 3: Intraday Monitoring (Surgical Trigger)
*   **08:00 AM - Preparation:** Apps Script dynamically schedules the afternoon trigger.
*   **03:30 PM - Open Market Evaluation:** The system performs a quick ping via the Yahoo Finance API to check for high breakouts and updates the `Diário de Bordo` tab with the Intraday status.

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

The architecture is designed to be fault-tolerant across three critical vectors:

1.  **Data API Rate Limits:** The Apps Script incorporates a dynamic delay (`Utilities.sleep(15000)`) between batches of 20 assets and supports automatic rotation of multiple Twelve Data keys. If a key hits its daily quota, the loop silently jumps to the next one.
2.  **AI Traffic Spikes (503 Unavailable Error):** The `agente_trading_git.py` script contains a `try/except` block wrapped in a `for` loop, powered by a Tenacity-style exponential backoff algorithm. If the API servers reject the request due to high demand, the system logs the failure and retries up to 10 times, escalating wait periods up to a maximum of 300 seconds (5 minutes) per attempt.
3.  **Cloud Scheduling Protection (Cron Jobs):** To prevent private repositories from pausing automated schedules due to inactivity (the 60-day rule), the commit cycle and manual/automated executions guarantee daily continuity. The infrastructure relies on the robust UTC time zone (`0 7 * * *`), perfectly aligned with the target morning delivery window.

## 4. Execution Pipeline (Chronological Flow)

The system's lifecycle is designed to bypass API rate limits and ensure that US market closing data is fully consolidated prior to analysis. The flow is divided into two main phases: **Nightly Processing** and **Morning Analysis**.

```mermaid
sequenceDiagram
    autonumber
    participant Sheets as Google Sheets
    participant GAS as Google Apps Script
    participant GH as GitHub Actions
    participant Py as Python Script<br/>(agente_trading_git.py)
    participant AI as Gemini AI<br/>(gemini-3.6-flash)

    Sheets->>GAS: Generate Data "Train" (Technical Indicators)
    GAS->>GH: POST API (workflow_dispatch)
    GH-->>GAS: 204 No Content (Trigger Activated)
    
    Note over GH: Starts Runner (ubuntu-latest)
    GH->>Py: Executes agente_trading_git.py
    
    Py->>Py: Applies strict filters & prepares Prompt
    Py->>AI: Sends data for tactical analysis
    
    alt Normal Execution
        AI-->>Py: Returns top 3 asset selection
    else Traffic Spike (Error 503 / 429)
        AI--xPy: Response Failure
        Note over Py,AI: Tenacity triggers (Exponential Backoff)<br/>Waits 15s, 30s, 60s... up to 300s (Max 10 attempts)
        Py->>AI: Retries analysis
        AI-->>Py: Returns top 3 asset selection
    end
    
    Py->>Py: Formats Daily Tactical Report
    Py->>GH: Final Output (Logs & Email Dispatch)

