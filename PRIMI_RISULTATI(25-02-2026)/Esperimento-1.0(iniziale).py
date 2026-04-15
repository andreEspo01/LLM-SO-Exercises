import os
import re
import subprocess
import requests
import json
import yaml
from pathlib import Path
from datetime import datetime


# ================= CONFIG =================

BASE_SUBMISSIONS_DIR = "/home/andre/esercitazione-5-server-multithread-submissions"
MAX_STUDENTS = 110

PRIMARY_MODEL = "llama3:8b"
JUDGE_MODEL = "llama3:8b"

OLLAMA_URL = "http://localhost:11434/api/generate"

MAX_README_CHARS = 1200
MAX_CODE_CHARS = 1200
MAX_STDOUT_CHARS = 500
MAX_STDERR_CHARS = 400

COMPILE_TIMEOUT = 120
TEST_TIMEOUT = 120
LLM_CONNECT_TIMEOUT = 30
LLM_READ_TIMEOUT = 900

OUTPUT_FILE = "risultati_llm_exp1_with_judge.json"

# ==========================================

def log(msg):
    print(f"[{datetime.now().strftime('%H:%M:%S')}] {msg}")


# ================= YAML RULE EXTRACTION =================

def extract_yaml_rules(test_dir):
    rules = []
    for yml in test_dir.glob("*.yml"):
        try:
            data = yaml.safe_load(yml.read_text())
            rules.append(data)
        except:
            pass
    return rules


def format_rules_for_prompt(rules):
    text = ""
    for i, rule in enumerate(rules):
        text += f"\n--- REGOLA {i+1} ---\n"
        text += json.dumps(rule, indent=2)
    return text if text else "Nessuna regola disponibile."


# ================= COMPILAZIONE =================

def compile_exercise(path):
    try:
        result = subprocess.run(
            ["make"],
            cwd=path,
            capture_output=True,
            text=True,
            timeout=COMPILE_TIMEOUT
        )
        return result.returncode == 0
    except:
        return False


# ================= TEST =================

def run_tests(exercise_path):

    test_dir = exercise_path / ".test"

    if not test_dir.exists():
        return False, "", "No .test directory", []

    rules = extract_yaml_rules(test_dir)

    test_scripts = list(test_dir.glob("*.sh"))
    if not test_scripts:
        return False, "", "No test script", rules

    test_script = test_scripts[0]

    try:
        result = subprocess.run(
            ["bash", test_script.name],
            cwd=test_dir,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            timeout=TEST_TIMEOUT
        )

        return (
            result.returncode == 0,
            result.stdout[:MAX_STDOUT_CHARS],
            result.stderr[:MAX_STDERR_CHARS],
            rules
        )

    except subprocess.TimeoutExpired:
        return False, "", "Test timeout", rules
    except Exception as e:
        return False, "", str(e), rules


# ================= FILE READING =================

def read_readme(path):
    readme_path = path / "readme.md"
    if readme_path.exists():
        return readme_path.read_text(errors="ignore")[:MAX_README_CHARS]
    return "Traccia non disponibile."


def collect_code(path):
    code = ""
    for root, _, files in os.walk(path):
        if ".test" in root:
            continue
        for file in files:
            if file.endswith(".c") or file.endswith(".h"):
                try:
                    full_path = Path(root, file)
                    content = full_path.read_text(errors="ignore")
                    code += f"\n--- FILE: {file} ---\n"
                    code += content
                except:
                    pass
    return code[:MAX_CODE_CHARS]


# ================= PRIMARY PROMPT =================

def build_primary_prompt(readme, code, stdout, stderr):

    return f"""
SEI UN ANALIZZATORE DETERMINISTICO.

Rispondi a 3 domande:

1) Il programma ESEGUE correttamente? (SI/NO)
2) Qual è la DIAGNOSI basata SOLO su stdout/stderr?
3) Se errore, indica FILE + LINEA + SNIPPET precisi.

NON fare code review generale.
NON inventare problemi non visibili nell'output.

Formato OBBLIGATORIO:

ESECUZIONE_CORRETTA: SI oppure NO
DIAGNOSI:
(max 6 righe)
LOCALIZZAZIONE:
File:
Linea:
Snippet:

### TRACCIA ###
{readme}

### STDOUT ###
{stdout}

### STDERR ###
{stderr}

### CODICE ###
{code}
"""


# ================= JUDGE PROMPT =================

def build_judge_prompt(stdout, stderr, rules,
                       diagnosi, localizzazione):

    rules_text = format_rules_for_prompt(rules)

    return f"""
SEI UN GIUDICE DETERMINISTICO AUTOMATICO.

DEVI RISPONDERE SOLO CON IL FORMATO SPECIFICATO.
SE NON RISPETTI IL FORMATO LA RISPOSTA È CONSIDERATA ERRATA.

NON aggiungere testo prima o dopo.
NON usare spiegazioni fuori formato.
NON usare markdown.

Verifica:

1) Se la DIAGNOSI è coerente con stdout/stderr e con le regole YAML.
2) Se la LOCALIZZAZIONE è verificabile.

NON usare markdown.
Formato OBBLIGATORIO:

DIAGNOSI_CORRETTA: SI oppure NO
LOCALIZZAZIONE_CORRETTA: SI oppure NO oppure NON_VERIFICABILE
MOTIVAZIONE_GIUDICE:
(max 4 righe)

### REGOLE YAML ###
{rules_text}

### STDOUT ###
{stdout}

### STDERR ###
{stderr}

### DIAGNOSI LLM ###
{diagnosi}

### LOCALIZZAZIONE LLM ###
{localizzazione}
"""


# ================= LLM CALL ROBUSTA =================

def query_model(prompt, model):

    payload = {
        "model": model,
        "prompt": prompt,
        "stream": False,
        "options": {
            "temperature": 0.0,
            "top_p": 0.1,
            "num_predict": 200
        }
    }

    try:
        response = requests.post(
            OLLAMA_URL,
            json=payload,
            timeout=(LLM_CONNECT_TIMEOUT, LLM_READ_TIMEOUT)
        )
        response.raise_for_status()
        return response.json().get("response", "")

    except requests.exceptions.ReadTimeout:
        log("LLM TIMEOUT")
        return "TIMEOUT_LLM"

    except Exception as e:
        log(f"ERRORE LLM: {e}")
        return "ERRORE_LLM"


# ================= PARSING =================

def extract_primary(text):

    if text in ["TIMEOUT_LLM", "ERRORE_LLM"]:
        return "TIMEOUT", "LLM non ha risposto", "N/A"

    esec = re.search(r"ESECUZIONE_CORRETTA:\s*(SI|NO)", text, re.I)
    diag = re.search(r"DIAGNOSI:\s*(.*?)\nLOCALIZZAZIONE:", text, re.S | re.I)
    loc = re.search(r"LOCALIZZAZIONE:\s*(.*)", text, re.S | re.I)

    return (
        esec.group(1).upper() if esec else "NON_RICONOSCIUTO",
        diag.group(1).strip() if diag else "",
        loc.group(1).strip() if loc else ""
    )


def extract_judge(text):

    if text in ["TIMEOUT_LLM", "ERRORE_LLM"]:
        return "TIMEOUT", "TIMEOUT", "Judge non ha risposto"

    text_upper = text.upper()

    # Diagnosi
    if "DIAGNOSI_CORRETTA" in text_upper:
        d_match = re.search(r"DIAGNOSI_CORRETTA.*?(SI|NO)", text_upper)
        diagnosi = d_match.group(1) if d_match else "FORMATO_ERRATO"
    else:
        diagnosi = "FORMATO_ERRATO"

    # Localizzazione
    if "LOCALIZZAZIONE_CORRETTA" in text_upper:
        l_match = re.search(r"LOCALIZZAZIONE_CORRETTA.*?(SI|NO|NON_VERIFICABILE)", text_upper)
        localizzazione = l_match.group(1) if l_match else "FORMATO_ERRATO"
    else:
        localizzazione = "FORMATO_ERRATO"

    # Motivazione
    mot_match = re.search(r"MOTIVAZIONE_GIUDICE:\s*(.*)", text, re.S | re.I)
    motivazione = mot_match.group(1).strip() if mot_match else ""

    return diagnosi, localizzazione, motivazione


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

            compile_ok = compile_exercise(exercise_dir)
            test_ok, stdout, stderr, rules = run_tests(exercise_dir)

            readme = read_readme(exercise_dir)
            code = collect_code(exercise_dir)

            # PRIMARY
            primary_prompt = build_primary_prompt(readme, code, stdout, stderr)
            primary_response = query_model(primary_prompt, PRIMARY_MODEL)
            esecuzione, diagnosi, localizzazione = extract_primary(primary_response)

            # JUDGE
            judge_prompt = build_judge_prompt(
                stdout, stderr, rules,
                diagnosi, localizzazione
            )
            judge_response = query_model(judge_prompt, JUDGE_MODEL)
            diagnosi_corr, localizz_corr, judge_mot = extract_judge(judge_response)

            result_entry = {
                "student": student_name,
                "exercise": exercise_dir.name,
                "compile_success": compile_ok,
                "test_success": test_ok,
                "llm_esecuzione_corretta": esecuzione,
                "llm_diagnosi": diagnosi,
                "llm_localizzazione": localizzazione,
                "judge_diagnosi_corretta": diagnosi_corr,
                "judge_localizzazione_corretta": localizz_corr,
                "judge_motivazione": judge_mot
            }

            results.append(result_entry)
            already_done.add((student_name, exercise_dir.name))

            # Salvataggio sicuro incrementale
            save_results(results)

    log("FINISHED")


if __name__ == "__main__":
    main().
	
Devo sistemarlo con questi accorgimenti: LLM judge -> eseguire test (check dinamico + check statico), dare solo l'output dei check al judge (non YAML intero) 
 
dividere esito in
- esecuzione (output) corretta
- codice corretto
 
per valutazione, bilanciare corretti e non corretti (si può prendere l'ultimo non-corretto)
 
analizzare i singoli esercizi (non tutto il repo insieme, ma le cartelle singolarmente)
 
tenere traccia di quale è la vera causa di malfunzionamento del codice dello studente (fallimento check dinamico oppure check statico)
 
per il judge, forniamo l'esito "vero" della analisi dinamica oppure della analisi statica, a seconda di quale sia il problema "vero" del programma dello studente. 
Inoltre mi è stato consigliato di usare Gitingest ma non ho capito in che modo.