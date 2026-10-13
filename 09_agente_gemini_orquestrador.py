import os
import sys
import time
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from datetime import datetime
from zoneinfo import ZoneInfo

# Importação da biblioteca Gemini com suporte a nova e antiga API
try:
    from google import genai
    USE_NEW_GENAI = True
except ImportError:
    import google.generativeai as genai
    USE_NEW_GENAI = False

# ===================================================================
# SISTEMA DE TRADING INSTITUCIONAL - AGENTE IA ORQUESTRADOR (PIPELINE)
# ===================================================================
# Descrição:
# Este script corre no final da pipeline diária. Varre o disco da máquina 
# virtual em busca de TODOS os ficheiros "comboio" gerados pelos motores.
# Envia primeiro um email de BACKUP BRUTO (para o caso de falha da IA)
# e depois tenta auditar via Gemini e enviar o Relatório Mestre Final.
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

# Função Auxiliar para Envio de Email
def enviar_email(assunto, corpo_texto):
    if not EMAIL_USER or not EMAIL_PASS:
        print("[AVISO] EMAIL_USER ou EMAIL_PASS não definidos. Email não enviado.")
        return False
        
    max_tentativas = 3
    for tentativa in range(max_tentativas):
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
            
            print(f"[SUCESSO] Email '{assunto}' enviado com sucesso na tentativa {tentativa + 1}!")
            return True
        except Exception as e:
            print(f"[ERRO] Falha ao enviar email (tentativa {tentativa + 1} de {max_tentativas}): {e}")
            if tentativa < max_tentativas - 1:
                time.sleep(5)
    return False

# 2. DEFINIR TODOS OS FICHEIROS GERADOS PELOS EXTRATORES E MOTORES
ficheiros_alvo = [
    "comboio_temp.txt",             # Ficheiro do Extrator US
    "comboio_europa.txt",           # Ficheiro do Extrator Europa
    "comboio_vcp_temp.txt",         # Ficheiro do Motor 07 (VCP Breakout)
    "comboio_reversao_temp.txt",    # Ficheiro do Motor 03 (Pânico)
    "comboio_earnings_temp.txt",    # Ficheiro do Motor 04 (PEAD)
    "comboio_connors_temp.txt",     # Ficheiro do Motor 05 (REVERSAO)
    "comboio_carver_temp.txt"       # Ficheiro do Motor 06 (Fast Trend Carver)
]

conteudo_bruto_total = ""

print("A procurar relatórios dos extratores e motores na máquina virtual...")

# 3. RECOLHER DADOS DE TODOS OS FICHEIROS DISPONÍVEIS
for ficheiro in ficheiros_alvo:
    if os.path.exists(ficheiro):
        with open(ficheiro, "r", encoding="utf-8") as f:
            dados = f.read().strip()
            
            conteudo_bruto_total += f"\n\n==================================\n"
            conteudo_bruto_total += f"📁 FONTE: {ficheiro}\n"
            conteudo_bruto_total += f"==================================\n"
            
            # Se tiver conteúdo válido de ativos
            if dados and "Nenhum ativo" not in dados and "[SEM OPORTUNIDADES]" not in dados:
                conteudo_bruto_total += f"{dados}\n"
                print(f"[ENCONTRADO] Dados detetados no {ficheiro}.")
            else:
                conteudo_bruto_total += "[SEM SINAIS OU OPORTUNIDADES PARA ESTA ESTRATÉGIA HOJE]\n"
                print(f"[VAZIO] {ficheiro} lido, adicionado como sem sinais ao relatório.")
    else:
        conteudo_bruto_total += f"\n\n==================================\n"
        conteudo_bruto_total += f"📁 FONTE: {ficheiro}\n"
        conteudo_bruto_total += f"==================================\n"
        conteudo_bruto_total += "[ERRO: FICHEIRO NÃO ENCONTRADO - MOTOR PODE TER FALHADO]\n"
        print(f"[FALTA] {ficheiro} não encontrado.")

if not conteudo_bruto_total.strip():
    print("\n[INFO] Nenhum dado gerado. A pipeline termina de forma silenciosa.")
    sys.exit(0)

# ===================================================================
# 4. PASSO ADICIONADO: ENVIAR DADOS BRUTOS POR EMAIL ANTES DA IA
# ===================================================================
data_hoje = datetime.now(ZoneInfo('Europe/Lisbon')).strftime('%d/%m/%Y')
assunto_backup = f"tradingRelatorioIA - 📦 DADOS BRUTOS PARA IA / BACKUP ({data_hoje})"

print("\nA enviar dados brutos consolidados para o Email de Backup...")
enviar_email(assunto_backup, conteudo_bruto_total)

# ===================================================================
# 5. CHAMADA E AUDITORIA DA IA (GEMINI)
# ===================================================================
prompt_orquestrador = f"""
És o Analista Quantitativo Principal (Agente Orquestrador).
Abaixo estão os relatórios em bruto e os dados gerados dinamicamente pelos Extratores de Mercado (US e Europa) e pelos vários Motores de Estratégia no fecho do mercado de hoje.

A tua missão é ler integralmente este conteúdo, processar todos os ativos que aparecem nas fontes e compilar um ÚNICO relatório consolidado, limpo, detalhado e altamente profissional para o Gestor de Conta aprovar na corretora.

🚨 REGRAS ESTRITAS ANTI-ALUCINAÇÃO & CONTEXTO DE GESTÃO 🚨
1. ZERO CRIATIVIDADE DE DADOS: Não inventes preços, tickers, stops ou tamanhos de posição. Utiliza unicamente e na íntegra os dados fornecidos nos ficheiros abaixo.
2. LEITURA INTEGRAL (PROIBIDO OMITIR ATIVOS OU ESTRATÉGIAS): Deves incluir todos os ativos, posições ativas, alertas macro e sinais de entrada. Se uma fonte indicar "[SEM SINAIS OU OPORTUNIDADES PARA ESTA ESTRATÉGIA HOJE]", DEVES criar a secção respetiva baseada no nome do ficheiro fonte e escrever explicitamente que não há sinais hoje. Não omitas NENHUMA estratégia.
3. ESTRUTURA INSTITUCIONAL DINÂMICA: Organiza o relatório por secções lógicas com base nas fontes lidas.
4. RESTRIÇÃO DE NOTAS OPERACIONAIS: O lembrete operacional referente à alteração do estado no Google Sheets para 'ATIVA_FAST' e à gestão de Trailing Stop diário deve ser posicionado estritamente e de forma exclusiva na secção afeta ao Fast Trend Carver. Nunca mistures esta regra com outras estratégias.
5. VETO DE SOBREPOSIÇÃO (CRÍTICO): Antes de sugerires qualquer NOVA ENTRADA num ativo (seja no VCP, Reversão, PEAD, Breakouts ou Carver Momentum), verifica obrigatoriamente se esse ativo já se encontra listado como [POSIÇÃO ATIVA - ATIVA_FAST] ou se tem 'PosicaoAtiva: SIM' noutra fonte. Se já estiver ativo na carteira, É ESTRITAMENTE PROIBIDO sugerir uma nova entrada para esse mesmo ticker em qualquer secção. Omite-o dos novos sinais.

DADOS RECOLHIDOS HOJE NOS FICHEIROS:
{conteudo_bruto_total}
"""

print("\nA enviar dados consolidados para o Gemini Auditar...")

relatorio_final = None

try:
    if USE_NEW_GENAI:
        client = genai.Client(api_key=GEMINI_API_KEY)
        response = client.models.generate_content(
            model='gemini-3.6-flash', # ou gemini-1.5-flash dependendo do modelo ativo na conta
            contents=prompt_orquestrador,
        )
        relatorio_final = response.text
    else:
        genai.configure(api_key=GEMINI_API_KEY)
        modelo_ia = genai.GenerativeModel('gemini-3.6-flash')
        resposta = modelo_ia.generate_content(prompt_orquestrador)
        relatorio_final = resposta.text
        
    print("[SUCESSO] Relatório mestre gerado pela IA!")

except Exception as e:
    print(f"\n[ALERTA DE QUOTA / ERRO IA] Falha ao comunicar com o Gemini: {e}")
    print("[INFO] A pipeline não vai falhar. O email com os DADOS BRUTOS já foi enviado para processamento manual.")
    
    # Envia email de aviso específico sobre a falha da IA
    assunto_erro = f"tradingRelatorioIA - ⚠️ AVISO: FALHA NA IA ({data_hoje})"
    corpo_erro = f"Ocorreu um erro ao gerar o relatório consolidado com a IA (Quota excedida ou limite de API).\n\nErro: {e}\n\nPor favor, utiliza o email com o assunto '[BACKUP BRUTO]' enviado anteriormente e cola o conteúdo no ChatGPT/Claude/Gemini Web manualmente para gerar o relatório."
    enviar_email(assunto_erro, corpo_erro)
    sys.exit(0)

# ===================================================================
# 6. ENVIAR EMAIL DO RELATÓRIO FINAL DA IA
# ===================================================================
if relatorio_final:
    print("\nA preparar envio do Relatório Mestre Formatado pela IA...")
    assunto_final = f"tradingRelatorioIA Global - 🤖 RELATÓRIO MESTRE ({data_hoje})"
    enviar_email(assunto_final, relatorio_final)
