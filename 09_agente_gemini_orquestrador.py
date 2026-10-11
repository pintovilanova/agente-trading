import os
import sys
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
# Este script corre no final da pipeline diária. A sua missão é varrer
# o disco da máquina virtual em busca dos ficheiros "comboio" gerados
# por TODOS os motores quantitativos que correram antes dele.
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

# Usa o modelo Gemini mais capaz para texto
modelo_ia = genai.GenerativeModel('gemini-3.6-flash')

# 2. DEFINIR OS FICHEIROS GERADOS PELOS TEUS MOTORES
# Ajusta estes nomes para os nomes exatos dos ficheiros TXT que os teus 
# motores 07, 03, 04 e 06 estão a criar localmente.
ficheiros_alvo = [
    "comboio_breakout_temp.txt",     # Ficheiro do Motor 07
    "comboio_reversao_temp.txt",     # Ficheiro do Motor 03 (Pânico)
    "comboio_earnings_temp.txt",     # Ficheiro do Motor 04 (PEAD)
    "comboio_fast_trend_temp.txt"    # Ficheiro do Motor 06
]

conteudo_bruto_total = ""
motores_ativos = 0

print("A procurar relatórios dos motores na máquina virtual...")

# 3. RECOLHER DADOS DE TODOS OS FICHEIROS DISPONÍVEIS
for ficheiro in ficheiros_alvo:
    if os.path.exists(ficheiro):
        with open(ficheiro, "r", encoding="utf-8") as f:
            dados = f.read().strip()
            # Só adiciona se o ficheiro tiver conteúdo útil (ignorar se disser "[SEM OPORTUNIDADES]")
            if dados and "Nenhum ativo" not in dados and "[SEM OPORTUNIDADES]" not in dados:
                conteudo_bruto_total += f"\n\n==================================\n"
                conteudo_bruto_total += f"📁 FONTE: {ficheiro}\n"
                conteudo_bruto_total += f"==================================\n{dados}\n"
                motores_ativos += 1
                print(f"[ENCONTRADO] Oportunidades detetadas no {ficheiro}.")
            else:
                print(f"[VAZIO] {ficheiro} lido, mas não contém oportunidades para hoje.")
    else:
        print(f"[FALTA] {ficheiro} não encontrado (o motor pode ter falhado ou não correu).")

# 4. VALIDAÇÃO DE SEGURANÇA
if motores_ativos == 0 or not conteudo_bruto_total.strip():
    print("\n[INFO] Nenhum dos motores gerou oportunidades válidas hoje. A pipeline termina aqui de forma silenciosa.")
    sys.exit(0)

# 5. PROMPT DO ORQUESTRADOR IA
prompt_orquestrador = f"""
És o Analista Quantitativo Principal (Agente Orquestrador).
Abaixo estão os relatórios em bruto e as linhas de comboio geradas pelos nossos múltiplos Motores de Trading (Breakouts, Mean Reversion, Earnings Drift, etc.) no fecho do mercado de hoje.

A tua missão é analisar estes dados e escrever um ÚNICO relatório consolidado, limpo e altamente profissional para o Gestor de Conta aprovar a execução na corretora.

🚨 REGRAS ESTRITAS ANTI-ALUCINAÇÃO 🚨
1. ZERO CRIATIVIDADE DE DADOS: Não inventes preços, tickers, stops ou tamanhos de posição. Usa exclusivamente os dados fornecidos abaixo.
2. ESTRUTURA CLARA: Divide o relatório por ESTRATÉGIA (ex: "🚀 OPORTUNIDADES BREAKOUT", "🩸 RECUPERAÇÃO DE PÂNICO", etc.).
3. FORMATO INSTITUCIONAL: Para cada ativo, indica claramente:
   - Ticker e Nome
   - Motivo (RS Score, RVOL, Variação)
   - Plano de Ação: Entrada, Stop Loss, Take-Profit e Tamanho da Posição ($/Qtd)
4. SÍNTESE: Sê direto e clínico. O gestor tem 1 minuto para ler este email.

DADOS RECOLHIDOS HOJE:
{conteudo_bruto_total}
"""

print("\nA enviar dados consolidados para o Gemini Auditar...")
try:
    resposta = modelo_ia.generate_content(prompt_orquestrador)
    relatorio_final = resposta.text
    print("[SUCESSO] Relatório mestre gerado pela IA!")
except Exception as e:
    print(f"[ERRO CRÍTICO] Falha ao comunicar com o Gemini: {e}")
    sys.exit(1)

# 6. ENVIAR EMAIL ÚNICO
print("\nA preparar envio do Email Institucional...")
try:
    msg = MIMEMultipart()
    msg['From'] = EMAIL_USER
    msg['To'] = EMAIL_USER
    # Assunto dinâmico com a data e quantidade de estratégias ativas
    data_hoje = datetime.now(ZoneInfo('Europe/Lisbon')).strftime('%d/%m/%Y')
    msg['Subject'] = f"tradingRelatorioIA US - 🤖 RELATÓRIO MESTRE ({data_hoje})"
    
    # Adicionar o relatório gerado pela IA
    msg.attach(MIMEText(relatorio_final, 'plain', 'utf-8'))
    
    server = smtplib.SMTP(SMTP_SERVER, SMTP_PORT)
    server.starttls()
    server.login(EMAIL_USER, EMAIL_PASS)
    server.sendmail(EMAIL_USER, EMAIL_USER, msg.as_string())
    server.quit()
    print("[SUCESSO] Email Mestre Orquestrado enviado com sucesso!")
except Exception as e:
    print(f"[ERRO] Falha ao enviar email mestre: {e}")
