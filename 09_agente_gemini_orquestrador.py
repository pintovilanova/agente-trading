import os
import sys
import time
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
import google.generativeai as genai
from datetime import datetime
from zoneinfo import ZoneInfo

# ===================================================================
# SISTEMA DE TRADING INSTITUCIONAL - AGENTE IA ORQUESTRADOR (PIPELINE)
# ===================================================================
# Descrição:
# Este script corre no final da pipeline diária. Varre o disco da máquina 
# virtual em busca de TODOS os ficheiros "comboio" (Extratores US/EU e Motores).
# Junta a informação, audita via Gemini LLM e envia um Email Unificado.
# ===================================================================

# 1. CREDENCIAIS (GitHub Secrets)
EMAIL_USER = os.environ.get("EMAIL_USER")
EMAIL_PASS = os.environ.get("EMAIL_PASS")
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY")
SMTP_SERVER = "smtp.gmail.com"
SMTP_PORT = 587

if not GEMINI_API_KEY:
    print("[ERRO] GEMINI_API_KEY não encontrada nas variáveis de ambiente.")
    sys.exit(1)

genai.configure(api_key=GEMINI_API_KEY)

# Usa o modelo Gemini configurado
modelo_ia = genai.GenerativeModel('gemini-3.6-flash')

# 2. DEFINIR OS FICHEIROS GERADOS PELOS EXTRATORES E MOTORES
ficheiros_alvo = [
    "comboio_temp.txt",     # Ficheiro do Extrator US
    "comboio_europa.txt", # Ficheiro do Extrator Europa
    "comboio_vcp_temp.txt",             # Ficheiro do Motor 07 (VCP Breakout)
    "comboio_reversao_temp.txt",        # Ficheiro do Motor 03 (Pânico)
    "comboio_earnings_temp.txt",        # Ficheiro do Motor 04 (PEAD)
    "comboio_connors_temp.txt",        # Ficheiro do Motor 05 (REVERSAO)
    "comboio_carver_temp.txt"           # Ficheiro do Motor 06 (Fast Trend Carver)
]

conteudo_bruto_total = ""
motores_ativos = 0

print("A procurar relatórios dos extratores e motores na máquina virtual...")

# 3. RECOLHER DADOS DE TODOS OS FICHEIROS DISPONÍVEIS
for ficheiro in ficheiros_alvo:
    if os.path.exists(ficheiro):
        with open(ficheiro, "r", encoding="utf-8") as f:
            dados = f.read().strip()
            if dados and "Nenhum ativo" not in dados and "[SEM OPORTUNIDADES]" not in dados:
                conteudo_bruto_total += f"\n\n==================================\n"
                conteudo_bruto_total += f"📁 FONTE: {ficheiro}\n"
                conteudo_bruto_total += f"==================================\n{dados}\n"
                motores_ativos += 1
                print(f"[ENCONTRADO] Dados detetados no {ficheiro}.")
            else:
                print(f"[VAZIO] {ficheiro} lido, mas sem conteúdo relevante para hoje.")
    else:
        print(f"[FALTA] {ficheiro} não encontrado.")

# 4. VALIDAÇÃO DE SEGURANÇA
if motores_ativos == 0 or not conteudo_bruto_total.strip():
    print("\n[INFO] Nenhum extrator ou motor gerou dados válidos hoje. A pipeline termina de forma silenciosa.")
    sys.exit(0)


# 5. PROMPT DO ORQUESTRADOR IA
prompt_orquestrador = f"""
És o Analista Quantitativo Principal (Agente Orquestrador).
Abaixo estão os relatórios em bruto e as linhas de dados recolhidas tanto pelos Extratores de Mercado (US e Europa) como pelos vários Motores de Estratégia no fecho do mercado de hoje.

A tua missão é analisar esta informação e escrever um relatório consolidado e altamente profissional para o Gestor de Conta aprovar na corretora.

🚨 REGRAS ESTRITAS ANTI-ALUCINAÇÃO & ANTI-CORTE 🚨
1. ZERO CRIATIVIDADE DE DADOS: Não inventes preços, tickers, stops ou tamanhos de posição. Usa exclusivamente os dados fornecidos abaixo.
2. PROIBIDO OMITIR ATIVOS: Deves incluir e listar TODOS os ativos presentes nos dados dos Extratores (US e Europa) e dos Motores. Não resumas excessivamente nem cortes ativos secundários ou suplementares. Cada linha de dados relevante tem de transparecer no relatório final.
3. ESTRUTURA CLARA: Divide o relatório por secções organizadas (ex: "🌍 PANORAMA MACRO & EXTRATORES US/EU", "🚀 OPORTUNIDADES BREAKOUT", etc.).
4. FORMATO INSTITUCIONAL: Mantém o rigor clínico e direto.

DADOS RECOLHIDOS HOJE:
{conteudo_bruto_total}
"""

print("\nA enviar dados consolidados (Extratores + Motores) para o Gemini Auditar...")
try:
    resposta = modelo_ia.generate_content(prompt_orquestrador)
    relatorio_final = resposta.text
    print("[SUCESSO] Relatório mestre gerado pela IA!")
except Exception as e:
    print(f"[ERRO CRÍTICO] Falha ao comunicar com o Gemini: {e}")
    sys.exit(1)

# 6. ENVIAR EMAIL ÚNICO (Com Sistema Anti-Falhas)
print("\nA preparar envio do Email Institucional...")

max_tentativas = 3
for tentativa in range(max_tentativas):
    try:
        msg = MIMEMultipart()
        msg['From'] = EMAIL_USER
        msg['To'] = EMAIL_USER
        
        data_hoje = datetime.now(ZoneInfo('Europe/Lisbon')).strftime('%d/%m/%Y')
        msg['Subject'] = f"tradingRelatorioIA Global - 🤖 RELATÓRIO MESTRE ({data_hoje})"
        
        msg.attach(MIMEText(relatorio_final, 'plain', 'utf-8'))
        
        server = smtplib.SMTP(SMTP_SERVER, SMTP_PORT, timeout=15)
        server.starttls()
        server.login(EMAIL_USER, EMAIL_PASS)
        server.sendmail(EMAIL_USER, EMAIL_USER, msg.as_string())
        server.quit()
        
        print(f"[SUCESSO] Email Mestre Global enviado com sucesso na tentativa {tentativa + 1}!")
        break
        
    except Exception as e:
        print(f"[ERRO] Falha ao enviar email mestre (tentativa {tentativa + 1} de {max_tentativas}): {e}")
        if tentativa < max_tentativas - 1:
            print("A aguardar 5 segundos antes de tentar novamente...")
            time.sleep(5)
        else:
            print("[ERRO CRÍTICO] O servidor Gmail fechou a ligação definitivamente.")
