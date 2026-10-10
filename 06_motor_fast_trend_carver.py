"""
===================================================================================
SISTEMA DE TRADING INSTITUCIONAL - MOTOR FAST TREND (ROBERT CARVER)
===================================================================================
Documentação e Arquitetura do Módulo:
1. OBJETIVO:
   Automatizar a deteção de sinais de momentum de alta frequência com base nos 
   princípios quantitativos de Robert Carver (Systematic Trading).

2. INDICADORES TÉCNICOS & CÁLCULOS:
   - Médias Móveis Exponenciais (EMA): EMA 8 (rápida) e EMA 32 (lenta).
   - Average True Range (ATR): Janela de 36 períodos para medição de volatilidade.
   - Forecast (Previsão de Tendência): Calculado como ((EMA8 - EMA32) / ATR36) * 5.0.
     * Acionamento de novos sinais: Requer Forecast >= 10.0.

3. GESTÃO DE RISCO E DIMENSIONAMENTO (VOLATILITY PARITY):
   - Alvo de Volatilidade Diária calculado com base no capital total da conta.
   - Dimensionamento (Multiplicador): Proporcional à força do forecast (capado a x2.0).
   - Stop Loss Inicial: 1.5x ATR abaixo do preço de entrada.
   - Take-Profit: 2.5x a distância do Stop Loss.

4. GESTÃO DE ESTADOS E POSIÇÕES ATIVAS:
   - Separação estricta entre posições 'ATIVA' (geridas por outros scripts, filtradas 
     de novos sinais e excluídas do trailing do Carver) e 'ATIVA_FAST' (geridas por 
     este motor com monitorização diária de Trailing Stop por ATR).
   - Regra de Inércia do Trailing Stop: O stop é unidirecional (só sobe ou mantém-se).
     Se o stop atual registado na folha for superior ao novo cálculo matemático, 
     o sistema força a manutenção do patamar mais alto (proteção de inércia).

5. FLUXO DE EXECUÇÃO:
   - Validação de fim de semana (descanso do motor).
   - Comunicação via Webhook com o Google Sheets (Watchlist + Diário de Bordo).
   - Envio automático de relatório bruto por email para o Agente IA realizar a auditoria.
===================================================================================
"""

import pandas as pd
import yfinance as yf
import numpy as np
from datetime import datetime
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
    print("[INFO] Fim de semana detetado. O motor Carver vai descansar.")
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
CAPITAL_TOTAL_CONTA = 10400.00  
ALVO_VOLATILIDADE_ANUAL = 0.05  
VOLATILIDADE_ALVO_DIARIA_USD = (CAPITAL_TOTAL_CONTA * ALVO_VOLATILIDADE_ANUAL) / 16.0 

# ===================================================================
# 2. FUNÇÕES DE REDE
# ===================================================================
def buscar_dados_completos():
    print("A carregar a Watchlist e Posições Ativas a partir do Google Sheets...")
    if not WEBHOOK_URL: 
        print("[ERRO] WEBHOOK_URL não configurado.")
        return [], {}
    try:
        resp = requests.get(WEBHOOK_URL)
        if resp.status_code == 200:
            dados = resp.json()
            if isinstance(dados, dict):
                return dados.get("ativos", []), dados.get("posicoesAtivas", {})
            elif isinstance(dados, list):
                return dados, {}
        return [], {}
    except Exception as e:
        print(f"[ERRO CRÍTICO] Sheets: {e}")
        return [], {}

def enviar_email_bruto(conteudo):
    print("\nA enviar o relatório de dados brutos do Carver para o Agente IA via email...")
    if not EMAIL_USER or not EMAIL_PASS:
        return
    try:
        msg = MIMEMultipart()
        msg['From'] = EMAIL_USER
        msg['To'] = EMAIL_USER
        msg['Subject'] = "tradingRelatorioIA US - FAST TREND CARVER"
        msg.attach(MIMEText(conteudo, 'plain', 'utf-8'))
        
        server = smtplib.SMTP(SMTP_SERVER, SMTP_PORT)
        server.starttls()
        server.login(EMAIL_USER, EMAIL_PASS)
        server.sendmail(EMAIL_USER, EMAIL_USER, msg.as_string())
        server.quit()
        print("[SUCESSO] Email bruto do Carver enviado!")
    except Exception as e:
        print(f"[ERRO] Falha ao enviar email: {e}")

# ===================================================================
# 3. MOTOR MATEMÁTICO: CÁLCULO NATIVO
# ===================================================================
def calcular_indicadores_tecnicos(ticker):
    try:
        df = yf.download(ticker, period="1y", interval="1d", progress=False)
        if df.empty or len(df) < 50:
            return None
            
        if isinstance(df.columns, pd.MultiIndex):
            df.columns = df.columns.droplevel(1)

        df['EMA_8'] = df['Close'].ewm(span=8, adjust=False).mean()
        df['EMA_32'] = df['Close'].ewm(span=32, adjust=False).mean()

        high = df['High']
        low = df['Low']
        close = df['Close']
        
        tr1 = high - low
        tr2 = (high - close.shift()).abs()
        tr3 = (low - close.shift()).abs()
        
        tr = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)
        df['ATR_36'] = tr.rolling(window=36).mean()

        ultimo = df.iloc[-1]
        return {
            "preco": float(ultimo['Close']),
            "ema8": float(ultimo['EMA_8']),
            "ema32": float(ultimo['EMA_32']),
            "atr36": float(ultimo['ATR_36'])
        }
    except Exception as e:
        print(f"[ERRO] Falha ao descarregar dados para {ticker}: {e}")
        return None

def analisar_tendencia_carver(ticker, nome_empresa, setor):
    ind = calcular_indicadores_tecnicos(ticker)
    if not ind: return None
    
    preco, ema8, ema32, atr36 = ind['preco'], ind['ema8'], ind['ema32'], ind['atr36']
    if pd.isna(ema8) or pd.isna(ema32) or pd.isna(atr36) or atr36 == 0:
        return None

    diferenca_bruta = ema8 - ema32
    forecast_carver = (diferenca_bruta / atr36) * 5.0
    
    if forecast_carver < 10.0:
        return None

    multiplicador = min(forecast_carver / 10.0, 2.0)
    estado_str = "FAST TREND - Carver Momentum"
    entrada = round(preco, 2)
    stop_loss = round(entrada - (atr36 * 1.5), 2)
    alvo_tp = round(entrada + ((entrada - stop_loss) * 2.5), 2)
    
    qtd_bruta = (VOLATILIDADE_ALVO_DIARIA_USD / atr36) * multiplicador
    qtd_acoes = round(qtd_bruta, 2)
    val_calc = entrada * qtd_acoes
    valor_investir = f"~{val_calc:.2f} USD"

    def limpa(v): return round(float(v), 2)

    linha_comboio = (
        f"{ticker},Nome: {nome_empresa},Setor: {setor},Preço: {limpa(preco)},"
        f"EMA8: {limpa(ema8)},EMA32: {limpa(ema32)},ATR36: {limpa(atr36)},"
        f"Forecast: {limpa(forecast_carver)},Multiplicador: x{limpa(multiplicador)},"
        f"Estado: {estado_str},Entrada: {limpa(entrada)},Stop: {limpa(stop_loss)},"
        f"Take-Profit: {limpa(alvo_tp)},Qtd: {qtd_acoes},ValorInvestir: {valor_investir},"
        f"Data: {datetime.now(ZoneInfo('Europe/Lisbon')).strftime('%d/%m/%Y %H:%M:%S')}"
    )

    return {
        "ticker": ticker,
        "forecast": forecast_carver,
        "comboio_str": linha_comboio
    }

def monitorizar_posicao_ativa(ticker, nome_empresa, status_atual, dados_posicao):
    ind = calcular_indicadores_tecnicos(ticker)
    if not ind: return None
    
    preco, ema8, ema32, atr36 = ind['preco'], ind['ema8'], ind['ema32'], ind['atr36']
    trailing_stop_calculado = round(preco - (atr36 * 1.5), 2)
    
    preco_entrada = dados_posicao.get("precoEntrada", "N/A")
    quantidade = dados_posicao.get("quantidade", "N/A")
    stop_atual_registado = dados_posicao.get("stopAtual", None)
    
    # REGRA DE OURO BLINDADA: O stop nunca desce, só sobe ou mantém-se
    stop_final = trailing_stop_calculado
    instrucao_risco = f"Atualizar stop para {trailing_stop_calculado}"
    
    if stop_atual_registado is not None and str(stop_atual_registado).strip() != "":
        try:
            stop_atual_val = float(stop_atual_registado)
            if stop_atual_val >= trailing_stop_calculado:
                stop_final = stop_atual_val
                instrucao_risco = f"MANTER o Stop atual em {stop_atual_val} (o cálculo matemático de hoje ({trailing_stop_calculado}) é inferior, aplicando-se a regra de inércia do trailing stop)."
            else:
                instrucao_risco = f"SUBIR o Stop do valor anterior ({stop_atual_val}) para o novo patamar ({trailing_stop_calculado})."
        except ValueError:
            pass

    diferenca_bruta = ema8 - ema32
    forecast_atual = (diferenca_bruta / atr36) * 5.0 if atr36 > 0 else 0

    linha_monitorizacao = (
        f"📌 [POSIÇÃO ATIVA - {status_atual}] {ticker} ({nome_empresa}) | "
        f"Qtd: {quantidade} | Entrada: {preco_entrada} | Preço Atual: {preco:.2f} | "
        f"EMA8: {ema8:.2f} | EMA32: {ema32:.2f} | Forecast: {forecast_atual:.2f} | "
        f"Stop Atual: {stop_atual_registado} | Novo Stop Sugerido: {stop_final} | "
        f"🛑 AÇÃO: {instrucao_risco} (ATR: {atr36:.2f})"
    )
    return linha_monitorizacao

# ===================================================================
# 4. EXECUÇÃO PRINCIPAL
# ===================================================================
def executar_motor():
    ativos, posicoes_ativas_dict = buscar_dados_completos()
    if not ativos and not posicoes_ativas_dict:
        sys.exit(1)
        
    ativos_acionados = []
    posicoes_em_gestao = []

    # 1. Analisa novos sinais (ignora qualquer ativo que já esteja no dicionário de posições ativas)
    for ativo_info in ativos:
        ticker = ativo_info.get("ticker")
        if not ticker or ticker == "#N/A": continue
        
        nome = ativo_info.get("nome", "N/A")
        setor = ativo_info.get("setor", "Desconhecido")

        if ticker in posicoes_ativas_dict:
            continue

        res = analisar_tendencia_carver(ticker, nome, setor)
        if res:
            ativos_acionados.append(res)
            
    # 2. Processa posições ativas APENAS se o estado for ATIVA_FAST (ignora as 'ATIVA' de outros scripts)
    for ticker, dados_pos in posicoes_ativas_dict.items():
        status_atual = dados_pos.get("status", "").strip().upper()
        
        if status_atual != "ATIVA_FAST":
            continue
            
        nome = dados_pos.get("nome", ticker)
        monitorizacao = monitorizar_posicao_ativa(ticker, nome, status_atual, dados_pos)
        if monitorizacao:
            posicoes_em_gestao.append(monitorizacao)

    ativos_acionados = sorted(ativos_acionados, key=lambda k: k['forecast'], reverse=True)

    prompt_ia = (
        "MODO ACELERADOR ESTATÍSTICO (CARVER FAST TREND)\n"
        "O teu mandato é auditar as entradas geradas e monitorizar as posições ativas do portefólio.\n"
        "ATENÇÃO À GESTÃO DE RISCO: Respeita estritamente a regra de inércia do trailing stop nas posições ativas "
        "(o stop nunca desce, se o stop atual registado já for superior ao novo cálculo sugerido, a instrução deve ser obrigatoriamente manter o valor atual).\n"
    )
    
    bloco_texto_ia = f"📊 RELATÓRIO DE DADOS BRUTOS - FAST TREND CARVER 🏄‍♂️\n\n{prompt_ia}\n\n--------------------------------------------------\n"

    if posicoes_em_gestao:
        bloco_texto_ia += "GESTÃO DE POSIÇÕES ATIVAS (TRAILING STOP SUGERIDO & QUANTIDADES):\n\n"
        for pos in posicoes_em_gestao:
            bloco_texto_ia += pos + "\n"
        bloco_texto_ia += "\n--------------------------------------------------\n"

    if not ativos_acionados:
        bloco_texto_ia += "[MERCADO LENTO] - Nenhum novo ativo apresenta aceleração matemática (Forecast > 10).\n"
    else:
        bloco_texto_ia += "NOVOS DADOS DE ENTRADA (COMBOIO):\n\n"
        for item in ativos_acionados:
            bloco_texto_ia += item["comboio_str"] + "\n"

    with open("comboio_carver_temp.txt", "w", encoding="utf-8") as f:
        f.write(bloco_texto_ia)

    enviar_email_bruto(bloco_texto_ia)

if __name__ == "__main__":
    executar_motor()
