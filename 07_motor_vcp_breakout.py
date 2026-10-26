# ===================================================================
# SISTEMA DE TRADING INSTITUCIONAL - MOTOR DE COMPRESSÃO VCP (BREAKOUT)
# ===================================================================
import pandas as pd
import yfinance as yf
import numpy as np
from datetime import datetime
from zoneinfo import ZoneInfo
import sys
import os
import requests
import smtplib
import time
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
import warnings
warnings.filterwarnings("ignore")

# ===================================================================
# 0. TRAVA DE FIM DE SEMANA
# ===================================================================
dia_da_semana = datetime.now(ZoneInfo("Europe/Lisbon")).weekday()
if dia_da_semana >= 5:
    print("[INFO] Fim de semana detetado. O Motor VCP vai descansar.")
    #sys.exit(0)

# ===================================================================
# 1. CONFIGURAÇÕES E CREDENCIAIS
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

MIN_RS_SCORE = 50.0

def limpar_float(val):
    """Converte com segurança valores numéricos (mesmo com vírgulas) para float."""
    if val is None: return None
    try:
        val_str = str(val).replace(",", ".").strip()
        if val_str == "" or val_str.lower() in ["nan", "n/a", "none"]: return None
        return float(val_str)
    except (ValueError, TypeError):
        return None

# ===================================================================
# 2. FUNÇÕES DE REDE
# ===================================================================
def buscar_watchlist():
    print("A carregar a Watchlist e Configurações a partir do Google Sheets...")
    if not WEBHOOK_URL: 
        print("[ERRO CRÍTICO] WEBHOOK_URL não encontrada nas variáveis de ambiente.")
        return [], {}
    try:
        url_alvo = WEBHOOK_URL if "?" in WEBHOOK_URL else f"{WEBHOOK_URL}?aba=Analise Compra"
        resp = requests.get(url_alvo, timeout=15)
        print(f"[DEBUG] Status Code do Webhook: {resp.status_code}")
        
        if resp.status_code == 200:
            try:
                dados = resp.json()
            except Exception as e:
                print(f"[ERRO] O Webhook não retornou JSON válido: {e}. Resposta: {resp.text[:200]}")
                return [], {}

            if isinstance(dados, dict):
                if "erro" in dados:
                    print(f"[ERRO DO SHEETS] {dados['erro']}")
                    return [], {}
                ativos = dados.get("ativos", [])
                configs = dados.get("configs", {})
                print(f"[SUCESSO] {len(ativos)} ativos e {len(configs)} configurações carregados.")
                return ativos, configs
            elif isinstance(dados, list):
                print(f"[SUCESSO] {len(dados)} ativos carregados (formato lista).")
                return dados, {}
            else:
                print(f"[ERRO] Formato de dados inesperado: {type(dados)}")
                return [], {}
        else:
            print(f"[ERRO HTTP] Falha ao descarregar dados: {resp.status_code}. Resposta: {resp.text[:200]}")
            return [], {}
    except Exception as e:
        print(f"[ERRO CRÍTICO] Falha de comunicação com Sheets: {e}")
        return [], {}

def enviar_email(conteudo):
    print("\nA enviar email VCP/Squeeze para o Agente IA...")
    
    if not EMAIL_USER or not EMAIL_PASS:
        print("[AVISO] Credenciais de email em falta. A saltar envio.")
        return

    if "@" not in EMAIL_USER or "." not in EMAIL_USER:
        print(f"[ERRO CRÍTICO] O e-mail configurado ('{EMAIL_USER}') não é um endereço válido. Verifica a Secret EMAIL_USER no GitHub.")
        return

    msg = MIMEMultipart()
    msg['From'] = EMAIL_USER
    msg['To'] = EMAIL_USER
    msg['Subject'] = "🎯 tradingRelatorioIA US - VCP BREAKOUT SQUEEZE"
    
    msg.attach(MIMEText(conteudo, 'plain', 'utf-8'))
    
    max_tentativas = 3
    for tentativa in range(max_tentativas):
        try:
            server = smtplib.SMTP(SMTP_SERVER, SMTP_PORT, timeout=15)
            server.starttls()
            server.login(EMAIL_USER, EMAIL_PASS)
            server.sendmail(EMAIL_USER, EMAIL_USER, msg.as_string())
            server.quit()
            
            print(f"[SUCESSO] Email VCP enviado na tentativa {tentativa + 1}!")
            break
            
        except Exception as e:
            print(f"[ERRO] Falha ao enviar o email (tentativa {tentativa + 1} de {max_tentativas}): {e}")
            if tentativa < max_tentativas - 1:
                print("A aguardar 5 segundos antes de tentar novamente...")
                time.sleep(5)
            else:
                print("[ERRO CRÍTICO] O servidor Gmail fechou a ligação definitivamente. Falha no envio.")

# ===================================================================
# 3. MOTOR MATEMÁTICO: COMPRESSÃO DE VOLATILIDADE
# ===================================================================
def analisar_compressao_vcp(ativo_info, vol_alvo_diaria_usd):
    try:
        ticker = str(ativo_info.get("ticker", "")).strip().upper()
        nome_empresa = ativo_info.get("nome", "N/A")
        setor = str(ativo_info.get("setor", "Desconhecido")).strip()
        rs_score = ativo_info.get("rs_score", "N/A")

        if not ticker or ticker == "#N/A" or ticker == "NONE":
            return None

        # CORREÇÃO 1: Conversão automática de BRK-A para BRK-B
        if ticker == "BRK-A":
            print("[AJUSTE] Ticker BRK-A convertido automaticamente para BRK-B.")
            ticker = "BRK-B"

        # CORREÇÃO 2: Filtro Anti-Laggard (RS Score >= 50)
        val_rs_num = limpar_float(rs_score)
        if val_rs_num is not None and val_rs_num < MIN_RS_SCORE:
            print(f"[VETO RS SCORE] {ticker} ignorado. RS Score fraco ({val_rs_num} < {MIN_RS_SCORE} - Laggard).")
            return None

        # CORREÇÃO 3: Fallback automático de setor e verificação de Earnings via yfinance
        alerta_earnings = "OK"
        try:
            ticker_obj = yf.Ticker(ticker)
            if setor in ["Desconhecido", "N/A", "", "NONE"]:
                setor_yf = ticker_obj.info.get('sector')
                if setor_yf:
                    setor = setor_yf

            calendario = ticker_obj.calendar
            if isinstance(calendario, dict) and 'Earnings Date' in calendario:
                proxima_data = calendario['Earnings Date'][0]
                if hasattr(proxima_data, 'date'):
                    proxima_data = proxima_data.date()
                
                hoje = datetime.now(ZoneInfo("Europe/Lisbon")).date()
                dias_restantes = (proxima_data - hoje).days
                
                if 0 <= dias_restantes <= 3:
                    alerta_earnings = f"PERIGO (em {dias_restantes} dias)"
        except Exception:
            pass

        df = yf.download(ticker, period="1y", interval="1d", progress=False)
        if df.empty:
            return None
            
        if isinstance(df.columns, pd.MultiIndex):
            df.columns = df.columns.droplevel(1)

        # BLINDAGEM CONTRA NaNs E BARRAS INCOMPLETAS:
        df = df.dropna(subset=['Close', 'High', 'Low', 'Volume'])
        if len(df) < 120:
            return None

        preco = float(df.iloc[-1]['Close'])
        
        # Filtros Anti-Lixo
        if pd.isna(preco) or preco < 5.00:
            return None
        if setor and any(termo in str(setor).lower() for termo in ["real estate", "reit"]):
            return None

        # Médias de Tendência
        df['SMA_50'] = df['Close'].rolling(window=50).mean()
        df['SMA_200'] = df['Close'].rolling(window=200).mean()
        
        # Bollinger Bands & Band Width (BBW)
        df['SMA_20'] = df['Close'].rolling(window=20).mean()
        df['STD_20'] = df['Close'].rolling(window=20).std()
        df['BB_Upper'] = df['SMA_20'] + (df['STD_20'] * 2)
        df['BB_Lower'] = df['SMA_20'] - (df['STD_20'] * 2)
        df['BBW'] = ((df['BB_Upper'] - df['BB_Lower']) / df['SMA_20']) * 100
        
        # Volume Seco
        df['Vol_SMA_50'] = df['Volume'].rolling(window=50).mean()
        vol_medio_3d = df['Volume'].iloc[-3:].mean()
        
        # ATR para Dimensionamento
        high = df['High']
        low = df['Low']
        close = df['Close']
        tr1 = high - low
        tr2 = (high - close.shift()).abs()
        tr3 = (low - close.shift()).abs()
        tr = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)
        df['ATR_14'] = tr.rolling(window=14).mean()

        df = df.dropna(subset=['SMA_50', 'SMA_200', 'BBW', 'Vol_SMA_50', 'ATR_14'])
        if df.empty:
            return None

        ultimo = df.iloc[-1]
        sma50 = float(ultimo['SMA_50'])
        sma200 = float(ultimo['SMA_200'])
        bbw_atual = float(ultimo['BBW'])
        vol_sma50 = float(ultimo['Vol_SMA_50'])
        atr = float(ultimo['ATR_14'])
        
        # Caixote de 5 dias
        max_5d = float(df['High'].iloc[-5:].max())
        min_5d = float(df['Low'].iloc[-5:].min())

        # Condições do Gatilho VCP (Squeeze)
        tendencia_alta = (preco > sma50) and (sma50 > sma200)
        bbw_120d_min = float(df['BBW'].iloc[-120:].min()) if len(df) >= 120 else float(df['BBW'].min())
        squeeze_ativo = bbw_atual <= (bbw_120d_min * 1.5) and bbw_atual < 8.0
        seca_volume = vol_medio_3d < (vol_sma50 * 0.6)

        if tendencia_alta and squeeze_ativo and seca_volume:
            estado = "SQUEEZE EXTREMO - Ignição Iminente"
            entrada_gatilho = round(max_5d * 1.002, 2)
            stop_loss = round(min_5d * 0.998, 2)
            
            risco = entrada_gatilho - stop_loss
            alvo_tp = round(entrada_gatilho + (risco * 3), 2)
            
            if atr > 0:
                qtd_calc = round(vol_alvo_diaria_usd / atr, 2)
            else:
                qtd_calc = round(vol_alvo_diaria_usd / risco, 2) if risco > 0 else 0
                
            # CORREÇÃO 4: Trava Anti-Quantidade Nula (Qtd <= 0)
            if qtd_calc <= 0:
                print(f"[FILTRADO] {ticker} rejeitado por quantidade calculada nula ({qtd_calc}).")
                return None

            qtd_acoes = qtd_calc
            val_calc = entrada_gatilho * qtd_acoes
            valor_investir = f"~{val_calc:.2f} USD"
            
            def limpa(v): 
                try:
                    if pd.isna(v) or v == "N/A": return "N/A"
                    return round(float(v), 2)
                except:
                    return "N/A"
            
            if val_rs_num is not None:
                if val_rs_num >= 80:
                    status_rs = "🔥 ELITE (RS >= 80 - Vento a Favor)"
                elif val_rs_num >= 50:
                    status_rs = "⚖️ NEUTRO (RS 50-79 - Acompanha o Mercado)"
                else:
                    status_rs = "⚠️ FRACO / LAGGARD (RS < 50 - Vento Contra)"
            else:
                status_rs = "❓ SEM DADO DE RS"
            
            linha_comboio = (
                f"{ticker},Nome: {nome_empresa},Setor: {setor},Preço: {limpa(preco)},"
                f"RS Score: {rs_score} ({status_rs}),"
                f"BBW Atual: {limpa(bbw_atual)}%,Volume 3D: Seco (-40%+),"
                f"Gatilho Compra (Buy Stop): {limpa(entrada_gatilho)},"
                f"Stop Físico (Min 5D): {limpa(stop_loss)},Alvo TP: {limpa(alvo_tp)},"
                f"Estado: {estado},Qtd: {qtd_acoes},ValorInvestir: {valor_investir},Earnings: {alerta_earnings},"
                f"Data: {datetime.now(ZoneInfo('Europe/Lisbon')).strftime('%d/%m/%Y %H:%M:%S')}"
            )

            return {
                "ticker": ticker,
                "bbw": bbw_atual,
                "comboio_str": linha_comboio
            }
            
        return None
    except Exception as e:
        print(f"[ERRO] Falha ao processar ativo {ativo_info.get('ticker')}: {e}")
        return None

# ===================================================================
# 4. EXECUÇÃO PRINCIPAL
# ===================================================================
def executar_motor():
    ativos, configs = buscar_watchlist()
    if not ativos:
        print("[AVISO] Nenhum ativo carregado para análise. A terminar a execução sem erro.")
        sys.exit(0)
        
    try:
        capital_total_conta = float(configs.get("CAPITAL_TOTAL_CONTA", 10400.00))
        alvo_volatilidade_anual = float(configs.get("ALVO_VOLATILIDADE_ANUAL", 0.05))
    except (ValueError, TypeError):
        capital_total_conta = 10400.00
        alvo_volatilidade_anual = 0.05

    volatilidade_alvo_diaria_usd = (capital_total_conta * alvo_volatilidade_anual) / 16.0

    print(f"[CONFIG] Capital Total da Conta: ${capital_total_conta:,.2f}")
    print(f"[CONFIG] Alvo Volatilidade Anual: {alvo_volatilidade_anual*100:.1f}%")
    print(f"[CONFIG] Orçamento Diário de Volatilidade: ${volatilidade_alvo_diaria_usd:.2f}\n")

    ativos_acionados = []
    for ativo_info in ativos:
        ticker = ativo_info.get("ticker")
        if not ticker or ticker == "#N/A": continue
        
        res = analisar_compressao_vcp(ativo_info, volatilidade_alvo_diaria_usd)
        if res:
            ativos_acionados.append(res)
            
    ativos_acionados = sorted(ativos_acionados, key=lambda k: k['bbw'])

    prompt_ia = """Atuas como Analista Quantitativo de Breakouts (Modelo Mark Minervini). O teu mandato é auditar ativos em fase de Squeeze (Contração de Volatilidade) preparados para explosão direcional.

REGRAS ESTRITAS:
1. O ativo não deve ser comprado a mercado. Recomenda SEMPRE ordens pendentes "Buy Stop" no Gatilho de Compra estipulado.
2. Destaca o facto do risco ser mínimo, dado que o Stop Loss está cravado na base da consolidação (caixote de 5 dias).
3. Avalia o Rácio Risco/Recompensa e presta especial atenção ao RS Score institucional anexado aos dados. Se detetar EARNINGS = PERIGO, desclassifica o sinal de imediato.

ESTRUTURA OBRIGATÓRIA:
🎯 [TICKER] - [Nome da Empresa] ([Setor])
- 🗜️ NÍVEL DE COMPRESSÃO: BBW a [X]% (Mola comprimida com seca de volume).
- 📊 CONTEXTO INSTITUCIONAL: RS Score e respetivo estado de Força Relativa.
- ⚙️ TÁTICA DE EXECUÇÃO: Colocar ordem pendente Buy Stop em [Gatilho] para apanhar o breakout.
- 🛡️ RISCO MICRO: Stop Físico cravado em [Stop] (Abaixo da base de 5 dias).
- 🔢 DADOS: Alvo: [TP] | Qtd: [X] | Alocação: [Valor] USD.
- 🔄 PASSAGEM DE TESTEMUNHO: Adiciona explicitamente o texto: "⚠️ ATENÇÃO: Assim que esta ordem for executada na corretora, altera imediatamente o estado no Google Sheets para 'ATIVA_FAST'. O Motor Carver assumirá automaticamente a gestão do Trailing Stop a partir daí."
"""
    
    bloco_texto_ia = f"📊 RELATÓRIO VCP BREAKOUT / SQUEEZE 🗜️\n\n{prompt_ia}\n\n--------------------------------------------------\n"
    
    if not ativos_acionados:
        bloco_texto_ia += "[SEM SINAIS VCP] - Nenhuma ação apresenta os critérios extremos de Squeeze e seca de volume hoje.\n"
    else:
        bloco_texto_ia += "ALVOS DE BREAKOUT IMINENTE:\n\n"
        for item in ativos_acionados:
            bloco_texto_ia += item["comboio_str"] + "\n"
            
    with open("comboio_vcp_temp.txt", "w", encoding="utf-8") as f:
        f.write(bloco_texto_ia)
        
    enviar_email(bloco_texto_ia)

if __name__ == "__main__":
    executar_motor()
