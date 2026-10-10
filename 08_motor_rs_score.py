# ===================================================================================
# SISTEMA DE TRADING INSTITUCIONAL - MOTOR DE FORÇA RELATIVA (RS SCORE & ROTAÇÃO)
# ===================================================================================

import pandas as pd
import yfinance as yf
from datetime import datetime
from zoneinfo import ZoneInfo
import sys
import os
import requests
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart

# ===================================================================
# 0. TRAVA DE FIM DE SEMANA
# ===================================================================
dia_da_semana = datetime.now(ZoneInfo("Europe/Lisbon")).weekday()
if dia_da_semana >= 5:
    print("[INFO] Fim de semana detetado. O Motor RS Score vai descansar.")
    #sys.exit(0)

# ===================================================================
# 1. CONFIGURAÇÕES E CREDENCIAIS
# ===================================================================
WEBHOOK_URL = os.environ.get('WEBHOOK_URL')
EMAIL_USER = os.environ.get("EMAIL_USER")
EMAIL_PASS = os.environ.get("EMAIL_PASS")

SMTP_SERVER = "smtp.gmail.com"
SMTP_PORT = 587

BENCHMARK = "SPY"
SETORES_ETFS = {
    "Tecnologia": "XLK", "Financeiro": "XLF", "Energia": "XLE", 
    "Saúde": "XLV", "Consumo Discricionário": "XLY", "Indústria": "XLI", 
    "Comunicações": "XLC", "Consumo Básico": "XLP", "Utilities": "XLU", 
    "Imobiliário": "XLRE", "Materiais Básicos": "XLB"
}

# ===================================================================
# 2. FUNÇÕES DE REDE E COMUNICAÇÃO
# ===================================================================
def buscar_watchlist():
    print("A carregar a Watchlist do Google Sheets...")
    if not WEBHOOK_URL: return []
    try:
        resp = requests.get(WEBHOOK_URL)
        if resp.status_code == 200:
            dados = resp.json()
            return dados.get("ativos", []) if isinstance(dados, dict) else dados
        return []
    except Exception as e:
        print(f"[ERRO] Sheets: {e}")
        return []

def atualizar_rs_no_sheets(lista_scores):
    print("\nA enviar atualização de RS Scores para o Google Sheets (Coluna O)...")
    if not WEBHOOK_URL: return
    try:
        payload = {
            "aba": "Analise Compra",
            "acao": "atualizar_rs_score",
            "dados": lista_scores
        }
        resp = requests.post(WEBHOOK_URL, json=payload)
        if resp.status_code == 200:
            print("[SUCESSO] RS Scores gravados na Coluna O do Google Sheets!")
        else:
            print(f"[ERRO] Falha ao atualizar Sheets: Código {resp.status_code}")
    except Exception as e:
        print(f"[ERRO] POST para o Sheets falhou: {e}")

def enviar_email_bruto(conteudo):
    print("\nA enviar dados de Força Relativa para o Agente IA...")
    if not EMAIL_USER or not EMAIL_PASS: return
    try:
        msg = MIMEMultipart()
        msg['From'] = EMAIL_USER
        msg['To'] = EMAIL_USER
        msg['Subject'] = "tradingRelatorioIA US - RS SCORE"
        msg.attach(MIMEText(conteudo, 'plain', 'utf-8'))
        
        server = smtplib.SMTP(SMTP_SERVER, SMTP_PORT)
        server.starttls()
        server.login(EMAIL_USER, EMAIL_PASS)
        server.sendmail(EMAIL_USER, EMAIL_USER, msg.as_string())
        server.quit()
        print("[SUCESSO] Email enviado para o Agente IA!")
    except Exception as e:
        print(f"[ERRO] Falha ao enviar email: {e}")

# ===================================================================
# 3. MATEMÁTICA DA FORÇA RELATIVA
# ===================================================================
def calcular_performance_historica(ticker):
    try:
        df = yf.download(ticker, period="6mo", interval="1d", progress=False)
        if df.empty or len(df) < 120: return None
        if isinstance(df.columns, pd.MultiIndex):
            df.columns = df.columns.droplevel(1)

        preco_atual = float(df['Close'].iloc[-1])
        preco_3m = float(df['Close'].iloc[-63])
        preco_6m = float(df['Close'].iloc[-125])

        perf_3m = ((preco_atual - preco_3m) / preco_3m) * 100
        perf_6m = ((preco_atual - preco_6m) / preco_6m) * 100
        
        composite = (perf_6m * 0.6) + (perf_3m * 0.4)

        return {
            "ticker": ticker, "preco": preco_atual,
            "perf_3m": perf_3m, "perf_6m": perf_6m, "composite": composite
        }
    except Exception:
        return None

# ===================================================================
# 4. EXECUÇÃO PRINCIPAL
# ===================================================================
def executar_radar():
    print(f"A descarregar o Benchmark ({BENCHMARK})...")
    spy_data = calcular_performance_historica(BENCHMARK)
    if not spy_data: sys.exit(1)

    print("A analisar ETFs Setoriais...")
    lista_setores = []
    for nome_setor, ticker in SETORES_ETFS.items():
        dados = calcular_performance_historica(ticker)
        if dados:
            dados['nome'] = nome_setor
            dados['alpha'] = dados['composite'] - spy_data['composite']
            lista_setores.append(dados)
            
    lista_setores = sorted(lista_setores, key=lambda k: k['alpha'], reverse=True)

    print("A analisar Watchlist Pessoal...")
    ativos = buscar_watchlist()
    lista_watchlist = []
    for ativo in ativos:
        ticker = ativo.get("ticker")
        if not ticker or ticker == "#N/A": continue
        dados = calcular_performance_historica(ticker)
        if dados:
            dados['alpha'] = dados['composite'] - spy_data['composite']
            lista_watchlist.append(dados)

    # CÁLCULO DO SCORE RS (1-99)
    dados_para_sheets = []
    if lista_watchlist:
        df_wl = pd.DataFrame(lista_watchlist)
        df_wl['RS_Score'] = df_wl['composite'].rank(pct=True) * 99
        lista_watchlist = df_wl.to_dict('records')
        lista_watchlist = sorted(lista_watchlist, key=lambda k: k['RS_Score'], reverse=True)
        
        # Preparar dados simplificados para gravar no Google Sheets
        for w in lista_watchlist:
            dados_para_sheets.append({"ticker": w['ticker'], "rs_score": int(w['RS_Score'])})

    # ATUALIZAR O GOOGLE SHEETS PRIMEIRO
    if dados_para_sheets:
        atualizar_rs_no_sheets(dados_para_sheets)

    # GERAR RELATÓRIO PARA O AGENTE IA
    prompt_ia = (
        "MODO CIO - RADAR DE LIDERANÇA E FORÇA RELATIVA (RS SCORE)\n"
        "REGRAS DE FORMATAÇÃO E AUDITORIA:\n"
        "1. ROTAÇÃO SETORIAL: Analisa a lista de ETFs. Destaca os líderes absolutos e a sangria.\n"
        "2. INFORMAÇÃO GERAL: Menciona no relatório que os RS Scores foram gravados com sucesso na "
        "base de dados (Google Sheets) para utilização dos algoritmos VCP e Carver durante a semana.\n"
    )

    bloco_texto_ia = f"📊 RELATÓRIO RS SCORE & ROTAÇÃO SETORIAL 🧭\n\n{prompt_ia}\n\n"
    bloco_texto_ia += "--------------------------------------------------\n"
    bloco_texto_ia += f"BENCHMARK (SPY) Composite: {spy_data['composite']:.2f}%\n"
    bloco_texto_ia += "--------------------------------------------------\n"

    bloco_texto_ia += "[ETFS SETORIAIS - RANKING]\n"
    for s in lista_setores:
        status = "🔥 LÍDER" if s['alpha'] > 0 else "🧊 LAGGARD"
        bloco_texto_ia += f"Setor: {s['nome']} ({s['ticker']}) | Alpha vs SPY: {s['alpha']:.2f}% | {status}\n"

    bloco_texto_ia += "\n--------------------------------------------------\n"
    bloco_texto_ia += "[WATCHLIST - TOP 10 RS SCORES (Ativos já gravados no Sheets)]\n"
    for w in lista_watchlist[:10]: # Envia só o Top 10 para o email não ficar gigante
        rs = int(w['RS_Score'])
        bloco_texto_ia += f"Ticker: {w['ticker']} | RS Score: {rs} | Alpha vs SPY: {w['alpha']:.2f}%\n"

    with open("comboio_rs_temp.txt", "w", encoding="utf-8") as f:
        f.write(bloco_texto_ia)

    enviar_email_bruto(bloco_texto_ia)

if __name__ == "__main__":
    executar_radar()
