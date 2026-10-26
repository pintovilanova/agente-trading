# ===================================================================================
# SISTEMA DE TRADING INSTITUCIONAL - MOTOR HOLY GRAIL (PULLBACKS DE LIDERANÇA)
# ===================================================================================
# Descrição Geral:
# Implementa a estratégia "Holy Grail" (popularizada por Linda Raschke/David Ryan).
# Procura ativos com Força Relativa de Elite (RS >= 80) e forte tendência direcional
# (ADX > 25), que estão a sofrer um pullback natural de curto prazo, tocando na 
# Média Móvel Exponencial (EMA) de 20 ou 21 dias, com forte contração de volume.
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
import json
import smtplib
import time
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
import warnings
warnings.filterwarnings("ignore")
import random

# ===================================================================
# 0. TRAVA DE FIM DE SEMANA
# ===================================================================
dia_da_semana = datetime.now(ZoneInfo("Europe/Lisbon")).weekday()
if dia_da_semana >= 5:
    print("[INFO] Fim de semana detetado. O Motor Holy Grail vai descansar.")
    #sys.exit(0)

# ===================================================================
# 1. CONFIGURAÇÕES E CREDENCIAIS
# ===================================================================
WEBHOOK_URL = os.environ.get('WEBHOOK_URL')
EMAIL_USER = os.environ.get("EMAIL_USER")
EMAIL_PASS = os.environ.get("EMAIL_PASS")

SMTP_SERVER = "smtp.gmail.com"
SMTP_PORT = 587

MIN_RS_SCORE_HOLY_GRAIL = 80.0  # Exigência extrema: Só pullbacks em líderes absolutos

def limpar_float(val):
    """Converte com segurança valores numéricos (mesmo com vírgulas) para float."""
    if val is None: return None
    try:
        val_str = str(val).replace(",", ".").strip()
        if val_str == "" or val_str.lower() in ["nan", "n/a", "none"]: return None
        return float(val_str)
    except (ValueError, TypeError):
        return None

# ===================================================================
# 2. FUNÇÕES DE REDE
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
    print("\nA enviar email do Holy Grail Pullbacks para o Agente IA...")
    if not EMAIL_USER or not EMAIL_PASS: return

    msg = MIMEMultipart()
    msg['From'] = EMAIL_USER
    msg['To'] = EMAIL_USER
    msg['Subject'] = "🏆 tradingRelatorioIA US - HOLY GRAIL PULLBACKS"
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
# 3. MOTOR MATEMÁTICO: HOLY GRAIL (PULLBACK À EMA20)
# ===================================================================
def analisar_holy_grail(ativo_info, vol_alvo_diaria_usd):
    try:
        ticker = str(ativo_info.get("ticker", "")).strip().upper()
        nome_empresa = ativo_info.get("nome", "N/A")
        setor = str(ativo_info.get("setor", "Desconhecido")).strip()
        rs_score = ativo_info.get("rs_score", "N/A")

        if not ticker or ticker == "#N/A" or ticker == "NONE": return None
        if ticker == "BRK-A": ticker = "BRK-B"

        # 1. FILTRO DE FORÇA RELATIVA EXTREMA (RS >= 80)
        val_rs_num = limpar_float(rs_score)
        if val_rs_num is None or val_rs_num < MIN_RS_SCORE_HOLY_GRAIL:
            return None

        # Pausa aleatória curta para evitar o bloqueio 401 do Yahoo Finance
        time.sleep(random.uniform(0.8, 1.8))

        # 2. CALENDÁRIO DE EARNINGS (Trava de Segurança)
        alerta_earnings = "OK"
        try:
            ticker_obj = yf.Ticker(ticker)
            if setor in ["Desconhecido", "N/A", "", "NONE"]:
                setor = ticker_obj.info.get('sector', setor)

            calendario = ticker_obj.calendar
            if isinstance(calendario, dict) and 'Earnings Date' in calendario:
                proxima_data = calendario['Earnings Date'][0]
                if hasattr(proxima_data, 'date'): proxima_data = proxima_data.date()
                dias_restantes = (proxima_data - datetime.now(ZoneInfo("Europe/Lisbon")).date()).days
                if 0 <= dias_restantes <= 3:
                    alerta_earnings = f"PERIGO (em {dias_restantes} dias)"
        except:
            pass

        # 3. DADOS FINANCEIROS COM TRATAMENTO DE RETENTATIVA
        df = pd.DataFrame()
        for tentativa_yf in range(3):
            try:
                df = yf.download(ticker, period="1y", interval="1d", progress=False, timeout=15)
                if not df.empty and len(df) >= 100:
                    break
            except Exception:
                time.sleep(2)

        if df.empty or len(df) < 100: return None
        if isinstance(df.columns, pd.MultiIndex): df.columns = df.columns.droplevel(1)
        df = df.dropna(subset=['Close', 'High', 'Low', 'Volume'])

        preco = float(df['Close'].iloc[-1])
        if preco < 5.00: return None

        # 4. INDICADORES (EMA, ADX, ATR, Volume)
        df['EMA_20'] = df['Close'].ewm(span=20, adjust=False).mean()
        df['EMA_50'] = df['Close'].ewm(span=50, adjust=False).mean()
        df['SMA_200'] = df['Close'].rolling(window=200).mean()
        
        # ADX (Medidor da força da tendência)
        adx_df = df.ta.adx(length=14)
        if adx_df is not None and not adx_df.empty:
            df = pd.concat([df, adx_df], axis=1)
        else:
            return None
            
        # ATR para Risco
        df.ta.atr(length=14, append=True)
        df['Vol_SMA_50'] = df['Volume'].rolling(window=50).mean()

        # Detetar colunas do ADX e ATR (lidar com nomes dinâmicos do pandas_ta)
        col_adx = [c for c in df.columns if str(c).startswith('ADX_')][0]
        col_atr = [c for c in df.columns if str(c).startswith('ATRr_') or str(c).startswith('ATR_')][0]
        
        df = df.dropna(subset=['EMA_20', 'EMA_50', 'SMA_200', col_adx, col_atr])
        if df.empty: return None

        ultimo = df.iloc[-1]
        ema20 = float(ultimo['EMA_20'])
        ema50 = float(ultimo['EMA_50'])
        sma200 = float(ultimo['SMA_200'])
        adx = float(ultimo[col_adx])
        atr = float(ultimo[col_atr])
        vol_sma50 = float(ultimo['Vol_SMA_50'])
        vol_atual = float(ultimo['Volume'])

        # 5. MATEMÁTICA DO PULLBACK (HOLY GRAIL GATILHOS)
        # Condição A: Forte Tendência de Alta (Preço no longo prazo subiu, ADX alto)
        trend_alta = (ema20 > ema50) and (ema50 > sma200) and (adx > 25.0)
        
        # Condição B: O Pullback (Preço testou a zona da EMA 20, mas não colapsou abaixo da EMA 50)
        minimo_hoje = float(ultimo['Low'])
        zona_inferior = ema20 * 0.985 # Pode escorregar até 1.5% abaixo da EMA20
        zona_superior = ema20 * 1.025 # Não pode estar mais de 2.5% acima da EMA20 (tem de estar a testar)
        
        pullback_valido = (minimo_hoje >= zona_inferior) and (minimo_hoje <= zona_superior) and (preco > ema50)

        # Condição C: Contração de Volume (Falta de convicção vendedora)
        seca_volume = vol_atual < (vol_sma50 * 0.8)

        if trend_alta and pullback_valido and seca_volume:
            estado = "HOLY GRAIL PULLBACK - Retração à EMA20"
            
            # Gatilho de compra: Superar a máxima do dia anterior ou máxima de hoje
            maximo_hoje = float(ultimo['High'])
            maximo_ontem = float(df['High'].iloc[-2])
            
            entrada_gatilho = round(max(maximo_hoje, maximo_ontem) * 1.002, 2)
            
            # Stop Loss Matemático: Abaixo do mínimo do pullback ou de 1 ATR abaixo da EMA20
            stop_loss = round(min(minimo_hoje * 0.99, ema20 - atr), 2)
            
            risco = entrada_gatilho - stop_loss
            alvo_tp = round(entrada_gatilho + (risco * 2.5), 2) # RR de 2.5x
            
            if atr > 0:
                qtd_calc = round(vol_alvo_diaria_usd / atr, 2)
            else:
                qtd_calc = round(vol_alvo_diaria_usd / risco, 2) if risco > 0 else 0
                
            if qtd_calc <= 0: return None

            qtd_acoes = qtd_calc
            val_calc = entrada_gatilho * qtd_acoes
            valor_investir = f"~{val_calc:.2f} USD"
            
            def limpa(v): 
                try: return round(float(v), 2)
                except: return "N/A"
            
            linha_comboio = (
                f"{ticker},Nome: {nome_empresa},Setor: {setor},Preço: {limpa(preco)},"
                f"RS Score: {rs_score} (🔥 ELITE - Liderança Pura),"
                f"ADX(14): {limpa(adx)},EMA20: {limpa(ema20)},"
                f"Gatilho Compra (Buy Stop): {limpa(entrada_gatilho)},"
                f"Stop Loss: {limpa(stop_loss)},Alvo TP: {limpa(alvo_tp)},"
                f"Estado: {estado},Qtd: {qtd_acoes},ValorInvestir: {valor_investir},Earnings: {alerta_earnings},"
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
        
        res = analisar_holy_grail(ativo_info, vol_diaria_usd)
        if res: ativos_acionados.append(res)

    prompt_ia = """MODO ESTRATÉGICO: PULLBACKS DE LIDERANÇA (HOLY GRAIL - LINDA RASCHKE)
O teu mandato é auditar ações de força relativa ELITE (RS >= 80) que sofreram um recuo (pullback) de curto prazo à Média Móvel Exponencial (EMA) de 20 períodos, apresentando seca de volume e tendência principal robusta (ADX forte).

REGRAS ESTRITAS:
1. O ativo não deve ser comprado a mercado. A entrada é SEMPRE validada via "Buy Stop" acima da máxima do pullback, garantindo que o fluxo comprador retomou o controlo.
2. Veto Fundamental: Se detetares "Earnings: PERIGO", desclassifica o sinal imediatamente.
3. Risco Assimétrico: Destaca a precisão deste trade. Ao comprar na EMA 20, o stop fica curto, permitindo alto retorno.

ESTRUTURA OBRIGATÓRIA:
🏆 [TICKER] - [Nome da Empresa] ([Setor])
- 📉 DIAGNÓSTICO DO PULLBACK: Teste à EMA 20 concluído com seca de volume. (ADX a [Valor] confirma força da tendência maior).
- 📊 CONTEXTO INSTITUCIONAL: RS Score de Elite (Vento a Favor).
- ⚙️ TÁTICA DE EXECUÇÃO: Colocar ordem pendente Buy Stop no Gatilho de [Entrada]. 
- 🛡️ RISCO E ALVO: Stop cravado em [Stop] (Abaixo da média/mínimo) | Alvo: [TP] | Qtd: [X] | Alocação: [Valor] USD.
- 🔄 PASSAGEM DE TESTEMUNHO: Adiciona: "⚠️ ATENÇÃO: Assim que executada, altera o estado no Sheets para 'ATIVA_FAST'. O Motor Carver assumirá a gestão."
"""
    
    bloco = f"📊 RELATÓRIO PULLBACKS DE LIDERANÇA (HOLY GRAIL) 🏆\n\n{prompt_ia}\n\n--------------------------------------------------\n"
    
    if not ativos_acionados:
        bloco += "[SEM SINAIS PULLBACK] - Nenhum ativo de Elite encontra-se num ponto ótimo de retração à EMA20 hoje.\n"
    else:
        bloco += "ALVOS DE COMPRA EM PULLBACK:\n\n"
        for item in ativos_acionados:
            bloco += item["comboio_str"] + "\n"
            
    with open("comboio_holygrail_temp.txt", "w", encoding="utf-8") as f:
        f.write(bloco)
        
    enviar_email(bloco)

if __name__ == "__main__":
    executar_motor()
