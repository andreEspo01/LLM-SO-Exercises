from email.mime import text
import os
import subprocess
from unittest import result
import requests
import json
import re
import random
from pathlib import Path
from datetime import datetime
from gitingest import ingest

# ================= CONFIG =================

BASE_SUBMISSIONS_DIR = "/home/andre/esercitazione-5-server-multithread-submissions"
GROUND_TRUTH_DIR = "/home/andre/ground_truth_es5"

PRIMARY_MODEL = "llama3:8b"
JUDGE_MODEL = "qwen2.5-coder:7b"

OLLAMA_URL = "http://localhost:11434/api/generate"

COMPILE_TIMEOUT = 120
TEST_TIMEOUT = 120

LLM_CONNECT_TIMEOUT = 30
LLM_READ_TIMEOUT = 1500

OUTPUT_FILE = "risultati_llm_quartaVersione.json"
LOG_SAMPLE_DIR = "experiment_logs"

MAX_STUDENTS = 20  # Per limitare il numero di studenti analizzati (None per tutti)

# ==========================================

def log(msg):
    print(f"[{datetime.now().strftime('%H:%M:%S')}] {msg}")

# ================= LLM =================

def query_model(prompt, model):
    payload = {
        "model": model,
        "prompt": prompt,
        "stream": False,
        "options": {
            "temperature": 0.0,
            "top_p": 0.1,
            "num_predict": 600
        }
    }

    try:
        r = requests.post(
            OLLAMA_URL,
            json=payload,
            timeout=(LLM_CONNECT_TIMEOUT, LLM_READ_TIMEOUT)
        )

        return r.json().get("response", "")

    except:
        return "ERRORE_LLM"

# ================= COMPILAZIONE =================

def compile_exercise(path):

    # rimuove file oggetto e binari vecchi
    try:
        subprocess.run(
            ["make", "clean"],
            cwd=path,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE
        )
    except:
        pass

    # ulteriore sicurezza: rimuove manualmente .o
    try:
        for f in path.glob("*.o"):
            f.unlink()
    except:
        pass

    try:
        res = subprocess.run(
            ["make"],
            cwd=path,
            capture_output=True,
            text=True,
            timeout=COMPILE_TIMEOUT
        )

        return res.returncode == 0, res.stdout + res.stderr

    except:
        return False, "timeout compilazione"

# ================= TEST DINAMICI =================

def run_tests(path):

    test_dir = path / ".test"

    if not test_dir.exists():
        return False, "", "directory .test mancante", "", ""

    scripts = list(test_dir.glob("*.sh"))

    if not scripts:
        return False, "", "script test mancante", "", ""

    feedback_file = "/tmp/feedback.md"
    output_file = "/tmp/output.txt"

    # pulizia file temporanei
    for f in [feedback_file, output_file]:
        try:
            if os.path.exists(f):
                os.remove(f)
        except:
            pass

    try:
        res = subprocess.run(
            ["bash", scripts[0].name],
            cwd=test_dir,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            timeout=TEST_TIMEOUT
        )

        script_out = res.stdout
        script_err = res.stderr

        # interpretazione robusta del risultato dei test
        lower_out = script_out.lower()

        if "pass" in lower_out:
            ok = True
        elif "fail" in lower_out:
            ok = False
        else:
            ok = res.returncode == 0

    except subprocess.TimeoutExpired:
        return False, "", "timeout esecuzione", "", ""

    except Exception as e:
        return False, "", f"errore esecuzione test: {str(e)}", "", ""

    # =============================
    # lettura output del programma
    # =============================

    program_output = ""

    if os.path.exists(output_file):
        try:
            program_output = Path(output_file).read_text(errors="ignore").strip()
        except:
            program_output = ""

    # se lo script non ha prodotto output.txt, fallback sicuro
    if not program_output:
        program_output = "The program produced no output."

    # =============================
    # lettura feedback dei test
    # =============================

    feedback_text = ""

    if os.path.exists(feedback_file):
        try:
            feedback_text = Path(feedback_file).read_text(errors="ignore").strip()
        except:
            feedback_text = ""

    # =============================
    # segnale esplicito output vuoto
    # =============================

    if not program_output:
        program_output = "The program produced no output."

    return ok, script_out, script_err, program_output, feedback_text

# ================= STATIC ANALYSIS =================

def run_static_analysis(path):
    test_dir = path / ".test"

    if not test_dir.exists():
        return []

    try:
        res = subprocess.run(
            ["semgrep", "--json", "--config", str(test_dir)],
            cwd=path,
            capture_output=True,
            text=True
        )

        data = json.loads(res.stdout)

        warnings = []

        for r in data.get("results", []):
            warnings.append({
                "file": r["path"],
                "line": r["start"]["line"],
                "message": r["extra"]["message"]
            })

        return warnings

    except:
        return []

# ================= GIT FUNCTIONS =================

def get_commits(repo_path):
    try:
        res = subprocess.run(["git", "rev-list", "HEAD"], cwd=repo_path,
                             capture_output=True, text=True)
        return res.stdout.strip().splitlines()
    except:
        return []

def checkout_commit(repo_path, commit_hash):
    subprocess.run(["git", "reset", "--hard"], cwd=repo_path,
                   stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    subprocess.run(["git", "clean", "-fd"], cwd=repo_path,
                   stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    subprocess.run(["git", "checkout", commit_hash], cwd=repo_path,
                   stdout=subprocess.PIPE, stderr=subprocess.PIPE)

def checkout_head(repo_path):
    subprocess.run(["git", "checkout", "HEAD"], cwd=repo_path,
                   stdout=subprocess.PIPE, stderr=subprocess.PIPE)

# ================= LETTURA FILE =================

def read_readme(path):
    readme = path / "readme.md"
    if readme.exists():
        return readme.read_text(errors="ignore")
    return "Traccia non disponibile"

def build_repo_view(exercise_path):
    try:
        repo_text = ingest(str(exercise_path))
        if isinstance(repo_text, str):
            return repo_text
        summary = ""
        for f in repo_text:
            if not isinstance(f, dict):
                continue
            path_file = f.get("path", "")
            content = f.get("content", "")
            if path_file.endswith((".c", ".h")):
                summary += f"\nFILE: {path_file}\n{content}\n"
        return summary
    except:
        return "Codice non disponibile."

def get_student_files(path):
    try:
        repo_text = ingest(str(path))
        if isinstance(repo_text, str):
            return {}
        student_files = {}
        for f in repo_text:
            if not isinstance(f, dict):
                continue
            path_file = f.get("path", "")
            content = f.get("content", "")
            if path_file.endswith((".c", ".h")):
                student_files[path_file] = content
        return student_files
    except:
        return {}

def extract_around(content, line, context=10):
    lines = content.splitlines()
    start = max(0, line - context - 1)
    end = min(len(lines), line + context)
    return '\n'.join(lines[start:end])

def read_student_code(path):
    return build_repo_view(path)

def read_solution_code(exercise_name):
    ground_truth = Path(GROUND_TRUTH_DIR)
    if not ground_truth.exists():
        return {}
    solution_dir = ground_truth / exercise_name
    if solution_dir.exists() and solution_dir.is_dir():
        solution_files = {}
        for f in solution_dir.glob("**/*.c"):
            solution_files[f.name] = f.read_text(errors="ignore")
        for f in solution_dir.glob("**/*.h"):
            solution_files[f.name] = f.read_text(errors="ignore")
        return solution_files
    return {}

# ================= PROMPT LLM =================

def prompt_output(readme, program_output):

    return f"""
You are analyzing the output of a concurrent C program.

Important context:

- The program may be correct.
- In concurrent programs, the order of printed messages may vary.
- Different ordering alone does NOT necessarily indicate an error.

EXERCISE DESCRIPTION:
{readme}

PROGRAM OUTPUT:
{program_output}

Important observations:

- If the program produces NO OUTPUT or the output is empty, this usually indicates a problem in the program (e.g., deadlock, crash, or incorrect logic).
- A correct program for this exercise is expected to produce visible output.
- If the program produces no output at all, you should normally consider the output incorrect.

Task:

Evaluate whether the observed output appears consistent with a correct execution of the program.

Respond ONLY in this format:

OUTPUT_CORRECT: YES or NO
OUTPUT_DIAGNOSIS: <max 3 lines>
"""

def prompt_codice(readme, program_output, code):

    return f"""
You are reviewing C code from a concurrent programming exercise.

Important:

- The program may be correct.
- However, the execution may have failed due to a bug in the code.
- Many concurrency bugs are subtle (race conditions, missing synchronization, incorrect message handling).

EXERCISE DESCRIPTION:
{readme}

PROGRAM OUTPUT:
{program_output}

STUDENT CODE:
{code}

Task:

Evaluate whether the code likely contains a bug.

Focus especially on:

- synchronization errors
- race conditions
- incorrect message queue usage
- incorrect thread logic

If the code clearly appears correct, answer YES.
Otherwise answer NO.

Respond ONLY with:

CODE_CORRECT: YES or NO
CODE_DIAGNOSIS: <max 4 lines>
"""

def prompt_codice_static(readme, code):
    return f"""
You are reviewing the source code of a concurrent C program.

Important guidelines:

- The program may be correct.
- Do NOT assume bugs without clear evidence.
- Some synchronization patterns may appear unusual but still be correct.

EXERCISE DESCRIPTION:
{readme}

STUDENT CODE:
{code}

Analysis process:

1. Look for concrete signs of correctness issues such as:
   - missing synchronization
   - potential race conditions
   - incorrect thread usage
   - unsafe shared resource handling

2. Avoid speculation. Only report issues that are reasonably supported by the code.

3. If the code appears reasonable and no clear problem is visible, assume it is correct.

Respond ONLY with:

CODE_CORRECT: YES or NO
CODE_DIAGNOSIS: <short explanation, max 4 lines>
"""

def prompt_giudice_output(diagnosi, errore_reale):

    return f"""
You are evaluating a diagnosis generated by another LLM.

The program is a concurrent C program.

LLM DIAGNOSIS:
{diagnosi}

REAL ERROR FROM TESTS:
{errore_reale}

Evaluation guidelines:

A diagnosis should be considered CORRECT if:

- it identifies that the output is incorrect
- it proposes a plausible explanation for the failure
- it refers to concurrency or incorrect program behavior

A diagnosis should be considered INCORRECT if:

- it claims the output is correct despite the test failure
- it ignores the failure completely
- it contradicts the observed error

The diagnosis does not need to match the exact wording of the error.

Respond exactly in this format:

DIAGNOSIS_CORRECT: YES or NO
"""

def prompt_giudice_codice(diagnosi, warnings, code_around, solution_code):

    warnings_text = ""
    if warnings:
        warnings_text = "\nSTATIC ANALYSIS WARNINGS:\n" + "\n".join(
            [f"- {w['file']}:{w['line']}: {w['message']}" for w in warnings]
        )

    return f"""
You are evaluating the quality of a diagnosis produced by another LLM.

The task is to determine whether the diagnosis correctly judges if the student's code is correct or incorrect.

LLM DIAGNOSIS:
{diagnosi}

{warnings_text}

STUDENT CODE (relevant excerpt):
{code_around}

REFERENCE SOLUTION (for context):
{solution_code}

Evaluation guidelines:

A diagnosis should be considered CORRECT if:
- it correctly identifies that the code likely contains a problem when warnings indicate issues
- it reasonably explains a concurrency or correctness issue
- it concludes the code is incorrect when clear problems exist

A diagnosis should be considered INCORRECT if:
- it claims the code is correct despite clear warnings or errors
- it describes an unrelated issue
- it misinterprets the code in a major way

The diagnosis does NOT need to mention the exact warning.

Respond exactly in this format:

DIAGNOSIS_CORRECT: YES or NO
"""

def prompt_giudice_codice_static(diagnosi, warnings):
    return f"""
You are evaluating the quality of a diagnosis produced by another LLM.

LLM DIAGNOSIS:
{diagnosi}

STATIC ANALYSIS WARNINGS (ground truth):
{warnings}

Evaluation guidelines:

A diagnosis should be considered CORRECT if:
- it concludes that the code likely contains a problem
- it provides a plausible explanation related to correctness or concurrency

A diagnosis should be considered INCORRECT if:
- it claims the code is correct despite the presence of warnings
- it describes a completely unrelated issue

The diagnosis does NOT need to reference the exact warning.

Respond exactly in this format:

DIAGNOSIS_CORRECT: YES or NO
"""
# ================= CLASSIFICAZIONE ERRORI =================

def classify_error_type(feedback_text, stderr, program_output, failure_category=None):
    """
    Classifica il tipo di errore a partire dal testo di feedback, stderr e output del programma.
    Se failure_category è 'static_check_failed', non verrà restituito runtime_error.
    """
    text = (feedback_text + "\n" + stderr + "\n" + program_output).lower()

    if not text.strip():
        return "unknown"

    # Se è solo un warning statico, evitiamo errori di runtime
    if failure_category == "static_check_failed":
        return "static_warning"

    # crash
    if any(k in text for k in [
        "segmentation fault",
        "segfault",
        "core dumped",
        "abort",
        "assertion failed"
    ]):
        return "crash"

    # timeout / deadlock
    if any(k in text for k in [
        "timeout",
        "timed out",
        "deadlock",
        "hang"
    ]):
        return "timeout_or_deadlock"

    # race / ordine errato output
    if any(k in text for k in [
        "ordine",
        "order",
        "unexpected output",
        "output non corretto",
        "execution order",
        "messaggi"
    ]):
        return "incorrect_output_order"

    # resource leak
    if any(k in text for k in [
        "memory leak",
        "resource leak",
        "file descriptor",
        "fd leak"
    ]):
        return "resource_leak"

    # errori thread / sync
    if any(k in text for k in [
        "mutex",
        "lock",
        "unlock",
        "race condition",
        "pthread"
    ]):
        return "concurrency_bug"

    # errori generici
    if any(k in text for k in [
        "error",
        "failed",
        "invalid"
    ]):
        return "runtime_error"

    return "unknown"

# ================= PARSING =================

YES_SET = {"YES", "Y", "TRUE", "T", "SI", "SÌ"}
NO_SET = {"NO", "N", "FALSE", "F"}

def normalize_bool(value):
    if not value:
        return ""

    v = value.strip().upper()

    v = v.replace(".", "").replace("*", "").strip()

    if v in YES_SET:
        return "YES"

    if v in NO_SET:
        return "NO"

    return v


def clean_text(text):
    if not text:
        return ""

    # rimuove markdown
    text = re.sub(r"```.*?```", "", text, flags=re.S)

    # rimuove bullet
    text = re.sub(r"^\s*[-*]\s*", "", text, flags=re.M)

    return text.strip()


def extract_field(text, field):
    """
    Parser robusto per estrarre campi dalle risposte LLM
    """

    if not text:
        return ""

    text = clean_text(text)

    patterns = [

        # FIELD: value
        rf"{field}\s*:\s*([^\n\r]+)",

        # FIELD = value
        rf"{field}\s*=\s*([^\n\r]+)",

        # **FIELD:** value
        rf"\*\*{field}\*\*\s*:\s*([^\n\r]+)",

        # FIELD - value
        rf"{field}\s*-\s*([^\n\r]+)",

    ]

    for pattern in patterns:
        m = re.search(pattern, text, re.IGNORECASE)
        if m:
            return normalize_bool(m.group(1))

    return ""


def extract_yes_no_anywhere(text):
    """
    fallback se il campo non viene trovato
    """

    if not text:
        return ""

    text = text.upper()

    if re.search(r"\byes\b|\bYes\b|\bYES\b", text):
        return "YES"

    if re.search(r"\bno\b|\bNo\b|\bNO\b", text):
        return "NO"

    return ""


def parse_response(text, expected_fields):
    """
    Estrae i campi attesi dalla risposta LLM.
    Per DIAGNOSI_OUTPUT o DIAGNOSI_CODICE prende solo il testo che segue il campo.
    Per *_CORRETTO usa SI/NO.
    """

    result = {}
    text = clean_text(text)

    for field in expected_fields:

        value = extract_field(text, field)

        if not value:

            if field in ["OUTPUT_DIAGNOSIS", "CODE_DIAGNOSIS"]:
                pattern = rf"{field}\s*:\s*(.*)"
                m = re.search(pattern, text, re.IGNORECASE | re.DOTALL)
                if m:
                    value = m.group(1).strip()
                else:
                    value = ""

            elif field.endswith("_CORRECT") and not value:
                value = extract_yes_no_anywhere(text)

        result[field] = value

    return result

# ================= SALVATAGGIO =================

def load_results():
    if Path(OUTPUT_FILE).exists():
        with open(OUTPUT_FILE) as f:
            return json.load(f)

    return []

def save_results(results):
    tmp = OUTPUT_FILE + ".tmp"

    with open(tmp, "w") as f:
        json.dump(results, f, indent=2)

    os.replace(tmp, OUTPUT_FILE)

# ================= LOG CAMPIONE =================

def save_sample(name, stdout, stderr, warnings, code, program_output=None):
    path = Path(LOG_SAMPLE_DIR) / name

    path.mkdir(parents=True, exist_ok=True)

    (path / "stdout.txt").write_text(stdout)
    (path / "stderr.txt").write_text(stderr)
    (path / "code.c").write_text(code)

    if program_output is not None:
        (path / "program_output.txt").write_text(program_output)

    with open(path / "static.json", "w") as f:
        json.dump(warnings, f, indent=2)

# ================= MAIN =================

def extract_student_name(folder_name):
    prefix = "esercitazione-5-server-multithread-"
    if folder_name.startswith(prefix):
        return folder_name[len(prefix):]
    return folder_name


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
    os.replace(tmp_file, OUTPUT_FILE)  # scrittura atomica

def main():

    base = Path(BASE_SUBMISSIONS_DIR)

    # Carica risultati esistenti
    results = load_existing_results()

    # Evita duplicati
    already_done = {
        (r["student"], r["exercise"])
        for r in results
    }

    student_dirs = sorted(
        [d for d in base.iterdir() if d.is_dir()],
        key=lambda x: extract_student_name(x.name).lower()
    )

    # Per limitare studenti
    if MAX_STUDENTS:
        student_dirs = student_dirs[:MAX_STUDENTS]

    total_students = len(student_dirs)

    # Per bilanciare: conta esercizi corretti e non
    correct_count = sum(1 for r in results if r.get("failure_category") == "correct")
    incorrect_count = len(results) - correct_count

    for i, student_dir in enumerate(student_dirs, start=1):

        student_name = extract_student_name(student_dir.name)
        log(f"[{i}/{total_students}] STUDENTE: {student_name}")

        exercise_dirs = sorted(
            [d for d in student_dir.iterdir()
             if d.is_dir() and not d.name.startswith(".")],
            key=lambda x: x.name.lower()
        )

        total_ex = len(exercise_dirs)

        for j, exercise_dir in enumerate(exercise_dirs, start=1):

            if (student_name, exercise_dir.name) in already_done:
                log(f"    ({j}/{total_ex}) {exercise_dir.name} - GIÀ ANALIZZATO")
                continue

            log(f"    ({j}/{total_ex}) Esercizio: {exercise_dir.name}")

            commits = get_commits(exercise_dir)[:3]  # LIMITATI A 3 COMMITS PER ESECUZIONE

            selected_commit = None
            for commit in commits:
                checkout_commit(exercise_dir, commit)

                compile_ok, compile_log = compile_exercise(exercise_dir)
                if compile_ok:
                    test_ok, stdout, stderr, program_out, feedback_text = run_tests(exercise_dir)
                else:
                    test_ok = False
                    stdout = ""
                    stderr = compile_log
                    program_out = ""
                    feedback_text = ""
                warnings = run_static_analysis(exercise_dir)

                if not compile_ok:
                    failure = "compile_error"
                elif not test_ok:
                    failure = "dynamic_check_failed"
                elif warnings:
                    failure = "static_check_failed"
                else:
                    failure = "correct"

                # Bilancia: preferisci commit con errori (compile, dynamic, o static) se ci sono più corretti, viceversa
                if (failure == "correct" and incorrect_count > correct_count) or (failure in ["compile_error", "dynamic_check_failed", "static_check_failed"] and correct_count >= incorrect_count):
                    selected_commit = commit
                    break

            if selected_commit is None:
                # Se nessun commit selezionato, usa l'ultimo
                selected_commit = commits[0] if commits else "HEAD"
                checkout_head(exercise_dir) if selected_commit == "HEAD" else checkout_commit(exercise_dir, selected_commit)
                compile_ok, compile_log = compile_exercise(exercise_dir)
                test_ok, stdout, stderr, program_out, feedback_text = run_tests(exercise_dir)
                warnings = run_static_analysis(exercise_dir)

                if not compile_ok:
                    failure = "compile_error"
                elif not test_ok:
                    failure = "dynamic_check_failed"
                elif warnings:
                    failure = "static_check_failed"
                else:
                    failure = "correct"

            readme = read_readme(exercise_dir)
            code = read_student_code(exercise_dir)
            student_files = get_student_files(exercise_dir)
            solution_files = read_solution_code(exercise_dir.name)

            # Inizializza variabili
            output_corr = ""
            diag_output = ""
            code_corr = ""
            diag_code = ""
            judge_out_ok = ""
            judge_code_ok = ""

            if failure == "dynamic_check_failed" or failure == "correct":
                # LLM primario per output e codice
                # use the actual program output (collected by run_tests) rather than
                # the script's pass/fail message
                resp_output = query_model(prompt_output(readme, program_out), PRIMARY_MODEL)
                resp_code = query_model(prompt_codice(readme, program_out, code), PRIMARY_MODEL)

                # Parsing robusto delle risposte
                fields_output = parse_response(resp_output, ["OUTPUT_CORRECT", "OUTPUT_DIAGNOSIS"])
                fields_code = parse_response(resp_code, ["CODE_CORRECT", "CODE_DIAGNOSIS"])

                output_corr = fields_output.get("OUTPUT_CORRECT", "")
                diag_output = fields_output.get("OUTPUT_DIAGNOSIS", "")

                code_corr = fields_code.get("CODE_CORRECT", "")
                diag_code = fields_code.get("CODE_DIAGNOSIS", "")

                # Giudice per output - solo se abbiamo una diagnosi
                judge_out_ok = ""
                if diag_output:
                    judge_out = query_model(prompt_giudice_output(diag_output, feedback_text), JUDGE_MODEL)
                    judge_out_ok = extract_field(judge_out, "DIAGNOSIS_CORRECT")
                    if not judge_out_ok:
                        judge_out_ok = extract_yes_no_anywhere(judge_out)

                # Per giudice codice: estrai codice attorno (semplificato, assumi tutto il codice)
                judge_code_ok = ""
                if diag_code:
                    snippets = []
                    for w in warnings:
                        file = w['file']
                        line = w['line']
                        if file in student_files:
                            snippet = extract_around(student_files[file], line)
                            snippets.append(f"File: {file}, Line: {line}\n{snippet}")
                    code_around = '\n\n'.join(snippets) if snippets else code
                    
                    sol_snippets = []
                    for w in warnings:
                        file = w['file']
                        line = w['line']
                        if file in solution_files:
                            snippet = extract_around(solution_files[file], line)
                            sol_snippets.append(f"File: {file}, Line: {line}\n{snippet}")
                    solution_code = '\n\n'.join(sol_snippets) if sol_snippets else "\n".join(solution_files.values())
                    
                    judge_code = query_model(prompt_giudice_codice(diag_code, warnings, code_around, solution_code), JUDGE_MODEL)
                    judge_code_ok = extract_field(judge_code, "DIAGNOSIS_CORRECT")
                    if not judge_code_ok:
                        judge_code_ok = extract_yes_no_anywhere(judge_code)

            elif failure == "static_check_failed":
                # LLM primario per output e codice
                resp_output = query_model(prompt_output(readme, program_out), PRIMARY_MODEL)
                resp_code = query_model(prompt_codice(readme, program_out, code), PRIMARY_MODEL)

                # Parsing robusto delle risposte
                fields_output = parse_response(resp_output, ["OUTPUT_CORRECT", "OUTPUT_DIAGNOSIS"])
                fields_code = parse_response(resp_code, ["CODE_CORRECT", "CODE_DIAGNOSIS"])

                output_corr = fields_output.get("OUTPUT_CORRECT", "")
                diag_output = fields_output.get("OUTPUT_DIAGNOSIS", "")

                code_corr = fields_code.get("CODE_CORRECT", "")
                diag_code = fields_code.get("CODE_DIAGNOSIS", "")

                # Giudice solo per codice
                judge_code_ok = ""
                if diag_code:
                    snippets = []
                    for w in warnings:
                        file = w['file']
                        line = w['line']
                        if file in student_files:
                            snippet = extract_around(student_files[file], line)
                            snippets.append(f"File: {file}, Line: {line}\n{snippet}")
                    code_around = '\n\n'.join(snippets) if snippets else code
                    
                    sol_snippets = []
                    for w in warnings:
                        file = w['file']
                        line = w['line']
                        if file in solution_files:
                            snippet = extract_around(solution_files[file], line)
                            sol_snippets.append(f"File: {file}, Line: {line}\n{snippet}")
                    solution_code = '\n\n'.join(sol_snippets)
                    
                    judge_code = query_model(prompt_giudice_codice(diag_code, warnings, code_around, solution_code), JUDGE_MODEL)
                    judge_code_ok = extract_field(judge_code, "DIAGNOSIS_CORRECT")
                    if not judge_code_ok:
                        judge_code_ok = extract_yes_no_anywhere(judge_code)

            # ===== LOG CAMPIONE =====

            if random.random() < 0.05:
                save_sample(
                    exercise_dir.name,
                    stdout,
                    stderr,
                    warnings,
                    code,
                    program_output=program_out
                )


            if failure == "compile_error":
                ground_truth_error_type = "compile_error"
            elif failure == "correct":
                ground_truth_error_type = ""
            else:
                ground_truth_error_type = classify_error_type(
                    feedback_text if 'feedback_text' in locals() else "",
                    stderr,
                    program_out
                )

            result = {
                "student": student_name,
                "exercise": exercise_dir.name,
                "commit_analyzed": selected_commit,

                "failure_category": failure,
                "error_type": ground_truth_error_type,
                "compile_success": compile_ok,
                "test_success": test_ok,

                # script stdout remains for backwards compatibility
                "stdout": stdout,
                "stderr": stderr,
                "test_feedback": feedback_text,
                # actual program output captured separately
                "program_output": program_out,

                "static_warnings": warnings,

                "llm_output_correct": output_corr,
                "llm_output_diagnosis": diag_output,

                "llm_code_correct": code_corr,
                "llm_code_diagnosis": diag_code,

                "judge_output_correct": judge_out_ok,
                "judge_code_correct": judge_code_ok
            }

            results.append(result)
            already_done.add((student_name, exercise_dir.name))

            save_results(results)

    log("FINISHED")

if __name__ == "__main__":
    main()