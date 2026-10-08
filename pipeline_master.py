# ===================================================================
# SISTEMA DE TRADING INSTITUCIONAL - PIPELINE MESTRE UNIFICADO
# ===================================================================
# Descrição Geral:
# Este script centraliza a execução de todos os motores quantitativos 
# do ecossistema (Regime Macro, Breakouts, Earnings Drift e Connors-Chan). 
# Orquestra a sequência de análise e consolida a entrega no servidor de nuvem.
# ===================================================================

import os
import sys
from datetime import datetime
from zoneinfo import ZoneInfo

def executar_pipeline_mestre():
    print("="*60)
    print("INÍCIO DO PIPELINE MESTRE DE TRADING INSTITUCIONAL")
    print("="*60)
    
    # 0. Trava de Fim de Semana
    dia_da_semana = datetime.now(ZoneInfo("Europe/Lisbon")).weekday()
    if dia_da_semana >= 5:
        print("[INFO] Fim de semana detetado. O mercado está fechado. Pipeline em repouso.")
        sys.exit(0)

    # 1. Executar Disjuntor Macro (Regime de Mercado / SPY)
    print("\n[PASSO 1] A verificar Regime de Mercado (Disjuntor Macro)...")
    ret_macro = os.system("python 00_motor_regime_mercado.py")
    if ret_macro != 0:
        print("[BLOQUEIO] O Disjuntor Macro interrompeu o pipeline. Condições desfavoráveis.")
        sys.exit(0)

    # 2. Executar Motor V2 (Breakouts)
    print("\n[PASSO 2] A executar Motor V2 (Breakouts)...")
    os.system("python 01_extrator_dados.py")

    # 3. Executar Motor de Earnings Drift (PEAD)
    print("\n[PASSO 3] A executar Motor Earnings Drift...")
    os.system("python 03_motor_earnings.py")

    # 4. Executar Motor Connors-Chan (Reversão Estatística de Curto Prazo)
    print("\n[PASSO 4] A executar Motor Connors-Chan...")
    os.system("python 05_motor_reversao_chan.py")

    # 5. Executar Orquestrador IA Final (Auditoria e Envio do Relatório Tático)
    print("\n[PASSO 5] A consolidar com o Agente IA (Gemini) e a enviar email final...")
    os.system("python 02_agente_gemini.py")

    print("\n" + "="*60)
    print("PIPELINE MESTRE CONCLUÍDO COM SUCESSO!")
    print("="*60)

if __name__ == "__main__":
    executar_pipeline_mestre()
