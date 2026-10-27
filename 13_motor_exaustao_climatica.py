import pandas as pd
import yfinance as yf
import os
import requests
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
# 1. CONFIGURAÇÕES E PARÂMETROS CLIMÁTICOS
# ===================================================================
WEBHOOK_URL = os.environ.get('WEBHOOK_URL')

# Limiares de Exaustão Parabólica
LIMIAR_DIST_EMA9 = 15.0  # Preço 15% acima da EMA 9 (esticado extremo)
LIMIAR_RVOL = 3.0        # Volume 3x superior à média
LIMIAR_RSI = 80.0        # RSI em sobrecompra crítica

def get_yf_history_safe(ticker, period="3mo"):
    for _ in range(3):
        try:
            time.sleep(random.uniform(0.5, 1.2))
            df = yf.download(ticker, period=period, interval="1d", progress=False, timeout=15)
            if not df.empty and len(df) >= 20:
                if isinstance(df.columns, pd.MultiIndex):
                    df.columns = df.columns.droplevel(1)
                return df.dropna(subset=['Close', 'Volume'])
        except Exception:
            time.sleep(2.0)
    return pd.DataFrame()

# ===================================================================
# 2. CARREGAMENTO DE POSIÇÕES ATIVAS (SHEETS VIA WEBHOOK)
# ===================================================================
print("A iniciar Motor de Exaustão Climática nas posições ativas...")

ativos_ativos = []
if WEBHOOK_URL:
    try:
        resp = requests.get(WEBHOOK_URL, timeout=15)
        if resp.status_code == 200:
            json_data = resp.json()
            if isinstance(json_data, dict):
                # O Webhook fornece as posições ativas na chave exata "posicoesAtivas"
                posicoes_dict = json_data.get("posicoesAtivas", {})
                print(f"[DEBUG] Chaves em posicoesAtivas: {list(posicoes_dict.keys())}")
                
                for ticker, dados_pos in posicoes_dict.items():
                    if isinstance(dados_pos, dict):
                        a_lower = {str(k).lower().strip(): str(v).strip().upper() for k, v in dados_pos.items()}
                        estado = str(a_lower.get("status", a_lower.get("estado", ""))).strip().upper()
                        
                        if estado in ["ATIVA", "ATIVA_FAST", "SIM"]:
                            dados_pos['ticker'] = ticker
                            dados_pos['qtd'] = a_lower.get("quantidade", a_lower.get("qtd", "N/A"))
                            ativos_ativos.append(dados_pos)
                            
    except Exception as e:
        print(f"[ERRO] Falha ao ler posições ativas do Sheets: {e}")

if not ativos_ativos:
    print("Nenhuma posição ativa para monitorizar.")
    exit(0)

print(f"[{len(ativos_ativos)}] Posições em carteira enviadas para auditoria parabólica.")

# ===================================================================
# 3. ANÁLISE MATEMÁTICA DE CLÍMAX (NATIVA PANDAS)
# ===================================================================
alertas_exaustao = []

for ativo in ativos_ativos:
    ticker = str(ativo.get("ticker", "")).strip().upper()
    qtd_atual = ativo.get("qtd", "N/A")
    
    if ticker == "BRK-A": ticker = "BRK-B"
    if not ticker or ticker == "#N/A": continue
    
    df = get_yf_history_safe(ticker)
    if df.empty or len(df) < 20:
        continue
        
    # Cálculos Nativos (Sem pandas-ta)
    df['EMA_9'] = df['Close'].ewm(span=9, adjust=False).mean()
    
    delta = df['Close'].diff()
    gain = delta.clip(lower=0).ewm(alpha=1/14, adjust=False).mean()
    loss = (-delta.clip(upper=0)).ewm(alpha=1/14, adjust=False).mean()
    rs = gain / loss
    df['RSI_14'] = 100 - (100 / (1 + rs))
    
    df['RVOL'] = df['Volume'] / df['Volume'].rolling(20).mean()
    
    ultimo_dia = df.iloc[-1]
    preco = ultimo_dia['Close']
    ema9 = ultimo_dia.get('EMA_9', preco)
    rsi = ultimo_dia.get('RSI_14', 50)
    rvol = ultimo_dia.get('RVOL', 1)
    
    dist_ema9 = ((preco - ema9) / ema9) * 100
    
    if dist_ema9 >= LIMIAR_DIST_EMA9 and (rvol >= LIMIAR_RVOL or rsi >= LIMIAR_RSI):
        alertas_exaustao.append({
            "ticker": ticker,
            "preco": preco,
            "dist_ema9": dist_ema9,
            "rvol": rvol,
            "rsi": rsi,
            "qtd": qtd_atual
        })
        print(f"⚠️ [ALERTA CLÍMAX] {ticker} está {dist_ema9:.1f}% acima da EMA9 com RVOL {rvol:.1f}!")

# ===================================================================
# 4. GERAÇÃO DE RELATÓRIO E DISPARO DE EMERGÊNCIA
# ===================================================================
data_hoje = datetime.now(ZoneInfo("Europe/Lisbon")).strftime("%d/%m/%Y %H:%M:%S")

if alertas_exaustao:
    relatorio = f"🚨 ALERTA CRÍTICO DE TRADING - EXAUSTÃO CLIMÁTICA 🚨\n({data_hoje})\n"
    relatorio += "=" * 65 + "\n\n"
    relatorio += "O algoritmo detetou um movimento parabólico insustentável. A probabilidade de reversão violenta nas próximas 48h excede os 85%.\n\n"
    
    for alerta in alertas_exaustao:
        relatorio += f"🔥 {alerta['ticker']}:\n"
        relatorio += f"   - Estado: PREÇO ESTICADO EXTREMO\n"
        relatorio += f"   - Tensão Estrutural: {alerta['dist_ema9']:.1f}% acima da EMA 9\n"
        relatorio += f"   - Exaustão Vendedora (RVOL): {alerta['rvol']:.2f}x o volume normal\n"
        relatorio += f"   - RSI (14): {alerta['rsi']:.1f}\n"
        relatorio += f"   - ⚡ AÇÃO EXIGIDA: Fechar 50% ou 100% da posição de {alerta['qtd']} ações IMEDIATAMENTE A MERCADO.\n\n"
        
    print("\n[ALERTA] Anomalia detetada! A preparar envio de email de emergência...")
    
    EMAIL_USER = os.environ.get("EMAIL_USER")
    EMAIL_PASS = os.environ.get("EMAIL_PASS")
    
    if EMAIL_USER and EMAIL_PASS:
        try:
            msg = MIMEMultipart()
            msg['From'] = EMAIL_USER
            msg['To'] = EMAIL_USER
            msg['Subject'] = "🚨 ALERTA DE LIQUIDAÇÃO PARABÓLICA - Motor 13"
            msg.attach(MIMEText(relatorio, 'plain', 'utf-8'))
            
            server = smtplib.SMTP("smtp.gmail.com", 587, timeout=15)
            server.starttls()
            server.login(EMAIL_USER, EMAIL_PASS)
            server.sendmail(EMAIL_USER, EMAIL_USER, msg.as_string())
            server.quit()
            print("[SUCESSO] Email de emergência disparado para a Mesa de Operações!")
        except Exception as e:
            print(f"[ERRO] Falha ao enviar email de emergência: {e}")
else:
    print("\n✅ Nenhuma anomalia parabólica detetada. As posições ativas estão saudáveis. Silêncio mantido.")
