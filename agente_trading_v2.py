import yfinance as yf
import pandas_ta as ta
import pandas as pd
import sys

# ===================================================================
# 1. VETO MACRO (SPY FLASH CRASH & BEAR MARKET)
# ===================================================================
print("A verificar Veto Macro (SPY)...")
try:
    df_spy = yf.download("SPY", period="2y", interval="1d", progress=False)
    if isinstance(df_spy.columns, pd.MultiIndex):
        df_spy.columns = df_spy.columns.droplevel(1)
        
    df_spy.ta.sma(length=200, append=True)
    spy_hoje = df_spy.iloc[-1]
    spy_ontem = df_spy.iloc[-2]
    
    preco_spy = spy_hoje['Close']
    preco_spy_ontem = spy_ontem['Close']
    sma200_spy = spy_hoje['SMA_200']
    
    queda_spy = ((preco_spy - preco_spy_ontem) / preco_spy_ontem) * 100
    
    if queda_spy <= -1.50:
        print(f"[BLOQUEIO] SPY em Pânico: Caiu {queda_spy:.2f}%. Execução abortada.")
        sys.exit(0)
        
    if preco_spy < sma200_spy:
        print(f"[BLOQUEIO] SPY em Baixa: Preço ({preco_spy:.2f}) abaixo da SMA200 ({sma200_spy:.2f}). Execução abortada.")
        sys.exit(0)
        
    print("[OK] SPY Saudável. A iniciar extração de ativos...\n")
except Exception as e:
    print(f"Erro na validação do SPY: {e}")

# ===================================================================
# 2. CONFIGURAÇÕES BASE E LISTA DE TICKERS
# ===================================================================
tickers = ["MSFT", "AAPL", "NVDA", "TSLA","PFE"]

risco_maximo_dolares = 25.00
multiplicador_trailing_ts = 1.5
racio_tp_base = 1.2

resultados = []

# ===================================================================
# 3. MOTOR MATEMÁTICO V2 E GUILHOTINA
# ===================================================================
for ticker in tickers:
    try:
        # Extração (2 anos para aquecimento perfeito do RSI e ATR)
        df = yf.download(ticker, period="2y", interval="1d", progress=False)
        if isinstance(df.columns, pd.MultiIndex):
            df.columns = df.columns.droplevel(1)

        # Cálculo de Indicadores (pandas-ta)
        df.ta.rsi(length=14, append=True)
        df.ta.adx(length=14, append=True)
        df.ta.atr(length=14, append=True)
        df.ta.sma(length=200, append=True)
        df.ta.sma(length=20, append=True)
        df.ta.mom(length=14, append=True)

        # Cálculo do RVOL (Média de 20 dias)
        media_volume_20 = df['Volume'].rolling(window=20).mean()
        df['RVOL'] = df['Volume'] / media_volume_20

        # Extração das velas de hoje e de ontem
        ultimo_dia = df.iloc[-1]
        dia_anterior = df.iloc[-2]

        preco = ultimo_dia['Close']
        preco_anterior = dia_anterior['Close']
        var_perc = ((preco - preco_anterior) / preco_anterior) * 100
        
        sma20 = ultimo_dia['SMA_20']
        dist_mm20 = ((preco - sma20) / sma20) * 100

        # Variáveis Técnicas
        rvol = ultimo_dia['RVOL']
        adx = ultimo_dia['ADX_14']
        rsi = ultimo_dia['RSI_14']
        atr = ultimo_dia['ATRr_14']
        momentum = ultimo_dia['MOM_14']

        # Variáveis de Execução (Reset)
        recomendacao = "Observar"
        preco_entrada = "N/A"
        preco_stop = "N/A"
        preco_tp = "N/A"
        preco_be = "N/A"
        qtd_acoes = "N/A"
        trailing_final = "N/A"
        multiplicador_atr = 1.0

        # Filtros Booleanos
        preco_caiu_hoje = preco < preco_anterior
        volume_despejo = rvol > 1.20

        # --- A LEI DA GUILHOTINA (BUSINESS LOGIC) ---
        
        # 1 & 2. VETO DE DESPEJO & VETO DE INÉRCIA
        if (preco_caiu_hoje and volume_despejo) or (momentum < -3.00):
            recomendacao = "Observar"
            
        # 3. PULLBACK BASAL
        elif var_perc > 0 and adx < 20:
            recomendacao = "Aguardar Recuo"
            preco_entrada = preco - (atr * 0.4)
            multiplicador_atr = 1.0
            
        # 4. FORÇA CONSOLIDADA
        elif var_perc > 0 and adx >= 25 and rvol >= 1.00 and (50.00 <= rsi <= 70.00) and (-1.00 <= dist_mm20 <= 2.50):
            recomendacao = "Forca Consolidada"
            preco_entrada = preco - (atr * 0.2)
            multiplicador_atr = 1.2
            
        # 5. ALERTA IMINENTE
        elif adx >= 20 and rvol >= 0.85 and (48.00 <= rsi <= 75.00) and (-2.00 <= dist_mm20 <= 3.50):
            recomendacao = "Alerta Iminente"
            preco_entrada = preco - (atr * 0.2)
            multiplicador_atr = 1.2

        # --- GESTÃO DE RISCO (POSITION SIZING) ---
        if recomendacao != "Observar" and preco_entrada != "N/A":
            preco_stop_calc = preco_entrada - (atr * multiplicador_atr)
            preco_stop = round(preco_stop_calc, 2)
            
            risco_por_acao = preco_entrada - preco_stop_calc
            
            if risco_por_acao > 0:
                risco_alocado = risco_maximo_dolares
                if rvol >= 3.00: risco_alocado += (risco_maximo_dolares * 0.5)
                if adx >= 35.00: risco_alocado += (risco_maximo_dolares * 0.5)
                    
                tp_calc = preco_entrada + (risco_por_acao * racio_tp_base)
                preco_tp = round(tp_calc, 2)
                
                qtd_acoes = round(risco_alocado / risco_por_acao, 2)
                
                dist_tp = preco_tp - preco_entrada
                preco_be = round(preco_entrada + (dist_tp / 2), 2)
                
            trailing_calculado = preco - (atr * multiplicador_trailing_ts)
            trailing_final = round(max(trailing_calculado, preco_stop_calc), 2)

        # Formatação do dicionário final para visualização / futuro Google Sheets
        dados_ativos = {
            "Ticker": ticker,
            "Preço": round(preco, 2),
            "RSI": round(rsi, 2),
            "ADX": round(adx, 2),
            "ATR": round(atr, 2),
            "RVOL": round(rvol, 2),
            "Dist MM20(%)": round(dist_mm20, 2),
            "MOM(14)": round(momentum, 2),
            "Estado": recomendacao,
            "Entrada": round(preco_entrada, 2) if isinstance(preco_entrada, float) else preco_entrada,
            "Stop": preco_stop,
            "Alvo": preco_tp,
            "B-Even": preco_be,
            "Qtd": qtd_acoes,
            "Trailing": trailing_final
        }
        resultados.append(dados_ativos)
        print(f"[OK] {ticker} analisado. Estado: {recomendacao}")

    except Exception as e:
        print(f"[ERRO] Falha ao processar {ticker}: {e}")

# ===================================================================
# 4. EXIBIÇÃO DA MATRIZ DE RESULTADOS
# ===================================================================
print("\n--- MATRIZ TÁTICA V2 ---")
df_final = pd.DataFrame(resultados)
print(df_final.to_string(index=False))
