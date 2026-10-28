# ===================================================================
# SISTEMA DE TRADING INSTITUCIONAL - MOTOR 15 (PROFIT HARVEST & REBALANCING)
# ===================================================================
import os
import sys
import json
import requests
import yfinance as yf
import pandas as pd
from datetime import datetime
from zoneinfo import ZoneInfo
import warnings
warnings.filterwarnings("ignore")

# ===================================================================
# 0. CONFIGURAÇÕES E CREDENCIAIS
# ===================================================================
WEBHOOK_URL = os.environ.get('WEBHOOK_URL')

if not WEBHOOK_URL:
    print("[AVISO] WEBHOOK_URL não definida. A terminar execução.")
    sys.exit(0)

print("A iniciar Motor 15 - Portfolio Rebalancing & Profit Harvest...")

# ===================================================================
# 1. OBTER POSIÇÕES ATIVAS DO GOOGLE SHEETS
# ===================================================================
try:
    resposta = requests.get(WEBHOOK_URL, timeout=15)
    if resposta.status_code != 200:
        print(f"[ERRO] Falha ao aceder ao Sheets: {resposta.status_code}")
        sys.exit(1)
        
    dados_webhook = resposta.json()
    posicoes_ativas = dados_webhook.get("posicoesAtivas", {})
    configs = dados_webhook.get("configs", {})
    
    capital_total = float(configs.get("CAPITAL_TOTAL_CONTA", 10400.00))
    
except Exception as e:
    print(f"[ERRO CRÍTICO] Falha de comunicação: {e}")
    sys.exit(1)

if not posicoes_ativas:
    print("[INFO] Nenhuma posição ativa em carteira. Motor em silêncio.")
    sys.exit(0)

# ===================================================================
# 2. AUDITORIA DE GAIN & CÁLCULO DE $2R$
# ===================================================================
relatorio_harvest = []
alertas_colheita = []

for ticker, pos in posicoes_ativas.items():
    status = pos.get('status', '')
    if status not in ['ATIVA', 'ATIVA_FAST']:
        continue
        
    try:
        preco_entrada = float(str(pos.get('precoEntrada', 0)).replace(',', '.'))
        stop_inicial = float(str(pos.get('stopInicial', pos.get('stopAtual', 0))).replace(',', '.'))
        stop_atual = float(str(pos.get('stopAtual', 0)).replace(',', '.'))
        qtd_atual = float(str(pos.get('quantidade', 0)).replace(',', '.'))
        
        if preco_entrada <= 0 or stop_inicial <= 0 or qtd_atual <= 0:
            continue
            
        # Obter Preço Atual em Tempo Real via yfinance
        df = yf.download(ticker, period="5d", interval="1d", progress=False)
        if df.empty:
            continue
            
        if isinstance(df.columns, pd.MultiIndex):
            df.columns = df.columns.droplevel(1)
            
        preco_atual = float(df['Close'].iloc[-1])
        
        # Matemática de Risco (1R e R-Multiple Atual)
        risco_1r = preco_entrada - stop_inicial
        if risco_1r <= 0:
            # Posição curta ou stop desalinhado
            risco_1r = preco_entrada * 0.03 # Fallback 3%
            
        r_multiple = (preco_atual - preco_entrada) / risco_1r
        ganho_pct = ((preco_atual - preco_entrada) / preco_entrada) * 100
        valor_posicao_usd = preco_atual * qtd_atual
        peso_carteira_pct = (valor_posicao_usd / capital_total) * 100
        
        # CONDICIONAL: GATILHO DE COLHEITA A 2R OU SUPERIOR
        if r_multiple >= 2.0:
            qtd_venda_parcial = round(qtd_atual / 2.0, 2)
            
            # ===================================================================
            # REGRA DE INÉRCIA DE STOP LOSS (NUNCA RECUAR UM STOP JÁ SUBIDO)
            # ===================================================================
            break_even_calculado = round(preco_entrada * 1.001, 2) # Entrada + 0.1% para taxas
            novo_stop_be = max(break_even_calculado, stop_atual)
            
            if stop_atual > break_even_calculado:
                nota_stop = f"Manter Stop Atual Protegido em ${novo_stop_be}"
            else:
                nota_stop = f"Subir Stop Loss para Break-Even em ${novo_stop_be}"
            
            lucro_estimado_usd = round((preco_atual - preco_entrada) * qtd_venda_parcial, 2)
            
            alertas_colheita.append({
                "ticker": ticker,
                "r_multiple": round(r_multiple, 2),
                "ganho_pct": round(ganho_pct, 2),
                "preco_atual": round(preco_atual, 2),
                "preco_entrada": round(preco_entrada, 2),
                "qtd_atual": qtd_atual,
                "qtd_venda": qtd_venda_parcial,
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
    bloco_texto += "🚨 OPORTUNIDADES DE COLHEITA DE LUCRO (>= 2R) DETETADAS:\n\n"
    
    for item in alertas_colheita:
        bloco_texto += (
            f"🎯 TICKER: {item['ticker']} | Retorno: +{item['ganho_pct']}% ({item['r_multiple']}R)\n"
            f"   - Preço Atual: ${item['preco_atual']} (Entrada: ${item['preco_entrada']})\n"
            f"   - AÇÃO RECOMENDADA: Fecho Parcial de 50% ({item['qtd_venda']} ações de {item['qtd_atual']})\n"
            f"   - AÇÃO NO STOP: {item['nota_stop']}\n"
            f"   - Capital a Colher: ~${item['lucro_usd']} USD | Peso Atual na Carteira: {item['peso_carteira']}%\n"
            f"--------------------------------------------------\n"
        )
else:
    bloco_texto = "✅ Nenhuma posição atingiu a fasquia de 2R para colheita parcial hoje. Risco sob controlo."

with open("comboio_harvest_temp.txt", "w", encoding="utf-8") as f:
    f.write(bloco_texto)

print(f"[SUCESSO] Auditoria de Profit Harvest concluída. Alertas gerados: {len(alertas_colheita)}")
