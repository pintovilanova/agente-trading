# ===================================================================
# SISTEMA DE TRADING INSTITUCIONAL - MOTOR DE REVERSÃO À MÉDIA (PÂNICO)
# ===================================================================
# Descrição Geral:
# Este script opera como um "Predador de Pânico" (Mean Reversion). O seu 
# objetivo não é caçar tendências, mas sim identificar quedas massivas e 
# anomalias estatísticas em ativos da Watchlist, acionando entradas cirúrgicas 
# para ressaltos rápidos ("Dead Cat Bounce" / Estratégia Hit & Run).
#
# Pilares Técnicos e Arquitetura:
# 1. Filtros de Segurança Estrutural (Anti-Lixo):
#    - Rejeição automática de Penny Stocks (Preço < 3.00 USD).
#    - Exclusão estrita do setor imobiliário / REITs / mREITs.
# 2. Gatilhos de Pânico Extremo (O Confluente):
#    - Distância à SMA20 inferior ou igual a -8.0%.
#    - RSI de 14 períodos em sobrevenda extrema (< 30).
#    - Confirmação institucional por Volume Relativo (RVOL >= 1.5) 
#      OU padrão de vela de Absorção (Sombra inferior > 1.5x o corpo).
# 3. Gestão de Risco Institucional (Método Carver - Target Volatility):
#    - Orçamento de flutuação diária calculado com base na volatilidade 
#      anual alvo lida da tab 'Configs' do Google Sheets.
#    - Dimensionamento de posições baseado no ATR (Average True Range) 
#      para nivelar o risco real por ativo.
# 4. Execução e Saída (Hit & Run):
#    - Stop Loss físico cravado a 1% abaixo do mínimo do dia de pânico.
#    - Validação matemática de Rácio Risco/Recompensa (Recompensa >= Risco).
#    - Alvo de Take-Profit fixo e cravado estritamente na EMA9 (sem trailing).
# ===================================================================

import pandas as pd
import yfinance as yf
import pandas_ta as ta  # <-- Importação explícita obrigatória para registar os métodos .ta
import numpy as np
from datetime import datetime
from zoneinfo import ZoneInfo
import sys
import os
import requests
import json
import smtplib
import time
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart

# ===================================================================
# 0. TRAVA DE FIM DE SEMANA
# ===================================================================
dia_da_semana = datetime.now(ZoneInfo("Europe/Lisbon")).weekday()
if dia_da_semana >= 5:
    print("[INFO] Fim de semana detetado. O mercado está fechado. O Agente de Reversão vai descansar.")
    #sys.exit(0)

# ===================================================================
# 1. CONFIGURAÇÕES E CREDENCIAIS (GitHub Secrets)
# ===================================================================
WEBHOOK_URL = os.environ.get('WEBHOOK_URL')
EMAIL_USER = os.environ.get("EMAIL_USER")
EMAIL_PASS = os.environ.get("EMAIL_PASS")

SMTP_SERVER = "smtp.gmail.com"
SMTP_PORT = 587

# ===================================================================
# 2. FUNÇÕES DE REDE
# ===================================================================
def buscar_watchlist():
    print("A carregar a Watchlist e Configurações a partir do Google Sheets...")
    if not WEBHOOK_URL: 
        print("[ERRO] WEBHOOK_URL não configurado.")
        return [], {}
    try:
        resp = requests.get(WEBHOOK_URL)
        if resp.status_code == 200:
            dados = resp.json()
            if isinstance(dados, dict):
                ativos = dados.get("ativos", [])
                configs = dados.get("configs", {})
            elif isinstance(dados, list):
                ativos = dados
                configs = {}
            else:
                ativos = []
                configs = {}
                
            print(f"[SUCESSO] {len(ativos)} ativos carregados para monitorização de pânico.")
            return ativos, configs
        else:
            print(f"[ERRO] Falha ao descarregar dados: {resp.status_code}")
            return [], {}
    except Exception as e:
        print(f"[ERRO CRÍTICO] Falha de comunicação com Sheets: {e}")
        return [], {}

def enviar_email(conteudo):
    print("\nA enviar email de Reversão para o Agente IA...")
    if not EMAIL_USER or not EMAIL_PASS:
        print("[AVISO] Credenciais de email em falta. A saltar envio.")
        return

    msg = MIMEMultipart()
    msg['From'] = EMAIL_USER
    msg['To'] = EMAIL_USER
    msg['Subject'] = "🚨 tradingRelatorioIA US - PÂNICO E REVERSÃO ⚡"
    
    msg.attach(MIMEText(conteudo, 'plain', 'utf-8'))
    
    # Sistema de Tolerância a Falhas (Retry) com Timeout
    max_tentativas = 3
    for tentativa in range(max_tentativas):
        try:
            # Adicionado timeout de 15 segundos para evitar timeouts do servidor
            server = smtplib.SMTP(SMTP_SERVER, SMTP_PORT, timeout=15)
            server.starttls()
            server.login(EMAIL_USER, EMAIL_PASS)
            server.sendmail(EMAIL_USER, EMAIL_USER, msg.as_string())
            server.quit()
            
            print(f"[SUCESSO] Email enviado na tentativa {tentativa + 1}! O Agente IA tem novos alvos para triagem.")
            break  # Sai do loop após sucesso
            
        except Exception as e:
            print(f"[ERRO] Falha ao enviar email (tentativa {tentativa + 1} de {max_tentativas}): {e}")
            if tentativa < max_tentativas - 1:
                print("A aguardar 5 segundos antes de tentar novamente...")
                time.sleep(5)
            else:
                print("[ERRO CRÍTICO] Falha definitiva na ligação ao servidor de email. Gravado apenas no comboio local.")

# ===================================================================
# 3. MOTOR MATEMÁTICO: REVERSÃO À MÉDIA (COM TARGET VOLATILITY)
# ===================================================================
def analisar_reversao_media(ativo_info, vol_alvo_diaria_usd):
    ticker = ativo_info.get("ticker")
    nome_empresa = ativo_info.get("nome", "N/A")
    setor = ativo_info.get("setor", "Desconhecido")
    rs_score = ativo_info.get("rs_score", "N/A")

    try:
        df = yf.download(ticker, period="1y", interval="1d", progress=False)
        if df.empty:
            return None
            
        if isinstance(df.columns, pd.MultiIndex):
            df.columns = df.columns.droplevel(1)

        # Verificar se há dados suficientes
        if len(df) < 25:
            return None

        preco = df.iloc[-1]['Close']

        # -------------------------------------------------------------
        # FILTROS DE SEGURANÇA ESTRUTURAL (ANTI-LIXO BOLSISTA)
        # -------------------------------------------------------------
        if pd.isna(preco) or preco < 3.00:
            print(f"[FILTRADO] {ticker} rejeitado por preço baixo (Preço: {preco}).")
            return None
            
        if setor and any(termo in setor.lower() for termo in ["real estate", "reit", "mortgage"]):
            print(f"[FILTRADO] {ticker} rejeitado por pertencer ao setor REIT/Imobiliário.")
            return None

        # Indicadores Base
        df['SMA_20'] = df['Close'].rolling(window=20).mean()
        
        # RSI 14 Rápido
        delta = df['Close'].diff()
        gain = (delta.where(delta > 0, 0)).rolling(window=14).mean()
        loss = (-delta.where(delta < 0, 0)).rolling(window=14).mean()
        rs = gain / loss
        df['RSI_14'] = 100 - (100 / (1 + rs))
        
        # Média Móvel de 9 (Alvo de Saída)
        df['EMA_9'] = df['Close'].ewm(span=9, adjust=False).mean()
        
        # Volume Relativo (RVOL) e ATR para o Carver
        df['SMA_20_Vol'] = df['Volume'].rolling(window=20).mean()
        df['RVOL'] = df['Volume'] / df['SMA_20_Vol']
        df.ta.atr(length=14, append=True)

        # Selecionar o último dia de forma segura após o cálculo das colunas
        ultimo_dia = df.iloc[-1]

        sma20 = ultimo_dia.get('SMA_20', np.nan)
        ema9 = ultimo_dia.get('EMA_9', preco)
        rsi = ultimo_dia.get('RSI_14', np.nan)
        rvol = ultimo_dia.get('RVOL', 1.0)
        atr = ultimo_dia.get('ATRr_14', np.nan)
        
        dist_mm20 = ((preco - sma20) / sma20) * 100 if pd.notna(sma20) and sma20 > 0 else 0.0
        
        # Deteção de Absorção (Candlestick)
        abertura = ultimo_dia.get('Open', preco)
        minimo = ultimo_dia.get('Low', preco)
        
        corpo = abs(abertura - preco)
        sombra_inferior = min(abertura, preco) - minimo
        absorcao = sombra_inferior > (corpo * 1.5)

        estado = "Observar"
        entrada = "N/A"
        alvo_tp = "N/A"
        stop_loss = "N/A"
        qtd_acoes = "N/A"
        valor_investir = "N/A"
        
        # -------------------------------------------------------------
        # A MATEMÁTICA DO GATILHO DE CHOQUE
        # -------------------------------------------------------------
        if pd.notna(dist_mm20) and dist_mm20 <= -8.0 and pd.notna(rsi) and rsi < 30 and (rvol >= 1.5 or absorcao):
            estado = "PÂNICO EXTREMO - Oportunidade de Reversão"
            entrada = round(preco, 2)
            alvo_tp = round(ema9, 2)
            stop_loss = round(minimo * 0.99, 2)
            
            risco = entrada - stop_loss
            recompensa = alvo_tp - entrada
            
            if recompensa < risco:
                 estado = "Rejeitado (Rácio de Risco Negativo)"
                 entrada = alvo_tp = stop_loss = "N/A"
            else:
                 # CÁLCULO DE MESTRE CARVER ADAPTADO A REVERSÃO:
                 if pd.notna(atr) and atr > 0:
                     qtd_acoes = round(vol_alvo_diaria_usd / atr, 2)
                 else:
                     qtd_acoes = round(vol_alvo_diaria_usd / risco, 2) if risco > 0 else "N/A"

                 if qtd_acoes != "N/A":
                     val_calc = entrada * qtd_acoes
                     valor_investir = f"~{val_calc:.2f} USD"

        def limpa(v):
            if pd.isna(v) or v == "N/A": return "N/A"
            return round(float(v), 2)

        # Análise contextual do RS Score (Coluna O)
        try:
            val_rs = float(rs_score)
            if val_rs >= 80:
                status_rs = "🔥 ELITE (RS >= 80 - Vento a Favor)"
            elif val_rs >= 50:
                status_rs = "⚖️ NEUTRO (RS 50-79 - Acompanha o Mercado)"
            else:
                status_rs = "⚠️ FRACO / LAGGARD (RS < 50 - Vento Contra)"
        except ValueError:
            status_rs = "❓ SEM DADO DE RS"

        linha_comboio = (
            f"{ticker},Nome: {nome_empresa},Setor: {setor},Preço: {limpa(preco)},"
            f"RS Score: {rs_score} ({status_rs}),"
            f"Dist MM20: {limpa(dist_mm20)}%,EMA9: {limpa(ema9)},"
            f"RSI: {limpa(rsi)},RVOL: {limpa(rvol)},Absorção: {'Sim' if absorcao else 'Não'},"
            f"Estado: {estado},Ordem: BUY LIMIT,Entrada: {limpa(entrada)},"
            f"Stop: {limpa(stop_loss)},Take-Profit: {limpa(alvo_tp)},"
            f"Qtd: {qtd_acoes},ValorInvestir: {valor_investir},"
            f"Data: {datetime.now(ZoneInfo('Europe/Lisbon')).strftime('%d/%m/%Y %H:%M:%S')}"
        )

        return {
            "ticker": ticker,
            "estado": estado,
            "comboio_str": linha_comboio
        }

    except Exception as e:
        print(f"[ERRO] Falha ao processar {ticker}: {e}")
        return None

# ===================================================================
# 4. EXECUÇÃO PRINCIPAL E GERAÇÃO DE PROMPT
# ===================================================================
def executar_motor():
    ativos, configs = buscar_watchlist()
    if not ativos:
        sys.exit(1)
        
    # Leitura dinâmica das configurações de risco da tab Configs (com fallback de segurança)
    try:
        capital_total_conta = float(configs.get("CAPITAL_TOTAL_CONTA", 10400.00))
        alvo_volatilidade_anual = float(configs.get("ALVO_VOLATILIDADE_ANUAL", 0.05))
    except (ValueError, TypeError):
        capital_total_conta = 10400.00
        alvo_volatilidade_anual = 0.05

    # Orçamento diário de volatilidade do Carver (constante 16 para raiz de 256 dias úteis)
    volatilidade_alvo_diaria_usd = (capital_total_conta * alvo_volatilidade_anual) / 16.0

    print(f"[CONFIG] Capital Total da Conta: ${capital_total_conta:,.2f}")
    print(f"[CONFIG] Alvo Volatilidade Anual: {alvo_volatilidade_anual*100:.1f}%")
    print(f"[CONFIG] Orçamento Diário de Volatilidade: ${volatilidade_alvo_diaria_usd:.2f}\n")

    ativos_acionados = []
    
    for ativo_info in ativos:
        ticker = ativo_info.get("ticker")
        if not ticker or ticker == "#N/A": continue
        
        res = analisar_reversao_media(ativo_info, volatilidade_alvo_diaria_usd)
        
        res_dict = res if isinstance(res, dict) else None
        if res_dict:
            print(f"[OK] {ticker} analisado. Estado: {res_dict['estado']}")
            if "PÂNICO EXTREMO" in res_dict['estado']:
                ativos_acionados.append(res_dict)
                
    # ==============================================================================
    # PROMPT DE SISTEMA PARA A IA (Instruções Rigorosas)
    # ==============================================================================
    prompt_ia = """Atuas como o Analista Quantitativo Chefe de um fundo institucional. O teu mandato é auditar ações que sofreram quedas massivas e identificar fundos institucionais para ressaltos rápidos (Dead Cat Bounce). 
Não estás à procura de tendências; estás a apanhar a correção de uma anomalia estatística baseada no orçamento de volatilidade da conta.

REGRAS ESTRITAS (ANTI-ALUCINAÇÃO):
- NUNCA inventes, deduzas ou alteres preços, tickers
