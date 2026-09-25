import yfinance as yf
import pandas_ta as ta
import pandas as pd

# 1. Lista de Teste (No futuro, isto virá do Google Sheets)
tickers = ["MSFT", "AAPL", "NVDA", "TSLA"]

print("A arrancar Motor Matemático V2...\n")

resultados = []

for ticker in tickers:
    try:
        # 2. Extração de Dados (aumentado para 2 anos para "aquecer" melhor o RSI e ATR)
        df = yf.download(ticker, period="2y", interval="1d", progress=False)
        
        if isinstance(df.columns, pd.MultiIndex):
            df.columns = df.columns.droplevel(1)

        # 3. O Cérebro Matemático (pandas-ta)
        df.ta.rsi(length=14, append=True)
        df.ta.adx(length=14, append=True)
        df.ta.atr(length=14, append=True)
        df.ta.sma(length=200, append=True)
        # CORREÇÃO: Usar MOM (Diferença em Dólares) em vez de ROC (Percentagem)
        df.ta.mom(length=10, append=True) 

        media_volume_20 = df['Volume'].rolling(window=20).mean()
        df['RVOL'] = df['Volume'] / media_volume_20

        ultimo_dia = df.iloc[-1]
        
        # 5. Formatar os dados
        dados_ativos = {
            "Ticker": ticker,
            "Preço": round(ultimo_dia['Close'], 2),
            "RSI": round(ultimo_dia['RSI_14'], 2),
            "ADX": round(ultimo_dia['ADX_14'], 2),
            "ATR": round(ultimo_dia['ATRr_14'], 2),
            "SMA200": round(ultimo_dia['SMA_200'], 2),
            "Momentum": round(ultimo_dia['MOM_10'], 2), # Atualizado aqui
            "RVOL": round(ultimo_dia['RVOL'], 2)
        }
        resultados.append(dados_ativos)
        
        print(f"[OK] {ticker} processado.")

    except Exception as e:
        print(f"[ERRO] Falha ao processar {ticker}: {e}")

# Mostrar o resultado final formatado
print("\n--- MATRIZ DE RESULTADOS V2 ---")
df_final = pd.DataFrame(resultados)
print(df_final.to_string(index=False))
