# ===================================================================
# SISTEMA DE TRADING INSTITUCIONAL - MOTOR FAST TREND (CARVER EWMA)
# ===================================================================
# Descrição Geral:
# Este script implementa a regra estatística de Tendência Acelerada baseada
# na framework de Robert Carver (Systematic Trading). Em vez de procurar 
# exaustões ou breakouts binários, este modelo avalia a velocidade de 
# expansão do preço cruzando uma EMA rápida (8) com uma EMA lenta (32), 
# normalizando o resultado pela volatilidade estrutural (ATR 36).
# O capital alocado aumenta dinamicamente consoante o grau de aceleração.
#
# Pilares Técnicos e Arquitetura de Execução:
# 1. Travas de Segurança e Calendário:
#    - Trava de Fim de Semana: Aborta automaticamente aos sábados e domingos.
# 2. Gestão de Risco Dinâmica (Forecast Scaling):
#    - Volatilidade Diária Alvo calculada sobre o capital ($10,400.00 a 5%).
#    - O escalar de previsão (Forecast) varia entre 0 e >20. O motor dispara
#      quando atinge +10.0, e escala a posição até um máximo de 200% do risco
#      base caso a tendência apresente força extrema (Forecast >= 20.0).
# 3. Integração Cloud & IA:
#    - Guarda os dados em "comboio_carver_temp.txt".
#    - Envia email com o prefixo correto para a triagem da IA Orquestradora.
# ===================================================================

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
            print(f"[SUCESSO] {len(ativos)} ativos carregados para auditoria.")
            return ativos
        else:
            print(f"[ERRO] Falha HTTP: {resp.status_code}")
            return []
    except Exception as e:
        print(f"[ERRO CRÍTICO] Sheets: {e}")
        return []

def enviar_email(conteudo):
    print("\nA enviar relatório de Carver Fast Trend para o Agente IA...")
    if not EMAIL_USER or not EMAIL_PASS:
        print("[AVISO] Credenciais de email em falta. A saltar envio.")
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
        print("[SUCESSO] Email Carver Fast Trend enviado!")
    except Exception as e:
        print(f"[ERRO] Falha ao enviar email: {e}")

# ===================================================================
# 3. MOTOR MATEMÁTICO: FAST EWMA MACD (CARVER)
# ===================================================================
def analisar_tendencia_carver(ticker, nome_empresa, setor):
    try:
        df = yf.download(ticker, period="1y", interval="1d", progress=False)
        if df.empty or len(df) < 50:
            return None
            
        if isinstance(df.columns, pd.MultiIndex):
            df.columns = df.columns.droplevel(1)

        # Indicadores Base de Carver
        df.ta.ema(length=8, append=True)
        df.ta.ema(length=32, append=True)
        df.ta.atr(length=36, append=True)

        ultimo_dia = df.iloc[-1]
        preco = ultimo_dia['Close']
        ema8 = ultimo_dia.get('EMA_8', np.nan)
        ema32 = ultimo_dia.get('EMA_32', np.nan)
        atr36 = ultimo_dia.get('ATRr_36', np.nan)

        if pd.isna(ema8) or pd.isna(ema32) or pd.isna(atr36) or atr36 == 0:
            return None

        # -------------------------------------------------------------
        # MATEMÁTICA DA CONVICÇÃO
        # -------------------------------------------------------------
        diferenca_bruta = ema8 - ema32
        forecast_carver = (diferenca_bruta / atr36) * 5.0
        
        estado = "Observar"
        entrada = "N/A"
        stop_loss = "N/A"
        alvo_tp = "N/A"
        qtd_acoes = "N/A"
        valor_investir = "N/A"
        multiplicador = 0.0

        # Dispara quando a tendência vence a inércia basal (Forecast > +10.0)
        if forecast_carver >= 10.0:
            # Escala a agressividade da posição, com teto nos 2.0 (Alavancagem Máx 200%)
            multiplicador = min(forecast_carver / 10.0, 2.0)
            
            estado = "FAST TREND - Carver Momentum"
            entrada = round(preco, 2)
            
            # Stop largo para acomodar o ruído institucional de longo prazo
            stop_loss = round(entrada - (atr36 * 1.5), 2)
            
            # Alvo simétrico projetado (Pode e deve ser gerido via Trailing)
            alvo_tp = round(entrada + ((entrada - stop_loss) * 2.5), 2)
            
            qtd_bruta = (VOLATILIDADE_ALVO_DIARIA_USD / atr36) * multiplicador
            qtd_acoes = round(qtd_bruta, 2)
            
            val_calc = entrada * qtd_acoes
            valor_investir = f"~{val_calc:.2f} USD"

        else:
            return None

        def limpa(v):
            if pd.isna(v) or v == "N/A": return "N/A"
            return round(float(v), 2)

        linha_comboio = (
            f"{ticker},Nome: {nome_empresa},Setor: {setor},Preço: {limpa(preco)},"
            f"EMA8: {limpa(ema8)},EMA32: {limpa(ema32)},ATR36: {limpa(atr36)},"
            f"Forecast: {limpa(forecast_carver)},Multiplicador: x{limpa(multiplicador)},"
            f"Estado: {estado},Entrada: {limpa(entrada)},Stop: {limpa(stop_loss)},"
            f"Take-Profit: {limpa(alvo_tp)},Qtd: {qtd_acoes},ValorInvestir: {valor_investir},"
            f"Data: {datetime.now(ZoneInfo('Europe/Lisbon')).strftime('%d/%m/%Y %H:%M:%S')}"
        )

        return {
            "ticker": ticker,
            "forecast": forecast_carver,
            "estado": estado,
            "comboio_str": linha_comboio
        }

    except Exception as e:
        print(f"[ERRO] Falha ao processar {ticker}: {e}")
        return None

# ===================================================================
# 4. EXECUÇÃO PRINCIPAL
# ===================================================================
def executar_motor():
    ativos = buscar_watchlist()
    if not ativos:
        sys.exit(1)
        
    ativos_acionados = []
    
    for ativo_info in ativos:
        ticker = ativo_info.get("ticker")
        if not ticker or ticker == "#N/A": continue
        
        res = analisar_tendencia_carver(
            ticker, 
            ativo_info.get("nome", "N/A"), 
            ativo_info.get("setor", "Desconhecido")
        )
        
        if res and res['forecast'] >= 10.0:
            print(f"[SUCESSO] {ticker} ativado no Carver (Forecast: {res['forecast']:.2f})!")
            ativos_acionados.append(res)
            
    # Ordena os ativos pelo valor do Forecast (da maior tendência para a menor)
    ativos_acionados = sorted(ativos_acionados, key=lambda k: k['forecast'], reverse=True)

    prompt_ia = (
        "MODO ACELERADOR ESTATÍSTICO (CARVER FAST TREND)\n"
        "O teu mandato é auditar as entradas geradas pelo sistema dinâmico de Robert Carver. "
        "A matemática já validou que estes ativos estão a expandir-se mais rápido do que a sua volatilidade base.\n\n"
        "🚨 REGRAS DE OURO (ANTI-ALUCINAÇÃO) 🚨\n"
        "1. ZERO CRIATIVIDADE: Não inventes razões fundamentais para a subida.\n"
        "2. A AUDITORIA: Verifica se o Forecast reportado é superior a 10. Quanto mais alto, mais agressivo é o multiplicador de risco aplicado.\n\n"
        "Estrutura Visual Obrigatória:\n"
        "🎯 [TICKER] - [Nome da Empresa] ([Setor])\n"
        "- 🏄‍♂️ ÍMPETO TENDENCIAL: [Lê o campo 'Forecast' e 'Multiplicador']. (Ex: Forecast de 15.2 justiticando um risco alocado de 1.5x)\n"
        "- ⚙️ TÁTICA: CARVER FAST TREND. Deixar o mercado ditar a saída pelo Trailing Stop.\n"
        "- 🔢 DADOS EXATOS: Entrada: X | Stop: X | TP: X | Qtd: X | Valor a Investir: X\n"
        "- 📋 REFERÊNCIA: [Linha do Comboio exata]\n"
    )
    
    bloco_texto_ia = f"📊 RELATÓRIO DE DADOS BRUTOS - FAST TREND CARVER 🏄‍♂️\n\n{prompt_ia}\n\n--------------------------------------------------\n"

    if not ativos_acionados:
        bloco_texto_ia += "[MERCADO LENTO] - Nenhum ativo apresenta aceleração matemática (Forecast > 10) superior ao ruído base.\n"
    else:
        bloco_texto_ia += "DADOS DOS ATIVOS ATIVADOS (COMBOIO):\n\n"
        for item in ativos_acionados:
            bloco_texto_ia += item["comboio_str"] + "\n"

    with open("comboio_carver_temp.txt", "w", encoding="utf-8") as f:
        f.write(bloco_texto_ia)

    enviar_email(bloco_texto_ia)

if __name__ == "__main__":
    executar_motor()
