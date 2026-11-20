# ===================================================================
# SISTEMA DE TRADING INSTITUCIONAL - MOTOR 11 (ROTAÇÃO SETORIAL)
# ===================================================================
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
import requests
import warnings
warnings.filterwarnings("ignore")

from F01_notificador_telegram import enviar_alerta

# ===================================================================
# BYPASS SESSÃO YAHOO FINANCE (PARA GITHUB ACTIONS)
# ===================================================================
session = requests.Session()
session.headers.update({
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
})

# ===================================================================
# 0. TRAVA DE FIM DE SEMANA
# ===================================================================
dia_da_semana = datetime.now(ZoneInfo("Europe/Lisbon")).weekday()
if dia_da_semana >= 5:
    print("[INFO] Fim de semana detetado. O Motor 11 (Rotação Setorial) vai descansar.")
    # sys.exit(0)

# ===================================================================
# 1. CONFIGURAÇÃO E MAPA DE ETFS SETORIAIS (PT + EN PARA ORQUESTRADOR)
# ===================================================================
WEBHOOK_URL = os.environ.get('WEBHOOK_URL')
EMAIL_USER = os.environ.get("EMAIL_USER")
EMAIL_PASS = os.environ.get("EMAIL_PASS")

if EMAIL_USER:
    EMAIL_USER = EMAIL_USER.strip()
if EMAIL_PASS:
    EMAIL_PASS = EMAIL_PASS.strip()

SMTP_SERVER = "smtp.gmail.com"
SMTP_PORT = 587

ETFS_SETORIAIS = {
    "XLK": {"pt": "Tecnologia", "en": "Technology", "tipo": "CICLICO"},
    "XLF": {"pt": "Financeiro", "en": "Financial Services", "tipo": "CICLICO"},
    "XLV": {"pt": "Saúde", "en": "Healthcare", "tipo": "DEFENSIVO"},
    "XLY": {"pt": "Consumo Discrecionário", "en": "Consumer Cyclical", "tipo": "CICLICO"},
    "XLP": {"pt": "Consumo Básico", "en": "Consumer Defensive", "tipo": "DEFENSIVO"},
    "XLE": {"pt": "Energia", "en": "Energy", "tipo": "CICLICO"},
    "XLI": {"pt": "Industrial", "en": "Industrials", "tipo": "CICLICO"},
    "XLB": {"pt": "Materiais Básicos", "en": "Basic Materials", "tipo": "CICLICO"},
    "XLU": {"pt": "Utilities (Serviços Públicos)", "en": "Utilities", "tipo": "DEFENSIVO"},
    "XLRE": {"pt": "Imobiliário (Real Estate)", "en": "Real Estate", "tipo": "DEFENSIVO"},
    "XLC": {"pt": "Serviços de Comunicação", "en": "Communication Services", "tipo": "CICLICO"}
}

def gravar_ficheiro_rotacao(conteudo):
    with open("comboio_rotacao_temp.txt", "w", encoding="utf-8") as f:
        f.write(conteudo)

def enviar_email(assunto, corpo_texto):
    if not EMAIL_USER or not EMAIL_PASS:
        print("[AVISO] EMAIL_USER ou EMAIL_PASS não definidos. Email não enviado.")
        return False
    for tentativa in range(3):
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
            print(f"[ERRO] Falha ao enviar email (tentativa {tentativa + 1}): {e}")
            if tentativa < 2:
                time.sleep(5)
    return False

def get_yf_data(ticker, period="1y"):
    for _ in range(3):
        try:
            df = yf.download(ticker, period=period, interval="1d", progress=False, session=session, timeout=15)
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
data_hoje = datetime.now(ZoneInfo("Europe/Lisbon")).strftime("%d/%m/%Y %H:%M:%S")

try:
    df_spy = get_yf_data("SPY", "1y")
    if df_spy.empty or len(df_spy) < 65:
        print("[ERRO CRÍTICO] Não foi possível obter dados suficientes do SPY.")
        gravar_ficheiro_rotacao(f"⚠️ MOTOR 11 - ROTAÇÃO SETORIAL ({data_hoje})\nDados SPY indisponíveis para cálculo de Alpha Setorial.\n")
        sys.exit(1)

    spy_close = float(df_spy['Close'].iloc[-1])
    spy_ret_1w = ((spy_close - float(df_spy['Close'].iloc[-6])) / float(df_spy['Close'].iloc[-6])) * 100
    spy_ret_1m = ((spy_close - float(df_spy['Close'].iloc[-22])) / float(df_spy['Close'].iloc[-22])) * 100
    spy_ret_3m = ((spy_close - float(df_spy['Close'].iloc[-64])) / float(df_spy['Close'].iloc[-64])) * 100

    resultados = []
    total_analisados = 0

    for ticker, meta in ETFS_SETORIAIS.items():
        total_analisados += 1
        time.sleep(random.uniform(0.25, 0.55))
        df_etf = get_yf_data(ticker, "1y")
        if df_etf.empty or len(df_etf) < 65:
            continue

        df_etf['EMA_20'] = df_etf['Close'].ewm(span=20, adjust=False).mean()
        df_etf['SMA_50'] = df_etf['Close'].rolling(window=50).mean()

        close_atual = float(df_etf['Close'].iloc[-1])
        ema20_atual = float(df_etf['EMA_20'].iloc[-1])
        sma50_atual = float(df_etf['SMA_50'].iloc[-1])

        close_1w = float(df_etf['Close'].iloc[-6])
        close_1m = float(df_etf['Close'].iloc[-22])
        close_3m = float(df_etf['Close'].iloc[-64])

        ret_1w = ((close_atual - close_1w) / close_1w) * 100
        ret_1m = ((close_atual - close_1m) / close_1m) * 100
        ret_3m = ((close_atual - close_3m) / close_3m) * 100

        # Força Relativa Homogénea (Alpha vs SPY em 1W, 1M e 3M)
        alpha_1w = ret_1w - spy_ret_1w
        alpha_1m = ret_1m - spy_ret_1m
        alpha_3m = ret_3m - spy_ret_3m
        score_rotacao = (alpha_1w * 0.40) + (alpha_1m * 0.40) + (alpha_3m * 0.20)

        if close_atual > ema20_atual and ema20_atual > sma50_atual:
            tendencia_etf = "ALTA (Preço > EMA20 > SMA50)"
        elif close_atual < sma50_atual:
            tendencia_etf = "BAIXA (< SMA50)"
        else:
            tendencia_etf = "LATERAL / PULLBACK"

        resultados.append({
            'ticker': ticker,
            'setor': meta['pt'],
            'setor_en': meta['en'],
            'tipo': meta['tipo'],
            'preco': close_atual,
            'ret_1w': ret_1w,
            'ret_1m': ret_1m,
            'ret_3m': ret_3m,
            'alpha_1w': alpha_1w,
            'alpha_1m': alpha_1m,
            'alpha_3m': alpha_3m,
            'tendencia': tendencia_etf,
            'score': score_rotacao
        })

    if not resultados:
        gravar_ficheiro_rotacao(f"⚠️ MOTOR 11 - ROTAÇÃO SETORIAL ({data_hoje})\nSem dados setoriais disponíveis hoje.\n")
        sys.exit(1)

    df_res = pd.DataFrame(resultados).sort_values(by='score', ascending=False).reset_index(drop=True)

    # ===================================================================
    # 3. DIAGNÓSTICO DE APETITE AO RISCO (RISK-ON VS RISK-OFF)
    # ===================================================================
    lideres = df_res.head(3)
    laggards = df_res.tail(3)

    qtd_defensivos_top3 = int((lideres['tipo'] == 'DEFENSIVO').sum())
    if qtd_defensivos_top3 >= 2:
        vies_rotacao = "🛡️ ROTAÇÃO DEFENSIVA (RISK-OFF) — Capital institucional a refugiar-se em setores defensivos (Utilities/Consumo Básico/Saúde). Reduzir exposição agressiva em Breakouts."
    elif qtd_defensivos_top3 == 1:
        vies_rotacao = "⚖️ ROTAÇÃO MISTA / SELETIVA — Fluxo dividido entre líderes cíclicos e proteção defensiva. Priorizar apenas ações nos setores Top 3."
    else:
        vies_rotacao = "🚀 ROTAÇÃO EXPANSIONISTA (RISK-ON) — Fluxo institucional concentrado em setores cíclicos/crescimento. Vento a favor para Breakouts e Momentum."

    setores_favorecidos_en = ", ".join([f"{r['setor_en']} ({r['ticker']})" for _, r in lideres.iterrows()])
    setores_evitar_en = ", ".join([f"{r['setor_en']} ({r['ticker']})" for _, r in laggards.iterrows()])

    # ===================================================================
    # 4. RELATÓRIO E SAÍDA PARA O ORQUESTRADOR
    # ===================================================================
    conteudo_relatorio = f"🏆 MOTOR 11 - ROTAÇÃO SETORIAL & FLUXO DE CAPITAL ({data_hoje})\n"
    conteudo_relatorio += "=" * 75 + "\n"
    conteudo_relatorio += f"📊 Benchmark SPY: ${spy_close:.2f} | 1W: {spy_ret_1w:+.2f}% | 1M: {spy_ret_1m:+.2f}% | 3M: {spy_ret_3m:+.2f}%\n"
    conteudo_relatorio += f"🧭 VIÉS MACRO DE FLUXO: {vies_rotacao}\n"
    conteudo_relatorio += f"✅ SETORES FAVORECIDOS (EN): {setores_favorecidos_en}\n"
    conteudo_relatorio += f"🚫 SETORES A EVITAR (EN): {setores_evitar_en}\n"
    conteudo_relatorio += "=" * 75 + "\n\n"

    conteudo_relatorio += "🔥 SETORES LÍDERES (FLUXO INSTITUCIONAL DE ENTRADA / ACUMULAÇÃO):\n"
    for _, r in lideres.iterrows():
        conteudo_relatorio += (
            f"• {r['ticker']} - {r['setor']} [{r['setor_en']}]: Preço ${r['preco']:.2f} | "
            f"1W: {r['ret_1w']:+.2f}% (Alpha: {r['alpha_1w']:+.2f}%) | "
            f"1M: {r['ret_1m']:+.2f}% (Alpha: {r['alpha_1m']:+.2f}%) | "
            f"Tendência: {r['tendencia']} | Score: {r['score']:+.2f}\n"
        )

    conteudo_relatorio += "\n❄️ SETORES LAGGARDS (SAÍDA DE CAPITAL / DISTRIBUIÇÃO):\n"
    for _, r in laggards.iterrows():
        conteudo_relatorio += (
            f"• {r['ticker']} - {r['setor']} [{r['setor_en']}]: Preço ${r['preco']:.2f} | "
            f"1W: {r['ret_1w']:+.2f}% (Alpha: {r['alpha_1w']:+.2f}%) | "
            f"1M: {r['ret_1m']:+.2f}% (Alpha: {r['alpha_1m']:+.2f}%) | "
            f"Tendência: {r['tendencia']} | Score: {r['score']:+.2f}\n"
        )

    conteudo_relatorio += "\n📋 RANKING COMPLETO DE FLUXO DE CAPITAL (11 SETORES S&P 500):\n"
    for i, (_, r) in enumerate(df_res.iterrows(), 1):
        status = "🟢 LÍDER" if i <= 3 else ("🔴 LAGGARD" if i >= 9 else "🟡 NEUTRO")
        conteudo_relatorio += (
            f"{i:02d}. [{status}] {r['ticker']} - {r['setor']} ({r['tipo']}): "
            f"Score {r['score']:+.2f} | 1W: {r['ret_1w']:+.2f}% | 1M: {r['ret_1m']:+.2f}% | 3M: {r['ret_3m']:+.2f}% | {r['tendencia']}\n"
        )

    # Guardar no ficheiro temporário para o Orquestrador ler
    gravar_ficheiro_rotacao(conteudo_relatorio)

    print("\n" + conteudo_relatorio)
    print("[SUCESSO] Relatório temporário 'comboio_rotacao_temp.txt' gerado!")

    # Enviar e-mail de notificação de rotação
    enviar_email(
        f"tradingRelatorioIA US - 🔄 ROTAÇÃO SETORIAL ({datetime.now(ZoneInfo('Europe/Lisbon')).strftime('%d/%m/%Y')})",
        conteudo_relatorio
    )

    # ===================================================================
    # 5. NOTIFICAÇÃO TELEGRAM DEBUG (CONTROLADA PELA FLAG DE CONFIGS)
    # ===================================================================
    debug_telegram_ativado = False
    try:
        if WEBHOOK_URL:
            url_alvo = WEBHOOK_URL if "?" in WEBHOOK_URL else f"{WEBHOOK_URL}?aba=Analise Compra"
            resp_cfg = requests.get(url_alvo, timeout=10)
            if resp_cfg.status_code == 200:
                dados_cfg = resp_cfg.json()
                if isinstance(dados_cfg, dict):
                    configs_dict = dados_cfg.get("configs", {})
                    debug_telegram_ativado = str(configs_dict.get("TELEGRAM_NOTIFICATIONS_DEBUG", "false")).strip().lower() in ["true", "1", "sim", "yes"]
    except Exception:
        pass

    if debug_telegram_ativado:
        print("A enviar notificação de Debug para o Telegram via função modular...")
        top3_str = ", ".join([f"{r['ticker']} ({r['score']:+.1f})" for _, r in lideres.iterrows()])
        mensagem_debug = (
            f"11 🏆 *ROTAÇÃO SETORIAL*\n\n"
            f"🔍 Execução concluída com sucesso.\n"
            f"📊 Setores analisados: *{total_analisados}* | Top 3: *{top3_str}*\n"
            f"🧭 {vies_rotacao.split('—')[0].strip()}"
        )
        enviar_alerta(mensagem_debug)

except Exception as e:
    print(f"[ERRO CRÍTICO] Falha no Motor de Rotação Setorial: {e}")
    gravar_ficheiro_rotacao(f"⚠️ MOTOR 11 - ERRO CRÍTICO ({data_hoje}): {e}\n")
    sys.exit(1)
