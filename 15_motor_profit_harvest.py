# ===================================================================
# SISTEMA DE TRADING INSTITUCIONAL - MOTOR 15 (PROFIT HARVEST & REBALANCING)
# ===================================================================
import os
import sys
import json
import time
import random
import requests
import yfinance as yf
import pandas as pd
import numpy as np
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
# 0. TRAVA DE FIM DE SEMANA & CONFIGURAÇÕES
# ===================================================================
dia_da_semana = datetime.now(ZoneInfo("Europe/Lisbon")).weekday()
if dia_da_semana >= 5:
    print("[INFO] Fim de semana detetado. O Motor 15 vai descansar.")
    # sys.exit(0)

WEBHOOK_URL = os.environ.get('WEBHOOK_URL')
MAX_PESO_CARTEIRA_PCT = 25.0  # Limite máximo de concentração por ativo na conta

def limpar_float(val):
    """Converte com segurança valores numéricos (mesmo com vírgulas) para float."""
    if val is None: return None
    try:
        val_str = str(val).replace(",", ".").strip()
        if val_str == "" or val_str.lower() in ["nan", "n/a", "none"]: return None
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

def gravar_ficheiro_saida(conteudo):
    with open("comboio_harvest_temp.txt", "w", encoding="utf-8") as f:
        f.write(conteudo)

if not WEBHOOK_URL:
    print("[AVISO] WEBHOOK_URL não definida. A terminar execução.")
    gravar_ficheiro_saida("⚠️ WEBHOOK_URL não configurada no Motor 15.")
    sys.exit(0)

print("A iniciar Motor 15 - Portfolio Rebalancing & Profit Harvest...")

# ===================================================================
# 1. OBTER POSIÇÕES ATIVAS DO GOOGLE SHEETS
# ===================================================================
configs_dict = {}
posicoes_ativas = {}
try:
    url_alvo = WEBHOOK_URL if "?" in WEBHOOK_URL else f"{WEBHOOK_URL}?aba=Analise Compra"
    resposta = requests.get(url_alvo, timeout=20)
    if resposta.status_code != 200:
        print(f"[ERRO] Falha ao aceder ao Sheets: {resposta.status_code}")
        gravar_ficheiro_saida(f"⚠️ Erro HTTP {resposta.status_code} ao aceder ao Google Sheets no Motor 15.")
        sys.exit(1)
        
    dados_webhook = resposta.json()
    posicoes_ativas = dados_webhook.get("posicoesAtivas", {}) or dados_webhook.get("posicoes", {})
    configs_dict = dados_webhook.get("configs", {})
    
    capital_total = limpar_float(configs_dict.get("CAPITAL_TOTAL_CONTA")) or 10400.00
    
except Exception as e:
    print(f"[ERRO CRÍTICO] Falha de comunicação: {e}")
    gravar_ficheiro_saida(f"⚠️ Erro crítico de comunicação no Motor 15: {e}")
    sys.exit(1)

if not posicoes_ativas:
    print("[INFO] Nenhuma posição ativa em carteira. Motor em silêncio.")
    gravar_ficheiro_saida("✅ Nenhuma posição ativa em carteira para auditoria de colheita hoje.")
    sys.exit(0)

# ===================================================================
# 2. AUDITORIA DE GAIN (2R / 4R) & CONCENTRAÇÃO DE CARTEIRA
# ===================================================================
alertas_colheita = []
total_posicoes_auditadas = 0

for ticker_raw, pos in posicoes_ativas.items():
    if not isinstance(pos, dict):
        continue
    status = str(pos.get('status', '')).strip().upper()
    # Cobre ATIVA, ATIVA_FAST, ATIVA_M10, ATIVA_SWING
    if not status.startswith('ATIVA'):
        continue
        
    total_posicoes_auditadas += 1
    ticker = "BRK-B" if ticker_raw.strip().upper() == "BRK-A" else ticker_raw.strip().upper().replace(".", "-")

    try:
        preco_entrada = limpar_float(pos.get('precoEntrada')) or 0.0
        stop_inicial = limpar_float(pos.get('stopInicial')) or limpar_float(pos.get('stopAtual')) or 0.0
        stop_atual = limpar_float(pos.get('stopAtual')) or 0.0
        qtd_atual = limpar_float(pos.get('quantidade')) or 0.0
        
        if preco_entrada <= 0 or stop_inicial <= 0 or qtd_atual <= 0:
            continue
            
        time.sleep(random.uniform(0.3, 0.7))
        df = yf.download(ticker, period="5d", interval="1d", progress=False, session=session)
        if df.empty:
            continue
            
        if isinstance(df.columns, pd.MultiIndex):
            df.columns = df.columns.droplevel(1)
            
        preco_fecho = float(df['Close'].iloc[-1])
        preco_atual = obter_preco_tempo_real(ticker, preco_fecho)
        
        # Matemática de Risco (1R e R-Multiple Atual)
        risco_1r = preco_entrada - stop_inicial
        if risco_1r <= 0:
            risco_1r = preco_entrada * 0.03  # Fallback 3%
            
        r_multiple = (preco_atual - preco_entrada) / risco_1r
        ganho_pct = ((preco_atual - preco_entrada) / preco_entrada) * 100
        valor_posicao_usd = preco_atual * qtd_atual
        peso_carteira_pct = (valor_posicao_usd / capital_total) * 100

        # Evita dupla colheita repetida: se stop_atual já está >= preço de entrada, a 1ª colheita (2R) já foi feita
        colheita_2r_ja_feita = (stop_atual >= preco_entrada) or (str(pos.get('colheitaFeita', '')).lower() in ['true', 'sim', '1'])

        motivo_alerta = None
        fracao_venda = 0.50

        if not colheita_2r_ja_feita and r_multiple >= 2.0:
            motivo_alerta = f"COLHEITA PARCIAL 1º PATAMAR (>= 2.0R | Atual: {r_multiple:.2f}R)"
            fracao_venda = 0.50
        elif colheita_2r_ja_feita and r_multiple >= 4.0:
            motivo_alerta = f"COLHEITA PARCIAL 2º PATAMAR (>= 4.0R | Atual: {r_multiple:.2f}R)"
            fracao_venda = 0.50
        elif peso_carteira_pct > MAX_PESO_CARTEIRA_PCT:
            motivo_alerta = f"REBALANCEAMENTO POR CONCENTRAÇÃO (Peso {peso_carteira_pct:.1f}% > {MAX_PESO_CARTEIRA_PCT:.0f}%)"
            excesso_usd = valor_posicao_usd - (capital_total * (MAX_PESO_CARTEIRA_PCT / 100.0))
            fracao_venda = min(max(excesso_usd / valor_posicao_usd, 0.25), 0.50)
        
        if motivo_alerta:
            qtd_venda_parcial = round(qtd_atual * fracao_venda, 2)
            if qtd_venda_parcial <= 0:
                continue
            
            # ===================================================================
            # REGRA DE INÉRCIA DE STOP LOSS (NUNCA RECUAR UM STOP JÁ SUBIDO)
            # ===================================================================
            break_even_calculado = round(preco_entrada * 1.002, 2)  # Entrada + 0.2% para taxas/slippage
            novo_stop_be = max(break_even_calculado, stop_atual)
            
            if stop_atual >= break_even_calculado:
                nota_stop = f"Manter Stop Loss Protegido em ${novo_stop_be:.2f}"
            else:
                nota_stop = f"Subir Stop Loss para Break-Even em ${novo_stop_be:.2f}"
            
            lucro_estimado_usd = round((preco_atual - preco_entrada) * qtd_venda_parcial, 2)
            
            alertas_colheita.append({
                "ticker": ticker,
                "status_pos": status,
                "motivo": motivo_alerta,
                "r_multiple": round(r_multiple, 2),
                "ganho_pct": round(ganho_pct, 2),
                "preco_ref_venda": round(preco_atual, 2),
                "preco_entrada": round(preco_entrada, 2),
                "tipo_ordem_venda": "SELL LIMIT ao Preço Atual (ou SELL MARKET)",
                "qtd_atual": qtd_atual,
                "qtd_venda": qtd_venda_parcial,
                "qtd_restante": round(qtd_atual - qtd_venda_parcial, 2),
                "novo_stop_be": novo_stop_be,
                "nota_stop": nota_stop,
                "lucro_usd": lucro_estimado_usd,
                "peso_carteira": round(peso_carteira_pct, 2)
            })
            
    except Exception as e:
        print(f"[ERRO] Falha ao processar {ticker} no Motor 15: {e}")

# ===================================================================
# 3. GERAR FICHEIRO TEMPORÁRIO PARA O ORQUESTRADOR
# ===================================================================
data_hoje = datetime.now(ZoneInfo("Europe/Lisbon")).strftime("%d/%m/%Y %H:%M")

if alertas_colheita:
    bloco_texto = f"✂️ MOTOR 15: REBALANCING & PROFIT HARVEST ({data_hoje})\n"
    bloco_texto += "🚨 OPORTUNIDADES DE COLHEITA DE LUCRO / REBALANCEAMENTO DETETADAS:\n\n"
    
    for item in alertas_colheita:
        bloco_texto += (
            f"🎯 TICKER: {item['ticker']} [{item['status_pos']}] | Retorno: +{item['ganho_pct']}% ({item['r_multiple']}R)\n"
            f"   - MOTIVO: {item['motivo']}\n"
            f"   - ORDEM DE VENDA PARCIAL: {item['tipo_ordem_venda']}\n"
            f"   - Preço de Referência Venda: ${item['preco_ref_venda']} (Entrada original: ${item['preco_entrada']})\n"
            f"   - Quantidade a Vender: {item['qtd_venda']} ações (de {item['qtd_atual']} totais | Sobram: {item['qtd_restante']})\n"
            f"   - Lucro Realizado a Colher: ~${item['lucro_usd']} USD | Peso Atual na Carteira: {item['peso_carteira']}%\n"
            f"   - ORDEM DE STOP LOSS (Restantes {item['qtd_restante']} ações): {item['nota_stop']}\n"
            f"--------------------------------------------------\n"
        )
else:
    bloco_texto = f"✅ ({data_hoje}) Nenhuma posição ativa atingiu a fasquia de colheita (2R/4R) ou excesso de concentração hoje. Risco sob controlo."

gravar_ficheiro_saida(bloco_texto)

print(f"[SUCESSO] Auditoria de Profit Harvest concluída. Posições auditadas: {total_posicoes_auditadas} | Alertas gerados: {len(alertas_colheita)}")

# ===================================================================
# 4. NOTIFICAÇÃO TELEGRAM (DEBUG OU ALERTA DE COLHEITA/REBALANCEAMENTO)
# ===================================================================
debug_telegram_ativado = str(configs_dict.get("TELEGRAM_NOTIFICATIONS_DEBUG", "false")).strip().lower() in ["true", "1", "sim", "yes"]

if debug_telegram_ativado or len(alertas_colheita) > 0:
    print("A enviar notificação para o Telegram via função modular...")
    tickers_str = ", ".join([f"{a['ticker']} (+{a['r_multiple']}R)" for a in alertas_colheita]) if alertas_colheita else "Nenhum"
    mensagem_debug = (
        f"15 ✂️ *MOTOR 15 (PROFIT HARVEST)*\n\n"
        f"🔍 Auditoria concluída com sucesso.\n"
        f"📊 Posições auditadas: *{total_posicoes_auditadas}* | Acionadas: *{len(alertas_colheita)}*\n"
        f"🎯 Alvos: *{tickers_str}*"
    )
    enviar_alerta(mensagem_debug)
