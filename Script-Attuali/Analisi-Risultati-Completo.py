'''

Dati questi risultati, nel file risultati_llm.json (dopo i : per i vari campi ci sono i valori che possono assumere) :

                "student": student_name,
                "exercise": exercise_dir.name,
                "commit_analyzed": selected_commit,

                "failure_category": compile_failure, dynamic_failure, static_failure, correct
                "error_type": unknown, crash, timeout_or_deadlock, incorrect_output_order, resource_leak, concurrency_bug, runtime_error
                "compile_success": true/false,
                "test_success": true/false,

                "stdout": stdout,
                "stderr": stderr,

                "static_warnings": warnings,

                "llm_Output_Correct": SI/NO,
                "llm_output_diagnosis": diag_output,

                "llm_Code_Correct": SI/NO,
                "llm_code_diagnosis": diag_code,

                "judge_Output_Correct": SI/NO,
                "judge_Code_Correct": SI/NO

Vogliamo effettuare un'analisi esplorativa dei risultati, con l'obiettivo di ottenere:

grafico iniziale:
- tabella o grafico a barre, contando i casi:
---- errori di compilazione
---- crash/timeout
---- resource leak
---- fallimento segnalato dai dynamic check
---- fallimento segnalato dagli static check

 
per i soli casi di esercizi che falliscono dynamic check:

primo grafico:
--- % LLM primario dice che output è corretto (non trova l'errore)
--- % LLM primario dice che è scorretto, ma diagnosi output non è corretta
--- % LLM primario dice che è scorretto, e anche la diagnosi output è scorretta
 
secondo grafico:
--- % LLM primario dice di non aver trovato l'errore nel codice (?)
--- % LLM primario dice che è scorretto, ma diagnosi codice non è corretta
--- % LLM primario dice che è scorretto, e anche la diagnosi codice è scorretta

per i soli casi di esercizi che falliscono static check (implica che i check dinamici sono superati):

terzo grafico:
--- % LLM primario dice che output è corretto (è ok, si trova con ground truth)
--- % LLM primario dice che è scorretto (diagnosi è scorretta a prescindere)
 
quarto grafico:
--- % LLM primario dice di non aver trovato l'errore nel codice (?)
--- % LLM primario dice che è scorretto, ma diagnosi codice non è corretta
--- % LLM primario dice che è scorretto, è anche la diagnosi codice è corretta

'''

import json
from matplotlib.ticker import MultipleLocator
import pandas as pd
import matplotlib.pyplot as plt
import seaborn as sns
from pathlib import Path

# ================= CONFIG =================
JSON_FILE = "risultati_es5_tutti_commit.json"
sns.set(style="whitegrid")
plt.rcParams["figure.figsize"] = (10, 6)
plt.rcParams["font.size"] = 10

# ================= LOAD =================
print("Caricamento dati...")
with open(JSON_FILE, "r", encoding="utf-8") as f:
    data = json.load(f)

df = pd.DataFrame(data)
print(f"Totale valutazioni: {len(df)}\n")

# ================= NORMALIZZAZIONE =================
def si_no_to_bin(x):
    """Converte YES/NO a 1/0, mantiene NA per valori mancanti."""
    v = str(x).strip().upper()

    if v in ("YES", "Y", "TRUE", "T"):
        return 1
    if v in ("NO", "N", "FALSE", "F"):
        return 0

    return pd.NA

df["llm_Output_Correct_bin"] = df["llm_Output_Correct"].apply(si_no_to_bin)
df["llm_Code_Correct_bin"] = df["llm_Code_Correct"].apply(si_no_to_bin)
df["judge_Output_Correct_bin"] = df["judge_Output_Correct"].apply(si_no_to_bin)
df["judge_Code_Correct_bin"] = df["judge_Code_Correct"].apply(si_no_to_bin)

# ================= GRAFICO 1: DISTRIBUZIONE FAILURE CATEGORY =================
print("=" * 80)
print("GRAFICO 1: DISTRIBUZIONE FAILURE CATEGORY")
print("=" * 80)

fig, ax = plt.subplots(figsize=(10, 6))
failure_categories = ["compile_failure", "crash" , "timeout", "ipc_leak", "dynamic_failure", "static_failure", "correct"]
failure_counts = df["failure_category"].value_counts().reindex(failure_categories, fill_value=0)
print("\nConteggio per failure_category:")
print(failure_counts)

colors = ["#d62728", "#ff7f0e", "#2ca02c", "#1f77b4", "#9467bd", "#8c564b", "#e377c2"]
failure_counts.plot(kind="bar", ax=ax, color=colors)
ax.yaxis.set_major_locator(MultipleLocator(100))
ax.set_title("Distribuzione dei Casi per Categoria di Fallimento", fontsize=14, fontweight='bold')
ax.set_ylabel("Numero di Casi", fontsize=12)
ax.set_xlabel("Categoria di Fallimento", fontsize=12)
ax.tick_params(axis='x', rotation=45)
plt.tight_layout()
plt.show()

# Tabella di riepilogo
print("\nRiepilogo percentuali:")
for cat, count in failure_counts.items():
    pct = (count / len(df)) * 100
    print(f"  {cat}: {count} ({pct:.1f}%)")

# ================= ANALISI dynamic_failure =================
print("\n" + "=" * 80)
print("ANALISI: DYNAMIC_FAILURE")
print("=" * 80)

df_dynamic = df[df["failure_category"] == "dynamic_failure"].copy()
print(f"\nTotale casi dynamic_failure: {len(df_dynamic)}")

if len(df_dynamic) > 0:
    
    # PRIMO GRAFICO: LLM OUTPUT CORRECT ANALYSIS
    print("\n--- Primo Grafico: Analisi Output LLM ---")
    
    df_dynamic["output_category"] = pd.NA
    df_dynamic.loc[df_dynamic["llm_Output_Correct_bin"] == 1, "output_category"] = "Output Corretto (SI)"
    df_dynamic.loc[(df_dynamic["llm_Output_Correct_bin"] == 0) & (df_dynamic["judge_Output_Correct_bin"] == 0), "output_category"] = "Scorretto, Diagnosi Sbagliata"
    df_dynamic.loc[(df_dynamic["llm_Output_Correct_bin"] == 0) & (df_dynamic["judge_Output_Correct_bin"] == 1), "output_category"] = "Scorretto, Diagnosi Corretta"
    
    output_categories = [
        "Output Corretto (SI)",
        "Scorretto, Diagnosi Sbagliata",
        "Scorretto, Diagnosi Corretta"
    ]
    output_counts = df_dynamic["output_category"].value_counts().reindex(output_categories, fill_value=0)
    print("\nDistribuzione Output Analysis:")
    for cat, count in output_counts.items():
        pct = (count / len(df_dynamic)) * 100
        print(f"  {cat}: {count} ({pct:.1f}%)")
    
    fig, ax = plt.subplots(figsize=(10, 6))
    colors_output = ["#2ca02c", "#d62728", "#ff7f0e"]
    output_counts.plot(kind="bar", ax=ax, color=colors_output)
    ax.set_title("Dynamic Failure - Analisi Output LLM Primario\n(Percentuali)", fontsize=14, fontweight='bold')
    ax.set_ylabel("Numero di Casi", fontsize=12)
    ax.set_xlabel("Categoria", fontsize=12)
    ax.tick_params(axis='x', rotation=45)
    
    # Aggiungi percentuali sulle barre
    for i, v in enumerate(output_counts.values):
        pct = (v / len(df_dynamic)) * 100
        ax.text(i, v + 0.5, f"{pct:.1f}%", ha='center', fontweight='bold')
    
    plt.tight_layout()
    plt.show()
    
    # SECONDO GRAFICO: LLM CODE CORRECT ANALYSIS
    print("\n--- Secondo Grafico: Analisi Codice LLM ---")
    
    df_dynamic["code_category"] = ""
    df_dynamic.loc[df_dynamic["llm_Code_Correct_bin"] == 1, "code_category"] = "Codice Corretto (SI)"
    df_dynamic.loc[(df_dynamic["llm_Code_Correct_bin"] == 0) & (df_dynamic["judge_Code_Correct_bin"] == 0), "code_category"] = "Scorretto, Diagnosi Sbagliata"
    df_dynamic.loc[(df_dynamic["llm_Code_Correct_bin"] == 0) & (df_dynamic["judge_Code_Correct_bin"] == 1), "code_category"] = "Scorretto, Diagnosi Corretta"
    
    code_categories = [
        "Codice Corretto (SI)",
        "Scorretto, Diagnosi Sbagliata",
        "Scorretto, Diagnosi Corretta"
    ]
    code_counts = df_dynamic["code_category"].value_counts().reindex(code_categories, fill_value=0)
    print("\nDistribuzione Code Analysis:")
    for cat, count in code_counts.items():
        pct = (count / len(df_dynamic)) * 100
        print(f"  {cat}: {count} ({pct:.1f}%)")
    
    fig, ax = plt.subplots(figsize=(10, 6))
    colors_code = ["#2ca02c", "#d62728", "#ff7f0e"]
    code_counts.plot(kind="bar", ax=ax, color=colors_code)
    ax.set_title("Dynamic Failure - Analisi Codice LLM Primario\n(Percentuali)", fontsize=14, fontweight='bold')
    ax.set_ylabel("Numero di Casi", fontsize=12)
    ax.set_xlabel("Categoria", fontsize=12)
    ax.tick_params(axis='x', rotation=45)
    
    # Aggiungi percentuali sulle barre
    for i, v in enumerate(code_counts.values):
        pct = (v / len(df_dynamic)) * 100
        ax.text(i, v + 0.5, f"{pct:.1f}%", ha='center', fontweight='bold')
    
    plt.tight_layout()
    plt.show()

# ================= ANALISI STATIC_FAILURE  =================
print("\n" + "=" * 80)
print("ANALISI: STATIC_FAILURE")
print("=" * 80)

df_static = df[df["failure_category"] == "static_failure"].copy()
print(f"\nTotale casi static_failure: {len(df_static)}")

if len(df_static) > 0:
    
    # TERZO GRAFICO: OUTPUT ANALYSIS (dovrebbe essere corretto per static)
    print("\n--- Terzo Grafico: Analisi Output (Static Check) ---")
    
    df_static["output_category_static"] = ""
    df_static.loc[df_static["llm_Output_Correct_bin"] == 1, "output_category_static"] = "Output Corretto (SI)"
    df_static.loc[df_static["llm_Output_Correct_bin"] == 0, "output_category_static"] = "Output Scorretto (Falso Allarme)"
    
    output_categories_static = [
        "Output Corretto (SI)",
        "Output Scorretto (Falso Allarme)"
    ]
    output_counts_static = df_static["output_category_static"].value_counts().reindex(output_categories_static, fill_value=0)
    print("\nDistribuzione Output (Static Check):")
    for cat, count in output_counts_static.items():
        pct = (count / len(df_static)) * 100
        print(f"  {cat}: {count} ({pct:.1f}%)")
    
    fig, ax = plt.subplots(figsize=(10, 6))
    colors_output_static = ["#2ca02c", "#d62728"]
    output_counts_static.plot(kind="bar", ax=ax, color=colors_output_static)
    ax.set_title("Static Failure - Analisi Output LLM Primario", fontsize=14, fontweight='bold')
    ax.set_ylabel("Numero di Casi", fontsize=12)
    ax.set_xlabel("Categoria", fontsize=12)
    ax.tick_params(axis='x', rotation=45)
    
    # Aggiungi percentuali sulle barre
    for i, v in enumerate(output_counts_static.values):
        pct = (v / len(df_static)) * 100
        ax.text(i, v + 0.5, f"{pct:.1f}%", ha='center', fontweight='bold')
    
    plt.tight_layout()
    plt.show()
    
    # QUARTO GRAFICO: CODE ANALYSIS (JUDGE EVALUATION)
    print("\n--- Quarto Grafico: Analisi Codice (Static Check) ---")
    
    df_static["code_category_static"] = ""
    df_static.loc[df_static["llm_Code_Correct_bin"] == 1, "code_category_static"] = "Codice Corretto (SI)"
    df_static.loc[(df_static["llm_Code_Correct_bin"] == 0) & (df_static["judge_Code_Correct_bin"] == 0), "code_category_static"] = "Scorretto, Diagnosi Sbagliata"
    df_static.loc[(df_static["llm_Code_Correct_bin"] == 0) & (df_static["judge_Code_Correct_bin"] == 1), "code_category_static"] = "Scorretto, Diagnosi Corretta"
    
    code_categories_static = [
        "Codice Corretto (SI)",
        "Scorretto, Diagnosi Sbagliata",
        "Scorretto, Diagnosi Corretta"
    ]
    code_counts_static = df_static["code_category_static"].value_counts().reindex(code_categories_static, fill_value=0)
    print("\nDistribuzione Code Analysis (Static Check):")
    for cat, count in code_counts_static.items():
        pct = (count / len(df_static)) * 100
        print(f"  {cat}: {count} ({pct:.1f}%)")
    
    fig, ax = plt.subplots(figsize=(10, 6))
    colors_code_static = ["#2ca02c", "#d62728", "#ff7f0e"]
    code_counts_static.plot(kind="bar", ax=ax, color=colors_code_static)
    ax.set_title("Static Failure - Analisi Codice LLM Primario\n(Percentuali)", fontsize=14, fontweight='bold')
    ax.set_ylabel("Numero di Casi", fontsize=12)
    ax.set_xlabel("Categoria", fontsize=12)
    ax.tick_params(axis='x', rotation=45)
    
    # Aggiungi percentuali sulle barre
    for i, v in enumerate(code_counts_static.values):
        pct = (v / len(df_static)) * 100
        ax.text(i, v + 0.5, f"{pct:.1f}%", ha='center', fontweight='bold')
    
    plt.tight_layout()
    plt.show()

# ================= ANALISI CORRECT (FALSI POSITIVI) =================
print("\n" + "=" * 80)
print("ANALISI: CORRECT (FALSI POSITIVI)")
print("=" * 80)

df_correct = df[df["failure_category"] == "correct"].copy()
print(f"\nTotale casi correct: {len(df_correct)}")

if len(df_correct) > 0:
    # Grafico Output - analisi falsi positivi
    print("\n--- Grafico: Analisi Output (Correct cases) ---")
    df_correct["output_category_correct"] = pd.NA
    df_correct.loc[df_correct["llm_Output_Correct_bin"] == 1, "output_category_correct"] = "Output Corretto (SI)"
    df_correct.loc[df_correct["llm_Output_Correct_bin"] == 0, "output_category_correct"] = "Output Corretto (NO)"

    output_categories_correct = [
        "Output Corretto (SI)",
        "Output Corretto (NO)"
    ]
    output_counts_correct = df_correct["output_category_correct"].value_counts().reindex(output_categories_correct, fill_value=0)
    print("\nDistribuzione Output (Correct cases):")
    for cat, count in output_counts_correct.items():
        pct = (count / len(df_correct)) * 100
        print(f"  {cat}: {count} ({pct:.1f}%)")

    fig, ax = plt.subplots(figsize=(10, 6))
    colors_output_correct = ["#2ca02c", "#d62728", "#ff7f0e"]
    output_counts_correct.plot(kind="bar", ax=ax, color=colors_output_correct)
    ax.set_title("Correct - Analisi Output LLM Primario (Falsi positivi)", fontsize=14, fontweight='bold')
    ax.set_ylabel("Numero di Casi", fontsize=12)
    ax.set_xlabel("Categoria", fontsize=12)
    ax.tick_params(axis='x', rotation=45)

    for i, v in enumerate(output_counts_correct.values):
        pct = (v / len(df_correct)) * 100
        ax.text(i, v + 0.5, f"{pct:.1f}%", ha='center', fontweight='bold')

    plt.tight_layout()
    plt.show()

    # Grafico Codice - analisi falsi positivi
    print("\n--- Grafico: Analisi Codice (Correct cases) ---")
    df_correct["code_category_correct"] = ""
    df_correct.loc[df_correct["llm_Code_Correct_bin"] == 1, "code_category_correct"] = "Codice Corretto (SI)"
    df_correct.loc[df_correct["llm_Code_Correct_bin"] == 0, "code_category_correct"] = "Codice Corretto (NO)"

    code_categories_correct = [
        "Codice Corretto (SI)",
        "Codice Corretto (NO)"
    ]
    code_counts_correct = df_correct["code_category_correct"].value_counts().reindex(code_categories_correct, fill_value=0)
    print("\nDistribuzione Code (Correct cases):")
    for cat, count in code_counts_correct.items():
        pct = (count / len(df_correct)) * 100
        print(f"  {cat}: {count} ({pct:.1f}%)")

    fig, ax = plt.subplots(figsize=(10, 6))
    colors_code_correct = ["#2ca02c", "#d62728"]
    code_counts_correct.plot(kind="bar", ax=ax, color=colors_code_correct)
    ax.set_title("Correct - Analisi Codice LLM Primario (Falsi positivi)", fontsize=14, fontweight='bold')
    ax.set_ylabel("Numero di Casi", fontsize=12)
    ax.set_xlabel("Categoria", fontsize=12)
    ax.tick_params(axis='x', rotation=45)

    for i, v in enumerate(code_counts_correct.values):
        pct = (v / len(df_correct)) * 100
        ax.text(i, v + 0.5, f"{pct:.1f}%", ha='center', fontweight='bold')

    plt.tight_layout()
    plt.show()

# ================= RIEPILOGO FINALE =================
print("\n" + "=" * 80)
print("RIEPILOGO FINALE")
print("=" * 80)

print("\nStatistiche Generali:")
print(f"  Totale valutazioni: {len(df)}")
print(f"  Compilazione riuscita: {df['compile_success'].sum()} ({df['compile_success'].sum()/len(df)*100:.1f}%)")
print(f"  Test superati: {df['test_success'].sum()} ({df['test_success'].sum()/len(df)*100:.1f}%)")

print("\nStatistiche LLM Output:")
print(f"  LLM dice Output Corretto: {df['llm_Output_Correct_bin'].sum()} ({df['llm_Output_Correct_bin'].sum()/len(df)*100:.1f}%)")

print("\nStatistiche LLM Codice:")
print(f"  LLM dice Codice Corretto: {df['llm_Code_Correct_bin'].sum()} ({df['llm_Code_Correct_bin'].sum()/len(df)*100:.1f}%)")

print("\nStatistiche Judge Output:")
if df['judge_Output_Correct_bin'].sum() > 0:
    print(f"  Judge dice Output Corretto: {df['judge_Output_Correct_bin'].sum()} ({df['judge_Output_Correct_bin'].sum()/(df['judge_Output_Correct_bin'].notna().sum())*100:.1f}%)")

print("\nStatistiche Judge Codice:")
if df['judge_Code_Correct_bin'].sum() > 0:
    print(f"  Judge dice Codice Corretto: {df['judge_Code_Correct_bin'].sum()} ({df['judge_Code_Correct_bin'].sum()/(df['judge_Code_Correct_bin'].notna().sum())*100:.1f}%)")

print("\n" + "=" * 80)
print("Analisi completata!")
print("=" * 80)
