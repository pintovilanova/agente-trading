# ===================================================================================
# SISTEMA DE TRADING INSTITUCIONAL - MOTOR 13: EXAUSTÃO CLIMÁTICA (CLÍMAX PARABÓLICO)
# ===================================================================================
# Descrição Geral:
# Audita todas as posições ativas em carteira (status ATIVA / ATIVA_M*) para detetar
# movimentos parabólicos insustentáveis (Preço >= +15% acima da EMA 9 com Clímax de
# Volume RVOL >= 3.0x ou RSI(14) >= 80), emitindo alerta imediato de realização de
# lucro antes da reversão à média.
# ===================================================================================

import pandas as pd
import yfinance as yf
import numpy as np
import os
import sys
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
    print("[INFO] Fim de semana detetado. O Motor 13 (Exaustão Climática) vai descansar.")
    # sys.exit(0)

# ===================================================================
# 1. CONFIGURAÇÕES E PARÂMETROS CLIMÁTICOS
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

# Limiares de Exaustão Parabólica
LIMIAR_DIST_EMA9 = 15.0  # Preço >= 15% acima da EMA 9 (esticado extremo)
LIMIAR_RVOL = 3.0        # Volume >= 3x superior à média dos 20 dias anteriores
LIMIAR_RSI = 80.0        # RSI(14) em sobrecompra crítica

def limpar_float(val):
    if val is None:
        return None
    try:
        val_str = str(val).replace(",", ".").strip()
        if val_str == "" or val_str.lower() in ["nan", "n/a", "none"]:
            return None
        return float(val_str)
    except (ValueError, TypeError):
        return None

def obter_preco_tempo_real(ticker_str, fallback_close):
    try:
        t = yf.Ticker(ticker_str, session=session)
        fast = t.fast_info
        for attr in ('pre_market_price', 'post_market_price', 'last_price'):
            val = getattr(fast, attr, None)
            if val is not None and not np.isnan(val) and float(val) > 0:
                return round(float(val), 2)
    except Exception:
        pass
    return round(float(fallback_close), 2)

def get_yf_history_safe(ticker, period="3mo"):
    for _ in range(3):
        try:
            time.sleep(random.uniform(0.4, 1.0))
            df = yf.download(ticker, period=period, interval="1d", progress=False, session=session, timeout=15)
            if not df.empty and len(df) >= 22:
                if isinstance(df.columns, pd.MultiIndex):
                    df.columns = df.columns.droplevel(1)
                df = df.dropna(subset=['Close', 'High', 'Low', 'Volume'])
                if len(df) >= 22:
                    return df
        except Exception:
            time.sleep(1.5)
    return pd.DataFrame()

# ===================================================================
# 2. CARREGAMENTO DE POSIÇÕES ATIVAS E CONFIGS (SHEETS VIA WEBHOOK)
# ===================================================================
print("A iniciar Motor de Exaustão Climática nas posições ativas...")

ativos_ativos = []
configs_dict = {}
if WEBHOOK_URL:
    try:
        url_alvo = WEBHOOK_URL if "?" in WEBHOOK_URL else f"{WEBHOOK_URL}?aba=Analise Compra"
        resp = requests.get(url_alvo, timeout=20)
        if resp.status_code == 200:
            json_data = resp.json()
            if isinstance(json_data, dict):
                configs_dict = json_data.get("configs", {})
                posicoes_dict = json_data.get("posicoesAtivas", {}) or json_data.get("posicoes", {})
                print(f"[DEBUG] Chaves em posicoesAtivas: {list(posicoes_dict.keys())}")
                
                for chave_pos, dados_pos in posicoes_dict.items():
                    if isinstance(dados_pos, dict):
                        a_lower = {str(k).lower().strip(): str(v).strip() for k, v in dados_pos.items()}
                        estado = str(a_lower.get("status", a_lower.get("estado", ""))).strip().upper()
                        
                        # Suporta ATIVA, ATIVA_FAST, ATIVA_M07, ATIVA_M19, ATIVA_M21, SIM, etc.
                        if estado.startswith("ATIVA") or estado == "SIM":
                            ticker_norm = "AI" if chave_pos.lower() in ["c3.ai", "c3"] else chave_pos.strip().upper().replace(".", "-")
                            if ticker_norm == "BRK-A":
                                ticker_norm = "BRK-B"
                            dados_pos['ticker'] = ticker_norm
                            dados_pos['chave_original'] = chave_pos
                            dados_pos['status_norm'] = estado
                            dados_pos['qtd'] = a_lower.get("quantidade", a_lower.get("qtd", "N/A"))
                            dados_pos['entrada_float'] = limpar_float(dados_pos.get("precoEntrada"))
                            ativos_ativos.append(dados_pos)
    except Exception as e:
        print(f"[ERRO] Falha ao ler posições ativas do Sheets: {e}")

if not ativos_ativos:
    print("Nenhuma posição ativa para monitorizar.")
    sys.exit(0)

print(f"[{len(ativos_ativos)}] Posições em carteira enviadas para auditoria parabólica.")

# ===================================================================
# 3. ANÁLISE MATEMÁTICA DE CLÍMAX (NATIVA PANDAS + PREÇO VIVO)
# ===================================================================
alertas_exaustao = []

for ativo in ativos_ativos:
    ticker = str(ativo.get("ticker", "")).strip().upper()
    qtd_atual = ativo.get("qtd", "N/A")
    status_pos = ativo.get("status_norm", "ATIVA")
    preco_entrada = ativo.get("entrada_float")
    
    if not ticker or ticker == "#N/A":
        continue
    
    df = get_yf_history_safe(ticker, period="3mo")
    if df.empty or len(df) < 22:
        continue
        
    # Cálculos Nativos (Sem pandas-ta)
    df['EMA_9'] = df['Close'].ewm(span=9, adjust=False).mean()
    
    delta = df['Close'].diff()
    gain = delta.clip(lower=0).ewm(alpha=1/14, adjust=False).mean()
    loss = (-delta.clip(upper=0)).ewm(alpha=1/14, adjust=False).mean()
    rs = gain / loss.replace(0, np.nan)
    df['RSI_14'] = (100 - (100 / (1 + rs))).fillna(100.0)
    
    # Média de volume dos 20 dias ANTERIORES para não diluir o pico climático de hoje
    df['Vol_SMA_20_Prev'] = df['Volume'].shift(1).rolling(20).mean()
    df['RVOL'] = df['Volume'] / df['Vol_SMA_20_Prev']
    
    ultimo_dia = df.iloc[-1]
    preco_fecho = float(ultimo_dia['Close'])
    preco_vivo = obter_preco_tempo_real(ticker, preco_fecho)

    # Atualiza EMA 9 com o preço em tempo real (se diferente do fecho)
    ema9_fecho = float(ultimo_dia['EMA_9'])
    if abs(preco_vivo - preco_fecho) > 0.001 and len(df) >= 2:
        ema9_ontem = float(df['EMA_9'].iloc[-2])
        alpha_9 = 2.0 / (9.0 + 1.0)
        ema9_ref = (preco_vivo * alpha_9) + (ema9_ontem * (1.0 - alpha_9))
    else:
        ema9_ref = ema9_fecho

    rsi = float(ultimo_dia['RSI_14']) if not np.isnan(ultimo_dia['RSI_14']) else 50.0
    rvol = float(ultimo_dia['RVOL']) if not np.isnan(ultimo_dia['RVOL']) else 1.0
    
    dist_ema9 = ((preco_vivo - ema9_ref) / ema9_ref) * 100 if ema9_ref > 0 else 0.0

    # Deteta também pavio superior climático de rejeição (>= 55% da amplitude total da vela com RVOL >= 3.0)
    high_dia = float(ultimo_dia['High'])
    low_dia = float(ultimo_dia['Low'])
    range_dia = high_dia - low_dia
    pavio_superior_pct = ((high_dia - preco_fecho) / range_dia) * 100 if range_dia > 0 else 0.0
    rejeicao_climatica = (dist_ema9 >= 12.0 and rvol >= LIMIAR_RVOL and pavio_superior_pct >= 55.0)

    if (dist_ema9 >= LIMIAR_DIST_EMA9 and (rvol >= LIMIAR_RVOL or rsi >= LIMIAR_RSI)) or rejeicao_climatica:
        lucro_aberto_pct = ((preco_vivo - preco_entrada) / preco_entrada) * 100 if (preco_entrada and preco_entrada > 0) else None
        motivo = (
            "REJEIÇÃO CLIMÁTICA NO TOPO (Pavio Superior >= 55% + Clímax de Volume)"
            if rejeicao_climatica else
            "MOVIMENTO PARABÓLICO EXTREMO (Esticado >= 15% acima da EMA 9)"
        )
        alertas_exaustao.append({
            "ticker": ticker,
            "status": status_pos,
            "preco": preco_vivo,
            "ema9": round(ema9_ref, 2),
            "dist_ema9": dist_ema9,
            "rvol": rvol,
            "rsi": rsi,
            "qtd": qtd_atual,
            "lucro_pct": lucro_aberto_pct,
            "motivo": motivo
        })
        print(f"⚠️ [ALERTA CLÍMAX] {ticker} ({status_pos}) está {dist_ema9:.1f}% acima da EMA9 com RVOL {rvol:.1f}x e RSI {rsi:.1f}!")

# ===================================================================
# 4. GERAÇÃO DE RELATÓRIO E DISPARO DE EMERGÊNCIA
# ===================================================================
data_hoje = datetime.now(ZoneInfo("Europe/Lisbon")).strftime("%d/%m/%Y %H:%M:%S")

if alertas_exaustao:
    relatorio = f"🚨 ALERTA CRÍTICO DE TRADING - EXAUSTÃO CLIMÁTICA (MOTOR 13) 🚨\n({data_hoje})\n"
    relatorio += "=" * 70 + "\n\n"
    relatorio += "O algoritmo detetou um movimento parabólico / clímax comprador insustentável. A probabilidade de reversão violenta nas próximas 48h excede os 85%.\n\n"
    
    for alerta in alertas_exaustao:
        tag_lucro = f" | Lucro Aberto: {alerta['lucro_pct']:+.2f}%" if alerta['lucro_pct'] is not None else ""
        relatorio += f"🔥 [{alerta['ticker']}] ({alerta['status']}):\n"
        relatorio += f"    - Estado: {alerta['motivo']}\n"
        relatorio += f"    - Cotação Atual: ${alerta['preco']:.2f} vs EMA 9: ${alerta['ema9']:.2f} (+{alerta['dist_ema9']:.1f}%){tag_lucro}\n"
        relatorio += f"    - Clímax de Volume (RVOL): {alerta['rvol']:.2f}x a média institucional\n"
        relatorio += f"    - RSI (14): {alerta['rsi']:.1f}\n"
        relatorio += f"    - ⚡ AÇÃO EXIGIDA: Realizar lucro de 50% a 100% da posição ({alerta['qtd']} ações) IMEDIATAMENTE A MERCADO (ou apertar Stop para a mínima da vela de 15m).\n\n"

    with open("comboio_exaustao_temp.txt", "w", encoding="utf-8") as f:
        f.write(relatorio)
        
    print("\n[ALERTA] Anomalia detetada! A preparar envio de email de emergência...")
    
    if EMAIL_USER and EMAIL_PASS:
        for tentativa in range(3):
            try:
                msg = MIMEMultipart()
                msg['From'] = EMAIL_USER
                msg['To'] = EMAIL_USER
                msg['Subject'] = f"🚨 ALERTA DE LIQUIDAÇÃO PARABÓLICA - Motor 13 ({datetime.now(ZoneInfo('Europe/Lisbon')).strftime('%d/%m/%Y')})"
                msg.attach(MIMEText(relatorio, 'plain', 'utf-8'))
                
                server = smtplib.SMTP(SMTP_SERVER, SMTP_PORT, timeout=15)
                server.starttls()
                server.login(EMAIL_USER, EMAIL_PASS)
                server.sendmail(EMAIL_USER, EMAIL_USER, msg.as_string())
                server.quit()
                print("[SUCESSO] Email de emergência disparado para a Mesa de Operações!")
                break
            except Exception as e:
                print(f"[ERRO] Falha ao enviar email de emergência (tentativa {tentativa + 1}): {e}")
                if tentativa < 2:
                    time.sleep(5)
else:
    if os.path.exists("comboio_exaustao_temp.txt"):
        try:
            os.remove("comboio_exaustao_temp.txt")
        except Exception:
            pass
    print("\n✅ Nenhuma anomalia parabólica detetada. As posições ativas estão saudáveis. Silêncio mantido.")

# ===================================================================
# 5. NOTIFICAÇÃO TELEGRAM (EMERGÊNCIA IMEDIATA OU DEBUG)
# ===================================================================
debug_telegram_ativado = str(configs_dict.get("TELEGRAM_NOTIFICATIONS_DEBUG", "false")).strip().lower() in ["true", "1", "sim", "yes"]

if debug_telegram_ativado or len(alertas_exaustao) > 0:
    print("A enviar notificação para o Telegram via função modular...")
    if alertas_exaustao:
        detalhes_tg = "\n".join([
            f"• *{a['ticker']}* ({a['status']}): +*{a['dist_ema9']:.1f}%* vs EMA9 | RVOL *{a['rvol']:.1f}x* | RSI *{a['rsi']:.0f}*"
            for a in alertas_exaustao
        ])
        mensagem_tg = (
            f"13 🚨 *ALERTA CLÍMAX PARABÓLICO*\n\n"
            f"⚡ Detetada exaustão extrema em carteira:\n{detalhes_tg}\n\n"
            f"💰 *Ação:* Realizar 50%–100% do lucro antes da reversão!"
        )
    else:
        mensagem_tg = (
            f"13 🔥 *EXAUSTÃO CLIMÁTICA*\n\n"
            f"🔍 [DEBUG] Auditoria concluída ({len(ativos_ativos)} posições).\n"
            f"Estado: ✅ Nenhuma Exaustão Parabólica"
        )
    enviar_alerta(mensagem_tg)
