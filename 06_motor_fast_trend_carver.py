# ===================================================================================
# SISTEMA DE TRADING INSTITUCIONAL - MOTOR FAST TREND (ROBERT CARVER)
# ===================================================================================
import pandas as pd
import yfinance as yf
import numpy as np
from datetime import datetime
from zoneinfo import ZoneInfo
import sys
import os
import requests
import json
import smtplib
import time
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
import warnings
warnings.filterwarnings("ignore")

# Importação da função modular de notificação do Telegram
from F01_notificador_telegram import enviar_alerta

# ===================================================================
# 0. TRAVA DE FIM DE SEMANA
# ===================================================================
dia_da_semana = datetime.now(ZoneInfo("Europe/Lisbon")).weekday()
if dia_da_semana >= 5:
    print("[INFO] Fim de semana detetado. O motor Carver vai descansar.")
    #sys.exit(0)

# ===================================================================
# 1. CONFIGURAÇÕES E CREDENCIAIS (GitHub Secrets)
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

# Limite máximo de novos sinais permitidos por cada setor no mesmo dia
MAX_NOVOS_SINAIS_POR_SETOR = 2

# Limiar de Força Relativa Institucional Mínima (Rejeita Laggards)
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
def buscar_dados_completos():
    print("A carregar a Watchlist, Posições Ativas e Configurações a partir do Google Sheets...")
    if not WEBHOOK_URL: 
        print("[ERRO] WEBHOOK_URL não configurado.")
        return [], {}, {}
    try:
        url_alvo = WEBHOOK_URL if "?" in WEBHOOK_URL else f"{WEBHOOK_URL}?aba=Analise Compra"
        resp = requests.get(url_alvo, timeout=15)
        
        if resp.status_code == 200:
            try:
                dados = resp.json()
            except json.JSONDecodeError:
                print(f"[ERRO] O Webhook não retornou um JSON válido. Resposta: {resp.text[:200]}")
                return [], {}, {}

            if isinstance(dados, dict):
                ativos = dados.get("ativos", [])
                posicoes = dados.get("posicoesAtivas", {})
                configs = dados.get("configs", {})
                return ativos, posicoes, configs
            elif isinstance(dados, list):
                return dados, {}, {}
                
        print(f"[AVISO] Webhook retornou status {resp.status_code}. Resposta: {resp.text[:200]}")
        return [], {}, {}
    except Exception as e:
        print(f"[ERRO CRÍTICO] Sheets: {e}")
        return [], {}, {}

def enviar_email_bruto(conteudo):
    print("\nA enviar o relatório de dados brutos do Carver para o Agente IA via email...")
    
    if not EMAIL_USER or not EMAIL_PASS:
        print("[AVISO] Credenciais de email em falta. A saltar envio.")
        return

    if "@" not in EMAIL_USER or "." not in EMAIL_USER:
        print(f"[ERRO CRÍTICO] O e-mail configurado ('{EMAIL_USER}') não é um endereço válido. Verifica a Secret EMAIL_USER no GitHub.")
        return

    msg = MIMEMultipart()
    msg['From'] = EMAIL_USER
    msg['To'] = EMAIL_USER
    msg['Subject'] = "tradingRelatorioIA US - FAST TREND CARVER"
    
    msg.attach(MIMEText(conteudo, 'plain', 'utf-8'))
    
    max_tentativas = 3
    for tentativa in range(max_tentativas):
        try:
            server = smtplib.SMTP(SMTP_SERVER, SMTP_PORT, timeout=15)
            server.starttls()
            server.login(EMAIL_USER, EMAIL_PASS)
            server.sendmail(EMAIL_USER, EMAIL_USER, msg.as_string())
            server.quit()
            
            print(f"[SUCESSO] Email bruto do Carver enviado na tentativa {tentativa + 1}!")
            break
            
        except Exception as e:
            print(f"[ERRO] Falha ao enviar o email (tentativa {tentativa + 1} de {max_tentativas}): {e}")
            if tentativa < max_tentativas - 1:
                print("A aguardar 5 segundos antes de tentar novamente...")
                time.sleep(5)
            else:
                print("[ERRO CRÍTICO] O servidor Gmail fechou a ligação definitivamente. Falha no envio.")

# ===================================================================
# 3. FILTRO DE REGIME MACRO (S&P 500 / SPY)
# ===================================================================
def verificar_regime_macro():
    """Avalia a saúde do mercado via SPY (S&P 500 ETF)."""
    try:
        spy = yf.download("SPY", period="6mo", interval="1d", progress=False)
        if spy.empty:
            return {"status": "NEUTRO", "fator_lote": 1.0, "min_forecast": 12.0}
            
        if isinstance(spy.columns, pd.MultiIndex):
            spy.columns = spy.columns.droplevel(1)
            
        spy = spy.dropna(subset=['Close'])
        spy['EMA_50'] = spy['Close'].ewm(span=50, adjust=False).mean()
        
        ultimo_preco = float(spy.iloc[-1]['Close'])
        ema50 = float(spy.iloc[-1]['EMA_50'])
        
        if ultimo_preco >= ema50:
            print(f"[MACRO] S&P 500 acima da EMA50 (${ultimo_preco:.2f} >= ${ema50:.2f}). Regime: FAVORÁVEL (Lote Completo, Forecast Min: 12.0).")
            return {"status": "FAVORÁVEL", "fator_lote": 1.0, "min_forecast": 12.0}
        else:
            print(f"[MACRO AVISO] S&P 500 abaixo da EMA50 (${ultimo_preco:.2f} < ${ema50:.2f}). Regime: DEFENSIVO (Lote Reduzido a 50%, Forecast Min: 14.0).")
            return {"status": "DEFENSIVO", "fator_lote": 0.5, "min_forecast": 14.0}
    except Exception as e:
        print(f"[AVISO MACRO] Falha ao verificar regime do mercado: {e}. A usar parâmetros padrão.")
        return {"status": "NEUTRO", "fator_lote": 1.0, "min_forecast": 12.0}

# ===================================================================
# 4. MOTOR MATEMÁTICO: CÁLCULO NATIVO
# ===================================================================
def calcular_indicadores_tecnicos(ticker):
    try:
        df = yf.download(ticker, period="1y", interval="1d", progress=False)
        if df.empty:
            return None
            
        if isinstance(df.columns, pd.MultiIndex):
            df.columns = df.columns.droplevel(1)

        df = df.dropna(subset=['Close', 'High', 'Low', 'Volume'])
        if df.empty or len(df) < 50:
            return None

        df['EMA_8'] = df['Close'].ewm(span=8, adjust=False).mean()
        df['EMA_32'] = df['Close'].ewm(span=32, adjust=False).mean()

        high = df['High']
        low = df['Low']
        close = df['Close']
        
        tr1 = high - low
        tr2 = (high - close.shift()).abs()
        tr3 = (low - close.shift()).abs()
        
        tr = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)
        df['ATR_36'] = tr.rolling(window=36).mean()

        df = df.dropna(subset=['EMA_8', 'EMA_32', 'ATR_36'])
        if df.empty:
            return None

        ultimo = df.iloc[-1]
        return {
            "preco": float(ultimo['Close']),
            "ema8": float(ultimo['EMA_8']),
            "ema32": float(ultimo['EMA_32']),
            "atr36": float(ultimo['ATR_36'])
        }
    except Exception as e:
        print(f"[ERRO] Falha ao descarregar dados para {ticker}: {e}")
        return None

def analisar_tendencia_carver(ativo_info, vol_alvo_diaria_usd, info_macro):
    ticker = str(ativo_info.get("ticker", "")).strip().upper()
    nome_empresa = ativo_info.get("nome", "N/A")
    setor = str(ativo_info.get("setor", "Desconhecido")).strip()
    rs_score = ativo_info.get("rs_score", "N/A")

    if not ticker or ticker == "#N/A" or ticker == "NONE":
        return None

    if ticker == "BRK-A":
        print("[AJUSTE] Ticker BRK-A convertido automaticamente para BRK-B.")
        ticker = "BRK-B"

    if setor in ["Desconhecido", "N/A", "", "NONE"]:
        try:
            ticker_obj = yf.Ticker(ticker)
            setor_yf = ticker_obj.info.get('sector')
            if setor_yf:
                setor = setor_yf
        except Exception:
            pass

    val_rs_num = limpar_float(rs_score)
    if val_rs_num is not None and val_rs_num < MIN_RS_SCORE:
        print(f"[VETO RS SCORE] {ticker} ignorado. RS Score fraco ({val_rs_num} < {MIN_RS_SCORE} - Laggard).")
        return None

    ind = calcular_indicadores_tecnicos(ticker)
    if not ind: return None
    
    preco, ema8, ema32, atr36 = ind['preco'], ind['ema8'], ind['ema32'], ind['atr36']
    if pd.isna(preco) or pd.isna(ema8) or pd.isna(ema32) or pd.isna(atr36) or atr36 == 0:
        return None

    diferenca_bruta = ema8 - ema32
    forecast_carver = (diferenca_bruta / atr36) * 5.0
    
    min_forecast = info_macro.get("min_forecast", 12.0)
    if forecast_carver < min_forecast:
        return None

    multiplicador = min(forecast_carver / 10.0, 2.0)
    estado_str = "FAST TREND - Carver Momentum"
    entrada = round(preco, 2)
    stop_loss = round(entrada - (atr36 * 1.5), 2)
    
    if entrada <= stop_loss:
        print(f"[VETO GAP DOWN] {ticker} ignorado. Preço (${entrada:.2f}) <= Stop Loss (${stop_loss:.2f}).")
        return None

    alvo_tp = round(entrada + ((entrada - stop_loss) * 3.0), 2)
    
    fator_lote = info_macro.get("fator_lote", 1.0)
    qtd_bruta = ((vol_alvo_diaria_usd / atr36) * multiplicador) * fator_lote
    qtd_acoes = round(qtd_bruta, 2)

    if qtd_acoes <= 0:
        print(f"[FILTRADO] {ticker} rejeitado por quantidade calculada nula ({qtd_acoes}).")
        return None

    val_calc = entrada * qtd_acoes
    label_lote = "Lote Completo" if fator_lote >= 1.0 else "Lote Reduzido a 50% (Macro Defensivo)"
    valor_investir = f"~{val_calc:.2f} USD ({label_lote})"

    def limpa(v):
        try:
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
        f"EMA8: {limpa(ema8)},EMA32: {limpa(ema32)},ATR36: {limpa(atr36)},"
        f"Forecast: {limpa(forecast_carver)},Multiplicador: x{limpa(multiplicador)},"
        f"Estado: {estado_str},Ordem: BUY STOP,Entrada: {limpa(entrada)},Stop: {limpa(stop_loss)},"
        f"Take-Profit: {limpa(alvo_tp)},Qtd: {qtd_acoes},ValorInvestir: {valor_investir},"
        f"Data: {datetime.now(ZoneInfo('Europe/Lisbon')).strftime('%d/%m/%Y %H:%M:%S')}"
    )

    return {
        "ticker": ticker,
        "setor": setor,
        "forecast": forecast_carver,
        "comboio_str": linha_comboio
    }

def monitorizar_posicao_ativa(ticker, nome_empresa, status_atual, dados_posicao):
    if ticker == "BRK-A":
        ticker = "BRK-B"

    ind = calcular_indicadores_tecnicos(ticker)
    if not ind: return None
    
    preco, ema8, ema32, atr36 = ind['preco'], ind['ema8'], ind['ema32'], ind['atr36']
    
    if pd.isna(preco) or pd.isna(ema8) or pd.isna(ema32) or pd.isna(atr36):
        print(f"[AVISO] Valores inválidos/NaN detetados para {ticker}. Monitorização ignorada hoje.")
        return None

    alerta_earnings = "OK"
    try:
        ticker_obj = yf.Ticker(ticker)
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

    trailing_stop_calculado = round(preco - (atr36 * 1.5), 2)
    
    preco_entrada = dados_posicao.get("precoEntrada", "N/A")
    quantidade = dados_posicao.get("quantidade", "N/A")
    stop_atual_registado = dados_posicao.get("stopAtual", None)
    
    stop_final = trailing_stop_calculado
    instrucao_risco = f"Atualizar stop para {trailing_stop_calculado}"
    
    stop_atual_val = limpar_float(stop_atual_registado)
    if stop_atual_val is not None:
        if stop_atual_val >= trailing_stop_calculado:
            stop_final = stop_atual_val
            instrucao_risco = f"MANTER o Stop atual em {stop_atual_val} (o cálculo matemático de hoje ({trailing_stop_calculado}) é inferior, aplicando-se a regra de inércia do trailing stop)."
        else:
            instrucao_risco = f"SUBIR o Stop do valor anterior ({stop_atual_val}) para o novo patamar ({trailing_stop_calculado})."

    if "PERIGO" in alerta_earnings:
        instrucao_risco += f" | ⚠️ ALERTA CRÍTICO: EARNINGS EM BREVE ({alerta_earnings}) - AVALIAR FECHO PREVENTIVO ANTES DOS RESULTADOS!"

    diferenca_bruta = ema8 - ema32
    forecast_atual = (diferenca_bruta / atr36) * 5.0 if atr36 > 0 else 0

    linha_monitorizacao = (
        f"📌 [POSIÇÃO ATIVA - {status_atual}] {ticker} ({nome_empresa}) | "
        f"Qtd: {quantidade} | Entrada: {preco_entrada} | Preço Atual: {preco:.2f} | "
        f"EMA8: {ema8:.2f} | EMA32: {ema32:.2f} | Forecast: {forecast_atual:.2f} | "
        f"Stop Atual: {stop_atual_registado} | Novo Stop Sugerido: {stop_final} | "
        f"Earnings: {alerta_earnings} | "
        f"🛑 AÇÃO: {instrucao_risco} (ATR: {atr36:.2f})"
    )
    return linha_monitorizacao

# ===================================================================
# 5. EXECUÇÃO PRINCIPAL
# ===================================================================
def executar_motor():
    ativos, posicoes_ativas_dict, configs = buscar_dados_completos()
    if not ativos and not posicoes_ativas_dict:
        print("[AVISO] Nenhum dado carregado do Sheets. A terminar sem erro.")
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
    
    info_macro = verificar_regime_macro()
        
    candidatos_novos = []
    posicoes_em_gestao = []

    for ativo_info in ativos:
        ticker = ativo_info.get("ticker")
        if not ticker or ticker == "#N/A": continue

        if ticker in posicoes_ativas_dict:
            continue

        res = analisar_tendencia_carver(ativo_info, volatilidade_alvo_diaria_usd, info_macro)
        if res:
            candidatos_novos.append(res)

    candidatos_novos = sorted(candidatos_novos, key=lambda k: k['forecast'], reverse=True)

    ativos_acionados = []
    contagem_setores = {}

    for item in candidatos_novos:
        setor = str(item.get("setor", "Desconhecido")).strip()
        qtd_atual_setor = contagem_setores.get(setor, 0)
        
        if qtd_atual_setor < MAX_NOVOS_SINAIS_POR_SETOR:
            ativos_acionados.append(item)
            contagem_setores[setor] = qtd_atual_setor + 1
        else:
            print(f"[CORRELAÇÃO BLOQUEADA] Ativo {item['ticker']} ignorado. Limite de {MAX_NOVOS_SINAIS_POR_SETOR} novos sinais para o setor '{setor}' atingido.")

    for ticker, dados_pos in posicoes_ativas_dict.items():
        status_atual = str(dados_pos.get("status", "")).strip().upper()
        
        if status_atual != "ATIVA_FAST":
            continue
            
        nome = dados_pos.get("nome", ticker)
        monitorizacao = monitorizar_posicao_ativa(ticker, nome, status_atual, dados_pos)
        if monitorizacao:
            posicoes_em_gestao.append(monitorizacao)

    prompt_ia = (
        "MODO ACELERADOR ESTATÍSTICO (CARVER FAST TREND)\n"
        "O teu mandato é auditar as entradas geradas e monitorizar as posições ativas do portefólio.\n"
        "Presta especial atenção ao RS Score institucional anexado aos dados de cada novo sinal para avaliar o contexto de força do mercado.\n"
        "ATENÇÃO À GESTÃO DE RISCO: Respeita estritamente a regra de inércia do trailing stop nas posições ativas "
        "(o stop nunca desce, se o stop atual registado já for superior ao novo cálculo sugerido, a instrução deve ser obrigatoriamente manter o valor atual).\n"
        "Se uma posição ativa apresentar aviso de Earnings em breve, reforça o alerta de fecho preventivo antes da apresentação de resultados.\n\n"
        "REGRAS ESTRITAS:\n"
        "- 🔄 GESTÃO DE ESTADOS NO SHEETS (LEMBRETE OBRIGATÓRIO): Termina o teu relatório com uma secção de 'Lembrete Operacional' contendo exatamente estas duas notas:\n"
        "  1. \"🟢 NOVAS ENTRADAS: Assim que abrires uma nova posição sugerida neste relatório, altera o seu estado no Google Sheets para 'ATIVA_FAST' para que eu inicie o cálculo diário do Trailing Stop.\"\n"
        "  2. \"🔴 SAÍDAS/STOPS: Se uma posição ativa atingir o Trailing Stop, altera o estado no Sheets para 'WIN' (se a trade fechou com lucro) ou 'LOSS' (se fechou com prejuízo) para as tuas estatísticas. Ao mudares o estado, eu deixarei de a monitorizar automaticamente.\"\n"
    )
    
    bloco_texto_ia = f"📊 RELATÓRIO DE DADOS BRUTOS - FAST TREND CARVER 🏄‍♂️\n\n{prompt_ia}\n\n--------------------------------------------------\n"

    if posicoes_em_gestao:
        bloco_texto_ia += "GESTÃO DE POSIÇÕES ATIVAS (TRAILING STOP SUGERIDO & QUANTIDADES):\n\n"
        for pos in posicoes_em_gestao:
            bloco_texto_ia += pos + "\n"
        bloco_texto_ia += "\n--------------------------------------------------\n"

    if not ativos_acionados:
        bloco_texto_ia += f"[MERCADO LENTO / FILTRADO] - Nenhum novo ativo aprovado (Regime Macro: {info_macro['status']}, Forecast Mínimo: {info_macro['min_forecast']}).\n"
    else:
        bloco_texto_ia += f"NOVOS DADOS DE ENTRADA (COMBOIO) - REGIME MACRO: {info_macro['status']}:\n\n"
        for item in ativos_acionados:
            bloco_texto_ia += item["comboio_str"] + "\n"

    with open("comboio_carver_temp.txt", "w", encoding="utf-8") as f:
        f.write(bloco_texto_ia)

    enviar_email_bruto(bloco_texto_ia)

    # ===================================================================
    # 6. NOTIFICAÇÃO TELEGRAM DEBUG (CONTROLADA PELA FLAG DE CONFIGS)
    # ===================================================================
    debug_telegram_ativado = str(configs.get("TELEGRAM_NOTIFICATIONS_DEBUG", "false")).strip().lower() in ["true", "1", "sim", "yes"]

    if debug_telegram_ativado:
        print("A enviar notificação de Debug para o Telegram via função modular...")
        mensagem_debug = "🏄‍♂️ *MOTOR FAST TREND (CARVER)*\n\n🔍 [DEBUG] Execução concluída com sucesso. Relatório Carver gerado e enviado por e-mail."
        enviar_alerta(mensagem_debug)

if __name__ == "__main__":
    executar_motor()
