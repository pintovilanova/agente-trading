import pandas as pd
import yfinance as yf
import numpy as np
import os
import glob
import time
import random
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from datetime import datetime
from zoneinfo import ZoneInfo
import warnings
warnings.filterwarnings("ignore")

# ===================================================================
# 1. CONFIGURAÇÕES
# ===================================================================
EMAIL_USER = os.environ.get("EMAIL_USER")
EMAIL_PASS = os.environ.get("EMAIL_PASS")
SMTP_SERVER = "smtp.gmail.com"
SMTP_PORT = 587

# Limiar de correlação considerado perigoso (80%)
LIMIAR_CORRELACAO = 0.80

def get_yf_history_safe(tickers_list, period="6mo"):
    """Descarrega dados em lote com resiliência contra rate-limits (HTTP 429)."""
    df_fechos = pd.DataFrame()
    for ticker in tickers_list:
        for tentativa in range(3):
            try:
                time.sleep(random.uniform(0.5, 1.2))
                df = yf.download(ticker, period=period, interval="1d", progress=False, timeout=15)
                if not df.empty:
                    if isinstance(df.columns, pd.MultiIndex):
                        df.columns = df.columns.droplevel(1)
                    df_fechos[ticker] = df['Close']
                    break
            except Exception:
                time.sleep(2.0)
    return df_fechos.dropna()

def extrair_tickers_dos_comboios():
    """Lê todos os ficheiros temporários para descobrir quais as ações com sinais hoje."""
    arquivos = glob.glob("comboio_*_temp.txt")
    tickers_hoje = set()
    
    for arq in arquivos:
        # Ignoramos a rotação setorial e a macro para focar apenas em sinais de compra
        if "rotacao" in arq or "macro" in arq:
            continue
            
        try:
            with open(arq, "r", encoding="utf-8") as f:
                linhas = f.readlines()
                for linha in linhas:
                    # Formato esperado da linha de sinal: "TICKER,Nome: Empresa,Setor: ..."
                    if "," in linha and "Nome:" in linha:
                        ticker = linha.split(",")[0].strip().upper()
                        if ticker.isalpha() or "-" in ticker:
                            tickers_hoje.add(ticker)
        except Exception:
            pass
            
    return list(tickers_hoje)

# ===================================================================
# 2. MOTOR MATEMÁTICO: MATRIZ DE CORRELAÇÃO DE PEARSON
# ===================================================================
print("A iniciar o Motor de Correlação de Risco (Portfolio Shield)...")

tickers_alvo = extrair_tickers_dos_comboios()

if len(tickers_alvo) < 2:
    relatorio = "🛡️ MOTOR 12 - CORRELAÇÃO DE RISCO\n==================================================\n"
    relatorio += "Nenhum risco de clusterização detetado. Menos de 2 sinais de entrada simultâneos hoje.\n"
    
    with open("comboio_correlacao_temp.txt", "w", encoding="utf-8") as f:
        f.write(relatorio)
    print("Análise concluída: Menos de 2 sinais. Matriz desnecessária hoje.")
    exit(0)

print(f"[{len(tickers_alvo)}] Sinais detetados para análise: {', '.join(tickers_alvo)}")
df_precos = get_yf_history_safe(tickers_alvo, period="6mo")

if df_precos.empty or df_precos.shape[1] < 2:
    print("[ERRO] Falha ao obter dados suficientes para correlação.")
    exit(1)

# Calcular os retornos percentuais diários e a matriz de correlação cruzada
df_retornos = df_precos.pct_change().dropna()
matriz_corr = df_retornos.corr()

# ===================================================================
# 3. GERAÇÃO DE ALERTAS E RESOLUÇÃO DE CONFLITOS
# ===================================================================
data_hoje = datetime.now(ZoneInfo("Europe/Lisbon")).strftime("%d/%m/%Y %H:%M:%S")
relatorio = f"🛡️ MOTOR 12 - ESCUDO DE CORRELAÇÃO DE RISCO ({data_hoje})\n"
relatorio += "=" * 65 + "\n\n"

conflitos_detetados = False
pares_analisados = set()

for i in range(len(matriz_corr.columns)):
    for j in range(i + 1, len(matriz_corr.columns)):
        ticker_1 = matriz_corr.columns[i]
        ticker_2 = matriz_corr.columns[j]
        correlacao = matriz_corr.iloc[i, j]
        
        # Cria um identificador único para o par evitar duplicados
        par = tuple(sorted([ticker_1, ticker_2]))
        if par in pares_analisados:
            continue
        pares_analisados.add(par)
        
        if correlacao >= LIMIAR_CORRELACAO:
            conflitos_detetados = True
            relatorio += f"⚠️ ALERTA DE CONFLITO: [{ticker_1}] e [{ticker_2}]\n"
            relatorio += f"   • Correlação: {correlacao*100:.1f}% (Movimentam-se de forma quase idêntica)\n"
            relatorio += f"   • Diagnóstico: Comprar ambas duplica o risco sistémico da tua carteira no mesmo movimento.\n"
            relatorio += f"   • Ação Tática Exigida: Escolher apenas o ativo com maior RS Score institucional OU executar ambas mas reduzir o lote de ambas para 25% (em vez de 50%).\n\n"

if not conflitos_detetados:
    relatorio += "✅ PIPELINE LIMPA: Os ativos sugeridos hoje para entrada têm baixa correlação entre si.\n"
    relatorio += "O risco sistémico e de setor está pulverizado de forma saudável.\n"

relatorio += "-" * 65 + "\n"
relatorio += "NOTA: Correlação > 80% indica que os fundos institucionais negociam estes ativos como se fossem um único bloco (ex: compra e venda via ETF setorial).\n"

# Guardar localmente para o Orquestrador ler
with open("comboio_correlacao_temp.txt", "w", encoding="utf-8") as f:
    f.write(relatorio)

print(relatorio)
print("\n[SUCESSO] Relatório de Correlação gerado.")
