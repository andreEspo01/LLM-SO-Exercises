import json
import re
import shutil
import subprocess
from collections import Counter, defaultdict
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np


HOME = Path("/home/andre")
RULES_REPO = HOME / ".cache" / "tesi-static-rules" / "0xdea-semgrep-rules"
RULES_CONFIG = RULES_REPO / "rules" / "c"
README_PATH = RULES_REPO / "README.md"
OUTPUT_DIR = HOME / "analisi_0xdea_ground_truth"

RESULT_JSONS = {
    1: HOME / "risultati_es1_static_semgrep_0xdea.json",
    2: HOME / "risultati_es2_static_semgrep_0xdea.json",
    3: HOME / "risultati_es3_static_semgrep_0xdea.json",
    4: HOME / "risultati_es4_static_semgrep_0xdea.json",
    5: HOME / "risultati_es5_static_semgrep_0xdea.json",
}

ALL_COMMITS_JSONS = {
    1: HOME / "risultati_es1_tutti_commit_bash.json",
    2: HOME / "risultati_es2_tutti_commit_bash.json",
    3: HOME / "risultati_es3_tutti_commit_bash.json",
    4: HOME / "risultati_es4_tutti_commit_bash.json",
    5: HOME / "risultati_es5_tutti_commit_bash.json",
}

GROUND_TRUTH_DIRS = {
    1: HOME / "ground_truth_es1",
    2: HOME / "ground_truth_es2",
    3: HOME / "ground_truth_es3",
    4: HOME / "ground_truth_es4",
    5: HOME / "ground_truth_es5",
}

EXERCISE_TITLES = {
    1: "Es.1 Semafori",
    2: "Es.2 Monitor",
    3: "Es.3 Threads",
    4: "Es.4 Messaggi",
    5: "Es.5 Server Multithread",
}

CATEGORY_COLORS = {
    "buffer overflows": "#c0392b",
    "integer overflows": "#d35400",
    "format strings": "#f39c12",
    "memory management": "#2980b9",
    "command injection": "#16a085",
    "race conditions": "#8e44ad",
    "privilege management": "#2c3e50",
    "denial of service": "#7f8c8d",
    "miscellaneous": "#27ae60",
}


def run_command(cmd, check=True):
    completed = subprocess.run(cmd, capture_output=True, text=True)
    if check and completed.returncode != 0:
        raise RuntimeError(
            f"Command failed ({completed.returncode}): {' '.join(str(part) for part in cmd)}\n"
            f"STDOUT:\n{completed.stdout}\nSTDERR:\n{completed.stderr}"
        )
    return completed


def ensure_rules_repo():
    if RULES_CONFIG.exists() and README_PATH.exists():
        return
    if shutil.which("git") is None:
        raise RuntimeError("git non disponibile, impossibile scaricare le regole 0xdea")
    RULES_REPO.parent.mkdir(parents=True, exist_ok=True)
    if RULES_REPO.exists():
        run_command(["rm", "-rf", str(RULES_REPO)])
    run_command(
        [
            "git",
            "clone",
            "--depth",
            "1",
            "--branch",
            "main",
            "https://github.com/0xdea/semgrep-rules.git",
            str(RULES_REPO),
        ]
    )


def parse_rule_categories():
    text = README_PATH.read_text(encoding="utf-8")
    category_map = {}
    current_category = None
    in_rules_section = False
    in_c_cpp = False

    for raw_line in text.splitlines():
        line = raw_line.strip()
        if line == "## Rules":
            in_rules_section = True
            continue
        if in_rules_section and line.startswith("## ") and line != "## Rules":
            break
        if not in_rules_section:
            continue
        if line == "### C/C++":
            in_c_cpp = True
            continue
        if line.startswith("### ") and line != "### C/C++":
            in_c_cpp = False
            current_category = None
            continue
        if not in_c_cpp:
            continue
        category_match = re.match(r"^####\s+(.+)$", line)
        if category_match:
            current_category = category_match.group(1).strip().lower()
            continue
        rule_match = re.match(r"^\*\s+\[\*\*([a-z0-9-]+)\*\*\]\(", line)
        if current_category and rule_match:
            rule_name = f"raptor-{rule_match.group(1)}"
            category_map[rule_name] = current_category

    if not category_map:
        raise RuntimeError("Impossibile costruire la mappa regola -> categoria dal README 0xdea")
    return category_map


def load_records(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


def record_key(record):
    return (
        record.get("student"),
        record.get("exercise"),
        record.get("commit_analyzed"),
    )


def collect_source_dirs(base_dir: Path):
    return [
        path for path in sorted(base_dir.iterdir())
        if path.is_dir() and not path.name.startswith(".") and path.name != "__pycache__"
    ]


def run_semgrep_on_solution(solution_dir: Path):
    completed = run_command(
        [
            "semgrep",
            "--json",
            "--quiet",
            "--error",
            "--metrics=off",
            "--no-git-ignore",
            "--config",
            str(RULES_CONFIG),
            str(solution_dir),
        ],
        check=False,
    )
    if completed.returncode not in {0, 1}:
        raise RuntimeError(
            f"Semgrep failed on {solution_dir}\nSTDOUT:\n{completed.stdout}\nSTDERR:\n{completed.stderr}"
        )
    payload = json.loads(completed.stdout or "{}")
    warnings = []
    for result in payload.get("results", []):
        result_path = Path(result.get("path", ""))
        try:
            relative_path = str(result_path.relative_to(solution_dir))
        except ValueError:
            relative_path = str(result_path)
        warnings.append(
            {
                "rule_id": result.get("check_id", "<unknown>"),
                "file": relative_path,
                "line": result.get("start", {}).get("line", 0),
                "message": result.get("extra", {}).get("message", ""),
                "severity": result.get("extra", {}).get("severity", ""),
            }
        )
    return warnings


def count_rules(warnings):
    return Counter(warning.get("rule_id", "<unknown>") for warning in warnings)


def counts_by_category(rule_counter, category_map):
    category_counter = Counter()
    for rule_id, count in rule_counter.items():
        category = category_map.get(rule_id, "miscellaneous")
        category_counter[category] += count
    return category_counter


def build_solution_baseline(category_map):
    solution_rule_counts = {}
    solution_category_counts = {}

    for exercise_number, ground_truth_dir in GROUND_TRUTH_DIRS.items():
        for solution_dir in collect_source_dirs(ground_truth_dir):
            warnings = run_semgrep_on_solution(solution_dir)
            rule_counter = count_rules(warnings)
            solution_rule_counts[(exercise_number, solution_dir.name)] = rule_counter
            solution_category_counts[(exercise_number, solution_dir.name)] = counts_by_category(
                rule_counter,
                category_map,
            )
    return solution_rule_counts, solution_category_counts


def subtract_rule_counts(student_counter, solution_counter):
    positive_diff = {}
    for rule_id in sorted(set(student_counter) | set(solution_counter)):
        diff = student_counter.get(rule_id, 0) - solution_counter.get(rule_id, 0)
        positive_diff[rule_id] = max(diff, 0)
    return positive_diff


def subtract_category_counts(student_counter, solution_counter):
    positive_diff = {}
    for category in sorted(set(student_counter) | set(solution_counter)):
        diff = student_counter.get(category, 0) - solution_counter.get(category, 0)
        positive_diff[category] = max(diff, 0)
    return positive_diff


def analyze_exercise(exercise_number, category_map, solution_rule_counts, solution_category_counts):
    result_path = RESULT_JSONS[exercise_number]
    records = load_records(result_path)
    detailed_records = []
    category_commit_counter = Counter()

    for record in records:
        record_key = (exercise_number, record["exercise"])
        solution_rule_counter = solution_rule_counts.get(record_key, Counter())
        solution_category_counter = solution_category_counts.get(record_key, Counter())

        student_rule_counter = count_rules(record.get("static_warnings", []))
        student_category_counter = counts_by_category(student_rule_counter, category_map)

        rule_diff = subtract_rule_counts(student_rule_counter, solution_rule_counter)
        category_diff = subtract_category_counts(student_category_counter, solution_category_counter)
        positive_categories = sorted([
            category for category, count in category_diff.items() if count > 0
        ])

        for category in positive_categories:
            category_commit_counter[category] += 1

        detailed_records.append(
            {
                "student": record.get("student"),
                "exercise": record.get("exercise"),
                "commit_analyzed": record.get("commit_analyzed"),
                "failure_category": record.get("failure_category"),
                "analysis_status": record.get("analysis_status"),
                "student_rule_counts": dict(student_rule_counter),
                "solution_rule_counts": dict(solution_rule_counter),
                "positive_rule_diff": rule_diff,
                "student_category_counts": dict(student_category_counter),
                "solution_category_counts": dict(solution_category_counter),
                "positive_category_diff": category_diff,
                "categories_with_positive_diff": positive_categories,
            }
        )

    return detailed_records, category_commit_counter, len(records)


def write_json(path: Path, payload):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def write_csv(path: Path, rows, fieldnames):
    path.parent.mkdir(parents=True, exist_ok=True)
    import csv

    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def build_summary_rows(all_counts, categories):
    rows = []
    for exercise_number in sorted(all_counts):
        row = {
            "exercise_number": exercise_number,
            "exercise_title": EXERCISE_TITLES[exercise_number],
        }
        for category in categories:
            row[category] = int(all_counts[exercise_number].get(category, 0))
        rows.append(row)
    return rows


def build_percentage_rows(all_counts, total_commits_by_exercise, categories):
    rows = []
    for exercise_number in sorted(all_counts):
        total_commits = total_commits_by_exercise.get(exercise_number, 0)
        row = {
            "exercise_number": exercise_number,
            "exercise_title": EXERCISE_TITLES[exercise_number],
            "total_commits_analyzed": total_commits,
        }
        for category in categories:
            count = all_counts[exercise_number].get(category, 0)
            row[category] = (count / total_commits * 100.0) if total_commits else 0.0
        rows.append(row)
    return rows


def build_normalized_percentage_rows(all_counts, categories):
    rows = []
    for exercise_number in sorted(all_counts):
        total_category_hits = sum(all_counts[exercise_number].get(category, 0) for category in categories)
        row = {
            "exercise_number": exercise_number,
            "exercise_title": EXERCISE_TITLES[exercise_number],
            "total_category_hits": total_category_hits,
        }
        for category in categories:
            count = all_counts[exercise_number].get(category, 0)
            row[category] = (count / total_category_hits * 100.0) if total_category_hits else 0.0
        rows.append(row)
    return rows


def filter_summary_rows(summary_rows, categories):
    filtered_rows = []
    for row in summary_rows:
        new_row = {
            "exercise_number": row["exercise_number"],
            "exercise_title": row["exercise_title"],
        }
        if "total_commits_analyzed" in row:
            new_row["total_commits_analyzed"] = row["total_commits_analyzed"]
        for category in categories:
            new_row[category] = row.get(category, 0)
        filtered_rows.append(new_row)
    return filtered_rows


def plot_grouped_bars(summary_rows, categories, title, output_name, ylabel, annotate_percent=False):
    exercise_labels = [row["exercise_title"] for row in summary_rows]
    x = np.arange(len(summary_rows))
    if not categories:
        raise ValueError("Nessuna categoria disponibile per il grafico")

    width = min(0.8 / len(categories), 0.22)

    fig, ax = plt.subplots(figsize=(18, 8.5))

    for index, category in enumerate(categories):
        offsets = x + (index - (len(categories) - 1) / 2) * width
        values = [row.get(category, 0) for row in summary_rows]
        color = CATEGORY_COLORS.get(category, None)
        bars = ax.bar(offsets, values, width=width, label=category.title(), color=color)
        if annotate_percent:
            for bar, value in zip(bars, values):
                if value <= 0:
                    continue
                ax.text(
                    bar.get_x() + bar.get_width() / 2,
                    bar.get_height(),
                    f"{value:.1f}%",
                    ha="center",
                    va="bottom",
                    fontsize=8,
                    rotation=0,
                )

    ax.set_title(title, fontsize=14, fontweight="bold")
    ax.set_ylabel(ylabel, fontsize=12)
    ax.set_xticks(x)
    ax.set_xticklabels(exercise_labels, rotation=15, ha="right")
    ax.grid(axis="y", alpha=0.3)
    ax.set_axisbelow(True)
    if annotate_percent:
        ax.margins(y=0.16)
    ax.legend(
        loc="upper center",
        bbox_to_anchor=(0.5, -0.16),
        fontsize=9,
        ncol=min(4, len(categories)),
        frameon=False,
    )
    fig.subplots_adjust(bottom=0.28, right=0.98, top=0.9)

    output_path = OUTPUT_DIR / output_name
    fig.savefig(output_path, dpi=300, bbox_inches="tight")
    plt.close(fig)
    return output_path


def build_overlap_rows(all_commits_records_by_exercise, semgrep_detailed_records_by_exercise):
    rows = []

    for exercise_number in sorted(all_commits_records_by_exercise):
        all_records = all_commits_records_by_exercise[exercise_number]
        semgrep_map = {
            record_key(record): record
            for record in semgrep_detailed_records_by_exercise[exercise_number]
        }

        target_records = [
            record for record in all_records
            if record.get("failure_category") in {"correct", "static_failure"}
        ]
        total_target = len(target_records)
        counts = Counter()

        for record in target_records:
            key = record_key(record)
            semgrep_record = semgrep_map.get(key, {})
            semgrep_flagged = bool(semgrep_record.get("categories_with_positive_diff"))
            custom_flagged = bool(record.get("static_warnings"))

            if semgrep_flagged and custom_flagged:
                counts["both"] += 1
            elif semgrep_flagged:
                counts["semgrep_only"] += 1
            elif custom_flagged:
                counts["custom_only"] += 1
            else:
                counts["neither"] += 1

        rows.append(
            {
                "exercise_number": exercise_number,
                "exercise_title": EXERCISE_TITLES[exercise_number],
                "total_correct_plus_static_failure": total_target,
                "semgrep_only_count": counts["semgrep_only"],
                "custom_only_count": counts["custom_only"],
                "both_count": counts["both"],
                "neither_count": counts["neither"],
                "semgrep_only_pct": (counts["semgrep_only"] / total_target * 100.0) if total_target else 0.0,
                "custom_only_pct": (counts["custom_only"] / total_target * 100.0) if total_target else 0.0,
                "both_pct": (counts["both"] / total_target * 100.0) if total_target else 0.0,
                "neither_pct": (counts["neither"] / total_target * 100.0) if total_target else 0.0,
            }
        )

    return rows


def plot_overlap_percentages(overlap_rows, output_name):
    categories = [
        ("semgrep_only_pct", "Solo Semgrep", "#d35400"),
        ("custom_only_pct", "Solo Regole Custom", "#2980b9"),
        ("both_pct", "Entrambi", "#16a085"),
        ("neither_pct", "Nessuno dei due", "#7f8c8d"),
    ]
    exercise_labels = [row["exercise_title"] for row in overlap_rows]
    x = np.arange(len(overlap_rows))
    width = 0.18

    fig, ax = plt.subplots(figsize=(16, 8.0))

    for index, (field, label, color) in enumerate(categories):
        offsets = x + (index - (len(categories) - 1) / 2) * width
        values = [row[field] for row in overlap_rows]
        bars = ax.bar(offsets, values, width=width, label=label, color=color)
        for bar, value in zip(bars, values):
            if value <= 0:
                continue
            ax.text(
                bar.get_x() + bar.get_width() / 2,
                bar.get_height(),
                f"{value:.1f}%",
                ha="center",
                va="bottom",
                fontsize=9,
            )

    ax.set_title(
        "Sovrapposizione tra Semgrep e Regole Custom su commit Correct + Static Failure",
        fontsize=14,
        fontweight="bold",
    )
    ax.set_ylabel("Percentuale sul totale dei commit Correct + Static Failure", fontsize=12)
    ax.set_xticks(x)
    ax.set_xticklabels(exercise_labels, rotation=15, ha="right")
    ax.grid(axis="y", alpha=0.3)
    ax.set_axisbelow(True)
    ax.margins(y=0.16)
    ax.legend(
        loc="upper center",
        bbox_to_anchor=(0.5, -0.14),
        fontsize=10,
        ncol=4,
        frameon=False,
    )
    fig.subplots_adjust(bottom=0.24, right=0.98, top=0.9)

    output_path = OUTPUT_DIR / output_name
    fig.savefig(output_path, dpi=300, bbox_inches="tight")
    plt.close(fig)
    return output_path


def main():
    ensure_rules_repo()
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    category_map = parse_rule_categories()
    categories = sorted(
        set(category_map.values()),
        key=lambda value: (
            0 if value in CATEGORY_COLORS else 1,
            list(CATEGORY_COLORS).index(value) if value in CATEGORY_COLORS else value,
        ),
    )
    solution_rule_counts, solution_category_counts = build_solution_baseline(category_map)

    all_counts = {}
    total_commits_by_exercise = {}
    semgrep_detailed_records_by_exercise = {}
    all_commits_records_by_exercise = {
        exercise_number: load_records(ALL_COMMITS_JSONS[exercise_number])
        for exercise_number in sorted(ALL_COMMITS_JSONS)
    }
    for exercise_number in sorted(RESULT_JSONS):
        detailed_records, category_commit_counter, total_commits = analyze_exercise(
            exercise_number,
            category_map,
            solution_rule_counts,
            solution_category_counts,
        )
        all_counts[exercise_number] = category_commit_counter
        total_commits_by_exercise[exercise_number] = total_commits
        semgrep_detailed_records_by_exercise[exercise_number] = detailed_records
        write_json(
            OUTPUT_DIR / f"risultati_es{exercise_number}_0xdea_ground_truth_diff.json",
            detailed_records,
        )

    summary_rows = build_summary_rows(all_counts, categories)
    write_csv(
        OUTPUT_DIR / "riepilogo_commit_con_diff_positivo_per_categoria.csv",
        summary_rows,
        ["exercise_number", "exercise_title"] + categories,
    )
    chart_path = plot_grouped_bars(
        summary_rows,
        categories,
        "Commit con warning 0xdea oltre la soluzione di riferimento",
        "grafico_0xdea_commit_oltre_ground_truth.pdf",
        "Numero di commit con differenza > 0",
    )

    percentage_summary_rows = build_percentage_rows(all_counts, total_commits_by_exercise, categories)
    write_csv(
        OUTPUT_DIR / "riepilogo_commit_con_diff_positivo_per_categoria_percentuale.csv",
        percentage_summary_rows,
        ["exercise_number", "exercise_title", "total_commits_analyzed"] + categories,
    )
    percentage_chart_path = plot_grouped_bars(
        percentage_summary_rows,
        categories,
        "Commit con warning 0xdea oltre la soluzione di riferimento (%)",
        "grafico_0xdea_commit_oltre_ground_truth_percentuale.pdf",
        "Percentuale sul totale dei commit analizzati",
        annotate_percent=True,
    )

    normalized_percentage_summary_rows = build_normalized_percentage_rows(all_counts, categories)
    write_csv(
        OUTPUT_DIR / "riepilogo_commit_con_diff_positivo_per_categoria_percentuale_normalizzata.csv",
        normalized_percentage_summary_rows,
        ["exercise_number", "exercise_title", "total_category_hits"] + categories,
    )
    normalized_percentage_chart_path = plot_grouped_bars(
        normalized_percentage_summary_rows,
        categories,
        "Distribuzione normalizzata delle categorie 0xdea oltre la soluzione (%)",
        "grafico_0xdea_commit_oltre_ground_truth_percentuale_normalizzata.pdf",
        "Percentuale normalizzata sul totale delle occorrenze di categoria",
        annotate_percent=True,
    )

    overlap_rows = build_overlap_rows(all_commits_records_by_exercise, semgrep_detailed_records_by_exercise)
    write_csv(
        OUTPUT_DIR / "riepilogo_overlap_semgrep_vs_custom_correct_static_failure.csv",
        overlap_rows,
        [
            "exercise_number",
            "exercise_title",
            "total_correct_plus_static_failure",
            "semgrep_only_count",
            "custom_only_count",
            "both_count",
            "neither_count",
            "semgrep_only_pct",
            "custom_only_pct",
            "both_pct",
            "neither_pct",
        ],
    )
    overlap_chart_path = plot_overlap_percentages(
        overlap_rows,
        "grafico_overlap_semgrep_vs_custom_correct_static_failure_percentuale.pdf",
    )
    write_json(
        OUTPUT_DIR / "meta_analisi_0xdea_ground_truth.json",
        {
            "rules_repo": str(RULES_REPO),
            "rules_config": str(RULES_CONFIG),
            "output_dir": str(OUTPUT_DIR),
            "chart_path": str(chart_path),
            "percentage_chart_path": str(percentage_chart_path),
            "normalized_percentage_chart_path": str(normalized_percentage_chart_path),
            "overlap_chart_path": str(overlap_chart_path),
            "categories": categories,
        },
    )

    print("Analisi completata.")
    print(f"Output directory: {OUTPUT_DIR}")
    print(f"Grafico: {chart_path}")
    print(f"Grafico percentuale: {percentage_chart_path}")
    print(f"Grafico percentuale normalizzato: {normalized_percentage_chart_path}")
    print(f"Grafico overlap: {overlap_chart_path}")


if __name__ == "__main__":
    main()
