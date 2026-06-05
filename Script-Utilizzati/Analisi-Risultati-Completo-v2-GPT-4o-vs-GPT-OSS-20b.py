import json
import re
import subprocess
from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
import seaborn as sns
from matplotlib.ticker import MultipleLocator


sns.set(style="whitegrid")
plt.rcParams["figure.figsize"] = (12.8, 7.4)
plt.rcParams["font.size"] = 14

MODEL_COMPARISON_FIGSIZE = (24.0, 12.0)
MODEL_COMPARISON_GLOBAL_FONTS = {
    "title": 28,
    "axis": 22,
    "tick": 20,
    "legend": 20,
    "annotation": 19,
}
MODEL_COMPARISON_GRID_FONTS = {
    "suptitle": 28,
    "subplot_title": 24,
    "axis": 20,
    "tick": 18,
    "legend": 19,
}

BASE_DIR = Path(__file__).resolve().parent
RESULTS_BASE_DIR = Path(r"C:\Users\andre\OneDrive\Desktop\TESI MAGISTRALE")
AGGREGATED_PLOT_PATH = RESULTS_BASE_DIR / "Distribuzione_tutte_esercitazioni.pdf"
AGGREGATED_LLM_PLOT_PATH = RESULTS_BASE_DIR / "Distribuzione_tutte_esercitazioni_LLM.pdf"
GPT4O_LABEL = "GPT-4o"
GPT_OSS_LABEL = "GPT-OSS-20b"
LLM_JSON_CANDIDATES = [
    RESULTS_BASE_DIR / "risultati_es1.json",
    RESULTS_BASE_DIR / "risultati_es2.json",
    RESULTS_BASE_DIR / "risultati_es3.json",
    RESULTS_BASE_DIR / "risultati_es4.json",
    RESULTS_BASE_DIR / "risultati_es5.json",
]
GPT_OSS_JSON_CANDIDATES = [
    Path(r"\\wsl.localhost\Ubuntu\home\andre\risultati_es1_gpt-oss.json"),
    Path(r"\\wsl.localhost\Ubuntu\home\andre\risultati_es2_gpt-oss.json"),
    Path(r"\\wsl.localhost\Ubuntu\home\andre\risultati_es3_gpt-oss.json"),
    Path(r"\\wsl.localhost\Ubuntu\home\andre\risultati_es4_gpt-oss.json"),
    Path(r"\\wsl.localhost\Ubuntu\home\andre\risultati_es5_gpt-oss.json"),
]
ALL_COMMITS_JSON_CANDIDATES = [
    RESULTS_BASE_DIR / "risultati_es1_tutti_commit_bash.json",
    RESULTS_BASE_DIR / "risultati_es2_tutti_commit_bash.json",
    RESULTS_BASE_DIR / "risultati_es3_tutti_commit_bash.json",
    RESULTS_BASE_DIR / "risultati_es4_tutti_commit_bash.json",
    RESULTS_BASE_DIR / "risultati_es5_tutti_commit_bash.json",
]
MODEL_COMPARISON_GLOBAL_PLOT_PATH = RESULTS_BASE_DIR / "Confronto_gpt-4o_vs_gpt-oss_metriche_globali.pdf"
MODEL_COMPARISON_EXERCISE_PLOT_PATH = RESULTS_BASE_DIR / "Confronto_gpt-4o_vs_gpt-oss_metriche_per_esercitazione.pdf"
MODEL_COMPARISON_FAILURE_PLOT_PATH = RESULTS_BASE_DIR / "Confronto_gpt-4o_vs_gpt-oss_metriche_per_categoria.pdf"
MODEL_COLORS = {
    GPT4O_LABEL: "#1f77b4",
    GPT_OSS_LABEL: "#ff7f0e",
}
METRIC_DEFINITIONS = [
    ("output_eval", "Valutazione Output"),
    ("code_eval", "Valutazione Codice"),
    ("output_diag", "Diagnosi Output"),
    ("code_diag", "Diagnosi Codice"),
]
FAILURE_CATEGORY_DISPLAY = {
    "crash": "crash",
    "timeout": "timeout",
    "ipc_leak": "ipc leak",
    "dynamic_failure": "dynamic failure",
    "static_failure": "static failure",
    "correct": "correct",
}

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
    match = re.search(r"risultati_es(\d+)(?:_.+)?\.json$", path.name)
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


def bool_to_bin(x):
    if pd.isna(x):
        return 0
    if isinstance(x, bool):
        return int(x)
    value = str(x).strip().upper()
    if value in {"YES", "Y", "TRUE", "T", "1"}:
        return 1
    if value in {"NO", "N", "FALSE", "F", "0"}:
        return 0
    return 0


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


def add_percent_labels(ax, values, total, x_positions=None, fontsize=15):
    ymin, ymax = ax.get_ylim()
    offset = (ymax - ymin) * 0.03
    positions = x_positions if x_positions is not None else range(len(values))
    for x_pos, value in zip(positions, values):
        pct = (value / total) * 100 if total else 0
        ax.text(
            x_pos,
            value + offset,
            f"{pct:.1f}%",
            ha="center",
            va="bottom",
            fontweight="bold",
            fontsize=fontsize,
        )
    max_val = max(values) if len(values) > 0 else 0
    ax.set_ylim(ymin, max_val + (ymax - ymin) * 0.18)


def save_and_show_plot(fig, output_path: Path = None):
    if output_path is not None:
        output_path.parent.mkdir(parents=True, exist_ok=True)
        fmt = "pdf" if str(output_path).lower().endswith(".pdf") else "png"
        fig.savefig(output_path, dpi=300, bbox_inches="tight", format=fmt)
        print(f"Grafico salvato: {output_path}")
    if "agg" not in plt.get_backend().lower():
        plt.show()
    plt.close(fig)


def plot_category_counts(counts, total, title, colors, ylabel="Numero di Casi", output_path: Path = None):
    fig, ax = plt.subplots(figsize=(13.6, 7.6))
    
    # Crea barre con spaziatura selettiva (spazio maggiore tra dynamic_failure e static_failure)
    x_positions = list(range(len(counts)))
    # Aggiungi uno spazio extra tra dynamic_failure (indice 4) e static_failure (indice 5)
    adjusted_positions = []
    for i, pos in enumerate(x_positions):
        if i > 4:  # Dopo dynamic_failure
            adjusted_positions.append(pos + 1.3)
        else:
            adjusted_positions.append(pos)
    
    ax.bar(adjusted_positions, counts.values, color=colors, width=0.6)
    ax.set_xticks(adjusted_positions)
    ax.set_xticklabels(counts.index, rotation=0, fontsize=14)

    ax.set_title(title, fontsize=19, fontweight="bold", pad=12)
    ax.set_ylabel(ylabel, fontsize=16, labelpad=12)
    ax.set_xlabel("Categoria", fontsize=16, labelpad=12)
    ax.tick_params(axis="x", labelsize=14, pad=10)
    ax.tick_params(axis="y", labelsize=14)
    add_percent_labels(ax, counts.values, total, adjusted_positions)
    fig.subplots_adjust(bottom=0.30, left=0.11, right=0.98, top=0.88)
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
    fig, axes = plt.subplots(1, len(all_data), figsize=(23, 8.2), sharey=True)
    if len(all_data) == 1:
        axes = [axes]
    
    colors = ["#d62728", "#ff7f0e", "#2ca02c", "#1f77b4", "#9467bd", "#8c564b", "#e377c2"]
    
    for idx, (ex_label, df) in enumerate(sorted(all_data.items())):
        failure_counts = df["failure_category"].value_counts().reindex(FAILURE_CATEGORIES, fill_value=0)
        
        # Plot bar chart direttamente con ax.bar per avere più controllo
        ax = axes[idx]
        x_pos = range(len(failure_counts))
        ax.bar(x_pos, failure_counts.values, color=colors[:len(failure_counts)])
        
        # Formattazione
        title = EXERCISE_TITLES.get(ex_label, f"Es.{ex_label}")
        ax.set_title(f"{title}", fontsize=17, fontweight="bold")
        ax.set_ylabel("# Commits" if idx == 0 else "", fontsize=15)
        ax.set_xlabel("")
        ax.set_xticks([])  # Nascondi le etichette dell'asse x
        ax.yaxis.set_major_locator(MultipleLocator(50))  # Tacche ogni 50 unità
        ax.tick_params(axis="y", labelsize=13)
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
        fontsize=13,
        bbox_to_anchor=(0.83, 0.85),
        bbox_transform=fig.transFigure,
        borderaxespad=0,
    )

    fig.suptitle(title_text, fontsize=20, fontweight="bold")
    fig.subplots_adjust(wspace=0.3, top=0.84, bottom=0.10, left=0.06, right=0.82)
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
    filename = filename.replace(".png", ".pdf")
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
        "test_success",
    ]:
        ensure_column(df_llm, column)

    df_llm["llm_Output_Correct_bin"] = df_llm["llm_Output_Correct"].apply(si_no_to_bin)
    df_llm["llm_Code_Correct_bin"] = df_llm["llm_Code_Correct"].apply(si_no_to_bin)
    df_llm["judge_Output_Correct_bin"] = df_llm["judge_Output_Correct"].apply(si_no_to_bin)
    df_llm["judge_Code_Correct_bin"] = df_llm["judge_Code_Correct"].apply(si_no_to_bin)
    df_llm["gt_output_correct_bin"] = df_llm["test_success"].apply(bool_to_bin)
    df_llm["gt_code_correct_bin"] = (df_llm["failure_category"] == "correct").astype(int)
    df_llm["llm_mod_key"] = build_unique_series(df_llm, ["student", "exercise", "commit_analyzed"])


def prepare_all_commits_dataframe(df_all: pd.DataFrame):
    for column in ["student", "exercise", "commit_analyzed", "failure_category"]:
        ensure_column(df_all, column)

    df_all["git_commit_key"] = build_unique_series(df_all, ["student", "commit_analyzed"])
    df_all["exercise_mod_key"] = build_unique_series(df_all, ["student", "exercise", "commit_analyzed"])


def accuracy_to_pct(correct_cases, total_cases):
    if total_cases == 0:
        return pd.NA
    return (correct_cases / total_cases) * 100


def format_pct(value):
    if pd.isna(value):
        return "N/A"
    return f"{value:.1f}%"


def format_accuracy_cell(correct_cases, total_cases):
    if total_cases == 0:
        return "N/A"
    return f"{accuracy_to_pct(correct_cases, total_cases):.1f}% ({int(correct_cases)}/{int(total_cases)})"


def build_plot_positions(labels, spacing=1.0, extra_gaps=None):
    positions = []
    current = 0.0
    extra_gaps = extra_gaps or {}
    for label in labels:
        positions.append(current)
        current += spacing + extra_gaps.get(label, 0.0)
    return np.array(positions)


def compute_accuracy_summary(df, prediction_col, truth_col):
    subset = df[df[prediction_col].notna()].copy()
    if subset.empty:
        return {"total_cases": 0, "correct_cases": 0, "accuracy_pct": pd.NA}

    correct_mask = subset[prediction_col].astype("Int64") == subset[truth_col].astype("Int64")
    correct_cases = int(correct_mask.sum())
    total_cases = int(len(subset))
    return {
        "total_cases": total_cases,
        "correct_cases": correct_cases,
        "accuracy_pct": accuracy_to_pct(correct_cases, total_cases),
    }


def compute_group_accuracy_table(df, group_col, prediction_col, truth_col):
    subset = df[df[prediction_col].notna()].copy()
    if subset.empty:
        return pd.DataFrame(columns=["total_cases", "correct_cases", "accuracy_pct"])

    subset["metric_correct"] = (
        subset[prediction_col].astype("Int64") == subset[truth_col].astype("Int64")
    ).astype(int)
    summary = subset.groupby(group_col, dropna=False)["metric_correct"].agg(
        total_cases="size",
        correct_cases="sum",
    )
    summary["accuracy_pct"] = summary.apply(
        lambda row: accuracy_to_pct(row["correct_cases"], row["total_cases"]),
        axis=1,
    )
    return summary.sort_index()


def compute_diagnosis_summary(df, detection_col, judge_col, truth_col):
    subset = df[
        (df[truth_col] == 0)
        & (df[detection_col] == 0)
        & df[judge_col].notna()
    ].copy()
    if subset.empty:
        return {"total_cases": 0, "correct_cases": 0, "accuracy_pct": pd.NA}

    correct_mask = subset[judge_col].astype("Int64") == 1
    correct_cases = int(correct_mask.sum())
    total_cases = int(len(subset))
    return {
        "total_cases": total_cases,
        "correct_cases": correct_cases,
        "accuracy_pct": accuracy_to_pct(correct_cases, total_cases),
    }


def compute_group_diagnosis_table(df, group_col, detection_col, judge_col, truth_col):
    subset = df[
        (df[truth_col] == 0)
        & (df[detection_col] == 0)
        & df[judge_col].notna()
    ].copy()
    if subset.empty:
        return pd.DataFrame(columns=["total_cases", "correct_cases", "accuracy_pct"])

    subset["metric_correct"] = (subset[judge_col].astype("Int64") == 1).astype(int)
    summary = subset.groupby(group_col, dropna=False)["metric_correct"].agg(
        total_cases="size",
        correct_cases="sum",
    )
    summary["accuracy_pct"] = summary.apply(
        lambda row: accuracy_to_pct(row["correct_cases"], row["total_cases"]),
        axis=1,
    )
    return summary.sort_index()


# ==================== NEW METRIC FUNCTIONS ====================

def compute_llm_output_correct_accuracy(df):
    """
    Statistica 1: LLM riesce a valutare correttamente se l'output è corretto?
    Verifica: llm_Output_Correct == "YES" AND (failure_category == "static_failure" OR failure_category == "correct")
    """
    subset = df[df["llm_Output_Correct"].notna()].copy()
    if subset.empty:
        return {"total_cases": 0, "correct_cases": 0, "accuracy_pct": pd.NA}
    
    correct_mask = (subset["llm_Output_Correct"] == "YES") & (
        (subset["failure_category"] == "static_failure") | (subset["failure_category"] == "correct")
    )
    correct_cases = int(correct_mask.sum())
    total_cases = int(len(subset))
    return {
        "total_cases": total_cases,
        "correct_cases": correct_cases,
        "accuracy_pct": accuracy_to_pct(correct_cases, total_cases),
    }


def compute_llm_code_correct_accuracy(df):
    """
    Statistica 2: LLM riesce a valutare correttamente se il codice è corretto?
    Verifica: llm_Code_Correct == "YES" AND failure_category == "correct"
    """
    subset = df[df["llm_Code_Correct"].notna()].copy()
    if subset.empty:
        return {"total_cases": 0, "correct_cases": 0, "accuracy_pct": pd.NA}
    
    correct_mask = (subset["llm_Code_Correct"] == "YES") & (subset["failure_category"] == "correct")
    correct_cases = int(correct_mask.sum())
    total_cases = int(len(subset))
    return {
        "total_cases": total_cases,
        "correct_cases": correct_cases,
        "accuracy_pct": accuracy_to_pct(correct_cases, total_cases),
    }


def compute_output_diagnosis_accuracy(df):
    """
    Statistica 3: Quando LLM rileva che l'output è errato, la diagnosi è corretta?
    Filtro: failure_category == "dynamic_failure" AND llm_Output_Correct == "NO"
    Verifica: judge_Output_Correct == "YES"
    """
    subset = df[
        (df["failure_category"] == "dynamic_failure")
        & (df["llm_Output_Correct"] == "NO")
        & df["judge_Output_Correct"].notna()
    ].copy()
    if subset.empty:
        return {"total_cases": 0, "correct_cases": 0, "accuracy_pct": pd.NA}
    
    correct_mask = subset["judge_Output_Correct"] == "YES"
    correct_cases = int(correct_mask.sum())
    total_cases = int(len(subset))
    return {
        "total_cases": total_cases,
        "correct_cases": correct_cases,
        "accuracy_pct": accuracy_to_pct(correct_cases, total_cases),
    }


def compute_code_diagnosis_accuracy(df):
    """
    Statistica 4: Quando LLM rileva che il codice è errato, la diagnosi è corretta?
    Filtro: failure_category in ["dynamic_failure", "static_failure", "crash", "ipc_leak", "timeout"] AND llm_Code_Correct == "NO"
    Verifica: judge_Code_Correct == "YES"
    """
    failure_types = ["dynamic_failure", "static_failure", "crash", "ipc_leak", "timeout"]
    subset = df[
        (df["failure_category"].isin(failure_types))
        & (df["llm_Code_Correct"] == "NO")
        & df["judge_Code_Correct"].notna()
    ].copy()
    if subset.empty:
        return {"total_cases": 0, "correct_cases": 0, "accuracy_pct": pd.NA}
    
    correct_mask = subset["judge_Code_Correct"] == "YES"
    correct_cases = int(correct_mask.sum())
    total_cases = int(len(subset))
    return {
        "total_cases": total_cases,
        "correct_cases": correct_cases,
        "accuracy_pct": accuracy_to_pct(correct_cases, total_cases),
    }


def compute_llm_output_correct_per_group(df, group_col):
    """Statistica 1 per gruppo - Solo failure_category in [static_failure, correct]"""
    subset = df[
        df["llm_Output_Correct"].notna() &
        ((df["failure_category"] == "static_failure") | (df["failure_category"] == "correct"))
    ].copy()
    if subset.empty:
        return pd.DataFrame(columns=["total_cases", "correct_cases", "accuracy_pct"])
    
    subset["metric_correct"] = subset["llm_Output_Correct"] == "YES"
    summary = subset.groupby(group_col, dropna=False)["metric_correct"].agg(
        total_cases="size",
        correct_cases="sum",
    )
    summary["accuracy_pct"] = summary.apply(
        lambda row: accuracy_to_pct(row["correct_cases"], row["total_cases"]),
        axis=1,
    )
    return summary.sort_index()


def compute_llm_code_correct_per_group(df, group_col):
    """Statistica 2 per gruppo - Solo failure_category == correct"""
    subset = df[
        df["llm_Code_Correct"].notna() &
        (df["failure_category"] == "correct")
    ].copy()
    if subset.empty:
        return pd.DataFrame(columns=["total_cases", "correct_cases", "accuracy_pct"])
    
    subset["metric_correct"] = subset["llm_Code_Correct"] == "YES"
    summary = subset.groupby(group_col, dropna=False)["metric_correct"].agg(
        total_cases="size",
        correct_cases="sum",
    )
    summary["accuracy_pct"] = summary.apply(
        lambda row: accuracy_to_pct(row["correct_cases"], row["total_cases"]),
        axis=1,
    )
    return summary.sort_index()


def compute_output_diagnosis_per_group(df, group_col):
    """Statistica 3 per gruppo"""
    subset = df[
        (df["failure_category"] == "dynamic_failure")
        & (df["llm_Output_Correct"] == "NO")
        & df["judge_Output_Correct"].notna()
    ].copy()
    if subset.empty:
        return pd.DataFrame(columns=["total_cases", "correct_cases", "accuracy_pct"])
    
    subset["metric_correct"] = subset["judge_Output_Correct"] == "YES"
    summary = subset.groupby(group_col, dropna=False)["metric_correct"].agg(
        total_cases="size",
        correct_cases="sum",
    )
    summary["accuracy_pct"] = summary.apply(
        lambda row: accuracy_to_pct(row["correct_cases"], row["total_cases"]),
        axis=1,
    )
    return summary.sort_index()


def compute_code_diagnosis_per_group(df, group_col):
    """Statistica 4 per gruppo"""
    failure_types = ["dynamic_failure", "static_failure", "crash", "ipc_leak", "timeout"]
    subset = df[
        (df["failure_category"].isin(failure_types))
        & (df["llm_Code_Correct"] == "NO")
        & df["judge_Code_Correct"].notna()
    ].copy()
    if subset.empty:
        return pd.DataFrame(columns=["total_cases", "correct_cases", "accuracy_pct"])
    
    subset["metric_correct"] = subset["judge_Code_Correct"] == "YES"
    summary = subset.groupby(group_col, dropna=False)["metric_correct"].agg(
        total_cases="size",
        correct_cases="sum",
    )
    summary["accuracy_pct"] = summary.apply(
        lambda row: accuracy_to_pct(row["correct_cases"], row["total_cases"]),
        axis=1,
    )
    return summary.sort_index()


def compute_llm_output_correct_accuracy(df):
    """Accuratezza della valutazione output rispetto alla ground truth."""
    return compute_accuracy_summary(df, "llm_Output_Correct_bin", "gt_output_correct_bin")


def compute_llm_code_correct_accuracy(df):
    """Accuratezza della valutazione codice rispetto alla ground truth."""
    return compute_accuracy_summary(df, "llm_Code_Correct_bin", "gt_code_correct_bin")


def compute_output_diagnosis_accuracy(df):
    """Accuratezza della diagnosi output con la logica precedente."""
    subset = df[
        (df["failure_category"] == "dynamic_failure")
        & (df["llm_Output_Correct"] == "NO")
        & df["judge_Output_Correct_bin"].notna()
    ].copy()
    if subset.empty:
        return {"total_cases": 0, "correct_cases": 0, "accuracy_pct": pd.NA}

    correct_mask = subset["judge_Output_Correct_bin"].astype("Int64") == 1
    correct_cases = int(correct_mask.sum())
    total_cases = int(len(subset))
    return {
        "total_cases": total_cases,
        "correct_cases": correct_cases,
        "accuracy_pct": accuracy_to_pct(correct_cases, total_cases),
    }


def compute_code_diagnosis_accuracy(df):
    """Accuratezza della diagnosi codice con la logica precedente."""
    failure_types = ["dynamic_failure", "static_failure", "crash", "ipc_leak", "timeout"]
    subset = df[
        (df["failure_category"].isin(failure_types))
        & (df["llm_Code_Correct"] == "NO")
        & df["judge_Code_Correct_bin"].notna()
    ].copy()
    if subset.empty:
        return {"total_cases": 0, "correct_cases": 0, "accuracy_pct": pd.NA}

    correct_mask = subset["judge_Code_Correct_bin"].astype("Int64") == 1
    correct_cases = int(correct_mask.sum())
    total_cases = int(len(subset))
    return {
        "total_cases": total_cases,
        "correct_cases": correct_cases,
        "accuracy_pct": accuracy_to_pct(correct_cases, total_cases),
    }


def compute_llm_output_correct_per_group(df, group_col):
    return compute_group_accuracy_table(df, group_col, "llm_Output_Correct_bin", "gt_output_correct_bin")


def compute_llm_code_correct_per_group(df, group_col):
    return compute_group_accuracy_table(df, group_col, "llm_Code_Correct_bin", "gt_code_correct_bin")


def compute_output_diagnosis_per_group(df, group_col):
    subset = df[
        (df["failure_category"] == "dynamic_failure")
        & (df["llm_Output_Correct"] == "NO")
        & df["judge_Output_Correct_bin"].notna()
    ].copy()
    if subset.empty:
        return pd.DataFrame(columns=["total_cases", "correct_cases", "accuracy_pct"])

    subset["metric_correct"] = (subset["judge_Output_Correct_bin"].astype("Int64") == 1).astype(int)
    summary = subset.groupby(group_col, dropna=False)["metric_correct"].agg(
        total_cases="size",
        correct_cases="sum",
    )
    summary["accuracy_pct"] = summary.apply(
        lambda row: accuracy_to_pct(row["correct_cases"], row["total_cases"]),
        axis=1,
    )
    return summary.sort_index()


def compute_code_diagnosis_per_group(df, group_col):
    failure_types = ["dynamic_failure", "static_failure", "crash", "ipc_leak", "timeout"]
    subset = df[
        (df["failure_category"].isin(failure_types))
        & (df["llm_Code_Correct"] == "NO")
        & df["judge_Code_Correct_bin"].notna()
    ].copy()
    if subset.empty:
        return pd.DataFrame(columns=["total_cases", "correct_cases", "accuracy_pct"])

    subset["metric_correct"] = (subset["judge_Code_Correct_bin"].astype("Int64") == 1).astype(int)
    summary = subset.groupby(group_col, dropna=False)["metric_correct"].agg(
        total_cases="size",
        correct_cases="sum",
    )
    summary["accuracy_pct"] = summary.apply(
        lambda row: accuracy_to_pct(row["correct_cases"], row["total_cases"]),
        axis=1,
    )
    return summary.sort_index()


def compute_metric_summary_bundle(df):
    return {
        "output_eval": compute_llm_output_correct_accuracy(df),
        "code_eval": compute_llm_code_correct_accuracy(df),
        "output_diag": compute_output_diagnosis_accuracy(df),
        "code_diag": compute_code_diagnosis_accuracy(df),
    }


def compute_metric_table(df, group_col, metric_key):
    if group_col == "failure_category":
        rows = []
        for failure_cat in [cat for cat in FAILURE_CATEGORIES if cat != "compile_failure"]:
            summary = compute_metric_for_category(df, failure_cat, metric_key)
            rows.append(
                {
                    "group_label": failure_cat,
                    "total_cases": summary["total_cases"],
                    "correct_cases": summary["correct_cases"],
                    "accuracy_pct": summary["accuracy_pct"],
                }
            )
        return pd.DataFrame(rows)

    group_functions = {
        "output_eval": compute_llm_output_correct_per_group,
        "code_eval": compute_llm_code_correct_per_group,
        "output_diag": compute_output_diagnosis_per_group,
        "code_diag": compute_code_diagnosis_per_group,
    }
    table = group_functions[metric_key](df, group_col).reset_index()
    table = table.rename(columns={group_col: "group_label"})
    return table


def build_model_comparison_rows(model_label, df, group_col=None):
    rows = []
    if group_col is None:
        summaries = compute_metric_summary_bundle(df)
        for metric_key, metric_label in METRIC_DEFINITIONS:
            summary = summaries[metric_key]
            rows.append(
                {
                    "model": model_label,
                    "metric_key": metric_key,
                    "metric_label": metric_label,
                    "group_label": "Globale",
                    "accuracy_pct": summary["accuracy_pct"],
                    "total_cases": summary["total_cases"],
                    "correct_cases": summary["correct_cases"],
                }
            )
        return pd.DataFrame(rows)

    for metric_key, metric_label in METRIC_DEFINITIONS:
        table = compute_metric_table(df, group_col, metric_key)
        if table.empty:
            continue
        table = table.copy()
        table["model"] = model_label
        table["metric_key"] = metric_key
        table["metric_label"] = metric_label
        rows.extend(table.to_dict("records"))
    return pd.DataFrame(rows)


def plot_model_comparison_global(df_global, output_path: Path):
    fig, ax = plt.subplots(figsize=MODEL_COMPARISON_FIGSIZE)
    metric_keys = [metric_key for metric_key, _ in METRIC_DEFINITIONS]
    metric_labels = [metric_label for _, metric_label in METRIC_DEFINITIONS]
    x = build_plot_positions(
        metric_labels,
        spacing=1.22,
        extra_gaps={
            "Valutazione Output": 0.18,
            "Valutazione Codice": 0.16,
            "Diagnosi Output": 0.14,
        },
    )
    width = 0.34

    for index, model_label in enumerate([GPT4O_LABEL, GPT_OSS_LABEL]):
        model_rows = (
            df_global[df_global["model"] == model_label]
            .set_index("metric_key")
            .reindex(metric_keys)
        )
        values = model_rows["accuracy_pct"].fillna(0).to_numpy()
        offsets = x + (index - 0.5) * width
        bars = ax.bar(
            offsets,
            values,
            width=width,
            label=model_label,
            color=MODEL_COLORS[model_label],
        )
        total_reference = 100 if len(values) else 1
        add_percent_labels(
            ax,
            values,
            total_reference,
            offsets,
            fontsize=MODEL_COMPARISON_GLOBAL_FONTS["annotation"],
        )

    ax.set_title(
        "Confronto globale tra gpt-4o e gpt-oss",
        fontsize=MODEL_COMPARISON_GLOBAL_FONTS["title"],
        fontweight="bold",
        pad=14,
    )
    ax.set_ylabel("Accuratezza (%)", fontsize=MODEL_COMPARISON_GLOBAL_FONTS["axis"], labelpad=12)
    ax.set_xlabel("Metrica", fontsize=MODEL_COMPARISON_GLOBAL_FONTS["axis"], labelpad=12)
    ax.set_xticks(x)
    ax.set_xticklabels(
        metric_labels,
        fontsize=MODEL_COMPARISON_GLOBAL_FONTS["tick"],
    )
    ax.tick_params(axis="x", pad=14)
    ax.tick_params(axis="y", labelsize=MODEL_COMPARISON_GLOBAL_FONTS["tick"])
    ax.margins(x=0.12)
    ax.grid(axis="y", alpha=0.3)
    ax.set_axisbelow(True)
    ax.legend(
        fontsize=MODEL_COMPARISON_GLOBAL_FONTS["legend"],
        frameon=False,
        loc="upper left",
    )
    fig.subplots_adjust(bottom=0.16, left=0.10, right=0.98, top=0.92)
    save_and_show_plot(fig, output_path)


def plot_model_comparison_grid(
    df_group,
    output_path: Path,
    title: str,
    group_order,
    tick_rotation=0,
    spacing=1.0,
    extra_gaps=None,
    bottom_margin=0.18,
):
    fig, axes = plt.subplots(2, 2, figsize=MODEL_COMPARISON_FIGSIZE, sharey=True)
    axes = axes.flatten()
    width = 0.34

    for subplot_index, (metric_key, metric_label) in enumerate(METRIC_DEFINITIONS):
        ax = axes[subplot_index]
        metric_rows = df_group[df_group["metric_key"] == metric_key].copy()
        current_group_order = group_order.get(metric_key, []) if isinstance(group_order, dict) else group_order
        display_labels = [
            FAILURE_CATEGORY_DISPLAY.get(label, label) if isinstance(group_order, dict) else label
            for label in current_group_order
        ]
        x = build_plot_positions(current_group_order, spacing=spacing, extra_gaps=extra_gaps)
        for model_index, model_label in enumerate([GPT4O_LABEL, GPT_OSS_LABEL]):
            model_rows = (
                metric_rows[metric_rows["model"] == model_label]
                .set_index("group_label")
                .reindex(current_group_order)
            )
            values = model_rows["accuracy_pct"].fillna(0).to_numpy()
            offsets = x + (model_index - 0.5) * width
            ax.bar(
                offsets,
                values,
                width=width,
                label=model_label,
                color=MODEL_COLORS[model_label],
            )

        ax.set_title(
            metric_label,
            fontsize=MODEL_COMPARISON_GRID_FONTS["subplot_title"],
            fontweight="bold",
            pad=10,
        )
        ax.set_xticks(x)
        ax.set_xticklabels(
            display_labels,
            rotation=0,
            ha="center",
            fontsize=MODEL_COMPARISON_GRID_FONTS["tick"],
        )
        ax.tick_params(axis="x", pad=12, length=6)
        ax.tick_params(axis="y", labelsize=MODEL_COMPARISON_GRID_FONTS["tick"])
        ax.margins(x=0.08)
        ax.grid(axis="y", alpha=0.3)
        ax.set_axisbelow(True)
        if subplot_index % 2 == 0:
            ax.set_ylabel("Accuratezza (%)", fontsize=MODEL_COMPARISON_GRID_FONTS["axis"])

    handles, labels = axes[0].get_legend_handles_labels()
    fig.legend(
        handles,
        labels,
        loc="upper center",
        ncol=2,
        fontsize=MODEL_COMPARISON_GRID_FONTS["legend"],
        frameon=False,
        bbox_to_anchor=(0.5, 0.97),
    )
    fig.suptitle(
        title,
        fontsize=MODEL_COMPARISON_GRID_FONTS["suptitle"],
        fontweight="bold",
        y=0.99,
    )
    fig.subplots_adjust(
        bottom=bottom_margin,
        left=0.06,
        right=0.98,
        top=0.90,
        hspace=0.50,
        wspace=0.22,
    )
    save_and_show_plot(fig, output_path)


def print_model_comparison_section(df_gpt4o_all, df_gpt_oss_all):
    print("\n" + "=" * 80)
    print("CONFRONTO GPT-4O VS GPT-OSS")
    print("=" * 80)
    rows = []
    summaries_by_model = {
        GPT4O_LABEL: compute_metric_summary_bundle(df_gpt4o_all),
        GPT_OSS_LABEL: compute_metric_summary_bundle(df_gpt_oss_all),
    }
    for metric_key, metric_label in METRIC_DEFINITIONS:
        summary_4o = summaries_by_model[GPT4O_LABEL][metric_key]
        summary_oss = summaries_by_model[GPT_OSS_LABEL][metric_key]
        delta = pd.NA
        if not pd.isna(summary_4o["accuracy_pct"]) and not pd.isna(summary_oss["accuracy_pct"]):
            delta = summary_oss["accuracy_pct"] - summary_4o["accuracy_pct"]
        rows.append(
            {
                "Metrica": metric_label,
                "gpt-4o": format_accuracy_cell(summary_4o["correct_cases"], summary_4o["total_cases"]),
                "gpt-oss": format_accuracy_cell(summary_oss["correct_cases"], summary_oss["total_cases"]),
                "Delta gpt-oss - gpt-4o": format_pct(delta),
            }
        )

    comparison_table = pd.DataFrame(rows)
    print(comparison_table.to_string(index=False))

def compute_metric_for_category(df, failure_cat, metric_type):
    """Versione coerente con le metriche globali e con il giudizio YES/NO del judge."""
    df_cat = df[df["failure_category"] == failure_cat].copy()
    if df_cat.empty:
        return {"total_cases": 0, "correct_cases": 0, "accuracy_pct": pd.NA}

    if metric_type == "output_eval":
        if failure_cat == "static_failure":
            # LLM valuta correttamente se output è CORRETTO
            subset = df_cat[df_cat["llm_Output_Correct"].notna()].copy()
            if subset.empty:
                return {"total_cases": 0, "correct_cases": 0, "accuracy_pct": pd.NA}
            correct_mask = subset["llm_Output_Correct"] == "YES"
        else:
            subset = df_cat[df_cat["llm_Output_Correct_bin"].notna()].copy()
            if subset.empty:
                return {"total_cases": 0, "correct_cases": 0, "accuracy_pct": pd.NA}
            correct_mask = subset["llm_Output_Correct_bin"].astype("Int64") == subset["gt_output_correct_bin"].astype("Int64")
    elif metric_type == "code_eval":
        if failure_cat == "static_failure":
            # LLM valuta correttamente se codice è SCORRETTO
            subset = df_cat[df_cat["llm_Code_Correct"].notna()].copy()
            if subset.empty:
                return {"total_cases": 0, "correct_cases": 0, "accuracy_pct": pd.NA}
            correct_mask = subset["llm_Code_Correct"] == "NO"
        else:
            subset = df_cat[df_cat["llm_Code_Correct_bin"].notna()].copy()
            if subset.empty:
                return {"total_cases": 0, "correct_cases": 0, "accuracy_pct": pd.NA}
            correct_mask = subset["llm_Code_Correct_bin"].astype("Int64") == subset["gt_code_correct_bin"].astype("Int64")
    elif metric_type == "output_diag":
        if failure_cat == "dynamic_failure":
            subset = df_cat[
                (df_cat["llm_Output_Correct"] == "NO")
                & df_cat["judge_Output_Correct_bin"].notna()
            ].copy()
        elif failure_cat in {"static_failure", "correct"}:
            subset = df_cat[
                (df_cat["llm_Output_Correct"] == "YES")
                & df_cat["judge_Output_Correct_bin"].notna()
            ].copy()
        else:
            return {"total_cases": 0, "correct_cases": 0, "accuracy_pct": pd.NA}
        if subset.empty:
            return {"total_cases": 0, "correct_cases": 0, "accuracy_pct": pd.NA}
        correct_mask = subset["judge_Output_Correct_bin"].astype("Int64") == 1
    elif metric_type == "code_diag":
        if failure_cat == "correct":
            subset = df_cat[
                (df_cat["llm_Code_Correct"] == "YES")
                & df_cat["judge_Code_Correct_bin"].notna()
            ].copy()
        else:
            subset = df_cat[
                (df_cat["llm_Code_Correct"] == "NO")
                & df_cat["judge_Code_Correct_bin"].notna()
            ].copy()
        if subset.empty:
            return {"total_cases": 0, "correct_cases": 0, "accuracy_pct": pd.NA}
        correct_mask = subset["judge_Code_Correct_bin"].astype("Int64") == 1
    else:
        return {"total_cases": 0, "correct_cases": 0, "accuracy_pct": pd.NA}

    correct_cases = int(correct_mask.sum())
    total_cases = int(len(subset))
    return {
        "total_cases": total_cases,
        "correct_cases": correct_cases,
        "accuracy_pct": accuracy_to_pct(correct_cases, total_cases),
    }


def build_new_conclusion_tables(df, group_col):
    """Costruisce tabelle di conclusione con le 4 nuove metriche per failure_category"""
    failure_categories = [cat for cat in FAILURE_CATEGORIES if cat != "compile_failure"]
    
    if group_col == "failure_category":
        # Tabella per failure_category: ogni riga è una categoria
        formatted = pd.DataFrame(index=failure_categories)
        
        for metric_type, metric_name in [
            ("output_eval", "Valutazione Output"),
            ("code_eval", "Valutazione Codice"),
            ("output_diag", "Diagnosi Output"),
            ("code_diag", "Diagnosi Codice"),
        ]:
            results = []
            for failure_cat in failure_categories:
                summary = compute_metric_for_category(df, failure_cat, metric_type)
                if summary["total_cases"] == 0:
                    results.append("N/A")
                else:
                    results.append(format_accuracy_cell(summary["correct_cases"], summary["total_cases"]))
            formatted[metric_name] = results
        
        return formatted, {}
    
    else:
        # Tabella per esercizio: ogni riga è un esercizio, ma filtra per categoria rilevante
        # Per ora manteniamo la logica originale se group_col != "failure_category"
        metric_tables = {
            "Valutazione Output": compute_llm_output_correct_per_group(df, group_col),
            "Valutazione Codice": compute_llm_code_correct_per_group(df, group_col),
            "Diagnosi Output": compute_output_diagnosis_per_group(df, group_col),
            "Diagnosi Codice": compute_code_diagnosis_per_group(df, group_col),
        }

        row_labels = sorted({
            label
            for table in metric_tables.values()
            for label in table.index.tolist()
        })
        if not row_labels:
            return pd.DataFrame(), metric_tables

        formatted = pd.DataFrame(index=row_labels)
        for column_name, table in metric_tables.items():
            formatted[column_name] = [
                format_accuracy_cell(
                    table.loc[label, "correct_cases"],
                    table.loc[label, "total_cases"],
                ) if label in table.index else "N/A"
                for label in row_labels
            ]
        return formatted, metric_tables


def build_conclusion_tables(df, group_col):
    metric_tables = {
        "Valutazione Output": compute_group_accuracy_table(
            df,
            group_col,
            "llm_Output_Correct_bin",
            "gt_output_correct_bin",
        ),
        "Valutazione Codice": compute_group_accuracy_table(
            df,
            group_col,
            "llm_Code_Correct_bin",
            "gt_code_correct_bin",
        ),
        "Diagnosi Output": compute_group_diagnosis_table(
            df,
            group_col,
            "llm_Output_Correct_bin",
            "judge_Output_Correct_bin",
            "gt_output_correct_bin",
        ),
        "Diagnosi Codice": compute_group_diagnosis_table(
            df,
            group_col,
            "llm_Code_Correct_bin",
            "judge_Code_Correct_bin",
            "gt_code_correct_bin",
        ),
    }

    row_labels = sorted({
        label
        for table in metric_tables.values()
        for label in table.index.tolist()
    })
    if not row_labels:
        return pd.DataFrame(), metric_tables

    formatted = pd.DataFrame(index=row_labels)
    for column_name, table in metric_tables.items():
        formatted[column_name] = [
            format_accuracy_cell(
                table.loc[label, "correct_cases"],
                table.loc[label, "total_cases"],
            ) if label in table.index else "N/A"
            for label in row_labels
        ]
    return formatted, metric_tables


def print_metric_summary_line(question, summary):
    print(
        f"- {question}: {format_pct(summary['accuracy_pct'])} "
        f"({summary['correct_cases']}/{summary['total_cases']})"
    )


def print_accuracy_extremes(metric_name, table):
    valid = table[table["total_cases"] > 0].copy()
    if valid.empty:
        print(f"  {metric_name}: nessun caso disponibile")
        return

    average_pct = valid["accuracy_pct"].mean()
    best_row = valid.sort_values(
        by=["accuracy_pct", "total_cases"],
        ascending=[False, False],
    ).iloc[0]
    worst_row = valid.sort_values(
        by=["accuracy_pct", "total_cases"],
        ascending=[True, False],
    ).iloc[0]
    best_label = valid.sort_values(
        by=["accuracy_pct", "total_cases"],
        ascending=[False, False],
    ).index[0]
    worst_label = valid.sort_values(
        by=["accuracy_pct", "total_cases"],
        ascending=[True, False],
    ).index[0]

    print(f"  {metric_name} - media gruppi: {average_pct:.1f}%")
    print(
        f"  {metric_name} - migliore: {best_label} = "
        f"{best_row['accuracy_pct']:.1f}% ({int(best_row['correct_cases'])}/{int(best_row['total_cases'])})"
    )
    print(
        f"  {metric_name} - peggiore: {worst_label} = "
        f"{worst_row['accuracy_pct']:.1f}% ({int(worst_row['correct_cases'])}/{int(worst_row['total_cases'])})"
    )


def print_conclusion_section(df_llm, exercise_title, model_label="LLM"):
    print("\n" + "=" * 80)
    print(f"CONCLUSIONI {model_label.upper()} - METRICHE DI ACCURATEZZA")
    print("=" * 80)
    print(f"Esercitazione: {exercise_title}")
    print("\nMetriche calcolate:")
    print("  1. Valutazione Output: match tra llm_Output_Correct e correttezza reale dell'output")
    print("  2. Valutazione Codice: match tra llm_Code_Correct e correttezza reale del codice")
    print("  3. Diagnosi Output: quando llm_Output_Correct='NO' nei dynamic_failure, judge_Output_Correct='YES'")
    print("  4. Diagnosi Codice: quando llm_Code_Correct='NO' nei casi di codice scorretto, judge_Code_Correct='YES'")

    output_eval_summary = compute_llm_output_correct_accuracy(df_llm)
    code_eval_summary = compute_llm_code_correct_accuracy(df_llm)
    output_diag_summary = compute_output_diagnosis_accuracy(df_llm)
    code_diag_summary = compute_code_diagnosis_accuracy(df_llm)

    print("\n--- Metriche Globali ---")
    print_metric_summary_line(
        "1. LLM valuta correttamente se l'output e' corretto",
        output_eval_summary,
    )
    print_metric_summary_line(
        "2. LLM valuta correttamente se il codice e' corretto",
        code_eval_summary,
    )
    print_metric_summary_line(
        "3. Quando LLM rileva output errato, la diagnosi e' corretta",
        output_diag_summary,
    )
    print_metric_summary_line(
        "4. Quando LLM rileva codice errato, la diagnosi e' corretta",
        code_diag_summary,
    )

    failure_table, failure_metric_tables = build_new_conclusion_tables(df_llm, "failure_category")
    if not failure_table.empty:
        print("\n--- Accuratezza per failure_category ---")
        print(failure_table.to_string())

    exercise_table, exercise_metric_tables = build_new_conclusion_tables(df_llm, "exercise")
    if not exercise_table.empty:
        print("\n--- Accuratezza per esercizio specifico ---")
        print(exercise_table.to_string())

    print("\n--- Statistiche dettagliate per failure_category ---")
    for metric_name, metric_table in failure_metric_tables.items():
        print(f"\n{metric_name}:")
        print_accuracy_extremes(metric_name, metric_table)

    print("\n--- Statistiche dettagliate per esercizio specifico ---")
    for metric_name, metric_table in exercise_metric_tables.items():
        print(f"\n{metric_name}:")
        print_accuracy_extremes(metric_name, metric_table)


def print_overall_conclusion_section(df_llm_all, model_label="LLM"):
    print("\n" + "=" * 80)
    print(f"CONCLUSIONI GLOBALI {model_label.upper()} - METRICHE DI ACCURATEZZA")
    print("=" * 80)
    print("\nMetriche calcolate:")
    print("  1. Valutazione Output: match tra llm_Output_Correct e correttezza reale dell'output")
    print("  2. Valutazione Codice: match tra llm_Code_Correct e correttezza reale del codice")
    print("  3. Diagnosi Output: quando llm_Output_Correct='NO' nei dynamic_failure, judge_Output_Correct='YES'")
    print("  4. Diagnosi Codice: quando llm_Code_Correct='NO' nei casi di codice scorretto, judge_Code_Correct='YES'")

    output_eval_summary = compute_llm_output_correct_accuracy(df_llm_all)
    code_eval_summary = compute_llm_code_correct_accuracy(df_llm_all)
    output_diag_summary = compute_output_diagnosis_accuracy(df_llm_all)
    code_diag_summary = compute_code_diagnosis_accuracy(df_llm_all)

    print("\n--- Metriche Globali Complessive ---")
    print_metric_summary_line(
        "1. LLM valuta correttamente se l'output e' corretto (media globale)",
        output_eval_summary,
    )
    print_metric_summary_line(
        "2. LLM valuta correttamente se il codice e' corretto (media globale)",
        code_eval_summary,
    )
    print_metric_summary_line(
        "3. Quando LLM rileva output errato, la diagnosi e' corretta (media globale)",
        output_diag_summary,
    )
    print_metric_summary_line(
        "4. Quando LLM rileva codice errato, la diagnosi e' corretta (media globale)",
        code_diag_summary,
    )

    df_llm_all["exercise_type"] = df_llm_all["exercise_number"].map(EXERCISE_TITLES)

    failure_table, failure_metric_tables = build_new_conclusion_tables(df_llm_all, "failure_category")
    if not failure_table.empty:
        print("\n--- Accuratezza globale per failure_category ---")
        print(failure_table.to_string())

    exercise_type_table, exercise_type_metric_tables = build_new_conclusion_tables(df_llm_all, "exercise_type")
    if not exercise_type_table.empty:
        print("\n--- Accuratezza globale per tipologia di esercitazione ---")
        print(exercise_type_table.to_string())

    print("\n--- Statistiche dettagliate globali per failure_category ---")
    for metric_name, metric_table in failure_metric_tables.items():
        print(f"\n{metric_name}:")
        print_accuracy_extremes(metric_name, metric_table)

    print("\n--- Statistiche dettagliate globali per tipologia di esercitazione ---")
    for metric_name, metric_table in exercise_type_metric_tables.items():
        print(f"\n{metric_name}:")
        print_accuracy_extremes(metric_name, metric_table)


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

    fig, ax = plt.subplots(figsize=(14.2, 7.6))
    failure_counts_all = df_all["failure_category"].value_counts().reindex(FAILURE_CATEGORIES, fill_value=0)
    print("\nConteggio per failure_category (tutti i commit):")
    print(failure_counts_all)

    colors = ["#d62728", "#ff7f0e", "#2ca02c", "#1f77b4", "#9467bd", "#8c564b", "#e377c2"]
    failure_counts_all.plot(kind="bar", ax=ax, color=colors)
    ax.yaxis.set_major_locator(MultipleLocator(50))
    ax.tick_params(axis="y", labelsize=14)
    ax.set_title(
        f"Distribuzione dei Casi per Categoria di Fallimento (Tutti i Commit) - {exercise_title}",
        fontsize=19,
        fontweight="bold",
        pad=12,
    )
    ax.set_ylabel("Numero di Casi", fontsize=16)
    ax.set_xlabel("Categoria di Fallimento", fontsize=16)
    ax.set_xticklabels(failure_counts_all.index, rotation=0, fontsize=13)
    ax.tick_params(axis="x", pad=10)
    fig.subplots_adjust(bottom=0.22, left=0.10, right=0.98, top=0.88)
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

    fig, ax = plt.subplots(figsize=(14.2, 7.6))
    failure_counts = df_llm["failure_category"].value_counts().reindex(FAILURE_CATEGORIES, fill_value=0)
    print("\nConteggio per failure_category:")
    print(failure_counts)

    colors = ["#d62728", "#ff7f0e", "#2ca02c", "#1f77b4", "#9467bd", "#8c564b", "#e377c2"]
    failure_counts.plot(kind="bar", ax=ax, color=colors)
    ax.yaxis.set_major_locator(MultipleLocator(50))
    ax.tick_params(axis="y", labelsize=14)
    ax.set_title(
        f"Distribuzione dei Casi per Categoria di Fallimento - {exercise_title}",
        fontsize=19,
        fontweight="bold",
        pad=12,
    )
    ax.set_ylabel("Numero di Casi", fontsize=16)
    ax.set_xlabel("Categoria di Fallimento", fontsize=16)
    ax.set_xticklabels(failure_counts.index, rotation=0, fontsize=13)
    ax.tick_params(axis="x", pad=10)
    fig.subplots_adjust(bottom=0.22, left=0.10, right=0.98, top=0.88)
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
        df_dynamic.loc[df_dynamic["llm_Output_Correct_bin"] == 1, "output_category"] = "Output Corretto"
        df_dynamic.loc[
            (df_dynamic["llm_Output_Correct_bin"] == 0)
            & (df_dynamic["judge_Output_Correct_bin"] == 0),
            "output_category",
        ] = "Output Scorretto (Diag. sbagliata)"
        df_dynamic.loc[
            (df_dynamic["llm_Output_Correct_bin"] == 0)
            & (df_dynamic["judge_Output_Correct_bin"] == 1),
            "output_category",
        ] = "Output Scorretto (Diag. giusta)"

        output_categories = [
            "Output Corretto",
            "Output Scorretto (Diag. sbagliata)",
            "Output Scorretto (Diag. giusta)",
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
        df_dynamic.loc[df_dynamic["llm_Code_Correct_bin"] == 1, "code_category"] = "Codice Corretto"
        df_dynamic.loc[
            (df_dynamic["llm_Code_Correct_bin"] == 0)
            & (df_dynamic["judge_Code_Correct_bin"] == 0),
            "code_category",
        ] = "Codice Scorretto (Diag. sbagliata)"
        df_dynamic.loc[
            (df_dynamic["llm_Code_Correct_bin"] == 0)
            & (df_dynamic["judge_Code_Correct_bin"] == 1),
            "code_category",
        ] = "Codice Scorretto (Diag. giusta)"

        code_categories = [
            "Codice Corretto",
            "Codice Scorretto (Diag. sbagliata)",
            "Codice Scorretto (Diag. giusta)",
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
        df_static.loc[df_static["llm_Output_Correct_bin"] == 1, "output_category_static"] = "Output Corretto"
        df_static.loc[df_static["llm_Output_Correct_bin"] == 0, "output_category_static"] = "Output Scorretto"

        output_categories_static = [
            "Output Corretto",
            "Output Scorretto",
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
        df_static.loc[df_static["llm_Code_Correct_bin"] == 1, "code_category_static"] = "Codice Corretto"
        df_static.loc[
            (df_static["llm_Code_Correct_bin"] == 0)
            & (df_static["judge_Code_Correct_bin"] == 0),
            "code_category_static",
        ] = "Codice Scorretto (Diag. sbagliata)"
        df_static.loc[
            (df_static["llm_Code_Correct_bin"] == 0)
            & (df_static["judge_Code_Correct_bin"] == 1),
            "code_category_static",
        ] = "Codice Scorretto (Diag. giusta)"

        code_categories_static = [
            "Codice Corretto",
            "Codice Scorretto (Diag. sbagliata)",
            "Codice Scorretto (Diag. giusta)",
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
        df_correct.loc[df_correct["llm_Output_Correct_bin"] == 1, "output_category_correct"] = "Output Corretto"
        df_correct.loc[df_correct["llm_Output_Correct_bin"] == 0, "output_category_correct"] = "Output Scorretto"

        output_categories_correct = [
            "Output Corretto",
            "Output Scorretto",
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
        df_correct.loc[df_correct["llm_Code_Correct_bin"] == 1, "code_category_correct"] = "Codice Corretto"
        df_correct.loc[df_correct["llm_Code_Correct_bin"] == 0, "code_category_correct"] = "Codice Scorretto"

        code_categories_correct = [
            "Codice Corretto",
            "Codice Scorretto",
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


def analyze_exercise(
    exercise_number: int,
    llm_json_file: Path,
    all_commits_json_file: Path,
    *,
    model_label: str,
    generate_plots: bool = True,
):
    exercise_title = EXERCISE_TITLES.get(exercise_number, f"Es.{exercise_number}")

    print("\n" + "#" * 80)
    print(f"ESERCITAZIONE {exercise_title} - {model_label}")
    print("#" * 80)

    df_llm = load_dataframe(llm_json_file, f"risultati LLM - {exercise_title}")
    df_all = load_dataframe(all_commits_json_file, f"risultati tutti i commit - {exercise_title}")

    prepare_llm_dataframe(df_llm)
    prepare_all_commits_dataframe(df_all)

    repo_stats = compute_repo_commit_stats(all_commits_json_file)
    json_stats = compute_json_commit_stats(df_all)

    print_global_stats(exercise_title, repo_stats, json_stats, df_llm, df_all)
    if generate_plots:
        plot_all_commits_distribution(df_all, exercise_title, exercise_number)
        plot_llm_failure_distribution(df_llm, exercise_title, exercise_number)
    print_conclusion_section(df_llm, exercise_title, model_label)
    if generate_plots:
        analyze_dynamic_failure(df_llm, exercise_title, exercise_number)
        analyze_static_failure(df_llm, exercise_title, exercise_number)
        analyze_correct_cases(df_llm, exercise_title, exercise_number)

    print("\n" + "=" * 80)
    print("RIEPILOGO FINALE")
    print("=" * 80)
    print(f"Esercitazione: {exercise_title}")
    print(f"Modello: {model_label}")
    print(f"File LLM usato: {llm_json_file.name}")
    print(f"File tutti i commit usato: {all_commits_json_file.name}")
    print(f"Totale valutazioni LLM: {len(df_llm)}")
    print(f"Totale record tutti i commit: {len(df_all)}")
    print("\nAnalisi completata!")
    return df_llm


def run_model_analysis(model_label, llm_candidates, *, generate_standard_plots, generate_aggregate_llm_plot):
    if generate_aggregate_llm_plot:
        print("\n" + "=" * 80)
        print(f"GRAFICO AGGREGATO {model_label.upper()}: TUTTE LE ESERCITAZIONI")
        print("=" * 80)
        plot_all_exercises_failure_distribution_llm()

    llm_map = build_candidate_map(llm_candidates)
    all_commits_map = build_candidate_map(ALL_COMMITS_JSON_CANDIDATES)
    exercise_numbers = sorted(set(llm_map) | set(all_commits_map))

    if not exercise_numbers:
        raise FileNotFoundError(f"Nessun file JSON trovato per il modello {model_label}")

    all_llm_frames = []
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

        analyzed_df = analyze_exercise(
            exercise_number,
            llm_json_file,
            all_commits_json_file,
            model_label=model_label,
            generate_plots=generate_standard_plots,
        )
        analyzed_df = analyzed_df.copy()
        analyzed_df["exercise_number"] = exercise_number
        analyzed_df["exercise_type"] = analyzed_df["exercise_number"].map(EXERCISE_TITLES)
        analyzed_df["model_label"] = model_label
        all_llm_frames.append(analyzed_df)

    if all_llm_frames:
        all_df = pd.concat(all_llm_frames, ignore_index=True)
        print_overall_conclusion_section(all_df, model_label)
        return all_df
    return pd.DataFrame()


def main():
    gpt4o_all = run_model_analysis(
        GPT4O_LABEL,
        LLM_JSON_CANDIDATES,
        generate_standard_plots=False,
        generate_aggregate_llm_plot=False,
    )
    gpt_oss_all = run_model_analysis(
        GPT_OSS_LABEL,
        GPT_OSS_JSON_CANDIDATES,
        generate_standard_plots=False,
        generate_aggregate_llm_plot=False,
    )

    if not gpt4o_all.empty and not gpt_oss_all.empty:
        print_model_comparison_section(gpt4o_all, gpt_oss_all)
        global_comparison = pd.concat(
            [
                build_model_comparison_rows(GPT4O_LABEL, gpt4o_all),
                build_model_comparison_rows(GPT_OSS_LABEL, gpt_oss_all),
            ],
            ignore_index=True,
        )
        plot_model_comparison_global(global_comparison, MODEL_COMPARISON_GLOBAL_PLOT_PATH)

        exercise_order = [EXERCISE_TITLES[index] for index in sorted(EXERCISE_TITLES)]
        exercise_comparison = pd.concat(
            [
                build_model_comparison_rows(GPT4O_LABEL, gpt4o_all, "exercise_type"),
                build_model_comparison_rows(GPT_OSS_LABEL, gpt_oss_all, "exercise_type"),
            ],
            ignore_index=True,
        )
        plot_model_comparison_grid(
            exercise_comparison,
            MODEL_COMPARISON_EXERCISE_PLOT_PATH,
            "Confronto gpt-4o vs gpt-oss per esercitazione",
            exercise_order,
            tick_rotation=0,
            spacing=2.2,
            extra_gaps={
                "Es.2 Monitor": 0.22,
                "Es.4 Messaggi": 0.50,
                "Es.5 Server Multithread": 0.25,
            },
            bottom_margin=0.14,
        )

        failure_order = {
            "output_eval": ["dynamic_failure", "static_failure", "correct"],
            "code_eval": ["crash", "timeout", "ipc_leak", "dynamic_failure", "static_failure", "correct"],
            "output_diag": ["dynamic_failure", "static_failure", "correct"],
            "code_diag": ["crash", "timeout", "ipc_leak", "dynamic_failure", "static_failure", "correct"],
        }
        failure_comparison = pd.concat(
            [
                build_model_comparison_rows(GPT4O_LABEL, gpt4o_all, "failure_category"),
                build_model_comparison_rows(GPT_OSS_LABEL, gpt_oss_all, "failure_category"),
            ],
            ignore_index=True,
        )
        plot_model_comparison_grid(
            failure_comparison,
            MODEL_COMPARISON_FAILURE_PLOT_PATH,
            "Confronto gpt-4o vs gpt-oss per categoria di fallimento",
            failure_order,
            tick_rotation=0,
            spacing=1.55,
            extra_gaps={
                "timeout": 0.20,
                "ipc_leak": 0.45,
                "dynamic_failure": 0.55,
                "static_failure": 0.50,
            },
            bottom_margin=0.14,
        )

if __name__ == "__main__":
    main()
