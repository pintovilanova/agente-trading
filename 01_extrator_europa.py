# ===================================================================================
# SISTEMA DE TRADING INSTITUCIONAL - MOTOR DE BREAKOUTS (EUROPA)
# ===================================================================================
from datetime import datetime
from zoneinfo import ZoneInfo
import yfinance as yf
import pandas_ta as ta
import pandas as pd
import requests
import os
import sys
import smtplib
import json
import numpy as np
import time
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
import warnings
warnings.filterwarnings("ignore")

# Importação da função modular de notificação do Telegram
from F01_notificador_telegram import enviar_alerta

# ===================================================================
# 0.1 TRAVA DE FIM DE SEMANA (Não corre ao Sábado e Domingo)
# ===================================================================
dia_da_semana = datetime.now(ZoneInfo("Europe/Lisbon")).weekday()
if dia_da_semana >= 5:
    print("[INFO] Fim de semana detetado. O mercado está fechado. O Agente vai descansar.")
    # sys.exit(0)

hoje_e_sexta = "SIM" if dia_da_semana == 4 else "NÃO"

# ===================================================================
# 0. CONFIGURAÇÕES E CREDENCIAIS (Lidas do GitHub Secrets)
# ===================================================================
WEBHOOK_URL = os.environ.get('WEBHOOK_URL')
EMAIL_USER = os.environ.get("EMAIL_USER")
EMAIL_PASS = os.environ.get("EMAIL_PASS")
NOME_ABA_EUROPA = "Analise Compra EU"

SMTP_SERVER = "smtp.gmail.com"
SMTP_PORT = 587

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
# 1. FUNÇÃO DE ENVIO DE EMAIL (Com Sistema Anti-Falhas)
# ===================================================================
def enviar_email_para_agente_ia(relatorio_texto, assunto="🇪🇺🎯 tradingRelatorioIA Europa 🛡️"):
    print(f"\nA enviar email para o Agente IA (Assunto: '{assunto}')...")
    
    if not EMAIL_USER or not EMAIL_PASS:
        print("[AVISO] Credenciais de email em falta. A saltar envio.")
        return

    msg = MIMEMultipart()
    msg['From'] = EMAIL_USER
    msg['To'] = EMAIL_USER
    msg['Subject'] = assunto
    
    msg.attach(MIMEText(relatorio_texto, 'plain', 'utf-8'))
    
    max_tentativas = 3
    for tentativa in range(max_tentativas):
        try:
            server = smtplib.SMTP(SMTP_SERVER, SMTP_PORT, timeout=15)
            server.starttls()
            server.login(EMAIL_USER, EMAIL_PASS)
            server.sendmail(EMAIL_USER, EMAIL_USER, msg.as_string())
            server.quit()
            
            print(f"[SUCESSO] Email enviado na tentativa {tentativa + 1}! O teu Agente IA já pode ler a caixa de entrada.")
            break
            
        except Exception as e:
            print(f"[ERRO] Falha ao enviar o email (tentativa {tentativa + 1} de {max_tentativas}): {e}")
            if tentativa < max_tentativas - 1:
                print("A aguardar 5 segundos antes de tentar novamente...")
                time.sleep(5)
            else:
                print("[ERRO CRÍTICO] O servidor Gmail fechou a ligação definitivamente. Falha no envio.")

# ===================================================================
# 2. BUSCAR A WATCHLIST, POSIÇÕES ATIVAS E CONFIGS (Google Sheets via Webhook)
# ===================================================================
print(f"A carregar a Watchlist, Posições Ativas e Configurações da Europa a partir do Google Sheets (Aba: {NOME_ABA_EUROPA})...")
ativos_data = []
posicoes_ativas = {}
configs = {}
try:
    url_get = f"{WEBHOOK_URL}?aba={NOME_ABA_EUROPA}"
    resposta_webhook = requests.get(url_get, timeout=15)
    if resposta_webhook.status_code == 200:
        dados_webhook = resposta_webhook.json()
        
        if isinstance(dados_webhook, dict) and "ativos" in dados_webhook:
            ativos_data = dados_webhook.get("ativos", [])
            posicoes_ativas = dados_webhook.get("posicoesAtivas", {})
            configs = dados_webhook.get("configs", {})
        elif isinstance(dados_webhook, list):
            ativos_data = dados_webhook
            posicoes_ativas = {}
            configs = {}
        else:
            ativos_data = []
            posicoes_ativas = {}
            configs = {}

        print(f"[SUCESSO] {len(ativos_data)} ativos europeus carregados da Watchlist.")
        print(f"[SUCESSO] {len(posicoes_ativas)} posições ativas detetadas no Diário de Bordo.")
    else:
        print(f"[ERRO] Falha ao descarregar dados: {resposta_webhook.status_code}")
except Exception as e:
    print(f"[ERRO CRÍTICO] Falha de comunicação com Sheets: {e}")

# ===================================================================
# LEITURA DINÂMICA DAS CONFIGURAÇÕES DE RISCO
# ===================================================================
try:
    capital_total_conta = float(configs.get("CAPITAL_TOTAL_CONTA", 10400.00))
    alvo_volatilidade_anual = float(configs.get("ALVO_VOLATILIDADE_ANUAL", 0.05))
except (ValueError, TypeError):
    capital_total_conta = 10400.00
    alvo_volatilidade_anual = 0.05

volatilidade_alvo_diaria_usd = (capital_total_conta * alvo_volatilidade_anual) / 16.0
risco_maximo_dolares = volatilidade_alvo_diaria_usd
multiplicador_trailing_ts = 1.5
racio_tp_base = 3.0

print(f"[CONFIG] Capital Total da Conta: ${capital_total_conta:,.2f}")
print(f"[CONFIG] Alvo Volatilidade Anual: {alvo_volatilidade_anual*100:.1f}%")
print(f"[CONFIG] Orçamento Diário de Volatilidade: ${volatilidade_alvo_diaria_usd:.2f}\n")

# ===================================================================
# 3. VERIFICAÇÃO DE VETO MACRO (SPY) - MODO NÃO-BLOQUEANTE
# ===================================================================
print("A verificar Veto Macro (SPY)...")
veto_macro_ativo = False
motivo_veto = ""

try:
    df_spy = yf.download("SPY", period="2y", interval="1d", progress=False)
    if isinstance(df_spy.columns, pd.MultiIndex):
        df_spy.columns = df_spy.columns.droplevel(1)
        
    df_spy = df_spy.dropna(subset=['Close', 'High', 'Low'])
    df_spy.ta.sma(length=200, append=True)
    spy_hoje = df_spy.iloc[-1]
    spy_ontem = df_spy.iloc[-2]
    
    preco_spy = float(spy_hoje['Close'])
    preco_spy_ontem = float(spy_ontem['Close'])
    sma200_spy = float(spy_hoje['SMA_200'])
    
    queda_spy = ((preco_spy - preco_spy_ontem) / preco_spy_ontem) * 100
    
    if queda_spy <= -1.50:
        veto_macro_ativo = True
        motivo_veto = f"SPY em Pânico: Caiu {queda_spy:.2f}% (<= -1.50%). Abertura de novas posições europeias bloqueada."
        print(f"[ALERTA MACRO] {motivo_veto}")
    elif preco_spy < sma200_spy:
        veto_macro_ativo = True
        motivo_veto = f"SPY em Tendência de Baixa: Preço (${preco_spy:.2f}) abaixo da SMA200 (${sma200_spy:.2f})."
        print(f"[ALERTA MACRO] {motivo_veto}")
    else:
        print("[OK] SPY Saudável. A iniciar análise normalmente...\n")
except Exception as e:
    print(f"[AVISO] Erro na validação do SPY: {e}")

dados_temporarios = []

# ===================================================================
# 4. MOTOR MATEMÁTICO V2 (Para todos os Ativos)
# ===================================================================
if not veto_macro_ativo and ativos_data:
    for ativo_info in ativos_data:
        ticker = str(ativo_info.get("ticker", "")).strip().upper()
        nome_empresa = ativo_info.get("nome", "N/A")
        rs_score = ativo_info.get("rs_score", "N/A")
        setor = str(ativo_info.get("setor", "Europa")).strip()
        
        if not ticker or ticker == "#N/A" or ticker == "NONE":
            continue
        
        try:
            df = yf.download(ticker, period="2y", interval="1d", progress=False)
            if df.empty:
                print(f"[AVISO] Sem dados para {ticker}.")
                continue
                
            if isinstance(df.columns, pd.MultiIndex):
                df.columns = df.columns.droplevel(1)

            df = df.dropna(subset=['Close', 'High', 'Low', 'Volume'])
            if df.empty or len(df) < 50:
                continue

            alerta_earnings = "OK"
            try:
                ticker_obj = yf.Ticker(ticker)
                
                if setor in ["Europa", "Desconhecido", "N/A", "", "NONE"]:
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

            df.ta.rsi(length=14, append=True)
            df.ta.adx(length=14, append=True)
            df.ta.atr(length=14, append=True)
            df.ta.sma(length=200, append=True)
            df.ta.sma(length=20, append=True)
            df.ta.mom(length=14, append=True)
            df.ta.ema(length=9, append=True)

            media_volume_20 = df['Volume'].rolling(window=20).mean()
            df['RVOL'] = df['Volume'] / media_volume_20

            df = df.dropna(subset=['RSI_14', 'ADX_14', 'ATRr_14', 'SMA_20', 'EMA_9', 'MOM_14'])
            if df.empty: continue

            ultimo_dia = df.iloc[-1]
            dia_anterior = df.iloc[-2]

            preco = float(ultimo_dia['Close'])
            preco_anterior = float(dia_anterior['Close'])
            var_perc = ((preco - preco_anterior) / preco_anterior) * 100
            
            sma20 = float(ultimo_dia['SMA_20'])
            dist_mm20 = ((preco - sma20) / sma20) * 100
            
            ema9 = float(ultimo_dia['EMA_9'])
            ema9_anterior = float(dia_anterior['EMA_9'])
            
            cruzou_ema9 = (preco > ema9) and (preco_anterior <= ema9_anterior) if pd.notna(ema9) and pd.notna(ema9_anterior) else False
            acima_ema9 = preco > ema9 if pd.notna(ema9) else False

            rvol = float(ultimo_dia['RVOL'])
            adx = float(ultimo_dia['ADX_14'])
            rsi = float(ultimo_dia['RSI_14'])
            atr = float(ultimo_dia['ATRr_14'])
            momentum = float(ultimo_dia['MOM_14'])

            atr_perc = round((atr / preco) * 100, 2) if pd.notna(atr) and pd.notna(preco) and preco > 0 else "N/A"

            recomendacao = "Observar"
            preco_entrada = "N/A"
            preco_stop = "N/A"
            preco_tp = "N/A"
            preco_be = "N/A"
            qtd_acoes = "N/A"
            multiplicador_atr = 1.0

            trailing_base = preco - (atr * multiplicador_trailing_ts) if pd.notna(preco) and pd.notna(atr) else "N/A"
            trailing_final = round(trailing_base, 2) if trailing_base != "N/A" else "N/A"

            preco_caiu_hoje = preco < preco_anterior if pd.notna(preco) and pd.notna(preco_anterior) else False
            volume_despejo = rvol > 1.20 if pd.notna(rvol) else False

            if pd.isna(momentum) or pd.isna(adx) or pd.isna(rvol) or pd.isna(rsi) or pd.isna(dist_mm20) or pd.isna(atr):
                 recomendacao = "Observar"
            elif (preco_caiu_hoje and volume_despejo) or (momentum <= 0.5):
                recomendacao = "Observar"
                
            elif var_perc > 0 and adx < 25 and not cruzou_ema9:
                recomendacao = "Aguardar Recuo"
                preco_entrada = round(preco - (atr * 0.4), 2)
                multiplicador_atr = 1.0
                
            elif cruzou_ema9 and rvol > 1.00 and momentum > 0.50 and rsi > 50 and dist_mm20 <= 3.00:
                recomendacao = "Ignicao EMA9"
                preco_entrada = round(preco - (atr * 0.1), 2)
                multiplicador_atr = 1.2
                
            elif var_perc > 0 and adx >= 30 and rvol >= 1.20 and (55.00 <= rsi <= 72.00) and (0.00 <= dist_mm20 <= 3.00) and momentum > 1.50 and acima_ema9:
                recomendacao = "Forca Consolidada"
                preco_entrada = round(preco - (atr * 0.1), 2)
                multiplicador_atr = 1.3 
                
            elif adx >= 25 and rvol >= 1.00 and (50.00 <= rsi <= 75.00) and (-1.00 <= dist_mm20 <= 3.00) and momentum > 0.50 and acima_ema9:
                recomendacao = "Alerta Iminente"
                preco_entrada = round(preco - (atr * 0.2), 2)
                multiplicador_atr = 1.2
                
            else:
                recomendacao = "Observar"

            # FILTRO DE SEGURANÇA: PREÇO FUGIDO (GAP > 1% DA ENTRADA)
            if recomendacao != "Observar" and isinstance(preco_entrada, (int, float)):
                variacao_pct_entrada = ((preco - preco_entrada) / preco_entrada) * 100
                if variacao_pct_entrada > 1.0:
                    recomendacao = "Observar"
                    preco_entrada = "N/A"

            if recomendacao != "Observar" and preco_entrada != "N/A":
                preco_stop_calc = preco_entrada - (atr * multiplicador_atr)
                if preco_stop_calc > sma20 and preco > sma20:
                    preco_stop_calc = sma20 * 0.995
                
                preco_stop = round(preco_stop_calc, 2)
                risco_por_acao = preco_entrada - preco_stop_calc
                
                if risco_por_acao > 0:
                    tp_calc = preco_entrada + (risco_por_acao * racio_tp_base)
                    preco_tp = round(tp_calc, 2)
                    qtd_calc = round(risco_maximo_dolares / risco_por_acao, 2) if risco_por_acao > 0 else 0
                    
                    if qtd_calc <= 0:
                        recomendacao = "Observar"
                        qtd_acoes = "N/A"
                    else:
                        qtd_acoes = qtd_calc
                        dist_tp = preco_tp - preco_entrada
                        preco_be = round(preco_entrada + (dist_tp / 2), 2)
                        trailing_final = round(max(trailing_base, preco_stop_calc), 2)

            data_atual = datetime.now(ZoneInfo("Europe/Lisbon")).strftime('%d/%m/%Y %H:%M:%S')

            if ticker in posicoes_ativas:
                pos_info = posicoes_ativas[ticker]
                status_pos = str(pos_info.get('status', 'ATIVA')).strip().upper()
                if status_pos in ['ATIVA_FAST', 'ATIVA_SWING']:
                    info_carteira = f"NÃO (Gerido pelo modelo {status_pos.replace('ATIVA_', '')} - {status_pos})"
                else:
                    info_carteira = f"SIM (Entrada: {pos_info.get('precoEntrada', 'N/A')}, StopAtual: {pos_info.get('stopAtual', 'N/A')}, Qtd: {pos_info.get('quantidade', 'N/A')})"
            else:
                info_carteira = "NÃO"

            def limpa(v):
                try:
                    if v == "N/A" or pd.isna(v): return "N/A"
                    val = float(v)
                    if np.isnan(val): return "N/A"
                    return round(val, 2)
                except:
                    return "N/A"

            val_rs_num = limpar_float(rs_score)
            if val_rs_num is not None:
                if val_rs_num >= 80:
                    status_rs = "🔥 ELITE (RS >= 80 - Vento a Favor)"
                elif val_rs_num >= 50:
                    status_rs = "⚖️ NEUTRO (RS 50-79 - Acompanha o Mercado)"
                else:
                    status_rs = "⚠️ FRACO / LAGGARD (RS < 50 - Vento Contra)"
            else:
                status_rs = "❓ SEM DADO DE RS"

            dados_temporarios.append({
                "ticker": ticker,
                "nome": nome_empresa,
                "setor": setor,
                "rs_score": rs_score,
                "status_rs": status_rs,
                "preco": limpa(preco),
                "dist_mm20": limpa(dist_mm20),
                "ema9": limpa(ema9),
                "momentum": limpa(momentum),
                "rsi": limpa(rsi),
                "adx": limpa(adx),
                "atr": limpa(atr),
                "atr_perc": limpa(atr_perc),
                "rvol": limpa(rvol),
                "estado": recomendacao,
                "entrada": round(preco_entrada, 2) if isinstance(preco_entrada, float) else preco_entrada,
                "stop": preco_stop,
                "tp": preco_tp,
                "be": preco_be,
                "qtd_bruta": qtd_acoes,
                "trailing": trailing_final,
                "earnings": alerta_earnings,
                "posicao_ativa": info_carteira,
                "data": data_atual
            })
            
            print(f"[OK] {ticker} analisado. Setor: {setor} | Estado: {recomendacao}")

        except Exception as e:
            print(f"[ERRO] Falha ao processar {ticker}: {e}")

# ===================================================================
# 4.1. AUDITORIA MACRO E CORTE MATEMÁTICO DE LOTES
# ===================================================================
total_ativos = len(dados_temporarios)
ativos_estagnados = sum(1 for d in dados_temporarios if d["estado"] in ["Observar", "Aguardar Recuo"])
macro_hostil = False

if hoje_e_sexta == "SIM":
    macro_hostil = True
elif total_ativos > 0 and (ativos_estagnados / total_ativos) >= 0.70:
    macro_hostil = True

tipo_lote = "Reduzido a 50%" if macro_hostil else "Completo"

resultados_para_sheets = []
comboio_ia = []

for d in dados_temporarios:
    qtd_final = d["qtd_bruta"]
    
    if qtd_final != "N/A" and macro_hostil:
        try:
            qtd_final = round(float(qtd_final) / 2, 2)
        except ValueError:
            pass
        
    valor_investir = "N/A - Posição Existente"
    if d['posicao_ativa'].startswith("NÃO") and d['entrada'] != "N/A" and qtd_final != "N/A":
        try:
            val_calc = float(d['entrada']) * float(qtd_final)
            valor_investir = f"~{val_calc:.2f} EUR"
        except ValueError:
            pass

    entrada_str = f"{d['entrada']:.2f}" if isinstance(d['entrada'], (int, float)) else d['entrada']
    
    linha_comboio = (
        f"{d['ticker']},Nome: {d['nome']},Setor: {d['setor']},Preço: {d['preco']},"
        f"RS Score: {d['rs_score']} ({d['status_rs']}),"
        f"Dist MM20: {d['dist_mm20']}%,EMA9: {d['ema9']},Momentum: {d['momentum']},"
        f"RSI: {d['rsi']},ADX: {d['adx']},ATR: {d['atr']} (Vol: {d['atr_perc']}%),"
        f"RVOL: {d['rvol']},Estado: {d['estado']},Entrada: {entrada_str},"
        f"Stop: {d['stop']},Take-Profit: {d['tp']},Break-Even: {d['be']},"
        f"Qtd: {qtd_final},ValorInvestir: {valor_investir},Trailing: {d['trailing']},Lote: {tipo_lote},Earnings: {d['earnings']},"
        f"PosicaoAtiva: {d['posicao_ativa']},Data: {d['data']}"
    )
    
    resultados_para_sheets.append({
        "ticker": d['ticker'],
        "preco": d['preco'],
        "rs_score": d['rs_score'],
        "momentum": d['momentum'],
        "rsi": d['rsi'],
        "adx": d['adx'],
        "atr": d['atr'],
        "time": d['data'],
        "comboio": linha_comboio
    })

    comboio_ia.append(d)
    comboio_ia[-1]["quantidade"] = qtd_final
    comboio_ia[-1]["valor_investir"] = valor_investir
    comboio_ia[-1]["lote"] = tipo_lote
    comboio_ia[-1]["comboio_str"] = linha_comboio

# ===================================================================
# 5. ENVIO PARA O GOOGLE SHEETS
# ===================================================================
if resultados_para_sheets and WEBHOOK_URL:
    print(f"\nA atualizar o Google Sheets (Aba: {NOME_ABA_EUROPA})...")
    try:
        payload_sheets = {
            "acao": "atualizar_colunas_todas",
            "aba": NOME_ABA_EUROPA,
            "dados": resultados_para_sheets
        }
        headers = {'Content-Type': 'application/json'}
        resposta = requests.post(WEBHOOK_URL, data=json.dumps(payload_sheets), headers=headers)
        if resposta.status_code == 200:
            print("[SUCESSO] Google Sheets atualizado com sucesso!")
        else:
            print(f"[ERRO] Status HTTP: {resposta.status_code} - {resposta.text}")
    except Exception as e:
        print(f"[ERRO CRÍTICO] Falha HTTP Sheets: {e}")

# ===================================================================
# 6. GERAR BLOCO DE TEXTO E ENVIAR PARA O AGENTE IA
# ===================================================================
data_hoje = datetime.now(ZoneInfo("Europe/Lisbon")).strftime("%d/%m/%Y %H:%M")

bloco_texto_ia = (
    f"🇪🇺 RELATÓRIO DE DADOS BRUTOS - EUROPEAN BREAKOUTS ({data_hoje})\n"
    f"==================================================================\n\n"
)

if veto_macro_ativo:
    bloco_texto_ia += f"🚨 [VETO MACRO ATIVADO]\n{motivo_veto}\n"
    bloco_texto_ia += "⚠️ Novas compras europeias suspensas hoje, mas a pipeline continua para auditar e gerir as POSIÇÕES ATIVAS em carteira.\n"
    bloco_texto_ia += "--------------------------------------------------\n\n"
else:
    bloco_texto_ia += "🟢 [MERCADO ESTÁVEL] Filtro do SPY dentro dos parâmetros normais. Pipeline autorizada.\n"
    bloco_texto_ia += "--------------------------------------------------\n\n"

ativos_acionados = [
    item for item in comboio_ia 
    if item["estado"] != "Observar" or item["posicao_ativa"] != "NÃO"
]

if veto_macro_ativo:
    bloco_texto_ia += "✅ Análise de novas entradas da watchlist omitida devido ao Veto Macro.\n"
elif not ativos_acionados:
    bloco_texto_ia += "[MERCADO ESTAGNADO - POSTURA DEFENSIVA] - Nenhum ativo europeu preencheu os requisitos mínimos de entrada.\n"
else:
    bloco_texto_ia += "DADOS DOS ATIVOS ACIONADOS (COMBOIO):\n\n"
    for item in ativos_acionados:
        bloco_texto_ia += item["comboio_str"] + "\n"

print("A gravar ficheiro temporário 'comboio_europa.txt'...")
with open("comboio_europa.txt", "w", encoding="utf-8") as f:
    f.write(bloco_texto_ia)
    
enviar_email_para_agente_ia(bloco_texto_ia, assunto="🇪🇺🎯 tradingRelatorioIA Europa 🛡️")

# ===================================================================
# 7. NOTIFICAÇÃO TELEGRAM DEBUG (CONTROLADA PELA FLAG DE CONFIGS)
# ===================================================================
debug_telegram_ativado = str(configs.get("TELEGRAM_NOTIFICATIONS_DEBUG", "false")).strip().lower() in ["true", "1", "sim", "yes"]

if debug_telegram_ativado:
    print("A enviar notificação de Debug para o Telegram via função modular...")
    total_analisados = len(dados_temporarios)
    total_acionados = len(ativos_acionados)
    mensagem_debug = (
        f"01 🇪🇺 *MOTOR BREAKOUTS (EUROPA)*\n\n"
        f"🔍 [DEBUG] Execução concluída com sucesso.\n"
        f"📊 Ativos analisados: *{total_analisados}* | Acionados: *{total_acionados}*\n"
        f"✉️ Relatório de breakout europeu gerado e enviado por e-mail."
    )
    enviar_alerta(mensagem_debug)

print("[SUCESSO] Execução do Motor de Breakouts (Europa) concluída sem erros.")
sys.exit(0)
