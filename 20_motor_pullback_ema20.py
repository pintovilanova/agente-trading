import pandas as pd
import yfinance as yf
import pandas_ta as ta
import time
import random

# ===================================================================
# MOTOR 20: PULLBACK INSTITUCIONAL À EMA 20
# ===================================================================
def analisar_pullback_ema20(ativo_info, vol_diaria_usd=1000, posicoes_ativas_dict=None):
    if posicoes_ativas_dict is None:
        posicoes_ativas_dict = {}
        
    try:
        ticker = str(ativo_info.get("ticker", "")).strip().upper()
        if not ticker or ticker == "#N/A" or ticker == "NONE": return None
        if ticker in posicoes_ativas_dict: return None
        if ticker == "BRK-A": ticker = "BRK-B"

        # FILTRO DE FORÇA RELATIVA (RS SCORE MÍNIMO DE 60)
        rs_score_raw = ativo_info.get("rs_score", 0)
        try:
            rs_score = float(str(rs_score_raw).replace(",", ".").strip())
        except (ValueError, TypeError):
            rs_score = 0.0
            
        if rs_score < 60.0: return None

        time.sleep(random.uniform(0.8, 1.8))

        df = pd.DataFrame()
        for _ in range(3):
            try:
                df = yf.download(ticker, period="6mo", interval="1d", progress=False, timeout=15)
                if not df.empty and len(df) >= 50:
                    break
            except Exception:
                time.sleep(2)

        if df.empty or len(df) < 50: return None
        if isinstance(df.columns, pd.MultiIndex): df.columns = df.columns.droplevel(1)
        df = df.dropna(subset=['Close', 'High', 'Low', 'Volume'])

        preco = float(df['Close'].iloc[-1])
        if preco < 5.00: return None

        # 1. Definição das Médias Móveis e ATR
        df['EMA_20'] = df['Close'].ewm(span=20, adjust=False).mean()
        df['SMA_50'] = df['Close'].rolling(window=50).mean()
        df.ta.atr(length=20, mamode="rma", append=True)
        
        col_atr = [c for c in df.columns if str(c).startswith('ATRr_') or str(c).startswith('ATR_')][0]

        df = df.dropna(subset=['EMA_20', 'SMA_50', col_atr])
        if df.empty: return None

        ultimo = df.iloc[-1]
        ema20 = float(ultimo['EMA_20'])
        sma50 = float(ultimo['SMA_50'])
        atr = float(ultimo[col_atr])
        maximo_hoje = float(ultimo['High'])
        minimo_hoje = float(ultimo['Low'])
        fecho_hoje = float(ultimo['Close'])

        # 2. Regime de Tendência de Alta
        tendencia_alta = (ema20 > sma50) and (fecho_hoje > sma50)

        # 3. O Toque do Pullback (Mínimo toca na zona da EMA 20, mas fecha acima)
        margem_toque = ema20 * 1.01 
        toque_ema20 = (minimo_hoje <= margem_toque) and (fecho_hoje > ema20)

        # 4. Cálculo de Ordens e Dimensionamento
        if tendencia_alta and toque_ema20:
            entrada_gatilho = round(maximo_hoje * 1.002, 2)
            stop_loss = round(entrada_gatilho - (atr * 1.5), 2)
            
            risco = entrada_gatilho - stop_loss
            alvo_tp = round(entrada_gatilho + (risco * 2.0), 2)

            if alvo_tp <= entrada_gatilho:
                alvo_tp = round(entrada_gatilho + (risco * 1.5), 2)

            qtd_calc = round(vol_diaria_usd / risco, 2) if risco > 0 else 0.0
            val_calc = entrada_gatilho * qtd_calc

            return {
                "ticker": ticker,
                "preco_atual": round(preco, 2),
                "gatilho": entrada_gatilho,
                "stop_loss": stop_loss,
                "alvo_tp": alvo_tp,
                "qtd_acoes": qtd_calc,
                "valor_investir": round(val_calc, 2),
                "estado_motor": "PULLBACK EMA 20 DETETADO"
            }
        return None
    except Exception as e:
        print(f"[ERRO] Falha ao processar ativo {ativo_info.get('ticker')} no Motor 20: {e}")
        return None
