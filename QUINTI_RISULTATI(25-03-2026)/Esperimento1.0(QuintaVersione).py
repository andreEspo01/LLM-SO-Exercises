from email.mime import text
import os
import subprocess
from unittest import result
import requests
import json
import re
import random
import shutil
import tempfile
import logging
from pathlib import Path
from datetime import datetime
from gitingest import ingest

# ================= CONFIG =================

BASE_SUBMISSIONS_DIR = "/home/andre/esercitazione-5-server-multithread-submissions"
GROUND_TRUTH_DIR = "/home/andre/ground_truth_es5"

PRIMARY_MODEL = "llama3:8b"
JUDGE_MODEL = "qwen2.5:3b"

OLLAMA_URL = "http://localhost:11434/api/generate"

COMPILE_TIMEOUT = 120
TEST_TIMEOUT = 120

LLM_CONNECT_TIMEOUT = 30
LLM_READ_TIMEOUT = 1500

OUTPUT_FILE = "risultati_llm_quintaVersione.json"
LOG_SAMPLE_DIR = "experiment_logs"

MAX_STUDENTS = 30  # Per limitare il numero di studenti analizzati (None per tutti)

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

# ================= INJECTION TESTS (COPIA NUOVI TEST) =================

BASE_TESTS_DIR = Path("/home/andre/so_esercitazione_5_messaggi_threads")

def inject_tests(student_dir, exercise_dir):
    """Copia i test generici e specifici nella cartella studente/esercizio
    senza cancellare eventuali file locali non Git-tracked.
    """
    generic_src = BASE_TESTS_DIR / ".test"
    specific_src = BASE_TESTS_DIR / exercise_dir.name / ".test"

    student_test_dir = student_dir / ".test"
    exercise_test_dir = exercise_dir / ".test"

    # Copia generica nella root dello studente
    if generic_src.exists():
        shutil.copytree(generic_src, student_test_dir, dirs_exist_ok=True)

    # Copia specifica nell'esercizio
    if specific_src.exists():
        shutil.copytree(specific_src, exercise_test_dir, dirs_exist_ok=True)

# ================= TEST DINAMICI MULTI-SCRIPT =================
def run_all_tests(path):
    """
    Esegue tutti gli script nella cartella .test dello studente.
    path: Path alla cartella dello studente/esercizio (es. .../studente/server_aggregatore_thread)
    Restituisce lista di dict con risultati per ogni script.
    """

    test_dir = path / ".test"
    if not test_dir.exists():
        raise FileNotFoundError(f"La cartella dei test non esiste: {test_dir}")

    # Trova tutti gli script .sh nella cartella test
    scripts = list(test_dir.glob("*.sh"))
    if not scripts:
        raise RuntimeError(f"Nessuno script .sh trovato in {test_dir}")

    feedback_file = "/tmp/feedback.md"
    output_file = "/tmp/output.txt"
    error_log = "/tmp/error-log.txt"

    all_results = []

    for script in sorted(scripts):
        # Pulizia file temporanei
        for f in [feedback_file, output_file, error_log]:
            if os.path.exists(f):
                os.remove(f)

        try:
            # Esecuzione script
            res = subprocess.run(
                ["bash", str(script.resolve())],
                cwd=test_dir,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                timeout=TEST_TIMEOUT
            )

            script_out = res.stdout
            script_err = res.stderr

            # Determina pass/fail basandosi sullo script output
            lower_out = script_out.lower()
            ok = "pass" in lower_out or (res.returncode == 0 and "fail" not in lower_out)

            # Legge l'output prodotto dal programma
            program_output = ""
            if os.path.exists(output_file):
                program_output = Path(output_file).read_text(errors="ignore").strip()
            if not program_output:
                program_output = "The program produced no output."

            # Legge feedback scritto dallo script
            feedback_text = ""
            if os.path.exists(feedback_file):
                feedback_text = Path(feedback_file).read_text(errors="ignore").strip()

            # Legge eventuale error log generato dallo script Perl
            error_text = ""
            if os.path.exists(error_log):
                error_text = Path(error_log).read_text(errors="ignore").strip()

            feedback_parts = []

            # Aggiungi solo messaggi di feedback generali, senza output del programma
            if feedback_text:
                # rimuovi la parte di output colorato se presente
                clean_feedback = re.sub(r"<br/><pre>.*?</pre>", "", feedback_text, flags=re.S)
                if clean_feedback.strip():
                    feedback_parts.append(clean_feedback.strip())

            # Aggiungi error log solo se non già incluso
            if error_text and error_text not in feedback_text:
                feedback_parts.append("[ERROR LOG]\n" + error_text)

            full_feedback = "\n\n".join(feedback_parts)
            full_feedback = clean_feedback_for_json(full_feedback)

            # Salva i risultati
            all_results.append({
                "script": script.name,
                "ok": ok,
                "script_out": script_out,
                "script_err": script_err,
                "program_output": program_output,
                "feedback": full_feedback
            })

        except subprocess.TimeoutExpired:
            all_results.append({
                "script": script.name,
                "ok": False,
                "script_out": "",
                "script_err": "",
                "program_output": "",
                "feedback": "timeout esecuzione"
            })

        except Exception as e:
            all_results.append({
                "script": script.name,
                "ok": False,
                "script_out": "",
                "script_err": "",
                "program_output": "",
                "feedback": f"errore esecuzione test: {str(e)}"
            })

    return all_results


# Per compatibilità con codice precedente che si aspetta una singola esecuzione test
def run_tests_compat(path):
    all_results = run_all_tests(path)

    if not all_results:
        return False, "", "", "", ""

    # Funzione interna per rimuovere i nomi degli script
    def remove_script_names(text):
        if not text:
            return ""
        return re.sub(r"\[.*?\.sh\]\s*\n?", "", text)

    # caso 1: un solo script → comportamento identico a prima, ma pulito
    if len(all_results) == 1:
        r = all_results[0]
        return (
            r["ok"],
            remove_script_names(r["script_out"]),
            remove_script_names(r["script_err"]),
            remove_script_names(r["program_output"]),
            remove_script_names(r["feedback"])
        )

    # caso 2: più script → aggrega e poi pulisci
    all_ok = all(r["ok"] for r in all_results)

    all_stdout = "".join(r["script_out"] for r in all_results)
    all_stderr = "".join(r["script_err"] for r in all_results)
    all_program_output = "".join(r["program_output"] for r in all_results)
    all_feedback = "".join(r["feedback"] for r in all_results)

    # Rimuove tutti i prefissi [nome_script.sh]
    all_stdout = remove_script_names(all_stdout)
    all_stderr = remove_script_names(all_stderr)
    all_program_output = remove_script_names(all_program_output)
    all_feedback = remove_script_names(all_feedback)

    return all_ok, all_stdout, all_stderr, all_program_output, all_feedback

def clean_feedback_for_json(feedback_text):
    if not feedback_text:
        return ""
    # rimuove emoji shortcode
    feedback_text = re.sub(r":[a-z_]+:", "", feedback_text)
    # sostituisce \n multipli con uno solo
    feedback_text = re.sub(r"\n+", "\n", feedback_text)
    # rimuove spazi iniziali/finali
    return feedback_text.strip()

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
                "file": r.get("path", ""),
                "line": r.get("start", {}).get("line", 0),
                "message": r.get("extra", {}).get("message", "")
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
You are analyzing the runtime output of a C program from an Operating Systems exercise.

Important context:
- The program may be correct. Only point out issues if you are reasonably sure.
- In concurrent programs, the order of printed messages may vary and still be correct.
- You currently only have access to program output, no code.
- There could be startup messages (e.g., process creation logs).

Exercise description:
{readme}

Program output:
{program_output}

Task:
Determine whether the observed output is consistent with a correct program execution.

You MUST check for the following types of issues:

1. Missing or incomplete output:
   - Expected messages not printed
   - Program stops prematurely or produces no output

2. Inconsistent or incorrect behavior:
   - Values that do not match expected logic
   - Contradictions within the output

3. Ordering and coordination issues:
   - Unexpected ordering of operations (only if it violates logical constraints)
   - Interleaving that suggests lack of coordination

4. Repetition or duplication:
   - Messages repeated unexpectedly
   - Operations executed multiple times when they should not

Guidelines:
- Empty or missing output may indicate deadlock, crash, or logic issue, but do not assume incorrectness without evidence.
- Focus on the behavior reflected in the output, including potential issues with thread execution or message ordering.
- Do NOT speculate about the code; base your reasoning only on the output.
- Do NOT speculate about internal coordination (threads, processes) unless directly observable from output.

Respond exactly in this format:

Output_Correct: Yes or No
Output_Diagnosis: <max 3 lines, describe the observed issue based only on output>
"""

def prompt_codice(readme, program_output, code):
    return f"""
You are reviewing C code from an Operating Systems exercise.

IMPORTANT:
- Even if program output appears correct, the code may contain hidden bugs.
- You must actively search for structural and logical issues.
- The program may be correct.
- If you do NOT find a clear and high-confidence bug directly in the code → Code_Correct: Yes

Exercise description:
{readme}

Program output:
{program_output}

Student code:
{code}

Task:
Determine whether the code contains correctness issues.

You MUST check for the following categories of problems:

1. Resource management:
   - Memory allocated but never freed
   - Incorrect allocation or lifetime of data structures
   - Use of stack variables where persistent memory is required

2. Synchronization and concurrency:
   - Shared data accessed without proper protection
   - Missing or incorrect synchronization
   - Overly restrictive synchronization reducing concurrency

3. Control flow and logic:
   - Incorrect loop conditions or termination logic
   - Missing checks or incorrect branching

4. Communication and coordination:
   - Incorrect use of inter-process or inter-thread communication
   - Mismatch between send/receive logic
   - Missing identification or filtering of messages/resources

5. API misuse:
   - Incorrect use of system or library calls
   - Missing error checks or wrong parameters

Guidelines:
- Do NOT mark the code as incorrect for minor issues (e.g., potential memory leaks, missing free, style issues) unless they clearly affect correctness in this exercise.
- Mark the code as incorrect ONLY if there is a concrete bug that can cause:
  - wrong results
  - deadlocks
  - race conditions affecting correctness
  - incorrect synchronization logic
- You MUST reference specific variables, functions, or code fragments.
- Do not justify correctness unless you have checked all categories above.

Respond exactly in this format:

Code_Correct: Yes or No
Code_Diagnosis: <max 4 lines, MUST reference code elements like variables/functions/code fragments and explain the issue>
"""

def prompt_codice_static(readme, code):
    return f"""
You are reviewing C code from an Operating Systems exercise.

IMPORTANT:
- You must actively search for structural and logical issues.

Exercise description:
{readme}

Student code:
{code}

Task:
Determine whether the code contains correctness issues.

You MUST check for the following categories of problems:

1. Resource management:
   - Memory allocated but never freed
   - Incorrect allocation or lifetime of data structures
   - Use of stack variables where persistent memory is required

2. Synchronization and concurrency:
   - Shared data accessed without proper protection
   - Missing or incorrect synchronization
   - Overly restrictive synchronization reducing concurrency

3. Control flow and logic:
   - Incorrect loop conditions or termination logic
   - Missing checks or incorrect branching

4. Communication and coordination:
   - Incorrect use of inter-process or inter-thread communication
   - Mismatch between send/receive logic
   - Missing identification or filtering of messages/resources

5. API misuse:
   - Incorrect use of system or library calls
   - Missing error checks or wrong parameters

Guidelines:
- If ANY suspicious pattern appears, consider the code incorrect.
- You MUST reference specific variables, functions, or code fragments.
- Do not justify correctness unless you have checked all categories above.

If the code clearly appears correct, answer YES.
Otherwise answer NO.

Respond exactly in this format:

Code_Correct: Yes or No
Code_Diagnosis: <max 4 lines, MUST reference code elements like variables/functions/code fragments and explain the issue>
"""

# ================= PROMPT GIUDICE =================

def prompt_giudice_output(diagnosi, errore_reale):
    return f"""
You are evaluating a diagnosis generated by another LLM regarding a C program.

LLM diagnosis:
{diagnosi}

Real error from tests:
{errore_reale}

Guidelines:
- The diagnosis was produced by an AI model (LLM); consider that the model may be imprecise.
- Consider the diagnosis CORRECT if it identifies runtime or output problems consistent with observed behavior.
- Consider the diagnosis INCORRECT if it claims correctness despite evident issues, ignores key symptoms, or references unrelated problems.
- Focus only on patterns visible in the program output, such as missing output, duplicated output, logical inconsistencies, or ordering issues.
- Do not penalize the diagnosis for mentioning expected variations due to concurrency, randomness, or scheduling.
- If the diagnosis identifies a potential issue with no output produced by the program, consider it CORRECT.

Respond exactly in this format:

Diagnosis_Correct: Yes or No
"""

def prompt_giudice_codice(diagnosi, warnings, code_around, solution_code):
    warnings_text = ""
    if warnings:
        warnings_text = "\nSTATIC ANALYSIS WARNINGS:\n" + "\n".join(
            [f"- {w['file']}:{w['line']}: {w['message']}" for w in warnings]
        )

    return f"""
You are evaluating the quality of a diagnosis produced by another LLM for a C program.

LLM diagnosis:
{diagnosi}

{warnings_text}

Student code (relevant excerpt):
{code_around}

Reference solution (for context):
{solution_code}

Guidelines:
- The diagnosis was produced by an AI model (LLM); consider that it may make mistakes.
- Consider the diagnosis CORRECT if it identifies code issues consistent with the static analysis warnings or evident bugs.
- Focus on whether the mentioned variables, functions, or code fragments actually correspond to potential problems.
- Consider the diagnosis INCORRECT if it ignores warnings, claims correctness despite issues, or references unrelated code.

Respond exactly in this format:

Diagnosis_Correct: Yes or No
"""

def prompt_giudice_codice_static(diagnosi, warnings):
    return f"""
You are evaluating the quality of a diagnosis produced by another LLM for a C program based on static analysis.

LLM diagnosis:
{diagnosi}

Static analysis warnings:
{warnings}

Guidelines:
- The diagnosis was produced by an AI model (LLM); it may miss or misinterpret issues.
- Consider the diagnosis CORRECT if it highlights issues consistent with the static analysis warnings, including specific variables, function calls, or code fragments.
- Consider the diagnosis INCORRECT if it claims correctness despite warnings, ignores key variables/functions, or references unrelated code.
- Consider the diagnosis INCORRECT if it fails to identify clear issues indicated by the static analysis warnings.

Respond exactly in this format:

Diagnosis_Correct: Yes or No
"""
# ================= CLASSIFICAZIONE ERRORI =================

def classify_failure_category(feedback_text, stderr, program_output):
    """Classifica il tipo di fallimento da usare in `failure_category`.

    Restituisce una delle categorie:
    - crash
    - timeout
    - ipc_leak
    - dynamic_failure

    Se non è possibile identificare una categoria più specifica, ritorna "dynamic_failure".
    """
    text = (feedback_text + "\n" + stderr + "\n" + program_output).lower()

    if not text.strip():
        return "dynamic_failure"

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
        return "timeout"

    # resource / IPC leak
    if any(k in text for k in [
        "memory leak",
        "resource leak",
        "file descriptor",
        "fd leak",
        "ipc",
        "pipe",
        "socket"
    ]):
        return "ipc_leak"

    # fallback per errori di runtime generici
    return "dynamic_failure"

# ================= PARSING =================

YES_SET = {"YES", "Y", "Yes", "yes", "TRUE", "T", "t", "SI", "SÌ", "SI'", "si'"}
NO_SET = {"NO", "N", "n", "No", "no", "FALSE", "F"}

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

            if field in ["Output_Diagnosis", "Code_Diagnosis"]:
                pattern = rf"{field}\s*:\s*(.*)"
                m = re.search(pattern, text, re.IGNORECASE | re.DOTALL)
                if m:
                    value = m.group(1).strip()
                else:
                    value = ""

            elif field.endswith("_Correct") and not value:
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
    tmp_file = OUTPUT_FILE + ".tmp"
    with open(tmp_file, "w") as f:
        json.dump(results, f, indent=4)
    os.replace(tmp_file, OUTPUT_FILE)  # scrittura atomica

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

def main():

    base = Path(BASE_SUBMISSIONS_DIR)

    # Carica risultati esistenti
    results = load_existing_results()

    # Evita duplicati
    already_done = {(r["student"], r["exercise"]) for r in results}

    student_dirs = sorted(
        [d for d in base.iterdir() if d.is_dir()],
        key=lambda x: extract_student_name(x.name).lower()
    )

    if MAX_STUDENTS:
        student_dirs = student_dirs[:MAX_STUDENTS]

    total_students = len(student_dirs)

    correct_count = sum(1 for r in results if r.get("failure_category") == "correct")
    incorrect_count = len(results) - correct_count

    for i, student_dir in enumerate(student_dirs, start=1):

        student_name = extract_student_name(student_dir.name)
        log(f"[{i}/{total_students}] STUDENTE: {student_name}")

        exercise_dirs = sorted(
            [d for d in student_dir.iterdir() if d.is_dir() and not d.name.startswith(".")],
            key=lambda x: x.name.lower()
        )

        total_ex = len(exercise_dirs)

        for j, exercise_dir in enumerate(exercise_dirs, start=1):

            if (student_name, exercise_dir.name) in already_done:
                log(f"    ({j}/{total_ex}) {exercise_dir.name} - GIÀ ANALIZZATO")
                continue

            log(f"    ({j}/{total_ex}) Esercizio: {exercise_dir.name}")

            commits = get_commits(student_dir)[:3]  # LIMITATI A 3 COMMITS
            selected_commit = None

            # =======================
            # SELEZIONE COMMIT SU COPIA TEMPORANEA CON git show
            # =======================
            import tempfile, subprocess, shutil

            with tempfile.TemporaryDirectory() as tmpdir:
                temp_ex_dir = Path(tmpdir) / exercise_dir.name
                temp_ex_dir.mkdir(parents=True, exist_ok=True)

                for commit in commits:
                    # Estrai tutti i file dell'esercizio dal commit senza fare checkout
                    files = subprocess.run(
                        ["git", "ls-tree", "-r", "--name-only", commit, str(exercise_dir)],
                        cwd=student_dir,
                        capture_output=True,
                        text=True
                    ).stdout.strip().splitlines()

                    for f in files:
                        f_path = Path(f)
                        # estrai il percorso relativo all'esercizio (non al repo)
                        try:
                            rel_path = f_path.relative_to(exercise_dir.name)
                        except ValueError:
                            # fallback: prendi solo il nome file
                            rel_path = f_path.name

                        dest_path = temp_ex_dir / rel_path
                        dest_path.parent.mkdir(parents=True, exist_ok=True)

                        blob_content = subprocess.run(
                            ["git", "show", f"{commit}:{f}"],
                            cwd=student_dir,
                            capture_output=True
                        ).stdout
                        with open(dest_path, "wb") as out_file:
                            out_file.write(blob_content)

                    # Compilazione e test sulla copia temporanea
                    compile_ok, _ = compile_exercise(temp_ex_dir)
                    if compile_ok:
                        test_ok, _, _, _, _ = run_tests_compat(temp_ex_dir)
                    else:
                        test_ok = False

                    # Regole per scegliere commit
                    if test_ok and incorrect_count > correct_count:
                        selected_commit = commit
                        break
                    elif not test_ok and correct_count >= incorrect_count:
                        selected_commit = commit
                        break

                    # Pulisci temp_ex_dir per il prossimo commit
                    shutil.rmtree(temp_ex_dir)
                    temp_ex_dir.mkdir(parents=True, exist_ok=True)

            # Fallback se nessun commit scelto
            if selected_commit is None:
                selected_commit = commits[0] if commits else "HEAD"

            # =======================
            # CHECKOUT FINALE SUL REPO REALE
            # =======================
            if selected_commit == "HEAD":
                checkout_head(student_dir)
            else:
                checkout_commit(student_dir, selected_commit)

            # =======================
            # COPIA TEST PERSONALIZZATI
            # =======================
            inject_tests(student_dir, exercise_dir)

            # Compilazione ed esecuzione finale
            compile_ok, compile_log = compile_exercise(exercise_dir)
            test_ok, stdout, stderr, program_out, feedback_text = run_tests_compat(exercise_dir)
            warnings = run_static_analysis(exercise_dir)

            if not compile_ok:
                failure = "compile_error"
            elif test_ok and warnings:
                failure = "static_failure"
            elif not test_ok:
                failure = classify_failure_category(feedback_text, stderr, program_out)
            else:
                failure = "correct"

            # =======================
            # ANALISI LLM
            # =======================
            readme = read_readme(exercise_dir)
            code = read_student_code(exercise_dir)
            student_files = get_student_files(exercise_dir)
            solution_files = read_solution_code(exercise_dir.name)

            output_corr = diag_output = code_corr = diag_code = judge_out_ok = judge_code_ok = ""

            # correct → LLM senza giudici
            if failure == "correct":
                resp_output = query_model(prompt_output(readme, program_out), PRIMARY_MODEL)
                resp_code = query_model(prompt_codice(readme, program_out, code), PRIMARY_MODEL)

                fields_output = parse_response(resp_output, ["Output_Correct", "Output_Diagnosis"])
                fields_code = parse_response(resp_code, ["Code_Correct", "Code_Diagnosis"])

                output_corr = fields_output.get("Output_Correct", "")
                diag_output = fields_output.get("Output_Diagnosis", "")
                code_corr = fields_code.get("Code_Correct", "")
                diag_code = fields_code.get("Code_Diagnosis", "")

            # dynamic / crash / timeout / ipc → LLM + giudici normali
            elif failure in ["dynamic_failure", "crash", "timeout", "ipc_leak"]:
                resp_output = query_model(prompt_output(readme, program_out), PRIMARY_MODEL)
                resp_code = query_model(prompt_codice(readme, program_out, code), PRIMARY_MODEL)

                fields_output = parse_response(resp_output, ["Output_Correct", "Output_Diagnosis"])
                fields_code = parse_response(resp_code, ["Code_Correct", "Code_Diagnosis"])

                output_corr = fields_output.get("Output_Correct", "")
                diag_output = fields_output.get("Output_Diagnosis", "")
                code_corr = fields_code.get("Code_Correct", "")
                diag_code = fields_code.get("Code_Diagnosis", "")

                if diag_output:
                    judge_out = query_model(prompt_giudice_output(diag_output, feedback_text), JUDGE_MODEL)
                    judge_out_ok = extract_field(judge_out, "Diagnosis_Correct") or extract_yes_no_anywhere(judge_out)

                if diag_code:
                    snippets = []
                    for w in warnings:
                        file = w['file']
                        line = w['line']
                        if file in student_files:
                            snippets.append(f"File: {file}, Line: {line}\n{extract_around(student_files[file], line)}")
                    code_around = '\n\n'.join(snippets) if snippets else code

                    sol_snippets = []
                    for w in warnings:
                        file = w['file']
                        line = w['line']
                        if file in solution_files:
                            sol_snippets.append(f"File: {file}, Line: {line}\n{extract_around(solution_files[file], line)}")
                    solution_code = '\n\n'.join(sol_snippets) if sol_snippets else "\n".join(solution_files.values())

                    judge_code = query_model(prompt_giudice_codice(diag_code, warnings, code_around, solution_code), JUDGE_MODEL)
                    judge_code_ok = extract_field(judge_code, "Diagnosis_Correct") or extract_yes_no_anywhere(judge_code)

            # static_failure → LLM static + giudice static
            elif failure == "static_failure":
                resp_output = query_model(prompt_output(readme, program_out), PRIMARY_MODEL)
                resp_code = query_model(prompt_codice_static(readme, code), PRIMARY_MODEL)

                fields_output = parse_response(resp_output, ["Output_Correct", "Output_Diagnosis"])
                fields_code = parse_response(resp_code, ["Code_Correct", "Code_Diagnosis"])

                output_corr = fields_output.get("Output_Correct", "")
                diag_output = fields_output.get("Output_Diagnosis", "")
                code_corr = fields_code.get("Code_Correct", "")
                diag_code = fields_code.get("Code_Diagnosis", "")

                if diag_code:
                    snippets = []
                    for w in warnings:
                        file = w['file']
                        line = w['line']
                        if file in student_files:
                            snippets.append(f"File: {file}, Line: {line}\n{extract_around(student_files[file], line)}")
                    code_around = '\n\n'.join(snippets) if snippets else code

                    judge_code = query_model(prompt_giudice_codice_static(diag_code, warnings), JUDGE_MODEL)
                    judge_code_ok = extract_field(judge_code, "Diagnosis_Correct") or extract_yes_no_anywhere(judge_code)

            if random.random() < 0.05:
                save_sample(
                    exercise_dir.name,
                    stdout,
                    stderr,
                    warnings,
                    code,
                    program_output=program_out
                )

            result = {
                "student": student_name,
                "exercise": exercise_dir.name,
                "commit_analyzed": selected_commit,
                "failure_category": failure,
                "compile_success": compile_ok,
                "test_success": test_ok,
                "stdout": stdout,
                "stderr": stderr,
                "test_feedback": feedback_text,
                "program_output": program_out,
                "static_warnings": warnings,
                "llm_Output_Correct": output_corr,
                "llm_Output_Diagnosis": diag_output,
                "llm_Code_Correct": code_corr,
                "llm_Code_Diagnosis": diag_code,
                "judge_Output_Correct": judge_out_ok,
                "judge_Code_Correct": judge_code_ok
            }

            results.append(result)
            already_done.add((student_name, exercise_dir.name))
            save_results(results)

    log("FINISHED")


if __name__ == "__main__":
    main()