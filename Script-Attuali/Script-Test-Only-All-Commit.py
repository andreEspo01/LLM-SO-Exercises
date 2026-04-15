#!/usr/bin/env python3
"""
Script per analisi SOLO compilazione, test e statica su TUTTI i commit di ogni studente.
Nessuna analisi LLM, risultati JSON puliti.
"""

import os
import subprocess
import json
import re
import shutil
import tempfile
from pathlib import Path
from datetime import datetime

# ================= CONFIG =================

BASE_SUBMISSIONS_DIR = "/home/andre/esercitazione-5-server-multithread-submissions"
GROUND_TRUTH_DIR = "/home/andre/ground_truth_es5"

COMPILE_TIMEOUT = 120
TEST_TIMEOUT = 120

OUTPUT_FILE = "risultati_es5_tutti_commit.json"
LOG_SAMPLE_DIR = "experiment_logs"

MAX_STUDENTS = None  # TEST: Controlla warnings

# ==========================================

def log(msg):
    print(f"[{datetime.now().strftime('%H:%M:%S')}] {msg}")

# ================= COMPILAZIONE =================

def compile_exercise(path):
    path = Path(path)  # Assicura che sia un Path
    try:
        subprocess.run(["make", "clean"], cwd=path, stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=COMPILE_TIMEOUT)
    except:
        pass

    try:
        for obj_file in path.rglob("*.o"):
            obj_file.unlink()
    except:
        pass

    try:
        result = subprocess.run(
            ["make"],
            cwd=path,
            capture_output=True,
            text=True,
            timeout=COMPILE_TIMEOUT
        )
        return result.returncode == 0, result.stdout + result.stderr
    except:
        return False, "Compilation timeout or error"

# ================= INJECTION TESTS =================

BASE_TESTS_DIR = Path("/home/andre/so_esercitazione_5_messaggi_threads")

def inject_tests(student_dir, exercise_dir):
    exercise_dir = Path(exercise_dir)  # Assicura che sia un Path
    student_dir = Path(student_dir)    # Assicura che sia un Path
    specific_src = BASE_TESTS_DIR / exercise_dir.name / ".test"
    exercise_test_dir = exercise_dir / ".test"

    if exercise_test_dir.exists():
        shutil.rmtree(exercise_test_dir)

    if specific_src.exists():
        shutil.copytree(specific_src, exercise_test_dir)

# ================= TEST DINAMICI =================

def extract_shell_assignment(script_path: Path, variable_name: str, default: str = ""):
    try:
        content = script_path.read_text(encoding="utf-8")
    except Exception:
        return default

    match = re.search(rf"(?m)^\s*{re.escape(variable_name)}=(.+?)\s*$", content)
    if not match:
        return default

    value = match.group(1).strip()
    if len(value) >= 2 and value[0] == value[-1] and value[0] in {"'", '"'}:
        return value[1:-1]

    return value or default


def run_all_tests(path):
    path = Path(path)  # Assicura che sia un Path
    test_dir = path / ".test"
    if not test_dir.exists():
        return []

    valid_scripts = {
        p.name for p in (BASE_TESTS_DIR / path.name / ".test").glob("*.sh")
    } if (BASE_TESTS_DIR / path.name / ".test").exists() else set()

    scripts = sorted([s for s in test_dir.glob("*.sh") if s.name in valid_scripts])
    if not scripts:
        return []

    feedback_file = Path("/tmp/feedback.md")
    all_results = []

    for script in sorted(scripts):
        # Estrai le variabili OUTPUT e ERROR_LOG dallo script
        output_file = extract_shell_assignment(script, "OUTPUT", "/tmp/output.txt")
        error_log = extract_shell_assignment(script, "ERROR_LOG", "/tmp/error-log.txt")

        # Pulizia file temporanei
        for f in {str(feedback_file), output_file, error_log, "/tmp/output.txt", "/tmp/minimo.txt"}:
            if Path(f).exists():
                try:
                    Path(f).unlink()
                except:
                    pass

        try:
            result = subprocess.run(
                ["bash", str(script.resolve())],
                cwd=str(test_dir),  # Esegui dalla cartella .test in modo che i path relativi funzionino
                capture_output=True,
                text=True,
                timeout=TEST_TIMEOUT
            )
            script_out = result.stdout
            script_err = result.stderr

            # Determina pass/fail basandosi sullo script output
            lower_out = script_out.lower()
            explicit_pass = re.search(r"(?m)^\s*pass\s*$", lower_out) is not None
            ok = result.returncode == 0 and explicit_pass and "fail" not in lower_out

            # Legge l'output prodotto dal programma
            program_output = ""
            output_file_path = Path(output_file)
            if output_file_path.exists():
                try:
                    program_output = output_file_path.read_text(errors="ignore").strip()
                except Exception as e:
                    pass
            
            # Se il file non esiste, tenta di leggere dal stdout dello script se contiene output
            if not program_output:
                script_content = script.read_text(encoding="utf-8", errors="ignore")
                if "compile_and_run" in script_content:
                    # Se è uno script compile_and_run e il file non esiste, prendi lo stdout escludendo pass/fail
                    if script_out and script_out.lower() not in {"pass", "pass\n", "fail", "fail\n"}:
                        program_output = script_out.replace("\npass", "").replace("\nfail", "").strip()
            
            if not program_output:
                program_output = "The program produced no output."

            # Legge feedback scritto dallo script
            feedback_text = ""
            if feedback_file.exists():
                try:
                    feedback_text = Path(feedback_file).read_text(encoding="utf-8")
                except:
                    pass

            all_results.append({
                "script": script.name,
                "ok": ok,
                "script_out": script_out,
                "script_err": script_err,
                "program_output": program_output,
                "feedback": feedback_text,
            })
        except subprocess.TimeoutExpired:
            all_results.append({
                "script": script.name,
                "ok": False,
                "script_out": "",
                "script_err": "Test timeout",
                "program_output": "The program produced no output.",
                "feedback": "Timeout",
            })
        except Exception as e:
            all_results.append({
                "script": script.name,
                "ok": False,
                "script_out": "",
                "script_err": str(e),
                "program_output": "The program produced no output.",
                "feedback": "",
            })

    return all_results


def run_tests_compat(path):
    path = Path(path)  # Assicura che sia un Path
    all_results = run_all_tests(path)

    if not all_results:
        return False, "fail\n", "", "", "", ""

    exercise_dir_name = path.name
    feedback_name_mapping = {
        "remote_procedure_call": "Esercizio remote procedure call",
        "server_aggregatore_thread": "Esercizio server aggregatore con thread",
        "un_primo_esempio_di_server_multithread": "Esercizio primo esempio di server multithread",
    }
    exercise_feedback_name = feedback_name_mapping.get(exercise_dir_name, f"Esercizio {exercise_dir_name.replace('_', ' ')}")

    def remove_script_names(text):
        return re.sub(r"\[[\w\-_.]+\.sh\]\s*", "", text)

    def filter_feedback_by_exercise(feedback_text, feedback_name):
        if not feedback_text:
            return ""
        lines = feedback_text.split("\n")
        start_idx = None
        for i, line in enumerate(lines):
            if feedback_name in line:
                start_idx = i
                break
        if start_idx is None:
            return feedback_text
        return "\n".join(lines[start_idx:])

    if len(all_results) == 1:
        r = all_results[0]
        return r["ok"], r["script_out"], r["script_err"], r["program_output"], filter_feedback_by_exercise(r["feedback"], exercise_feedback_name)

    all_ok = all(r["ok"] for r in all_results)
    all_stdout = "".join(r["script_out"] for r in all_results if r["script_out"])
    all_stderr = "".join(r["script_err"] for r in all_results if r["script_err"])
    all_program_output = "".join(r["program_output"] for r in all_results if r["program_output"])
    all_feedback = "".join(r["feedback"] for r in all_results if r["feedback"])

    all_stdout = remove_script_names(all_stdout)
    all_stderr = remove_script_names(all_stderr)
    all_program_output = remove_script_names(all_program_output)
    all_feedback = remove_script_names(all_feedback)
    all_feedback = filter_feedback_by_exercise(all_feedback, exercise_feedback_name)

    return all_ok, all_stdout, all_stderr, all_program_output, all_feedback

# ================= STATIC ANALYSIS =================

def run_static_analysis(exercise_path: str):
    """
    Esegue Semgrep sui file .c corrispondenti ai file .yml nella cartella .test.
    Restituisce warnings strutturati {'file', 'line', 'message'} con nome file originale.
    """
    exercise_path = Path(exercise_path)
    test_dir = exercise_path / ".test"

    if not test_dir.exists():
        return []

    warnings = []

    # Prendi tutti i .yml nella cartella .test
    yml_files = sorted(test_dir.glob("*.yml"))
    if not yml_files:
        return []

    for yml_file in yml_files:
        c_file = exercise_path / (yml_file.stem + ".c")
        if not c_file.exists():
            continue  # Ignora se il .c non esiste

        # Preprocessa il file
        preprocessed = exercise_path / (c_file.stem + ".preprocessed.c")
        try:
            subprocess.run(["cp", str(c_file), str(preprocessed)], check=True, capture_output=True)
        except:
            continue

        # Esegui preprocessor.pl se esiste
        preprocessor = test_dir / "preprocessor.pl"
        if preprocessor.exists():
            try:
                subprocess.run(["perl", str(preprocessor), str(preprocessed)], check=True, capture_output=True)
            except:
                pass

        # Esegui Semgrep sul file preprocessato
        try:
            res = subprocess.run(
                ["semgrep", "--json", "--config", str(yml_file), str(preprocessed)],
                cwd=str(exercise_path),
                capture_output=True,
                text=True,
                timeout=30
            )
            if res.returncode in [0, 1]:  # 0=success, 1=findings
                try:
                    data = json.loads(res.stdout)
                    for r in data.get("results", []):
                        warnings.append({
                            "file": c_file.name,
                            "line": r.get("start", {}).get("line", 0),
                            "message": r.get("extra", {}).get("message", "")
                        })
                except json.JSONDecodeError:
                    pass
        except Exception:
            pass
        finally:
            if preprocessed.exists():
                try:
                    preprocessed.unlink()
                except:
                    pass

    return warnings

# ================= GIT FUNCTIONS =================

def get_commits(repo_path):
    """Restituisce i commit del branch main in ordine reverse cronologico (più vecchio per primo)"""
    try:
        result = subprocess.run(
            ["git", "rev-list", "main"],  # Solo il branch main (quello che vedi su GitHub)
            cwd=repo_path,
            capture_output=True,
            text=True
        )
        commits = [c.strip() for c in result.stdout.strip().split("\n") if c.strip()]
        # Inverti per avere il più vecchio per primo
        return list(reversed(commits))
    except:
        return []

def checkout_commit(repo_path, commit_hash):
    subprocess.run(
        ["git", "checkout", "-q", commit_hash, "--"],
        cwd=repo_path,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL
    )

def checkout_head(repo_path):
    subprocess.run(
        ["git", "checkout", "-q", "HEAD", "--"],
        cwd=repo_path,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL
    )

# ================= CLASSIFICAZIONE ERRORI =================

def classify_failure_category(feedback_text):
    if not feedback_text:
        return "dynamic_failure"

    text = feedback_text.lower()
    mapping = {
        "l'esecuzione del programma è andata in crash": "crash",
        "l'esecuzione del programma è andata in timeout": "timeout",
        "è necessario deallocare le risorse ipc": "ipc_leak",
        "non è stato possibile compilare il programma": "compile_failure",
        "terminata con codice di ritorno non-nullo": "dynamic_failure",
        "l'esecuzione non è corretta": "dynamic_failure",
        "anche se il programma esegue, sono stati riscontrati i seguenti difetti all'interno del codice": "static_failure",
        "congratulazioni, l'esercizio compila ed esegue correttamente": "correct",
    }

    for msg, category in mapping.items():
        if msg in text:
            return category

    return "dynamic_failure"

# ================= PULIZIA FEEDBACK =================

def clean_feedback_for_json(feedback_text):
    if not feedback_text:
        return ""
    # rimuove emoji shortcode
    feedback_text = re.sub(r":[a-z_]+:", "", feedback_text)
    # sostituisce \n multipli con uno solo
    feedback_text = re.sub(r"\n+", "\n", feedback_text)
    # rimuove spazi iniziali/finali
    return feedback_text.strip()

# ================= SALVATAGGIO =================

def load_existing_results():
    if Path(OUTPUT_FILE).exists():
        try:
            with open(OUTPUT_FILE, "r") as f:
                return json.load(f)
        except:
            return []
    return []

def save_results(results):
    tmp_file = OUTPUT_FILE + ".tmp"
    with open(tmp_file, "w") as f:
        json.dump(results, f, indent=4)
    os.replace(tmp_file, OUTPUT_FILE)

# ================= MAIN =================

def extract_student_name(folder_name):
    prefix = "esercitazione-5-server-multithread-"
    if folder_name.startswith(prefix):
        return folder_name[len(prefix):]
    return folder_name

def main():
    log("=" * 60)
    log("SCRIPT: Compile Only (NO LLM)")
    log("=" * 60)

    base = Path(BASE_SUBMISSIONS_DIR)
    results = load_existing_results()
    already_done = {(r["student"], r["exercise"], r["commit_analyzed"]) for r in results}

    student_dirs = sorted(
        [d for d in base.iterdir() if d.is_dir()],
        key=lambda x: extract_student_name(x.name).lower()
    )

    if MAX_STUDENTS:
        student_dirs = student_dirs[:MAX_STUDENTS]

    total_students = len(student_dirs)

    for i, student_dir in enumerate(student_dirs, start=1):
        student_name = extract_student_name(student_dir.name)
        log(f"[{i}/{total_students}] STUDENTE: {student_name}")

        valid_exercises = {
            d.name for d in BASE_TESTS_DIR.iterdir()
            if d.is_dir() and not d.name.startswith(".")
        }

        exercise_dirs = sorted([
            d for d in student_dir.iterdir()
            if d.is_dir() and d.name in valid_exercises
        ])

        total_ex = len(exercise_dirs)

        for j, exercise_dir in enumerate(exercise_dirs, start=1):
            log(f"    ({j}/{total_ex}) Esercizio: {exercise_dir.name}")

            commits = get_commits(student_dir)
            if not commits:
                commits = ["HEAD"]

            # ===== ANALIZZARE TUTTI I COMMIT =====
            for commit_idx, commit in enumerate(commits, start=1):
                log(f"         Commit {commit_idx}/{len(commits)}: {commit[:8]}...")

                if (student_name, exercise_dir.name, commit) in already_done:
                    log(f"         (GIÀ ANALIZZATO)")
                    continue

                try:
                    # Checkout del commit nel repo reale dello studente
                    if commit == "HEAD":
                        checkout_head(student_dir)
                    else:
                        checkout_commit(student_dir, commit)

                    # Copia i test personalizzati
                    inject_tests(student_dir, exercise_dir)

                    # Compilazione
                    log(f"           → Compilazione...")
                    compile_ok, compile_log = compile_exercise(exercise_dir)
                    log(f"           → Compilazione: {'✓ OK' if compile_ok else '✗ FAIL'}")

                    # Test
                    log(f"           → Test esecuzione...")
                    test_ok, stdout, stderr, program_out, feedback_text = run_tests_compat(exercise_dir)
                    log(f"           → Test: {'✓ PASS' if test_ok else '✗ FAIL'}")

                    # Static analysis
                    log(f"           → Analisi statica...")
                    warnings = run_static_analysis(exercise_dir)
                    log(f"           → Avvisi: {len(warnings) if warnings else 0}")

                    # Classificazione fallimento
                    if test_ok and warnings:
                        failure = "static_failure"
                    else:
                        failure = classify_failure_category(feedback_text)

                    # Salva risultato
                    result = {
                        "student": student_name,
                        "exercise": exercise_dir.name,
                        "commit_analyzed": commit,
                        "failure_category": failure,
                        "compile_success": compile_ok,
                        "test_success": test_ok,
                        "stdout": stdout,
                        "stderr": stderr,
                        "test_feedback": clean_feedback_for_json(feedback_text),  # Pulizia feedback
                        "program_output": program_out,
                        "static_warnings": warnings,
                    }

                    results.append(result)
                    already_done.add((student_name, exercise_dir.name, commit))
                    save_results(results)
                    log(f"           → Salvato")

                except Exception as e:
                    log(f"         ✗ Errore nell'analisi: {str(e)[:100]}")
                    continue

            # Ripristina HEAD dopo aver analizzato tutti i commit dell'esercizio
            checkout_head(student_dir)

    log("=" * 60)
    log("FINISHED")
    log(f"Risultati salvati in: {OUTPUT_FILE}")

if __name__ == "__main__":
    main()
