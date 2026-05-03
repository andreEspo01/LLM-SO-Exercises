import json
import re
import subprocess
from pathlib import Path

import matplotlib.pyplot as plt
import pandas as pd
import seaborn as sns
from matplotlib.ticker import MultipleLocator


sns.set(style="whitegrid")
plt.rcParams["figure.figsize"] = (10, 6)
plt.rcParams["font.size"] = 10

BASE_DIR = Path(__file__).resolve().parent
RESULTS_BASE_DIR = Path(r"C:\Users\andre\OneDrive\Desktop\TESI MAGISTRALE")
AGGREGATED_PLOT_PATH = RESULTS_BASE_DIR / "Distribuzione_tutte_esercitazioni.png"
AGGREGATED_LLM_PLOT_PATH = RESULTS_BASE_DIR / "Distribuzione_tutte_esercitazioni_LLM.png"
LLM_JSON_CANDIDATES = [
    BASE_DIR / "risultati_es1.json",
    BASE_DIR / "risultati_es2.json",
    BASE_DIR / "risultati_es3.json",
    BASE_DIR / "risultati_es4.json",
    BASE_DIR / "risultati_es5.json",
]
ALL_COMMITS_JSON_CANDIDATES = [
    BASE_DIR / "risultati_es1_tutti_commit_bash.json",
    BASE_DIR / "risultati_es2_tutti_commit_bash.json",
    BASE_DIR / "risultati_es3_tutti_commit_bash.json",
    BASE_DIR / "risultati_es4_tutti_commit_bash.json",
    BASE_DIR / "risultati_es5_tutti_commit_bash.json",
]

FAILURE_CATEGORIES = [
    "compile_failure",
    "crash",
    "timeout",
    "ipc_leak",
    "dynamic_failure",
    "static_failure",
    "correct",
]

EXERCISE_TITLES = {
    1: "Es.1 Semafori",
    2: "Es.2 Monitor",
    3: "Es.3 Threads",
    4: "Es.4 Messaggi",
    5: "Es.5 Server Multithread",
}

EXERCISE_RESULTS_DIRS = {
    1: RESULTS_BASE_DIR / "RISULTATI-ES1",
    2: RESULTS_BASE_DIR / "RISULTATI-ES2",
    3: RESULTS_BASE_DIR / "RISULTATI-ES3",
    4: RESULTS_BASE_DIR / "RISULTATI-ES4",
    5: RESULTS_BASE_DIR / "RISULTATI-ES5",
}

EXERCISE_SUBMISSIONS_DIRS = {
    0: "/home/andre/esercitazione-0-uso-di-git-submissions",
    1: "/home/andre/esercitazione-1-semafori-submissions",
    2: "/home/andre/esercitazione-2-monitor-submissions",
    3: "/home/andre/esercitazione-3-threads-submissions",
    4: "/home/andre/esercitazione-4-messaggi-submissions",
    5: "/home/andre/esercitazione-5-server-multithread-submissions",
}


def choose_existing(candidates):
    for candidate in candidates:
        if candidate.exists():
            return candidate
    raise FileNotFoundError(
        "Nessuno dei file attesi esiste:\n" + "\n".join(str(p) for p in candidates)
    )


def load_dataframe(path: Path, label: str) -> pd.DataFrame:
    print(f"Caricamento {label}: {path}")
    with open(path, "r", encoding="utf-8") as f:
        data = json.load(f)
    df = pd.DataFrame(data)
    print(f"  Record caricati: {len(df)}\n")
    return df


def infer_exercise_number_from_filename(path: Path):
    match = re.search(r"risultati_es(\d+)(?:_tutti_commit_bash)?\.json$", path.name)
    if not match:
        return None
    return int(match.group(1))


def compute_repo_commit_stats(all_commits_json_file: Path):
    exercise_number = infer_exercise_number_from_filename(all_commits_json_file)
    submissions_dir = EXERCISE_SUBMISSIONS_DIRS.get(exercise_number)

    if not submissions_dir:
        raise ValueError(
            f"Impossibile dedurre la directory submissions da {all_commits_json_file.name}"
        )

    probe_script = f"""
import json
import subprocess
from pathlib import Path

base = Path({submissions_dir!r})
students_with_commits = 0
total_git_commits = 0

for student_dir in sorted([p for p in base.iterdir() if p.is_dir()]):
    res = subprocess.run(
        ['git', 'rev-list', '--count', 'HEAD'],
        cwd=student_dir,
        capture_output=True,
        text=True,
    )
    count = int(res.stdout.strip()) if res.returncode == 0 and res.stdout.strip().isdigit() else 0
    if count > 0:
        students_with_commits += 1
    total_git_commits += count

print(json.dumps({{
    'submissions_dir': str(base),
    'students_with_commits': students_with_commits,
    'total_git_commits': total_git_commits,
}}))
"""

    res = subprocess.run(
        ["wsl", "python3", "-c", probe_script],
        capture_output=True,
        text=True,
        check=True,
    )
    return json.loads(res.stdout)


def compute_json_commit_stats(df: pd.DataFrame):
    """Conta modifiche agli esercizi dal dataframe JSON."""
    
    # Assicura che le colonne necessarie esistano
    ensure_column(df, 'student')
    ensure_column(df, 'commit_analyzed')
    ensure_column(df, 'exercise')
    
    # Modifiche agli esercizi: (student, exercise, commit_analyzed) distinti
    exercise_mod_key = build_unique_series(df, ["student", "exercise", "commit_analyzed"])
    total_modifications = exercise_mod_key.nunique()
    
    # Dettaglio per esercizio
    modifications_per_exercise = {}
    if 'exercise' in df.columns:
        for exercise in df['exercise'].dropna().unique():
            df_ex = df[df['exercise'] == exercise]
            ex_key = build_unique_series(df_ex, ["student", "exercise", "commit_analyzed"])
            modifications_per_exercise[str(exercise)] = ex_key.nunique()
    
    return {
        'total_modifications': int(total_modifications),
        'modifications_per_exercise': modifications_per_exercise,
    }


def si_no_to_bin(x):
    value = str(x).strip().upper()
    if value in {"YES", "Y", "TRUE", "T"}:
        return 1
    if value in {"NO", "N", "FALSE", "F"}:
        return 0
    return pd.NA


def ensure_column(df: pd.DataFrame, column: str):
    if column not in df.columns:
        df[column] = pd.NA


def build_unique_series(df: pd.DataFrame, columns):
    safe = []
    for column in columns:
        if column in df.columns:
            safe.append(df[column].fillna("<NA>").astype(str))
        else:
            safe.append(pd.Series(["<NA>"] * len(df), index=df.index))
    return pd.Series(
        ["|".join(parts) for parts in zip(*safe)],
        index=df.index,
    )


def add_percent_labels(ax, values, total):
    ymin, ymax = ax.get_ylim()
    offset = (ymax - ymin) * 0.03
    for i, value in enumerate(values):
        pct = (value / total) * 100 if total else 0
        ax.text(i, value + offset, f"{pct:.1f}%", ha="center", fontweight="bold")
    max_val = max(values) if len(values) > 0 else 0
    ax.set_ylim(ymin, max_val + (ymax - ymin) * 0.18)


def save_and_show_plot(fig, output_path: Path = None):
    if output_path is not None:
        output_path.parent.mkdir(parents=True, exist_ok=True)
        fig.savefig(output_path, dpi=300, bbox_inches="tight")
        print(f"Grafico salvato: {output_path}")
    if "agg" not in plt.get_backend().lower():
        plt.show()
    plt.close(fig)


def plot_category_counts(counts, total, title, colors, ylabel="Numero di Casi", output_path: Path = None):
    fig, ax = plt.subplots(figsize=(10, 6))
    counts.plot(kind="bar", ax=ax, color=colors)
    ax.set_title(title, fontsize=14, fontweight="bold")
    ax.set_ylabel(ylabel, fontsize=12)
    ax.set_xlabel("Categoria", fontsize=12)
    ax.tick_params(axis="x", rotation=45)
    add_percent_labels(ax, counts.values, total)
    plt.tight_layout()
    save_and_show_plot(fig, output_path)


def load_exercises_data(candidates):
    """Carica tutti i file JSON delle esercitazioni e restituisce dict con esercitazione -> dataframe."""
    all_data = {}
    
    for candidate in candidates:
        if candidate.exists():
            ex_num = infer_exercise_number_from_filename(candidate)
            if ex_num is not None:
                print(f"Caricamento: {candidate.name}")
                with open(candidate, "r", encoding="utf-8") as f:
                    data = json.load(f)
                df = pd.DataFrame(data)
                ensure_column(df, "failure_category")
                all_data[ex_num] = df
                print(f"  Record caricati: {len(df)}\n")
    
    return all_data


def plot_exercises_failure_distribution(all_data, title_text, output_path):
    """Crea un grafico con la distribuzione delle failure categories per ogni esercitazione."""
    
    if not all_data:
        print("Nessun file JSON trovato per le esercitazioni")
        return

    # Crea i subplot
    fig, axes = plt.subplots(1, len(all_data), figsize=(18, 5), sharey=True)
    if len(all_data) == 1:
        axes = [axes]
    
    colors = ["#d62728", "#ff7f0e", "#2ca02c", "#1f77b4", "#9467bd", "#8c564b", "#e377c2"]
    
    for idx, (ex_label, df) in enumerate(sorted(all_data.items())):
        failure_counts = df["failure_category"].value_counts().reindex(FAILURE_CATEGORIES, fill_value=0)
        
        # Plot bar chart direttamente con ax.bar per avere piÃ¹ controllo
        ax = axes[idx]
        x_pos = range(len(failure_counts))
        ax.bar(x_pos, failure_counts.values, color=colors[:len(failure_counts)])
        
        # Formattazione
        title = EXERCISE_TITLES.get(ex_label, f"Es.{ex_label}")
        ax.set_title(f"{title}", fontsize=12, fontweight="bold")
        ax.set_ylabel("# Commits" if idx == 0 else "", fontsize=11)
        ax.set_xlabel("")
        ax.set_xticks([])  # Nascondi le etichette dell'asse x
        ax.yaxis.set_major_locator(MultipleLocator(50))  # Tacche ogni 50 unitÃ 
        ax.grid(axis="y", alpha=0.3)
    
    # Crea legenda manuale esterna
    from matplotlib.patches import Patch
    legend_elements = [
        Patch(facecolor=colors[i], label=FAILURE_CATEGORIES[i].replace("_", " ").capitalize())
        for i in range(len(FAILURE_CATEGORIES))
    ]
    fig.legend(
        handles=legend_elements,
        loc="upper left",
        fontsize=10,
        bbox_to_anchor=(0.83, 0.88),
        bbox_transform=fig.transFigure,
        borderaxespad=0,
    )

    fig.suptitle(title_text, fontsize=13, fontweight="bold")
    plt.tight_layout(rect=[0, 0, 0.82, 0.93])
    save_and_show_plot(fig, output_path)


def plot_all_exercises_failure_distribution():
    plot_exercises_failure_distribution(
        load_exercises_data(ALL_COMMITS_JSON_CANDIDATES),
        "Distribuzione delle Categorie di Fallimento per Esercitazione (Tutti i Commit)",
        AGGREGATED_PLOT_PATH,
    )


def plot_all_exercises_failure_distribution_llm():
    plot_exercises_failure_distribution(
        load_exercises_data(LLM_JSON_CANDIDATES),
        "Distribuzione delle Categorie di Fallimento per Esercitazione (Analisi con LLM)",
        AGGREGATED_LLM_PLOT_PATH,
    )


def build_candidate_map(candidates):
    candidate_map = {}
    for candidate in candidates:
        if candidate.exists():
            ex_num = infer_exercise_number_from_filename(candidate)
            if ex_num is not None:
                candidate_map[ex_num] = candidate
    return candidate_map


def build_plot_path(exercise_number: int, filename: str) -> Path:
    return EXERCISE_RESULTS_DIRS[exercise_number] / filename


def prepare_llm_dataframe(df_llm: pd.DataFrame):
    for column in [
        "llm_Output_Correct",
        "llm_Code_Correct",
        "judge_Output_Correct",
        "judge_Code_Correct",
        "failure_category",
        "student",
        "exercise",
        "commit_analyzed",
    ]:
        ensure_column(df_llm, column)

    df_llm["llm_Output_Correct_bin"] = df_llm["llm_Output_Correct"].apply(si_no_to_bin)
    df_llm["llm_Code_Correct_bin"] = df_llm["llm_Code_Correct"].apply(si_no_to_bin)
    df_llm["judge_Output_Correct_bin"] = df_llm["judge_Output_Correct"].apply(si_no_to_bin)
    df_llm["judge_Code_Correct_bin"] = df_llm["judge_Code_Correct"].apply(si_no_to_bin)
    df_llm["llm_mod_key"] = build_unique_series(df_llm, ["student", "exercise", "commit_analyzed"])


def prepare_all_commits_dataframe(df_all: pd.DataFrame):
    for column in ["student", "exercise", "commit_analyzed", "failure_category"]:
        ensure_column(df_all, column)

    df_all["git_commit_key"] = build_unique_series(df_all, ["student", "commit_analyzed"])
    df_all["exercise_mod_key"] = build_unique_series(df_all, ["student", "exercise", "commit_analyzed"])


def print_global_stats(exercise_title, repo_stats, json_stats, df_llm, df_all):
    print("\n" + "=" * 80)
    print("CONTEGGI GLOBALI")
    print("=" * 80)
    print(f"Esercitazione: {exercise_title}")
    print(f"Directory submissions usata per i conteggi git: {repo_stats['submissions_dir']}")
    print(f"Numero di studenti con almeno 1 commit: {repo_stats['students_with_commits']}")
    print(f"Numero totale di commit git (esercitazione): {repo_stats['total_git_commits']}")
    print(f"Numero totale di modifiche agli esercizi (dal JSON): {json_stats['total_modifications']}")
    print(f"Numero di modifiche analizzate tramite LLM: {df_llm['llm_mod_key'].nunique()}")

    print("\nDettaglio modifiche per esercizio (dal JSON):")
    for exercise, count in sorted(json_stats['modifications_per_exercise'].items()):
        print(f"  {exercise}: {count} modifiche")

    print("\nTabella categorie di fallimento per esercizio:")
    failure_by_exercise = pd.crosstab(
        df_all["exercise"],
        df_all["failure_category"],
    ).reindex(columns=FAILURE_CATEGORIES, fill_value=0)
    print(failure_by_exercise.to_string())


def plot_all_commits_distribution(df_all, exercise_title, exercise_number):
    print("\n" + "=" * 80)
    print("GRAFICO 0: DISTRIBUZIONE FAILURE CATEGORY SUI TUTTI-COMMIT")
    print("=" * 80)

    fig, ax = plt.subplots(figsize=(10, 6))
    failure_counts_all = df_all["failure_category"].value_counts().reindex(FAILURE_CATEGORIES, fill_value=0)
    print("\nConteggio per failure_category (tutti i commit):")
    print(failure_counts_all)

    colors = ["#d62728", "#ff7f0e", "#2ca02c", "#1f77b4", "#9467bd", "#8c564b", "#e377c2"]
    failure_counts_all.plot(kind="bar", ax=ax, color=colors)
    ax.yaxis.set_major_locator(MultipleLocator(50))
    ax.set_title(
        f"Distribuzione dei Casi per Categoria di Fallimento (Tutti i Commit) - {exercise_title}",
        fontsize=14,
        fontweight="bold",
    )
    ax.set_ylabel("Numero di Casi", fontsize=12)
    ax.set_xlabel("Categoria di Fallimento", fontsize=12)
    ax.tick_params(axis="x", rotation=45)
    plt.tight_layout()
    save_and_show_plot(
        fig,
        build_plot_path(exercise_number, f"Failure_Category_Tutti_Commit_es{exercise_number}.png"),
    )

    print("\nRiepilogo percentuali (tutti i commit):")
    for category, count in failure_counts_all.items():
        pct = (count / len(df_all)) * 100 if len(df_all) else 0
        print(f"  {category}: {count} ({pct:.1f}%)")


def plot_llm_failure_distribution(df_llm, exercise_title, exercise_number):
    print("\n" + "=" * 80)
    print("GRAFICO 1: DISTRIBUZIONE FAILURE CATEGORY")
    print("=" * 80)

    fig, ax = plt.subplots(figsize=(10, 6))
    failure_counts = df_llm["failure_category"].value_counts().reindex(FAILURE_CATEGORIES, fill_value=0)
    print("\nConteggio per failure_category:")
    print(failure_counts)

    colors = ["#d62728", "#ff7f0e", "#2ca02c", "#1f77b4", "#9467bd", "#8c564b", "#e377c2"]
    failure_counts.plot(kind="bar", ax=ax, color=colors)
    ax.yaxis.set_major_locator(MultipleLocator(50))
    ax.set_title(
        f"Distribuzione dei Casi per Categoria di Fallimento - {exercise_title}",
        fontsize=14,
        fontweight="bold",
    )
    ax.set_ylabel("Numero di Casi", fontsize=12)
    ax.set_xlabel("Categoria di Fallimento", fontsize=12)
    ax.tick_params(axis="x", rotation=45)
    plt.tight_layout()
    save_and_show_plot(
        fig,
        build_plot_path(exercise_number, f"Failure_Category_LLM_es{exercise_number}.png"),
    )

    print("\nRiepilogo percentuali:")
    for category, count in failure_counts.items():
        pct = (count / len(df_llm)) * 100 if len(df_llm) else 0
        print(f"  {category}: {count} ({pct:.1f}%)")


def analyze_dynamic_failure(df_llm, exercise_title, exercise_number):
    print("\n" + "=" * 80)
    print("ANALISI: DYNAMIC_FAILURE")
    print("=" * 80)
    df_dynamic = df_llm[df_llm["failure_category"] == "dynamic_failure"].copy()
    print(f"\nTotale casi dynamic_failure: {len(df_dynamic)}")

    if len(df_dynamic) > 0:
        df_dynamic["output_category"] = pd.NA
        df_dynamic.loc[df_dynamic["llm_Output_Correct_bin"] == 1, "output_category"] = "Output Corretto (LLM è errato)"
        df_dynamic.loc[
            (df_dynamic["llm_Output_Correct_bin"] == 0)
            & (df_dynamic["judge_Output_Correct_bin"] == 0),
            "output_category",
        ] = "Output Scorretto, Diagnosi sbagliata (LLM è errato)"
        df_dynamic.loc[
            (df_dynamic["llm_Output_Correct_bin"] == 0)
            & (df_dynamic["judge_Output_Correct_bin"] == 1),
            "output_category",
        ] = "Output Scorretto, Diagnosi giusta (LLM è corretto)"

        output_categories = [
            "Output Corretto (LLM è errato)",
            "Output Scorretto, Diagnosi sbagliata (LLM è errato)",
            "Output Scorretto, Diagnosi giusta (LLM è corretto)",
        ]
        output_counts = df_dynamic["output_category"].value_counts().reindex(output_categories, fill_value=0)
        print("\nDistribuzione Output Analysis:")
        for category, count in output_counts.items():
            pct = (count / len(df_dynamic)) * 100
            print(f"  {category}: {count} ({pct:.1f}%)")

        plot_category_counts(
            output_counts,
            len(df_dynamic),
            f"Dynamic Failure - Analisi Output LLM Primario - {exercise_title}",
            ["#2ca02c", "#d62728", "#ff7f0e"],
            output_path=build_plot_path(exercise_number, f"Dynamic_Failure_Output_es{exercise_number}.png"),
        )

        df_dynamic["code_category"] = pd.NA
        df_dynamic.loc[df_dynamic["llm_Code_Correct_bin"] == 1, "code_category"] = "Codice Corretto (LLM è errato)"
        df_dynamic.loc[
            (df_dynamic["llm_Code_Correct_bin"] == 0)
            & (df_dynamic["judge_Code_Correct_bin"] == 0),
            "code_category",
        ] = "Codice Scorretto, Diagnosi sbagliata (LLM è errato)"
        df_dynamic.loc[
            (df_dynamic["llm_Code_Correct_bin"] == 0)
            & (df_dynamic["judge_Code_Correct_bin"] == 1),
            "code_category",
        ] = "Codice Scorretto, Diagnosi giusta (LLM è corretto)"

        code_categories = [
            "Codice Corretto (LLM è errato)",
            "Codice Scorretto, Diagnosi sbagliata (LLM è errato)",
            "Codice Scorretto, Diagnosi giusta (LLM è corretto)",
        ]
        code_counts = df_dynamic["code_category"].value_counts().reindex(code_categories, fill_value=0)
        print("\nDistribuzione Code Analysis:")
        for category, count in code_counts.items():
            pct = (count / len(df_dynamic)) * 100
            print(f"  {category}: {count} ({pct:.1f}%)")

        plot_category_counts(
            code_counts,
            len(df_dynamic),
            f"Dynamic Failure - Analisi Codice LLM Primario - {exercise_title}",
            ["#2ca02c", "#d62728", "#ff7f0e"],
            output_path=build_plot_path(exercise_number, f"Dynamic_Failure_Codice_es{exercise_number}.png"),
        )


def analyze_static_failure(df_llm, exercise_title, exercise_number):
    print("\n" + "=" * 80)
    print("ANALISI: STATIC_FAILURE")
    print("=" * 80)
    df_static = df_llm[df_llm["failure_category"] == "static_failure"].copy()
    print(f"\nTotale casi static_failure: {len(df_static)}")

    if len(df_static) > 0:
        df_static["output_category_static"] = pd.NA
        df_static.loc[df_static["llm_Output_Correct_bin"] == 1, "output_category_static"] = "Output Corretto (caso desiderato)"
        df_static.loc[df_static["llm_Output_Correct_bin"] == 0, "output_category_static"] = "Output Scorretto (falso allarme)"

        output_categories_static = [
            "Output Corretto (caso desiderato)",
            "Output Scorretto (falso allarme)",
        ]
        output_counts_static = df_static["output_category_static"].value_counts().reindex(output_categories_static, fill_value=0)
        print("\nDistribuzione Output (Static Check):")
        for category, count in output_counts_static.items():
            pct = (count / len(df_static)) * 100
            print(f"  {category}: {count} ({pct:.1f}%)")

        plot_category_counts(
            output_counts_static,
            len(df_static),
            f"Static Failure - Analisi Output LLM Primario - {exercise_title}",
            ["#2ca02c", "#d62728"],
            output_path=build_plot_path(exercise_number, f"Static_Failure_Output_es{exercise_number}.png"),
        )

        df_static["code_category_static"] = pd.NA
        df_static.loc[df_static["llm_Code_Correct_bin"] == 1, "code_category_static"] = "Codice Corretto (LLM è errato)"
        df_static.loc[
            (df_static["llm_Code_Correct_bin"] == 0)
            & (df_static["judge_Code_Correct_bin"] == 0),
            "code_category_static",
        ] = "Codice Scorretto, Diagnosi sbagliata (LLM è errato)"
        df_static.loc[
            (df_static["llm_Code_Correct_bin"] == 0)
            & (df_static["judge_Code_Correct_bin"] == 1),
            "code_category_static",
        ] = "Codice Scorretto, Diagnosi giusta (LLM è corretto)"

        code_categories_static = [
            "Codice Corretto (LLM è errato)",
            "Codice Scorretto, Diagnosi sbagliata (LLM è errato)",
            "Codice Scorretto, Diagnosi giusta (LLM è corretto)",
        ]
        code_counts_static = df_static["code_category_static"].value_counts().reindex(code_categories_static, fill_value=0)
        print("\nDistribuzione Code Analysis (Static Check):")
        for category, count in code_counts_static.items():
            pct = (count / len(df_static)) * 100
            print(f"  {category}: {count} ({pct:.1f}%)")

        plot_category_counts(
            code_counts_static,
            len(df_static),
            f"Static Failure - Analisi Codice LLM Primario - {exercise_title}",
            ["#2ca02c", "#d62728", "#ff7f0e"],
            output_path=build_plot_path(exercise_number, f"Static_Failure_Codice_es{exercise_number}.png"),
        )


def analyze_correct_cases(df_llm, exercise_title, exercise_number):
    print("\n" + "=" * 80)
    print("ANALISI: CORRECT (FALSI POSITIVI)")
    print("=" * 80)
    df_correct = df_llm[df_llm["failure_category"] == "correct"].copy()
    print(f"\nTotale casi correct: {len(df_correct)}")

    if len(df_correct) > 0:
        df_correct["output_category_correct"] = pd.NA
        df_correct.loc[df_correct["llm_Output_Correct_bin"] == 1, "output_category_correct"] = "Output Corretto (caso desiderato)"
        df_correct.loc[df_correct["llm_Output_Correct_bin"] == 0, "output_category_correct"] = "Output Scorretto (falso allarme)"

        output_categories_correct = [
            "Output Corretto (caso desiderato)",
            "Output Scorretto (falso allarme)",
        ]
        output_counts_correct = df_correct["output_category_correct"].value_counts().reindex(output_categories_correct, fill_value=0)
        print("\nDistribuzione Output (Correct cases):")
        for category, count in output_counts_correct.items():
            pct = (count / len(df_correct)) * 100
            print(f"  {category}: {count} ({pct:.1f}%)")

        plot_category_counts(
            output_counts_correct,
            len(df_correct),
            f"Correct - Analisi Output LLM Primario - {exercise_title}",
            ["#2ca02c", "#d62728"],
            output_path=build_plot_path(exercise_number, f"Correct_Output_es{exercise_number}.png"),
        )

        df_correct["code_category_correct"] = pd.NA
        df_correct.loc[df_correct["llm_Code_Correct_bin"] == 1, "code_category_correct"] = "Codice Corretto (caso desiderato)"
        df_correct.loc[df_correct["llm_Code_Correct_bin"] == 0, "code_category_correct"] = "Codice Scorretto (falso allarme)"

        code_categories_correct = [
            "Codice Corretto (caso desiderato)",
            "Codice Scorretto (falso allarme)",
        ]
        code_counts_correct = df_correct["code_category_correct"].value_counts().reindex(code_categories_correct, fill_value=0)
        print("\nDistribuzione Code (Correct cases):")
        for category, count in code_counts_correct.items():
            pct = (count / len(df_correct)) * 100
            print(f"  {category}: {count} ({pct:.1f}%)")

        plot_category_counts(
            code_counts_correct,
            len(df_correct),
            f"Correct - Analisi Codice LLM Primario - {exercise_title}",
            ["#2ca02c", "#d62728"],
            output_path=build_plot_path(exercise_number, f"Correct_Codice_es{exercise_number}.png"),
        )


def analyze_exercise(exercise_number: int, llm_json_file: Path, all_commits_json_file: Path):
    exercise_title = EXERCISE_TITLES.get(exercise_number, f"Es.{exercise_number}")

    print("\n" + "#" * 80)
    print(f"ESERCITAZIONE {exercise_title}")
    print("#" * 80)

    df_llm = load_dataframe(llm_json_file, f"risultati LLM - {exercise_title}")
    df_all = load_dataframe(all_commits_json_file, f"risultati tutti i commit - {exercise_title}")

    prepare_llm_dataframe(df_llm)
    prepare_all_commits_dataframe(df_all)

    repo_stats = compute_repo_commit_stats(all_commits_json_file)
    json_stats = compute_json_commit_stats(df_all)

    print_global_stats(exercise_title, repo_stats, json_stats, df_llm, df_all)
    plot_all_commits_distribution(df_all, exercise_title, exercise_number)
    plot_llm_failure_distribution(df_llm, exercise_title, exercise_number)
    analyze_dynamic_failure(df_llm, exercise_title, exercise_number)
    analyze_static_failure(df_llm, exercise_title, exercise_number)
    analyze_correct_cases(df_llm, exercise_title, exercise_number)

    print("\n" + "=" * 80)
    print("RIEPILOGO FINALE")
    print("=" * 80)
    print(f"Esercitazione: {exercise_title}")
    print(f"File LLM usato: {llm_json_file.name}")
    print(f"File tutti i commit usato: {all_commits_json_file.name}")
    print(f"Totale valutazioni LLM: {len(df_llm)}")
    print(f"Totale record tutti i commit: {len(df_all)}")
    print("\nAnalisi completata!")


def main():
    print("=" * 80)
    print("GRAFICO AGGREGATO: TUTTE LE ESERCITAZIONI")
    print("=" * 80)
    plot_all_exercises_failure_distribution()
    print("\n" + "=" * 80)
    print("GRAFICO AGGREGATO LLM: TUTTE LE ESERCITAZIONI")
    print("=" * 80)
    plot_all_exercises_failure_distribution_llm()

    llm_map = build_candidate_map(LLM_JSON_CANDIDATES)
    all_commits_map = build_candidate_map(ALL_COMMITS_JSON_CANDIDATES)
    exercise_numbers = sorted(set(llm_map) | set(all_commits_map))

    if not exercise_numbers:
        raise FileNotFoundError("Nessun file JSON trovato nelle liste LLM_JSON_CANDIDATES e ALL_COMMITS_JSON_CANDIDATES")

    for exercise_number in exercise_numbers:
        llm_json_file = llm_map.get(exercise_number)
        all_commits_json_file = all_commits_map.get(exercise_number)

        if llm_json_file is None or all_commits_json_file is None:
            print("\n" + "!" * 80)
            print(f"Salto esercitazione {exercise_number}: manca uno dei file richiesti.")
            print(f"  LLM: {llm_json_file}")
            print(f"  Tutti i commit: {all_commits_json_file}")
            print("!" * 80)
            continue

        analyze_exercise(exercise_number, llm_json_file, all_commits_json_file)

if __name__ == "__main__":
    main()
