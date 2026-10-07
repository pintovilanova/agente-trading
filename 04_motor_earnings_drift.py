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

RISCO_MAXIMO_DOLARES = 25.00

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
            print(f"[ERRO] Falha ao descarregar dados: {resp.status_code}")
            return []
    except Exception as e:
        print(f"[ERRO CRÍTICO] Falha de comunicação com Sheets: {e}")
        return []

def enviar_email(conteudo):
    print("\nA enviar relatório de Earnings Drift para o Agente IA...")
    if not EMAIL_USER or not EMAIL_PASS:
        print("[AVISO] Credenciais de email em falta. A saltar envio.")
        return
    try:
        msg = MIMEMultipart()
        msg['From'] = EMAIL_USER
        msg['To'] = EMAIL_USER
        msg['Subject'] = "tradingRelatorioIA US - EARNINGS DRIFT & MOMENTUM"
        
        msg.attach(MIMEText(conteudo, 'plain', 'utf-8'))
        
        server = smtplib.SMTP(SMTP_SERVER, SMTP_PORT)
        server.starttls()
        server.login(EMAIL_USER, EMAIL_PASS)
        server.sendmail(EMAIL_USER, EMAIL_USER, msg.as_string())
        server.quit()
        print("[SUCESSO] Email de Earnings enviado!")
    except Exception as e:
        print(f"[ERRO] Falha ao enviar email: {e}")

# ===================================================================
# 3. MOTOR MATEMÁTICO: EARNINGS DRIFT (PEAD)
# ===================================================================
def analisar_earnings_drift(ticker, nome_empresa, setor):
    try:
        ticker_obj = yf.Ticker(ticker)
        
        df = ticker_obj.history(period="3mo")
        if df.empty:
            return None
            
        if isinstance(df.columns, pd.MultiIndex):
            df.columns = df.columns.droplevel(1)

        df.ta.atr(length=14, append=True)
        df.ta.sma(length=20, append=True)
        df.ta.ema(length=9, append=True)
        
        media_volume_20 = df['Volume'].rolling(window=20).mean()
        df['RVOL'] = df['Volume'] / media_volume_20

        earnings_recente = False
        data_earnings_str = "N/A"
        
        try:
            earnings_df = ticker_obj.earnings_dates
            if earnings_df is not None and not earnings_df.empty:
                hoje = datetime.now(ZoneInfo("Europe/Lisbon")).date()
                for idx, row in earnings_df.head(3).iterrows():
                    if hasattr(idx, 'date'):
                        d_earn = idx.date()
                    else:
                        d_earn = pd.to_datetime(idx).date()
                    
                    dias_passados = (hoje - d_earn).days
                    if 0 <= dias_passados <= 5:
                        earnings_recente = True
                        data_earnings_str = d_earn.strftime('%d/%m/%Y')
                        break
        except Exception:
            pass

        if not earnings_recente:
            return None

        ultimo_dia = df.iloc[-1]
        dia_anterior = df.iloc[-2]

        preco = ultimo_dia['Close']
        preco_anterior = dia_anterior['Close']
        var_perc = ((preco - preco_anterior) / preco_anterior) * 100
        rvol = ultimo_dia['RVOL']
        minimo_dia = ultimo_dia['Low']

        if var_perc >= 2.0 and rvol >= 2.0:
            estado = "EARNINGS MOMENTUM - Drift Detetado"
            entrada = round(preco, 2)
            stop_loss = round(minimo_dia * 0.99, 2)
            alvo_tp = round(entrada + ((entrada - stop_loss) * 2.0), 2)
            
            risco = entrada - stop_loss
            qtd_acoes = round(RISCO_MAXIMO_DOLARES / risco, 2) if risco > 0 else "N/A"
            valor_investir = f"~{(entrada * float(qtd_acoes)):.2f} USD" if qtd_acoes != "N/A" else "N/A"
        else:
            return None

        def limpa(v):
            if pd.isna(v) or v == "N/A": return "N/A"
            return round(float(v), 2)

        linha_comboio = (
            f"{ticker},Nome: {nome_empresa},Setor: {setor},Preço: {limpa(preco)},"
            f"DataEarnings: {data_earnings_str},VarDia: {limpa(var_perc)}%,RVOL: {limpa(rvol)},"
            f"Estado: {estado},Entrada: {limpa(entrada)},Stop: {limpa(stop_loss)},"
            f"Take-Profit: {limpa(alvo_tp)},Qtd: {qtd_acoes},ValorInvestir: {valor_investir},"
            f"Data: {datetime.now(ZoneInfo('Europe/Lisbon')).strftime('%d/%m/%Y %H:%M:%S')}"
        )

        return {
            "ticker": ticker,
            "preco": limpa(preco),
            "data_earnings": data_earnings_str,
            "var_perc": f"{limpa(var_perc)}%",
            "rvol": limpa(rvol),
            "estado": estado,
            "entrada": limpa(entrada),
            "stop": limpa(stop_loss),
            "tp": limpa(alvo_tp),
            "qtd": qtd_acoes,
            "valor_investir": valor_investir,
            "comboio_str": linha_comboio
        }

    except Exception as e:
        print(f"[ERRO] Falha ao processar {ticker} para Earnings Drift: {e}")
        return None

# ===================================================================
# 4. EXECUÇÃO PRINCIPAL E INTEGRAÇÃO (Sheets + Email)
# ===================================================================
def executar_motor():
    # Inicialização obrigatória das variáveis no topo da função
    resultados_para_sheets = []
    comboio_ia = []
    
    ativos = buscar_watchlist()
    if not ativos:
        sys.exit(1)
        
    for ativo_info in ativos:
        ticker = ativo_info.get("ticker")
        if not ticker or ticker == "#N/A": continue
        
        res = analisar_earnings_drift(
            ticker, 
            ativo_info.get("nome", "N/A"), 
            ativo_info.get("setor", "Desconhecido")
        )
        
        if res:
            print(f"[SUCESSO] {ticker} ativado no motor PEAD!")
            resultados_para_sheets.append({
                "ticker": res['ticker'],
                "preco": res['preco'],
                "data_earnings": res['data_earnings'],
                "var_perc": res['var_perc'],
                "rvol": res['rvol'],
                "estado": res['estado'],
                "entrada": res['entrada'],
                "stop": res['stop'],
                "tp": res['tp'],
                "qtd": res['qtd'],
                "valor_investir": res['valor_investir'],
                "time": datetime.now(ZoneInfo("Europe/Lisbon")).strftime('%d/%m/%Y %H:%M:%S'),
                "comboio": res['comboio_str']
            })
            comboio_ia.append(res['comboio_str'])

    # Atualizar o Google Sheets (Aba: Earnings Drift)
    if WEBHOOK_URL:
        print("\nA atualizar o Google Sheets (Aba: Earnings Drift)...")
        try:
            payload_sheets = {
                "acao": "atualizar_earnings_drift",
                "aba": "Earnings Drift",
                "dados": resultados_para_sheets
            }
            headers = {'Content-Type': 'application/json'}
            resposta = requests.post(WEBHOOK_URL, data=json.dumps(payload_sheets), headers=headers)
            if resposta.status_code == 200:
                print("[SUCESSO] Google Sheets atualizado com sucesso!")
            else:
                print(f"[ERRO] Status HTTP: {resposta.status_code} - {resposta.text}")
        except Exception as e:
            print(f"[ERRO CRÍTICO] Falha HTTP Sheets: {e}")

    # Construção do Prompt e Envio de Email para o Agente IA
    prompt_ia = (
        "MODO CAÇADOR DE EARNINGS DRIFT (PEAD)\n"
        "O teu mandato é identificar empresas que surpreenderam o mercado nos resultados trimestrais e dispararam com volume institucional maciço.\n"
        "Estamos a surfar a onda de revisão em alta de lucros pelos analistas.\n\n"
        "Regras de Validação:\n"
        "1. VALIDAÇÃO DO CATALISADOR: Confirma se o volume (RVOL >= 2.0) e a variação de preço validam a forte entrada de fundos após os resultados.\n"
        "2. TÁTICA DE SAÍDA: O rácio de risco é superior (2:1), permitindo surfar o movimento com o Stop Loss bem protegido abaixo do mínimo da vela de arranque.\n\n"
        "Estrutura Visual Obrigatória:\n"
        "🎯 [TICKER] - [Nome da Empresa] ([Setor])\n"
        "- 🚀 CATALISADOR DE EARNINGS: [Data e Variação Pós-Resultados]\n"
        "- 🩸 PEGADA INSTITUCIONAL: [RVOL Elevado]\n"
        "- ⚙️ TÁTICA: EARNINGS DRIFT. Surfar tendência com rácio 2:1.\n"
        "- 🔢 DADOS EXATOS: Entrada: X | Stop: X | TP: X | Qtd: X | Valor a Investir: X\n"
        "- 📋 REFERÊNCIA: [Linha do Comboio]\n"
    )
    
    bloco_texto_ia = f"{prompt_ia}\n--------------------------------------------------\n"
    
    if not comboio_ia:
        bloco_texto_ia += "[SEM OPORTUNIDADES PEAD] - Nenhuma ação da Watchlist apresentou resultados com desvio explosivo nos últimos dias.\n"
    else:
        bloco_texto_ia += "DADOS DOS ATIVOS EM EARNINGS DRIFT (COMBOIO):\n\n"
        for linha in comboio_ia:
            bloco_texto_ia += linha + "\n"
            
    with open("comboio_earnings_temp.txt", "w", encoding="utf-8") as f:
        f.write(bloco_texto_ia)
        
    enviar_email(bloco_texto_ia)

if __name__ == "__main__":
    executar_motor()
