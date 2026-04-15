import os
import subprocess
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

OUTPUT_FILE = "risultati_llm.json"
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
            "num_predict": 1200
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
        return False, "", "directory .test mancante", ""

    scripts = list(test_dir.glob("*.sh"))

    if not scripts:
        return False, "", "script test mancante", ""

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
        ok = res.returncode == 0
    except:
        return False, "", "timeout esecuzione", ""

    # cerca eseguibili prodotti dal makefile e raccogli il loro output (per analisi LLM)
    prog_outs = []
    try:
        for f in path.iterdir():
            # skip non-file e file nascosti
            if not f.is_file() or f.name.startswith('.'):
                continue
            # ignora file oggetto
            if f.suffix == '.o':
                continue
            # controlla permessui esecuzione
            if os.access(f, os.X_OK):
                try:
                    pr = subprocess.run(
                        [str(f)],
                        cwd=path,
                        stdout=subprocess.PIPE,
                        stderr=subprocess.PIPE,
                        text=True,
                        timeout=TEST_TIMEOUT
                    )
                    prog_outs.append(pr.stdout)
                except:
                    # ignora failure nell'esecuzione dei programmi, non vogliamo che blocchi l'intero processo
                    pass
    except Exception:
        pass

    program_output = "\n".join(prog_outs)
    return ok, script_out, script_err, program_output

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
                summary += f"\nFILE: {path_file}\n"
                summary += content + "\n"
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
    """Legge il codice soluzione dalla cartella GROUND_TRUTH_DIR"""
    ground_truth = Path(GROUND_TRUTH_DIR)
    
    if not ground_truth.exists():
        return {}
    
    # Cerca una cartella che corrisponda all'esercizio
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
Sei un assistente che analizza l'esecuzione di programmi C concorrenti.

ATTENZIONE:

* I programmi potrebbero essere corretti.
* Non assumere errori se non sei sicuro.
* Essendo programmi concorrenti, l'ordine delle stampe può cambiare.

Questo è il programma che è stato eseguito, con la sua traccia e l'output risultante.

TRACCIA ESERCIZIO:
{readme}

OUTPUT DEL PROGRAMMA:
{program_output}

Rispondi solo con:

OUTPUT_CORRETTO: SI oppure NO
DIAGNOSI_OUTPUT: <max 3 righe>
"""

def prompt_codice(readme, program_output, code):

    return f"""
Sei un analista statico che analizza codice C concorrente.

ATTENZIONE:

* Il programma potrebbe essere corretto.
* Non assumere errori se non sei sicuro.
* Vedi solo parti del codice a causa di limiti di contesto.

Questo è il programma che è stato eseguito, con la sua traccia, l'output risultante e il codice sorgente.

TRACCIA:
{readme}

OUTPUT:
{program_output}

CODICE STUDENTE:
{code}

Rispondi solo con:

CODICE_CORRETTO: SI oppure NO
DIAGNOSI_CODICE: <max 4 righe>
"""

def prompt_giudice_output(diagnosi, errore_reale):
    return f"""
Sei un giudice esperto di output di programmi C concorrenti.
Valuta questa diagnosi sulla correttezza dell'output.

NOTA: il programma è concorrente, quindi l'ordine delle stampe può variare.

Questa è la diagnosi che devi giudicare, confrontandola con l'errore reale osservato nei test:

DIAGNOSI LLM:
{diagnosi}

ERRORE REALE DAL TEST:
{errore_reale}

La diagnosi LLM spiegata è coerente con l'errore reale osservato? Valuta obiettivamente se la diagnosi spiega adeguatamente l'errore o è troppo vaga/superficiale.

Rispondi esattamente in questo formato:
DIAGNOSI_CORRETTA: SI oppure NO
"""

def prompt_giudice_codice(diagnosi, warnings, code_around, solution_code):
    warnings_text = ""
    if warnings:
        warnings_text = "\nWARNING ANALISI STATICA (SE PRESENTI):\n" + "\n".join([f"- {w['file']}:{w['line']}: {w['message']}" for w in warnings])

    return f"""
Sei un giudice esperto di codice C concorrente.
Valuta questa diagnosi sulla correttezza del codice realizzato dallo studente, confrontandola con il codice della soluzione.

DIAGNOSI LLM:
{diagnosi}{warnings_text}

CODICE STUDENTE:
{code_around}

CODICE SOLUZIONE:
{solution_code}

I warning di analisi statica rappresentano problemi reali nel codice. Usa questi come verità assoluta per valutare se la diagnosi dell'LLM identifica correttamente i problemi presenti.

Dati il codice della soluzione e i warning reali, la diagnosi LLM individua correttamente il problema nel codice?

Rispondi esattamente in questo formato:
DIAGNOSI_CORRETTA: SI oppure NO
"""

def prompt_giudice_codice_static(diagnosi, warnings):
    return f"""
Sei un giudice esperto di codice C concorrente.
Valuta questa diagnosi sulla correttezza del codice.

DIAGNOSI LLM:
{diagnosi}

WARNING ANALISI STATICA (SE PRESENTI):
{warnings}

I warning di analisi statica rappresentano problemi reali nel codice. Usa questi come verità assoluta per valutare se la diagnosi dell'LLM identifica correttamente i problemi presenti.

Dati i warning reali, la diagnosi LLM individua correttamente il problema nel codice?

Rispondi esattamente in questo formato:
DIAGNOSI_CORRETTA: SI oppure NO
"""

# ================= PARSING =================

YES_SET = {"SI", "SÌ", "YES", "Y", "TRUE", "T"}
NO_SET = {"NO", "N", "FALSE", "F"}

def normalize_bool(value):
    if not value:
        return ""

    v = value.strip().upper()

    v = v.replace(".", "").replace("*", "").strip()

    if v in YES_SET:
        return "SI"

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

    if re.search(r"\bSI\b|\bSÌ\b|\bYES\b", text):
        return "SI"

    if re.search(r"\bNO\b", text):
        return "NO"

    return ""


def parse_response(text, expected_fields):

    result = {}

    for field in expected_fields:

        value = extract_field(text, field)

        if not value:

            if field in ["DIAGNOSI_OUTPUT", "DIAGNOSI_CODICE"]:

                value = text  # Usa la risposta completa come diagnosi se non estratta

            elif field.endswith(("_CORRETTO", "_CORRETTA")):

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
                test_ok, stdout, stderr, program_out = run_tests(exercise_dir)
                warnings = run_static_analysis(exercise_dir)

                if not compile_ok:
                    failure = "compile_error"
                elif not test_ok:
                    failure = "dynamic_check_failed"
                elif warnings:
                    failure = "static_check_failed"
                else:
                    failure = "correct"

                # Bilancia: preferisci commit non corretto se ci sono più corretti, viceversa
                if (failure == "correct" and incorrect_count > correct_count) or (failure != "correct" and correct_count >= incorrect_count):
                    selected_commit = commit
                    break

            if selected_commit is None:
                # Se nessun commit selezionato, usa l'ultimo
                selected_commit = commits[0] if commits else "HEAD"
                checkout_head(exercise_dir) if selected_commit == "HEAD" else checkout_commit(exercise_dir, selected_commit)
                compile_ok, compile_log = compile_exercise(exercise_dir)
                test_ok, stdout, stderr, program_out = run_tests(exercise_dir)
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

            if failure == "dynamic_check_failed":
                # LLM primario per output e codice
                # use the actual program output (collected by run_tests) rather than
                # the script's pass/fail message
                resp_output = query_model(prompt_output(readme, program_out), PRIMARY_MODEL)
                resp_code = query_model(prompt_codice(readme, program_out, code), PRIMARY_MODEL)

                # Parsing robusto delle risposte
                fields_output = parse_response(resp_output, ["OUTPUT_CORRETTO", "DIAGNOSI_OUTPUT"])
                fields_code = parse_response(resp_code, ["CODICE_CORRETTO", "DIAGNOSI_CODICE"])

                output_corr = fields_output.get("OUTPUT_CORRETTO", "")
                diag_output = fields_output.get("DIAGNOSI_OUTPUT", "")

                code_corr = fields_code.get("CODICE_CORRETTO", "")
                diag_code = fields_code.get("DIAGNOSI_CODICE", "")

                # Giudice per output - solo se abbiamo una diagnosi
                judge_out_ok = ""
                if diag_output:
                    judge_out = query_model(prompt_giudice_output(diag_output, stdout), JUDGE_MODEL)
                    judge_out_ok = extract_field(judge_out, "DIAGNOSI_CORRETTA")
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
                    solution_code = '\n\n'.join(sol_snippets)
                    
                    judge_code = query_model(prompt_giudice_codice(diag_code, warnings, code_around, solution_code), JUDGE_MODEL)
                    judge_code_ok = extract_field(judge_code, "DIAGNOSI_CORRETTA")
                    if not judge_code_ok:
                        judge_code_ok = extract_yes_no_anywhere(judge_code)

            elif failure == "static_check_failed":
                # LLM primario per output e codice
                resp_output = query_model(prompt_output(readme, program_out), PRIMARY_MODEL)
                resp_code = query_model(prompt_codice(readme, program_out, code), PRIMARY_MODEL)

                # Parsing robusto delle risposte
                fields_output = parse_response(resp_output, ["OUTPUT_CORRETTO", "DIAGNOSI_OUTPUT"])
                fields_code = parse_response(resp_code, ["CODICE_CORRETTO", "DIAGNOSI_CODICE"])

                output_corr = fields_output.get("OUTPUT_CORRETTO", "")
                diag_output = fields_output.get("DIAGNOSI_OUTPUT", "")

                code_corr = fields_code.get("CODICE_CORRETTO", "")
                diag_code = fields_code.get("DIAGNOSI_CODICE", "")

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
                    judge_code_ok = extract_field(judge_code, "DIAGNOSI_CORRETTA")
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

            result = {
                "student": student_name,
                "exercise": exercise_dir.name,
                "commit_analyzed": selected_commit,

                "failure_category": failure,

                "compile_success": compile_ok,
                "test_success": test_ok,

                # script stdout remains for backwards compatibility
                "stdout": stdout,
                "stderr": stderr,
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