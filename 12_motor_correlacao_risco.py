# ===================================================================================
# SISTEMA DE TRADING INSTITUCIONAL - MOTOR 12: ESCUDO DE CORRELAÇÃO DE RISCO
# ===================================================================================
# Descrição Geral:
# Analisa a Matriz de Correlação de Pearson (6 meses) entre:
# 1. Novos Sinais de Entrada emitidos hoje pelos diversos Motores (comboio_*_temp.txt)
# 2. Posições Ativas já abertas em carteira (Google Sheets -> posicoesAtivas)
# Evita duplicação oculta de risco sistémico (Correlação >= 80%).
# ===================================================================================

import pandas as pd
import yfinance as yf
import numpy as np
import os
import re
import sys
import glob
import time
import random
import requests
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
    print("[INFO] Fim de semana detetado. O Motor 12 (Correlação) vai descansar.")
    # sys.exit(0)

# ===================================================================
# 1. CONFIGURAÇÕES
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

# Limiar de correlação considerado perigoso (80%)
LIMIAR_CORRELACAO = 0.80

def gravar_ficheiro_correlacao(conteudo):
    with open("comboio_correlacao_temp.txt", "w", encoding="utf-8") as f:
        f.write(conteudo)

def enviar_email(assunto, corpo_texto):
    if not EMAIL_USER or not EMAIL_PASS:
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

def buscar_posicoes_e_configs():
    """Obtém as posições ativas em carteira e configs a partir do Google Sheets."""
    ativos_carteira = set()
    configs_dict = {}
    if not WEBHOOK_URL:
        return ativos_carteira, configs_dict
    try:
        url_alvo = WEBHOOK_URL if "?" in WEBHOOK_URL else f"{WEBHOOK_URL}?aba=Analise Compra"
        resp = requests.get(url_alvo, timeout=15)
        if resp.status_code == 200:
            dados = resp.json()
            if isinstance(dados, dict):
                configs_dict = dados.get("configs", {})
                posicoes = dados.get("posicoesAtivas", {}) or dados.get("posicoes", {})
                for chave_pos, info in posicoes.items():
                    if isinstance(info, dict) and str(info.get("status", "")).strip().upper().startswith("ATIVA"):
                        t_pos = "AI" if chave_pos.lower() in ["c3.ai", "c3"] else chave_pos.strip().upper().replace(".", "-")
                        if t_pos == "BRK-A":
                            t_pos = "BRK-B"
                        ativos_carteira.add(t_pos)
    except Exception as e:
        print(f"[AVISO] Falha ao ler posicoesAtivas do Sheets: {e}")
    return ativos_carteira, configs_dict

def get_yf_history_safe(tickers_list, period="6mo"):
    """Descarrega dados históricos com resiliência contra rate-limits e sem dropna global destrutivo."""
    series_fechos = {}
    for ticker in sorted(set(tickers_list)):
        for tentativa in range(3):
            try:
                time.sleep(random.uniform(0.35, 0.85))
                df = yf.download(ticker, period=period, interval="1d", progress=False, session=session, timeout=15)
                if not df.empty and len(df) >= 45:
                    if isinstance(df.columns, pd.MultiIndex):
                        df.columns = df.columns.droplevel(1)
                    s_close = df['Close'].dropna()
                    if len(s_close) >= 45:
                        series_fechos[ticker] = s_close
                        break
            except Exception:
                time.sleep(1.5)
    if not series_fechos:
        return pd.DataFrame()
    return pd.DataFrame(series_fechos)

def extrair_tickers_dos_comboios():
    """
    Lê todos os ficheiros temporários comboio_*_temp.txt para descobrir os sinais novos de hoje,
    ignorando a secção de gestão de posições ativas para evitar falsos positivos.
    """
    arquivos = sorted(glob.glob("comboio_*_temp.txt"))
    origem_sinais = {}  # ticker -> list de ficheiros/motores onde surgiu

    padrao_novo = re.compile(r"^\s*(?:🔹|💎|🚀|⚡|🎯|📌)?\s*\[([A-Z]{1,6}(?:-[A-Z]{1,2})?)\]\s*-")

    for arq in arquivos:
        if any(ign in arq for ign in ("rotacao", "macro", "correlacao")):
            continue

        nome_fonte = arq.replace("comboio_", "").replace("_temp.txt", "").upper()
        try:
            with open(arq, "r", encoding="utf-8") as f:
                em_gestao_ativas = False
                for linha in f:
                    linha_strip = linha.strip()
                    if "GESTÃO DE POSIÇÕES ATIVAS" in linha_strip.upper():
                        em_gestao_ativas = True
                        continue
                    if em_gestao_ativas and ("NOVOS SINAIS" in linha_strip.upper() or "SINAIS DE ALTA PROBABILIDADE" in linha_strip.upper() or "MODO DEFENSIVO" in linha_strip.upper()):
                        em_gestao_ativas = False
                        continue
                    if em_gestao_ativas:
                        continue

                    # 1. Formato atual: "🔹 [NVDA] - Nvidia..." ou "💎 [MSFT] - Microsoft..."
                    m = padrao_novo.match(linha_strip)
                    if m:
                        ticker = m.group(1).strip().upper().replace(".", "-")
                        if ticker == "BRK-A":
                            ticker = "BRK-B"
                        origem_sinais.setdefault(ticker, []).append(nome_fonte)
                        continue

                    # 2. Formato legado: "NVDA,Nome: Nvidia,Setor: ..."
                    if "," in linha_strip and "Nome:" in linha_strip:
                        ticker = linha_strip.split(",")[0].strip().upper().replace(".", "-")
                        if ticker == "BRK-A":
                            ticker = "BRK-B"
                        if re.match(r"^[A-Z]{1,6}(?:-[A-Z]{1,2})?$", ticker):
                            origem_sinais.setdefault(ticker, []).append(nome_fonte)
        except Exception as e:
            print(f"[AVISO] Falha ao ler {arq}: {e}")

    return origem_sinais

# ===================================================================
# 2. MOTOR MATEMÁTICO: MATRIZ DE CORRELAÇÃO DE PEARSON
# ===================================================================
print("A iniciar o Motor de Correlação de Risco (Portfolio Shield)...")
data_hoje = datetime.now(ZoneInfo("Europe/Lisbon")).strftime("%d/%m/%Y %H:%M:%S")

origem_sinais_hoje = extrair_tickers_dos_comboios()
tickers_novos = sorted(origem_sinais_hoje.keys())
tickers_carteira, configs_dict = buscar_posicoes_e_configs()

todos_tickers = sorted(set(tickers_novos) | tickers_carteira)

if len(tickers_novos) == 0 or len(todos_tickers) < 2:
    relatorio = f"🛡️ MOTOR 12 - ESCUDO DE CORRELAÇÃO DE RISCO ({data_hoje})\n"
    relatorio += "=" * 65 + "\n"
    relatorio += f"📊 Sinais novos hoje: {len(tickers_novos)} | Posições ativas em carteira: {len(tickers_carteira)}\n"
    relatorio += "✅ Nenhum risco de clusterização detetado. Menos de 2 ativos elegíveis para cruzamento hoje.\n"
    
    gravar_ficheiro_correlacao(relatorio)
    print(relatorio)
    sys.exit(0)

print(f"[{len(tickers_novos)}] Novos Sinais: {', '.join(tickers_novos)}")
if tickers_carteira:
    print(f"[{len(tickers_carteira)}] Em Carteira: {', '.join(sorted(tickers_carteira))}")

df_precos = get_yf_history_safe(todos_tickers, period="6mo")

if df_precos.empty or df_precos.shape[1] < 2:
    relatorio = f"🛡️ MOTOR 12 - ESCUDO DE CORRELAÇÃO DE RISCO ({data_hoje})\n"
    relatorio += "=" * 65 + "\n"
    relatorio += "⚠️ Dados históricos insuficientes no Yahoo Finance para calcular a matriz de correlação hoje.\n"
    gravar_ficheiro_correlacao(relatorio)
    print("[AVISO] Falha ao obter dados suficientes para correlação.")
    sys.exit(0)

# Retornos diários e correlação pairwise (resiliente a feriados/datas distintas)
df_retornos = df_precos.pct_change()
matriz_corr = df_retornos.corr(min_periods=40)

# ===================================================================
# 3. GERAÇÃO DE ALERTAS E RESOLUÇÃO DE CONFLITOS
# ===================================================================
relatorio = f"🛡️ MOTOR 12 - ESCUDO DE CORRELAÇÃO DE RISCO ({data_hoje})\n"
relatorio += "=" * 65 + "\n"
relatorio += f"📊 Novos Sinais Analisados ({len(tickers_novos)}): {', '.join(tickers_novos)}\n"
if tickers_carteira:
    relatorio += f"📌 Posições Ativas Cruzadas ({len(tickers_carteira)}): {', '.join(sorted(tickers_carteira))}\n"
relatorio += "=" * 65 + "\n\n"

conflitos_novos_vs_novos = []
conflitos_novos_vs_carteira = []
pares_analisados = set()

colunas_validas = list(matriz_corr.columns)
for i in range(len(colunas_validas)):
    for j in range(i + 1, len(colunas_validas)):
        t1 = colunas_validas[i]
        t2 = colunas_validas[j]
        correlacao = float(matriz_corr.iloc[i, j])

        if np.isnan(correlacao) or correlacao < LIMIAR_CORRELACAO:
            continue

        par = tuple(sorted([t1, t2]))
        if par in pares_analisados:
            continue
        pares_analisados.add(par)

        t1_novo = t1 in origem_sinais_hoje
        t2_novo = t2 in origem_sinais_hoje
        t1_cart = t1 in tickers_carteira
        t2_cart = t2 in tickers_carteira

        # Ignora pares compostos apenas por posições já antigas em carteira
        if not (t1_novo or t2_novo):
            continue

        if t1_novo and t2_novo:
            m1 = "/".join(sorted(set(origem_sinais_hoje[t1])))
            m2 = "/".join(sorted(set(origem_sinais_hoje[t2])))
            conflitos_novos_vs_novos.append((t1, m1, t2, m2, correlacao))

        if (t1_novo and t2_cart) or (t2_novo and t1_cart):
            novo_t = t1 if t1_novo else t2
            cart_t = t2 if t1_novo else t1
            m_novo = "/".join(sorted(set(origem_sinais_hoje[novo_t])))
            conflitos_novos_vs_carteira.append((novo_t, m_novo, cart_t, correlacao))

conflitos_detetados = bool(conflitos_novos_vs_novos or conflitos_novos_vs_carteira)

if conflitos_novos_vs_carteira:
    relatorio += "🚨 CONFLITO COM POSIÇÕES JÁ ATIVAS EM CARTEIRA (PRIORIDADE MÁXIMA):\n"
    for novo_t, m_novo, cart_t, corr in sorted(conflitos_novos_vs_carteira, key=lambda x: x[3], reverse=True):
        relatorio += f"⚠️ [{novo_t}] ({m_novo}) vs [{cart_t}] (EM CARTEIRA) -> Correlação: {corr*100:.1f}%\n"
        relatorio += f"    • Diagnóstico: Já tens [{cart_t}] aberta; entrar em [{novo_t}] duplica a exposição ao mesmo movimento institucional.\n"
        relatorio += f"    • Ação Tática Exigida: DESCARTAR entrada em [{novo_t}] (ou entrar apenas com 50% do lote se [{cart_t}] já tiver Stop em Break-Even).\n\n"

if conflitos_novos_vs_novos:
    relatorio += "⚠️ CONFLITO ENTRE NOVOS SINAIS DE HOJE (CLUSTERIZAÇÃO):\n"
    for t1, m1, t2, m2, corr in sorted(conflitos_novos_vs_novos, key=lambda x: x[4], reverse=True):
        relatorio += f"⚠️ [{t1}] ({m1}) vs [{t2}] ({m2}) -> Correlação: {corr*100:.1f}%\n"
        relatorio += f"    • Diagnóstico: Movimentam-se em bloco (>= 80%). Comprar ambas duplica o risco num único fator.\n"
        relatorio += f"    • Ação Tática Exigida: Executar APENAS o ativo com maior RS Score institucional OU dividir o risco (50% do lote em cada).\n\n"

if not conflitos_detetados:
    relatorio += "✅ PIPELINE LIMPA: Os ativos sugeridos hoje têm baixa correlação (< 80%) entre si e face à carteira atual.\n"
    relatorio += "O risco sistémico e setorial está diversificado de forma saudável.\n"

relatorio += "-" * 65 + "\n"
relatorio += "NOTA: Correlação >= 80% (6 meses) indica que fundos institucionais negociam estes ativos como um único bloco.\n"

# Guardar localmente para o Orquestrador ler
gravar_ficheiro_correlacao(relatorio)

print(relatorio)
print("\n[SUCESSO] Relatório de Correlação gerado.")

if conflitos_detetados:
    enviar_email(
        f"🛡️ tradingRelatorioIA US - ALERTA CORRELAÇÃO DE RISCO ({datetime.now(ZoneInfo('Europe/Lisbon')).strftime('%d/%m/%Y')})",
        relatorio
    )

# ===================================================================
# 4. NOTIFICAÇÃO TELEGRAM (DEBUG OU ALERTA DE CONFLITO)
# ===================================================================
debug_telegram_ativado = str(configs_dict.get("TELEGRAM_NOTIFICATIONS_DEBUG", "false")).strip().lower() in ["true", "1", "sim", "yes"]

if debug_telegram_ativado or conflitos_detetados:
    print("A enviar notificação para o Telegram via função modular...")
    total_conflitos = len(conflitos_novos_vs_carteira) + len(conflitos_novos_vs_novos)
    status_msg = f"⚠️ *{total_conflitos} Conflito(s) de Correlação (>=80%)* detetado(s)!" if conflitos_detetados else "✅ Pipeline Limpa (Sem Conflitos)"
    mensagem_debug = (
        f"12 🛡️ *ESCUDO DE CORRELAÇÃO*\n\n"
        f"🔍 Cruzamento concluído ({len(tickers_novos)} sinais vs {len(tickers_carteira)} em carteira).\n"
        f"Estado: {status_msg}\n"
        f"📄 Relatório anexado ao Orquestrador."
    )
    enviar_alerta(mensagem_debug)
