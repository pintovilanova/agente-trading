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

## 2. Execution Pipeline (Chronological Flow)

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
