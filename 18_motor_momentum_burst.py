# ===================================================================================
# SISTEMA DE TRADING INSTITUCIONAL - MOTOR 18: MOMENTUM BURST & VOLUME SURGE
# ===================================================================================
# Descrição Geral:
# Identifica ativos de alta liquidez a sofrer uma explosão de volume institucional 
# (RVOL >= 2.0) acompanhada de um rompimento direcional de curto prazo (Hit and Run).
# ===================================================================================

import pandas as pd
import yfinance as yf
import pandas_ta as ta
import numpy as np
from datetime import datetime
from zoneinfo import ZoneInfo
import sys
import os
import requests
import smtplib
import time
import random
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
import warnings
warnings.filterwarnings("ignore")

# Importação da função modular de notificação do Telegram
from F01_notificador_telegram import enviar_alerta

# ===================================================================
# 0. TRAVA DE FIM DE SEMANA
# ===================================================================
dia_da_semana = datetime.now(ZoneInfo("Europe/Lisbon")).weekday()
if dia_da_semana >= 5:
    print("[INFO] Fim de semana detetado. O Motor Momentum Burst vai descansar.")
    # sys.exit(0)

# ===================================================================
# 1. CONFIGURAÇÕES E CREDENCIAIS
# ===================================================================
WEBHOOK_URL = os.environ.get('WEBHOOK_URL')
EMAIL_USER = os.environ.get("EMAIL_USER")
EMAIL_PASS = os.environ.get("EMAIL_PASS")

SMTP_SERVER = "smtp.gmail.com"
SMTP_PORT = 587

def limpar_float(val):
    if val is None: return None
    try:
        val_str = str(val).replace(",", ".").strip()
        if val_str == "" or val_str.lower() in ["nan", "n/a", "none"]: return None
        return float(val_str)
    except (ValueError, TypeError):
        return None

# ===================================================================
# 2. FUNÇÕES DE REDE E CONFIGS
# ===================================================================
def buscar_watchlist():
    print("A carregar a Watchlist do Google Sheets...")
    if not WEBHOOK_URL: 
        print("[ERRO] WEBHOOK_URL não configurado.")
        return [], {}
    try:
        url_alvo = WEBHOOK_URL if "?" in WEBHOOK_URL else f"{WEBHOOK_URL}?aba=Analise Compra"
        resp = requests.get(url_alvo, timeout=15)
        
        if resp.status_code == 200:
            dados = resp.json()
            if isinstance(dados, dict):
                return dados.get("ativos", []), dados.get("configs", {})
            elif isinstance(dados, list):
                return dados, {}
        return [], {}
    except Exception as e:
        print(f"[ERRO CRÍTICO] Sheets: {e}")
        return [], {}

def enviar_email(conteudo):
    print("\nA enviar email do Motor 18 para o Agente IA...")
    if not EMAIL_USER or not EMAIL_PASS: return

    msg = MIMEMultipart()
    msg['From'] = EMAIL_USER
    msg['To'] = EMAIL_USER
    msg['Subject'] = "⚡ tradingRelatorioIA US - MOTOR 18 MOMENTUM BURST"
    msg.attach(MIMEText(conteudo, 'plain', 'utf-8'))
    
    for tentativa in range(3):
        try:
            server = smtplib.SMTP(SMTP_SERVER, SMTP_PORT, timeout=15)
            server.starttls()
            server.login(EMAIL_USER, EMAIL_PASS)
            server.sendmail(EMAIL_USER, EMAIL_USER, msg.as_string())
            server.quit()
            print(f"[SUCESSO] Email enviado na tentativa {tentativa + 1}!")
            break
        except Exception as e:
            if tentativa < 2: time.sleep(5)

# ===================================================================
# 3. MOTOR MATEMÁTICO: MOMENTUM BURST & RVOL
# ===================================================================
def analisar_momentum_burst(ativo_info, vol_alvo_diaria_usd):
    try:
        ticker = str(ativo_info.get("ticker", "")).strip().upper()
        nome_empresa = ativo_info.get("nome", "N/A")
        setor = str(ativo_info.get("setor", "Desconhecido")).strip()
        rs_score = ativo_info.get("rs_score", "N/A")

        if not ticker or ticker == "#N/A" or ticker == "NONE": return None
        if ticker == "BRK-A": ticker = "BRK-B"

        time.sleep(random.uniform(0.8, 1.8))

        # Dados fundamentais e Máximo de 52 Semanas (Travão Técnico)
        max_52s = None
        alerta_earnings = "OK"
        try:
            ticker_obj = yf.Ticker(ticker)
            info_dados = ticker_obj.info
            if setor in ["Desconhecido", "N/A", "", "NONE"]:
                setor = info_dados.get('sector', setor)
            max_52s = info_dados.get('fiftyTwoWeekHigh', None)

            calendario = ticker_obj.calendar
            if isinstance(calendario, dict) and 'Earnings Date' in calendario:
                proxima_data = calendario['Earnings Date'][0]
                if hasattr(proxima_data, 'date'): proxima_data = proxima_data.date()
                dias_restantes = (proxima_data - datetime.now(ZoneInfo("Europe/Lisbon")).date()).days
                if 0 <= dias_restantes <= 3:
                    alerta_earnings = f"PERIGO (em {dias_restantes} dias)"
        except:
            pass

        # Obtenção de dados históricos
        df = pd.DataFrame()
        for _ in range(3):
            try:
                df = yf.download(ticker, period="1y", interval="1d", progress=False, timeout=15)
                if not df.empty and len(df) >= 60:
                    break
            except Exception:
                time.sleep(2)

        if df.empty or len(df) < 60: return None
        if isinstance(df.columns, pd.MultiIndex): df.columns = df.columns.droplevel(1)
        df = df.dropna(subset=['Close', 'High', 'Low', 'Volume'])

        preco = float(df['Close'].iloc[-1])
        if preco < 5.00: return None

        # Indicadores técnicos
        df['EMA_20'] = df['Close'].ewm(span=20, adjust=False).mean()
        df['Vol_SMA_20'] = df['Volume'].rolling(window=20).mean()
        df.ta.atr(length=14, append=True)

        col_atr = [c for c in df.columns if str(c).startswith('ATRr_') or str(c).startswith('ATR_')][0]
        df = df.dropna(subset=['EMA_20', 'Vol_SMA_20', col_atr])
        if df.empty: return None

        ultimo = df.iloc[-1]
        vol_atual = float(ultimo['Volume'])
        vol_sma20 = float(ultimo['Vol_SMA_20'])
        atr = float(ultimo[col_atr])
        ema20 = float(ultimo['EMA_20'])

        # Cálculo do RVOL (Relative Volume)
        rvol = vol_atual / vol_sma20 if vol_sma20 > 0 else 0.0

        # Máxima dos últimos 5 dias (excluindo a barra atual)
        max_5d = float(df['High'].iloc[-6:-1].max())
        minimo_hoje = float(ultimo['Low'])
        maximo_hoje = float(ultimo['High'])

        # Condições de Entrada (Burst de Momento e Volume)
        # 1. RVOL >= 2.0 (Volume duplicado face à média)
        # 2. Preço atual rompe a máxima dos últimos 5 dias
        # 3. Tendência de suporte (Preço acima da EMA20)
        cond_rvol = rvol >= 2.0
        cond_rompimento = maximo_hoje >= max_5d
        cond_tendencia = preco > ema20

        if cond_rvol and cond_rompimento and cond_tendencia:
            estado = "MOMENTUM BURST - Explosão de Volume e Rompimento"
            
            entrada_gatilho = round(maximo_hoje * 1.002, 2)
            stop_loss = round(min(minimo_hoje * 0.99, entrada_gatilho - (atr * 1.5)), 2)
            
            risco = entrada_gatilho - stop_loss
            alvo_tp = round(entrada_gatilho + (risco * 2.0), 2) # Rácio 2.0R para rotação rápida

            # Travão de Teto Técnico (Máximo 52 semanas)
            if max_52s and max_52s > 0 and alvo_tp > max_52s:
                alvo_tp = round(max_52s, 2)

            if risco > 0:
                qtd_calc = round(vol_alvo_diaria_usd / risco, 2)
            else:
                return None

            val_calc = entrada_gatilho * qtd_calc
            valor_investir = f"~{val_calc:.2f} USD"

            def limpa(v):
                try: return round(float(v), 2)
                except: return "N/A"

            linha_comboio = (
                f"{ticker},Nome: {nome_empresa},Setor: {setor},Preço: {limpa(preco)},"
                f"RVOL: {limpa(rvol)}x (🚀 EXPLOSÃO DE VOLUME),"
                f"Gatilho Compra (Buy Stop): {limpa(entrada_gatilho)},"
                f"Stop Loss: {limpa(stop_loss)},Alvo TP: {limpa(alvo_tp)},"
                f"Estado: {estado},Qtd: {qtd_calc},ValorInvestir: {valor_investir},Earnings: {alerta_earnings},"
                f"Data: {datetime.now(ZoneInfo('Europe/Lisbon')).strftime('%d/%m/%Y %H:%M:%S')}"
            )

            return {
                "ticker": ticker,
                "comboio_str": linha_comboio
            }

        return None
    except Exception as e:
        print(f"[ERRO] Falha ao processar ativo {ativo_info.get('ticker')}: {e}")
        return None

# ===================================================================
# 4. EXECUÇÃO PRINCIPAL
# ===================================================================
def executar_motor():
    ativos, configs = buscar_watchlist()
    if not ativos: sys.exit(0)
        
    try:
        capital = float(configs.get("CAPITAL_TOTAL_CONTA", 10400.00))
        vol_anual = float(configs.get("ALVO_VOLATILIDADE_ANUAL", 0.05))
    except (ValueError, TypeError):
        capital, vol_anual = 10400.00, 0.05

    vol_diaria_usd = (capital * vol_anual) / 16.0
    print(f"[CONFIG] Orçamento Diário de Volatilidade: ${vol_diaria_usd:.2f}\n")

    ativos_acionados = []
    for ativo_info in ativos:
        ticker = ativo_info.get("ticker")
        if not ticker or ticker == "#N/A": continue
        
        res = analisar_momentum_burst(ativo_info, vol_diaria_usd)
        if res: ativos_acionados.append(res)

    prompt_ia = """MODO ESTRATÉGICO: MOTOR 18 - MOMENTUM BURST & VOLUME SURGE
O teu mandato é auditar oportunidades de curto prazo (Hit and Run) focadas em explosões institucionais de volume.

ESTRUTURA OBRIGATÓRIA:
⚡ [TICKER] - [Nome da Empresa] ([Setor])
- 🚀 DIAGNÓSTICO DE MOMENTO: Explosão de volume detetada (RVOL elevado) com quebra de máximos de curto prazo.
- ⚙️ TÁTICA DE EXECUÇÃO: Colocar ordem Buy Stop no Gatilho de [Entrada].
- 🛡️ RISCO E ALVO: Stop em [Stop] | Alvo: [TP] | Qtd: [X] | Alocação: [Valor] USD.
- 🔄 PASSAGEM DE TESTEMUNHO: Adiciona: "⚠️ ATENÇÃO: Operação puramente HIT AND RUN. Assim que executada, regista o estado no Sheets como 'ATIVA_M18'. Logo que atinja o Alvo (TP), fecha a posição integralmente para libertar capital."
"""

    bloco = f"⚡ RELATÓRIO MOTOR 18 - MOMENTUM BURST 🚀\n\n{prompt_ia}\n\n--------------------------------------------------\n"

    if not ativos_acionados:
        bloco += "[SEM SINAIS MOMENTUM BURST] - Nenhum ativo apresenta explosão de volume e momento hoje.\n"
    else:
        bloco += "ALVOS DE MOMENTUM BURST:\n\n"
        for item in ativos_acionados:
            bloco += item["comboio_str"] + "\n"

    with open("comboio_momentumburst_temp.txt", "w", encoding="utf-8") as f:
        f.write(bloco)

    enviar_email(bloco)

    # Notificação simples no Telegram (respeitando o Sheets)
    telegram_ativado = str(configs.get("TELEGRAM_NOTIFICATIONS", "true")).strip().lower() in ["true", "1", "sim", "yes"]
    if telegram_ativado:
        print("A enviar notificação curta de conclusão do Motor 18 para o Telegram...")
        mensagem_curta = "⚡ *MOTOR 18 (MOMENTUM BURST)*\n\n✅ Execução concluída com sucesso. Verifica o e-mail para consultar os sinais detetados."
        enviar_alerta(mensagem_curta)

if __name__ == "__main__":
    executar_motor()
