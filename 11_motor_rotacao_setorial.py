import yfinance as yf
import pandas as pd
import numpy as np
import os
import sys
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from datetime import datetime
from zoneinfo import ZoneInfo
import time
import random
import warnings
warnings.filterwarnings("ignore")

# ===================================================================
# 1. CONFIGURAÇÃO E MAPA DE ETFS SETORIAIS
# ===================================================================
EMAIL_USER = os.environ.get("EMAIL_USER")
EMAIL_PASS = os.environ.get("EMAIL_PASS")
SMTP_SERVER = "smtp.gmail.com"
SMTP_PORT = 587

ETFS_SETORIAIS = {
    "XLK": "Tecnologia",
    "XLF": "Financeiro",
    "XLV": "Saúde",
    "XLY": "Consumo Discrecionário",
    "XLP": "Consumo Básico",
    "XLE": "Energia",
    "XLI": "Industrial",
    "XLB": "Materiais Básicos",
    "XLU": "Utilities (Serviços Públicos)",
    "XLRE": "Imobiliário (Real Estate)",
    "XLC": "Serviços de Comunicação"
}

def enviar_email(assunto, corpo_texto):
    if not EMAIL_USER or not EMAIL_PASS:
        print("[AVISO] EMAIL_USER ou EMAIL_PASS não definidos. Email não enviado.")
        return False
    try:
        msg = MIMEMultipart()
        msg['From'] = EMAIL_USER
        msg['To'] = EMAIL_USER
        msg['Subject'] = assunto
        msg.attach(MIMEText(corpo_texto, 'plain', 'utf-8'))
        
        server = smtplib.SMTP(SMTP_SERVER, SMTP_PORT, timeout=15)
        server.starttls()
        server.login(EMAIL_USER, EMAIL_PASS)
        server.sendmail(EMAIL_USER, EMAIL_USER, msg.as_string())
        server.quit()
        print(f"[SUCESSO] Email '{assunto}' enviado com sucesso!")
        return True
    except Exception as e:
        print(f"[ERRO] Falha ao enviar email: {e}")
        return False

# Função corrigida com "1y" por padrão para evitar parâmetros inválidos
def get_yf_data(ticker, period="1y"):
    for _ in range(3):
        try:
            df = yf.download(ticker, period=period, interval="1d", progress=False, timeout=15)
            if not df.empty:
                if isinstance(df.columns, pd.MultiIndex):
                    df.columns = df.columns.droplevel(1)
                return df.dropna(subset=['Close'])
        except Exception:
            pass
        time.sleep(random.uniform(0.5, 1.2))
    return pd.DataFrame()

# ===================================================================
# 2. CÁLCULO DE FORÇA RELATIVA & ROTAÇÃO DE CAPITAL
# ===================================================================
print("A executar análise de Rotação Setorial e Fluxo de Capital (Money Flow)...")

try:
    df_spy = get_yf_data("SPY", "1y")
    if df_spy.empty:
        print("[ERRO CRÍTICO] Não foi possível obter dados do SPY.")
        sys.exit(1)

    spy_ret_1w = ((df_spy['Close'].iloc[-1] - df_spy['Close'].iloc[-5]) / df_spy['Close'].iloc[-5]) * 100
    spy_ret_1m = ((df_spy['Close'].iloc[-1] - df_spy['Close'].iloc[-21]) / df_spy['Close'].iloc[-21]) * 100

    resultados = []

    for ticker, nome_setor in ETFS_SETORIAIS.items():
        df_etf = get_yf_data(ticker, "1y")
        if df_etf.empty or len(df_etf) < 60:
            continue

        close_atual = float(df_etf['Close'].iloc[-1])
        close_1w = float(df_etf['Close'].iloc[-5])
        close_1m = float(df_etf['Close'].iloc[-21])
        close_3m = float(df_etf['Close'].iloc[-60])

        ret_1w = ((close_atual - close_1w) / close_1w) * 100
        ret_1m = ((close_atual - close_1m) / close_1m) * 100
        ret_3m = ((close_atual - close_3m) / close_3m) * 100

        # Força Relativa vs SPY (Ponderada)
        alpha_1w = ret_1w - spy_ret_1w
        alpha_1m = ret_1m - spy_ret_1m
        score_rotacao = (alpha_1w * 0.40) + (alpha_1m * 0.40) + (ret_3m * 0.20)

        resultados.append({
            'ticker': ticker,
            'setor': nome_setor,
            'preco': close_atual,
            'ret_1w': ret_1w,
            'ret_1m': ret_1m,
            'alpha_1w': alpha_1w,
            'alpha_1m': alpha_1m,
            'score': score_rotacao
        })

    df_res = pd.DataFrame(resultados).sort_values(by='score', ascending=False)

    # ===================================================================
    # 3. RELATÓRIO E SAÍDA PARA O ORQUESTRADOR
    # ===================================================================
    data_hoje = datetime.now(ZoneInfo("Europe/Lisbon")).strftime("%d/%m/%Y %H:%M:%S")
    
    conteudo_relatorio = f"🏆 MOTOR 11 - ROTAÇÃO SETORIAL & FLUXO DE CAPITAL ({data_hoje})\n"
    conteudo_relatorio += "=" * 65 + "\n\n"

    conteudo_relatorio += "🔥 SETORES LÍDERES (FLUXO INSTITUCIONAL DE ENTRADA / ACUMULAÇÃO):\n"
    lideres = df_res.head(3)
    for _, r in lideres.iterrows():
        conteudo_relatorio += f"• {r['ticker']} ({r['setor']}): Preço ${r['preco']:.2f} | 1W: {r['ret_1w']:+.2f}% (vs SPY: {r['alpha_1w']:+.2f}%) | 1M: {r['ret_1m']:+.2f}% | Score: {r['score']:.2f}\n"

    conteudo_relatorio += "\n❄️ SETORES LAGGARDS (SAÍDA DE CAPITAL / DISTRIBUIÇÃO):\n"
    laggards = df_res.tail(3)
    for _, r in laggards.iterrows():
        conteudo_relatorio += f"• {r['ticker']} ({r['setor']}): Preço ${r['preco']:.2f} | 1W: {r['ret_1w']:+.2f}% (vs SPY: {r['alpha_1w']:+.2f}%) | 1M: {r['ret_1m']:+.2f}% | Score: {r['score']:.2f}\n"

    conteudo_relatorio += "\n📋 RANKING COMPLETO DE FLUXO DE CAPITAL:\n"
    for i, (_, r) in enumerate(df_res.iterrows(), 1):
        status = "🟢 LÍDER" if i <= 3 else ("🔴 FRACASSO" if i >= 9 else "🟡 NEUTRO")
        conteudo_relatorio += f"{i:02d}. [{status}] {r['ticker']} - {r['setor']}: Score {r['score']:.2f} (1W: {r['ret_1w']:+.2f}% | 1M: {r['ret_1m']:+.2f}%)\n"

    # Guardar no ficheiro temporário para o Orquestrador ler
    with open("comboio_rotacao_temp.txt", "w", encoding="utf-8") as f:
        f.write(conteudo_relatorio)

    print("\n" + conteudo_relatorio)
    print("[SUCESSO] Relatório temporário 'comboio_rotacao_temp.txt' gerado!")

    # Enviar e-mail de notificação de rotação
    enviar_email(f"tradingRelatorioIA US - 🔄 ROTAÇÃO SETORIAL ({datetime.now(ZoneInfo('Europe/Lisbon')).strftime('%d/%m/%Y')})", conteudo_relatorio)

except Exception as e:
    print(f"[ERRO CRÍTICO] Falha no Motor de Rotação Setorial: {e}")
    sys.exit(1)
