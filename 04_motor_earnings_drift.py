# ===================================================================
# SISTEMA DE TRADING INSTITUCIONAL - MOTOR DE EARNINGS DRIFT (PEAD)
# ===================================================================
# Descrição Geral:
# Este script opera como um "Caçador de Anomalias Pós-Resultados" (PEAD). 
# O seu objetivo é detetar empresas da Watchlist que reportaram lucros trimestrais 
# recentes e dispararam com volume institucional massivo, antecipando o 
# fenómeno de desvio continuado (drift) na revisão de lucros pelos analistas.
#
# Pilares Técnicos e Arquitetura:
# 1. Travas de Segurança e Calendário:
#    - Trava de Fim de Semana: Interrompe a execução automaticamente aos 
#      sábados e domingos para salvaguardar recursos na nuvem.
# 2. Deteção de Catalisadores Temporais (Earnings Window):
#    - Varredura de dados históricos de resultados (`earnings_dates`) para 
#      identificar ativos que reportaram nos últimos 0 a 5 dias úteis.
# 3. Filtros de Momentum e Volume Institucional:
#    - Validação de arranque explosivo pós-earnings: Variação diária positiva 
#      superior ou igual a 2.0% em conjugação com Volume Relativo (RVOL) >= 2.0.
# 4. Gestão de Risco assimétrica (Rácio 2:1) com Método Carver:
#    - Stop Loss físico posicionado a 1% abaixo do mínimo da vela de arranque.
#    - Take-Profit fixo projetado com um rácio de recompensa 2:1 face ao risco.
#    - Alocação de risco controlada pelo ATR e Orçamento de Volatilidade da Conta.
# 5. Integração Cloud & LLM:
#    - Atualização automatizada da aba "Earnings Drift" no Google Sheets via Webhook.
#    - Envio de relatório formatado ("Comboio PEAD") por email para auditoria por IA.
# ===================================================================

import pandas as pd
import yfinance as yf
import pandas_ta as ta
import numpy as np
from datetime import datetime, date, timedelta
from zoneinfo import ZoneInfo
import sys
import os
import requests
import json
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart

# ===================================================================
# 0. TRAVA DE FIM DE SEMANA
# ===================================================================
dia_da_semana = datetime.now(ZoneInfo("Europe/Lisbon")).weekday()
if dia_da_semana >= 5:
    print("[INFO] Fim de semana detetado. O mercado está fechado. O Motor de Earnings vai descansar.")
    sys.exit(0)

# ===================================================================
# 1. CONFIGURAÇÕES E CREDENCIAIS (GitHub Secrets)
# ===================================================================
WEBHOOK_URL = os.environ.get('WEBHOOK_URL')
EMAIL_USER = os.environ.get("EMAIL_USER")
EMAIL_PASS = os.environ.get("EMAIL_PASS")

SMTP_SERVER = "smtp.gmail.com"
SMTP_PORT = 587

# ===================================================================
# CONFIGURAÇÕES DE RISCO INSTITUCIONAL (MÉTODO CARVER)
# ===================================================================
CAPITAL_TOTAL_CONTA = 10400.00  # Capital atualizado da conta
ALVO_VOLATILIDADE_ANUAL = 0.05  # Alvo de 5% ao ano de flutuação (Conservador)

# Orçamento diário de volatilidade do Carver (constante 16 para raiz de 256 dias úteis)
VOLATILIDADE_ALVO_DIARIA_USD = (CAPITAL_TOTAL_CONTA * ALVO_VOLATILIDADE_ANUAL) / 16.0 

# ===================================================================
# 2. FUNÇÕES DE REDE (Google Sheets e Email)
# ===================================================================
def buscar_watchlist():
    print("A carregar a Watchlist a partir do Google Sheets...")
    if not WEBHOOK_URL: 
        print("[ERRO] WEBHOOK_URL não configurado.")
        return []
    try:
        resp = requests.get(WEBHOOK_URL)
        if resp.status_code == 200:
            dados = resp.json()
            ativos = dados.get("ativos", []) if isinstance(dados, dict) else dados
            print(f"[SUCESSO] {len(ativos)} ativos carregados para auditoria de Earnings.")
            return ativos
        else:
            print(f
