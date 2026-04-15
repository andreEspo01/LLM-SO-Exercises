import os
import subprocess
import requests
import json
import re
from pathlib import Path
from datetime import datetime
from gitingest import ingest

# ================= CONFIG =================

BASE_SUBMISSIONS_DIR = "/home/andre/esercitazione-5-server-multithread-submissions"
GROUND_TRUTH_DIR = "/home/andre/ground_truth_es5"
MAX_STUDENTS = 25  # Metti None per processarli tutti, oppure un numero intero

PRIMARY_MODEL = "llama3:8b"
JUDGE_MODEL = "llama3:8b"
OLLAMA_URL = "http://localhost:11434/api/generate"

COMPILE_TIMEOUT = 120
TEST_TIMEOUT = 120
LLM_CONNECT_TIMEOUT = 30
LLM_READ_TIMEOUT = 1500

OUTPUT_FILE = "risultati_llm_exp1.0.json"

# ==========================================

def log(msg):
    print(f"[{datetime.now().strftime('%H:%M:%S')}] {msg}")

# ================= GITINGEST =================

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

# ================= TBD EXTRACTION =================

def extract_function_block(lines, start_index):
    start_func = None
    for i in range(start_index, -1, -1):
        if "{" in lines[i]:
            start_func = i
            break

    if start_func is None:
        return None

    brace_balance = 0
    end_func = None

    for i in range(start_func, len(lines)):
        brace_balance += lines[i].count("{")
        brace_balance -= lines[i].count("}")
        if brace_balance == 0:
            end_func = i
            break

    if end_func is None:
        return None

    return "\n".join(lines[start_func:end_func+1])

def collect_tbd_code(path):
    blocks = []
    for root, dirs, files in os.walk(path):
        dirs[:] = [d for d in dirs if not d.startswith(".")]
        for file in files:
            if not file.endswith(".c"):
                continue
            full = Path(root, file)
            try:
                lines = full.read_text(errors="ignore").splitlines()
                for idx, line in enumerate(lines):
                    if "TBD" in line:
                        function_block = extract_function_block(lines, idx)
                        if function_block:
                            blocks.append(
                                f"FILE: {file}\n"
                                f"LINEA_INIZIO: {idx+1}\n"
                                f"{function_block}"
                            )
                        else:
                            blocks.append(
                                f"FILE: {file}\n"
                                f"LINEA_INIZIO: {idx+1}\n"
                                f"{line}"
                            )
            except:
                pass

    if not blocks:
        return ""
    return "\n\n".join(blocks)

# ================= FILES =================

def read_readme(path):
    readme_path = path / "readme.md"
    if readme_path.exists():
        return readme_path.read_text(errors="ignore")
    return "Traccia non disponibile."

# ================= COMPILAZIONE & TEST =================

def compile_exercise(path):
    try:
        result = subprocess.run(
            ["make"], cwd=path, capture_output=True, text=True, timeout=COMPILE_TIMEOUT
        )
        return result.returncode == 0
    except:
        return False

def run_tests(path):
    test_dir = path / ".test"
    if not test_dir.exists():
        return False, "", "No .test directory"

    scripts = list(test_dir.glob("*.sh"))
    if not scripts:
        return False, "", "No test script"

    try:
        res = subprocess.run(
            ["bash", scripts[0].name], cwd=test_dir, stdout=subprocess.PIPE,
            stderr=subprocess.PIPE, text=True, timeout=TEST_TIMEOUT
        )
        return (res.returncode == 0, res.stdout, res.stderr)
    except:
        return False, "", "Errore test"
    
# ================= GROUND TRUTH =================

def get_reference_exercise_path(exercise_name):
    ref_base = Path(GROUND_TRUTH_DIR)
    for d in ref_base.iterdir():
        if d.is_dir() and not d.name.startswith("."):
            if d.name.lower() == exercise_name.lower():
                return d
    return None

def normalize_output(text):
    return "\n".join(line.strip() for line in text.strip().splitlines() if line.strip())

def get_reference_output(exercise_name):
    ref_path = get_reference_exercise_path(exercise_name)
    if not ref_path: return None
    test_ok, stdout, stderr = run_tests(ref_path)
    if not test_ok: return None
    return normalize_output(stdout)

# ================= STATIC COMPARISON =================

def normalize_code_block(code):
    code = re.sub(r"//.*", "", code)
    code = re.sub(r"/\*.*?\*/", "", code, flags=re.DOTALL)
    code = re.sub(r"\s+", " ", code)
    return code.strip()

def extract_tbd_blocks(path):
    raw = collect_tbd_code(path)
    if not raw: return []
    blocks = []
    split_blocks = raw.split("FILE:")
    for block in split_blocks:
        block = block.strip()
        if not block: continue
        lines = block.splitlines()
        code_lines = [line for line in lines if not line.startswith(("LINEA_INIZIO", "FILE"))]
        cleaned = normalize_code_block("\n".join(code_lines))
        if cleaned: blocks.append(cleaned)
    return blocks

def compare_static_code(student_path, exercise_name):
    ref_path = get_reference_exercise_path(exercise_name)
    if not ref_path: return False
    student_blocks = extract_tbd_blocks(student_path)
    reference_blocks = extract_tbd_blocks(ref_path)
    if not reference_blocks: return False
    return set(student_blocks) == set(reference_blocks)

# ================= LLM QUERY OTTIMIZZATA =================
def query_model(prompt, model, max_chars=15000):
    """
    Limita la lunghezza del prompt e gestisce timeout.
    """
    if len(prompt) > max_chars:
        prompt = prompt[:max_chars] + "\n...<TRUNCATED>..."

    payload = {
        "model": model,
        "prompt": prompt,
        "stream": False,
        "options": {"temperature": 0.0, "top_p": 0.1, "num_predict": 800}
    }
    try:
        r = requests.post(
            OLLAMA_URL,
            json=payload,
            timeout=(LLM_CONNECT_TIMEOUT, LLM_READ_TIMEOUT)
        )
        r.raise_for_status()
        return r.json().get("response", "")
    except requests.exceptions.Timeout:
        log(f"Timeout LLM ({model}) - prompt troppo grande o modello lento.")
        return "LLM_TIMEOUT"
    except Exception as e:
        log(f"Errore LLM ({model}): {e}")
        return "LLM_ERROR"

# ================= PROMPT OTTIMIZZATI =================
def build_dynamic_prompt(readme: str, stdout: str, stderr: str) -> str:
    MAX_LINES = 100
    stdout_lines = "\n".join(stdout.strip().splitlines()[-MAX_LINES:])
    stderr_lines = "\n".join(stderr.strip().splitlines()[-MAX_LINES:])
    return f"""SEI UN ANALIZZATORE DETERMINISTICO.
Rispondi a 2 domande:
1) Il programma ESEGUE correttamente? (SI/NO)
2) Qual è la DIAGNOSI basata SOLO su stdout/stderr?
Formato OBBLIGATORIO di risposta:
ESECUZIONE_CORRETTA: SI oppure NO
DIAGNOSI: <massimo 3 righe>
### TRACCIA ###
{readme}
### STDOUT ###
{stdout_lines}
### STDERR ###
{stderr_lines}
"""

# ================= LLM STATICO AGGIORNATO =================
def build_static_prompt(readme: str, tbd_blocks: str) -> str:
    """
    L'LLM vede solo i blocchi TBD e verifica che siano logicamente corretti,
    non solo se presenti.
    """
    MAX_CODE = 4000
    prompt = f"""
SEI UN  ANALIZZATORE DETERMINISTICO.

ATTENZIONE:
- Devi valutare i blocchi TBD nel codice.
- Non solo verifica se i blocchi sono presenti, ma assicurati che ogni blocco TBD
  sia logicamente corretto e coerente con la traccia.
- Se i blocchi non sono corretti, considera il codice come NON corretto.

Formato OBBLIGATORIO di risposta:

CODICE_CORRETTO: SI oppure NO
DIAGNOSI: <max 2 righe, solo violazioni reali>
FILE: <nome file o N/A>
LINEA: <numero o N/A>

### TRACCIA ###
{readme}

### BLOCCI TBD ###
{tbd_blocks if tbd_blocks else 'NESSUN BLOCCO TBD'}
"""
    if len(prompt) > MAX_CODE:
        prompt = prompt[:MAX_CODE] + "\n...<TRUNCATED>..."
    return prompt

# ================= PROMPT GIUDICE AGGIORNATO =================
def build_judge_prompt(true_cause: str,
                       true_dynamic: bool,
                       true_static: bool,
                       llm_exec_esito: str,
                       llm_exec_diag: str,
                       llm_code_esito: str,
                       llm_code_diag: str) -> str:

    # Determina quale esito fornire in base alla causa vera
    if true_cause == "dynamic":
        # Fornire l'esito dinamico "vero"
        llm_esito = llm_exec_esito
        llm_diag = llm_exec_diag
    elif true_cause == "static":
        # Fornire l'esito statico "vero"
        llm_esito = llm_code_esito
        llm_diag = llm_code_diag
    else:
        # Caso di compilazione fallita, esito NO e motivazione
        llm_esito = "NO"
        llm_diag = "Errore di compilazione, codice non compilato."

    return f"""
SEI UN GIUDICE DETERMINISTICO.

GROUND TRUTH:
ESECUZIONE_CORRETTA: {"SI" if true_dynamic else "NO"}
CODICE_CORRETTO: {"SI" if true_static else "NO"}

RISPOSTA LLM:
ESECUZIONE: {llm_exec_esito}
DIAGNOSI_ESECUZIONE: {llm_exec_diag}
CODICE: {llm_code_esito}
DIAGNOSI_CODICE: {llm_code_diag}

Richiesta:
Verifica se l'LLM ha classificato correttamente la causa principale (dinamico o statico) del programma rispetto alla ground truth fornita: {true_cause}.

Formato OBBLIGATORIO di risposta:
CLASSIFICAZIONE_CORRETTA: SI oppure NO
MOTIVAZIONE: <massimo 3 righe>
"""
# ================= PARSING & UTILS =================

def clean_llm_output(text):
    return text.replace("**", "").replace("```", "").strip()

def extract_field(text: str, field: str) -> str:
    pattern = rf"{field}\s*:\s*(.+)"
    match = re.search(pattern, text, re.IGNORECASE)
    if match:
        return match.group(1).strip()
    return ""

def extract_student_name(folder_name):
    prefix = "esercitazione-5-server-multithread-"
    if folder_name.startswith(prefix): return folder_name[len(prefix):]
    return folder_name

def load_existing_results():
    if Path(OUTPUT_FILE).exists():
        try:
            with open(OUTPUT_FILE, "r") as f: return json.load(f)
        except: return []
    return []

def save_results(results):
    tmp_file = OUTPUT_FILE + ".tmp"
    with open(tmp_file, "w") as f: json.dump(results, f, indent=4)
    os.replace(tmp_file, OUTPUT_FILE)

# ================= TRUE CAUSE =================

def determine_true_static(student_path, exercise_name, compile_ok):
    if not compile_ok: return False
    return compare_static_code(student_path, exercise_name)

# ================= GIT UTILITIES =================

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

def main():
    base = Path(BASE_SUBMISSIONS_DIR)
    results = load_existing_results()
    already_done = {(r["student"], r["exercise"]) for r in results}

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

            commits = get_commits(exercise_dir)[:2]  # LIMITATI A 2 COMMITS PER ESECUZIONE

            selected_data = None
            selected_true_cause = None
            selected_commit = None

            for commit in commits:

                checkout_commit(exercise_dir, commit)

                compile_ok = compile_exercise(exercise_dir)
                test_ok, stdout, stderr = run_tests(exercise_dir)
                readme = read_readme(exercise_dir)

                reference_output = get_reference_output(exercise_dir.name)

                if reference_output is not None:
                    true_dynamic = normalize_output(stdout) == reference_output
                else:
                    true_dynamic = test_ok

                true_static = determine_true_static(exercise_dir, exercise_dir.name, compile_ok)

                if not compile_ok:
                    true_cause = "compile"
                elif not true_dynamic:
                    true_cause = "dynamic"
                elif not true_static:
                    true_cause = "static"
                else:
                    true_cause = "none"

                if true_cause != "none":
                    selected_data = (compile_ok, test_ok, stdout, stderr, readme)
                    selected_true_cause = true_cause
                    selected_commit = commit
                    break

                if selected_data is None:
                    selected_data = (compile_ok, test_ok, stdout, stderr, readme)
                    selected_true_cause = true_cause
                    selected_commit = commit

            if selected_data is None:
                continue

            checkout_commit(exercise_dir, selected_commit)

            compile_ok, test_ok, stdout, stderr, readme = selected_data
            true_cause = selected_true_cause

            # SALTA TUTTO SE CORRETTO
            if true_cause == "none":
                result_entry = {
                    "student": student_name,
                    "exercise": exercise_dir.name,
                    "commit_analyzed": selected_commit,
                    "compile_success": compile_ok,
                    "test_success": test_ok,
                    "true_cause": true_cause,
                    "llm_esecuzione_corretta": "SI",
                    "llm_diagnosi_esecuzione": "Programma corretto.",
                    "llm_codice_corretto": "SI",
                    "llm_diagnosi_codice": "Programma corretto.",
                    "errore_file": "N/A",
                    "errore_linea": "N/A",
                    "judge_corretto": "SI",
                    "judge_motivazione": "Caso corretto."
                }
                results.append(result_entry)
                already_done.add((student_name, exercise_dir.name))
                save_results(results)
                checkout_head(exercise_dir)
                continue

            # ===== LLM DYNAMIC =====
            dyn_prompt = build_dynamic_prompt(readme, stdout, stderr)
            dyn_response = clean_llm_output(query_model(dyn_prompt, PRIMARY_MODEL))
            llm_dyn = extract_field(dyn_response, "ESECUZIONE_CORRETTA")
            diag_dyn = extract_field(dyn_response, "DIAGNOSI")

            if llm_dyn not in ["SI", "NO"]:
                llm_dyn = "NO"

            # ===== LLM STATIC SEMPRE ESEGUITO, ANCHE SE FALLIMENTO DINAMICO =====

            tbd_blocks = collect_tbd_code(exercise_dir)
            stat_prompt = build_static_prompt(readme, tbd_blocks)
            stat_response = clean_llm_output(query_model(stat_prompt, PRIMARY_MODEL))

            llm_stat = extract_field(stat_response, "CODICE_CORRETTO")
            diag_stat = extract_field(stat_response, "DIAGNOSI")
            file_loc = extract_field(stat_response, "FILE")
            line_loc = extract_field(stat_response, "LINEA")

            # fallback se LLM non risponde correttamente
            if llm_stat not in ["SI", "NO"]:
                llm_stat = "NO"
                diag_stat = diag_stat or "Diagnosi LLM non disponibile."
            if llm_stat == "SI":
                file_loc = "N/A"
                line_loc = "N/A"
            else:
                if not file_loc or file_loc == "ERR":
                    file_loc = "N/A"
                if not line_loc or line_loc == "ERR":
                    line_loc = "N/A"

            # ===== GIUDICE =====

            judge_prompt = build_judge_prompt(
                true_cause,
                true_dynamic,
                true_static,
                llm_dyn,
                diag_dyn,
                llm_stat,
                diag_stat
            )

            judge_raw = clean_llm_output(query_model(judge_prompt, JUDGE_MODEL))

            # Estrai la risposta del modello per il giudice
            judge_classification = extract_field(judge_raw, "CLASSIFICAZIONE_CORRETTA")
            judge_motivazione = extract_field(judge_raw, "MOTIVAZIONE")

            # Se il modello non fornisce una risposta valida, impostiamo valori di fallback
            if judge_classification not in ["SI", "NO"]:
                judge_classification = "NO"
                judge_motivazione = "Risposta judge non conforme al formato richiesto."

            result_entry = {
                "student": student_name,
                "exercise": exercise_dir.name,
                "commit_analyzed": selected_commit,
                "compile_success": compile_ok,
                "test_success": test_ok,
                "true_cause": true_cause,
                "llm_esecuzione_corretta": llm_dyn,
                "llm_diagnosi_esecuzione": diag_dyn,
                "llm_codice_corretto": llm_stat,
                "llm_diagnosi_codice": diag_stat,
                "errore_file": file_loc,
                "errore_linea": line_loc,
                "judge_corretto": judge_classification,
                "judge_motivazione": judge_motivazione
            }

            results.append(result_entry)
            already_done.add((student_name, exercise_dir.name))
            save_results(results)

            checkout_head(exercise_dir)
    log("FINISHED - Tutti gli studenti analizzati.")

if __name__ == "__main__":
    main()