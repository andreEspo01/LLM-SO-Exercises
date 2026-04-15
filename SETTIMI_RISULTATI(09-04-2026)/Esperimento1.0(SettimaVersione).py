from email.mime import text
import os
import subprocess
from unittest import result
import requests
import json
import re
import random
import difflib
import hashlib
import shutil
import tempfile
import time
import logging
from pathlib import Path
from datetime import datetime

# ================= CONFIG =================

BASE_SUBMISSIONS_DIR = "/home/andre/esercitazione-5-server-multithread-submissions"
GROUND_TRUTH_DIR = "/home/andre/ground_truth_es5"
OLLAMA_URL = "http://localhost:11434/api/generate"

# Modelli Groq
PRIMARY_MODEL = "meta-llama/llama-4-scout-17b-16e-instruct"  # modello principale per analisi (groq oppure locale, Ollama)
JUDGE_MODEL   = "meta-llama/llama-4-scout-17b-16e-instruct" # modello giudice per valutare la qualità delle diagnosi (sempre Groq, senza fallback)

COMPILE_TIMEOUT = 120
TEST_TIMEOUT = 120

LLM_CONNECT_TIMEOUT = 60
LLM_READ_TIMEOUT = 2000

OUTPUT_FILE = "risultati_es5.json"
LOG_SAMPLE_DIR = "experiment_logs"
LLM_CACHE_FILE = "llm_cache.json"

MAX_STUDENTS = 105  # Per limitare il numero di studenti analizzati (None per tutti)

# ==========================================

def log(msg):
    print(f"[{datetime.now().strftime('%H:%M:%S')}] {msg}")

# ================= LLM =================
import re
import time

PRIMARY_SYSTEM_PROMPT = (
    "You analyze student C solutions for Operating Systems exercises. "
    "Use only the provided evidence. "
    "Do not invent hidden requirements, hidden expected values, invisible code paths, or unsupported causes. "
    "Prefer conservative, evidence-based judgments. "
    "Do not overclaim correctness from partial traces, later side effects, or loosely related code details. "
    "Keep the boolean field and diagnosis consistent. "
    "Write diagnoses in English, using at most 100 words. "
    "Return exactly the requested fields."
)

JUDGE_SYSTEM_PROMPT = (
    "You are a strict semantic grader. "
    "Accept only diagnoses that match the same concrete symptom or defect as the ground truth. "
    "Reject generic, speculative, partially related, unsupported, or different diagnoses. "
    "When the ground truth is generic, do not promote it into a more specific diagnosis. "
    "When the ground truth says the submission is correct, accept concise no-defect diagnoses unless they invent a problem. "
    "Return exactly the requested field."
)

def dedupe_models(models):
    ordered = []
    for model in models:
        if model not in ordered:
            ordered.append(model)
    return ordered

try:
    with open(LLM_CACHE_FILE, "r", encoding="utf-8") as f:
        LLM_CACHE = json.load(f)
except:
    LLM_CACHE = {}

CURRENT_MODEL_USAGE = {"PRIMARY": "llama3:8b", "JUDGE": "meta-llama/llama-4-scout-17b-16e-instruct"}
MODEL_REQUEST_TOKEN_LIMITS = {
    "qwen/qwen3-32b": 40960,                 # max completion tokens
    "openai/gpt-oss-20b": 65536,            # max completion tokens
    "meta-llama/llama-4-scout-17b-16e-instruct": 8192,  # max completion tokens
    "llama-3.3-70b-versatile": 32768,       # max completion tokens
    "openai/gpt-oss-120b": 65536,           # max completion tokens
}

DISABLED_MODELS = {}
ROLE_DISABLED_MODELS = {"PRIMARY": set(), "JUDGE": set()}

def reset_model_usage():
    CURRENT_MODEL_USAGE["PRIMARY"] = ""
    CURRENT_MODEL_USAGE["JUDGE"] = ""
    ROLE_DISABLED_MODELS["PRIMARY"].clear()
    ROLE_DISABLED_MODELS["JUDGE"].clear()


def get_used_models(role):
    return CURRENT_MODEL_USAGE.get(role, "")


def system_prompt_for(model):
    if model == JUDGE_MODEL:
        return JUDGE_SYSTEM_PROMPT
    return PRIMARY_SYSTEM_PROMPT

def system_prompt_for_role(logical_role):
    if logical_role == "JUDGE":
        return JUDGE_SYSTEM_PROMPT
    return PRIMARY_SYSTEM_PROMPT

def cache_key_for(model, system_prompt, prompt, max_completion_tokens):
    digest = hashlib.sha256(
        f"{model}\n{max_completion_tokens}\n{system_prompt}\n{prompt}".encode("utf-8", errors="ignore")
    ).hexdigest()
    return digest

def load_cached_response(model, system_prompt, prompt, max_completion_tokens):
    key = cache_key_for(model, system_prompt, prompt, max_completion_tokens)
    return LLM_CACHE.get(key)

def save_cached_response(model, system_prompt, prompt, max_completion_tokens, response):
    key = cache_key_for(model, system_prompt, prompt, max_completion_tokens)
    LLM_CACHE[key] = response
    try:
        with open(LLM_CACHE_FILE, "w", encoding="utf-8") as f:
            json.dump(LLM_CACHE, f)
    except:
        pass

def groq_safe_call(fn, prompt, model, system_prompt, max_completion_tokens=None):

    MAX_RETRIES = 3
    retries = 0

    while retries < MAX_RETRIES:
        try:
            return fn(prompt, model, system_prompt)

        except Exception as e:
            msg = str(e)

            # TPD LIMIT
            if "tokens per day" in msg:
                m = re.search(r"try again in ([0-9.]+)s", msg)
                wait = float(m.group(1)) if m else 60
                retries += 1
                print(f"[TPD WAIT] {model} → sleeping {wait:.2f}s (retry {retries}/{MAX_RETRIES})")
                time.sleep(wait + 2)
                continue

            # PROMPT TOO LARGE
            if "Request too large" in msg or "reduce your message size" in msg:
                raise Exception(f"PROMPT_TOO_LARGE::{msg}")

            # RATE LIMIT BREVE
            m = re.search(r"try again in ([0-9.]+)s", msg)
            if m:
                wait = float(m.group(1))
                if wait <= 10:
                    retries += 1
                    print(f"[RATE WAIT] sleeping {wait:.2f}s")
                    time.sleep(wait)
                    continue
                else:
                    # questo modello ora va messo in cooldown, prova un altro
                    raise Exception(f"MODEL_RATE_LIMIT::{msg}")

            # fallback → errore reale
            raise


def query_groq(prompt, model, system_prompt):
    """
    Interrogazione a Groq AI (aggiornata con endpoint corretto)
    """
    try:
        headers = {
            "Authorization": f"Bearer {os.getenv('GROQ_API_KEY')}",
            "Content-Type": "application/json"
        }

        payload = {
            "model": model,
            "messages": [
                {
                    "role": "system",
                    "content": system_prompt,
                },
                {"role": "user", "content": prompt},
            ],
            "temperature": 0.0
        }

        # Nuovo endpoint API Groq
        r = requests.post(
            "https://api.groq.com/openai/v1/chat/completions",
            headers=headers,
            json=payload,
            timeout=(LLM_CONNECT_TIMEOUT, LLM_READ_TIMEOUT)
        )

        data = r.json()

        if "choices" not in data:
            raise Exception(data)

        return data["choices"][0]["message"]["content"]

    except Exception as e:
        raise Exception(f"GROQ ERROR: {e}")

def query_model_local(prompt, model):
    payload = {
        "model": model,
        "prompt": prompt,
        "max_tokens": 600,
        "temperature": 0.0,
        "top_p": 0.1,
    }
    try:
        r = requests.post(
            OLLAMA_URL,
            json=payload,
            timeout=(LLM_CONNECT_TIMEOUT, LLM_READ_TIMEOUT)
        )

        response_text = ""
        # ogni riga è un JSON separato
        for line in r.text.splitlines():
            if not line.strip():
                continue
            try:
                chunk = json.loads(line)
                response_text += chunk.get("response", "")
            except Exception as e:
                print("DEBUG parse chunk failed:", e, "line:", line)

        #print("DEBUG LLM FULL RESPONSE:", response_text)
        return response_text or "ERRORE_LLM"

    except Exception as e:
        print("DEBUG Ollama ERROR:", e)
        return "ERRORE_LLM"

def query_model(prompt, model, max_completion_tokens=None, retry_depth=0, max_total_wait=300, role="PRIMARY"):
    """
    Interroga modelli LLM usando sempre Groq, sia per PRIMARY_MODEL che JUDGE_MODEL.
    """
    if model not in {PRIMARY_MODEL, JUDGE_MODEL}:
        raise ValueError(f"Model {model} not supported in this configuration")

    system_prompt = system_prompt_for_role(role)

    response = groq_safe_call(
        query_groq,
        prompt,
        model,
        system_prompt
    )

    return response

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


def extract_compile_errors(compile_log, max_items=4):
    if not compile_log:
        return []

    errors = []
    for line in compile_log.splitlines():
        stripped = line.strip()
        if ": error:" in stripped:
            errors.append(stripped)

    return errors[:max_items]


# ================= STATIC ANALYSIS =================

def run_static_analysis(exercise_path: str):
    """
    Esegue Semgrep solo sui file .c corrispondenti ai file .yml nella cartella .test.
    Restituisce warnings strutturati {'file', 'line', 'message'} con nome file originale.
    """
    exercise_path = Path(exercise_path)
    test_dir = exercise_path / ".test"
    semgrep_json = Path("/tmp/semgrep.json")

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
        subprocess.run(["cp", str(c_file), str(preprocessed)], check=True)

        preprocessor = test_dir / "preprocessor.pl"
        if preprocessor.exists():
            subprocess.run(["perl", str(preprocessor), str(preprocessed)], check=True)

        # Esegui Semgrep sul file preprocessato
        try:
            res = subprocess.run(
                ["semgrep", "--json", "--config", str(yml_file), str(preprocessed)],
                cwd=exercise_path,
                capture_output=True,
                text=True,
                check=True
            )
            data = json.loads(res.stdout)
            for r in data.get("results", []):
                warnings.append({
                    # usa solo il nome originale del file .c
                    "file": c_file.name,
                    "line": r.get("start", {}).get("line", 0),
                    "message": r.get("extra", {}).get("message", "")
                })
        except subprocess.CalledProcessError:
            continue
        finally:
            if preprocessed.exists():
                preprocessed.unlink()

    return warnings

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

def add_line_numbers(content):
    lines = content.splitlines()
    width = max(3, len(str(len(lines))))
    return "\n".join(f"{i+1:>{width}}: {line}" for i, line in enumerate(lines))

def iter_source_files(root):
    ignore_parts = {".git", ".test", "__pycache__"}
    for file_path in sorted(root.rglob("*")):
        if not file_path.is_file():
            continue
        if file_path.suffix.lower() not in {".c", ".h"}:
            continue
        rel_parts = file_path.relative_to(root).parts
        if any(part in ignore_parts for part in rel_parts):
            continue
        yield file_path

def build_repo_view(exercise_path):
    try:
        sections = []
        for file_path in iter_source_files(exercise_path):
            rel_path = file_path.relative_to(exercise_path).as_posix()
            content = file_path.read_text(errors="ignore")
            sections.append(f"FILE: {rel_path}\n{add_line_numbers(content)}")
        if sections:
            return "\n\n".join(sections)
        return "No C source files were found in the exercise directory."
    except:
        return "Code not available."

def get_student_files(path):
    try:
        student_files = {}
        for file_path in iter_source_files(path):
            rel_path = file_path.relative_to(path).as_posix()
            content = file_path.read_text(errors="ignore")
            student_files[rel_path] = content
        return student_files
    except:
        return {}

def lookup_file_content(files_map, file_name):
    if not file_name:
        return None
    if file_name in files_map:
        return files_map[file_name]

    target = file_name.replace("\\", "/").lower()
    target_name = Path(file_name).name.lower()

    for key, content in files_map.items():
        key_norm = key.replace("\\", "/").lower()
        if key_norm == target or key_norm.endswith(f"/{target}") or Path(key_norm).name.lower() == target_name:
            return content
    return None

def extract_around(content, line, context=10):
    lines = content.splitlines()
    start = max(0, line - context - 1)
    end = min(len(lines), line + context)
    width = max(3, len(str(len(lines))))
    return '\n'.join(
        f"{idx+1:>{width}}: {lines[idx]}"
        for idx in range(start, end)
    )

def extract_span(content, start_line, end_line):
    lines = content.splitlines()
    start = max(0, start_line - 1)
    end = min(len(lines), end_line)
    width = max(3, len(str(len(lines))))
    return "\n".join(
        f"{idx+1:>{width}}: {lines[idx]}"
        for idx in range(start, end)
    )

def extract_identifiers(text):
    if not text:
        return []
    found = []
    seen = set()

    for token in re.findall(r"`([^`]+)`", text):
        token = token.strip()
        if token and token not in seen:
            seen.add(token)
            found.append(token)

    for token in re.findall(r"\b[a-zA-Z_][a-zA-Z0-9_]{2,}\b", text):
        low = token.lower()
        if low in {
            "the", "this", "that", "with", "from", "without", "because", "result",
            "code", "line", "lines", "file", "function", "thread", "process",
            "value", "values", "correct", "incorrect", "diagnosis", "student",
            "solution", "missing", "wrong", "uses", "using", "call", "calls"
        }:
            continue
        if token not in seen:
            seen.add(token)
            found.append(token)
        if len(found) >= 20:
            break
    return found

def extract_file_mentions(text):
    if not text:
        return []
    return re.findall(r"[\w./\\-]+\.(?:c|h)\b", text, flags=re.IGNORECASE)

def build_change_blocks(student_text, solution_text, file_label, identifiers=None, max_blocks=4, context=3):
    identifiers = identifiers or []
    s_lines = student_text.splitlines()
    sol_lines = solution_text.splitlines()
    sm = difflib.SequenceMatcher(None, s_lines, sol_lines)
    candidate_blocks = []

    for tag, i1, i2, j1, j2 in sm.get_opcodes():
        if tag == "equal":
            continue

        s_start = max(1, i1 + 1 - context)
        s_end = min(len(s_lines), i2 + context)
        sol_start = max(1, j1 + 1 - context)
        sol_end = min(len(sol_lines), j2 + context)
        student_snippet = extract_span(student_text, s_start, s_end)
        solution_snippet = extract_span(solution_text, sol_start, sol_end)
        combined = f"{student_snippet}\n{solution_snippet}".lower()
        score = 0
        for ident in identifiers:
            if ident.lower() in combined:
                score += 3
        score += max(i2 - i1, j2 - j1)
        candidate_blocks.append(
            (
                score,
                (
                    f"FILE: {file_label}\n"
                    f"STUDENT LINES {s_start}-{s_end}:\n{student_snippet}\n"
                    f"SOLUTION LINES {sol_start}-{sol_end}:\n{solution_snippet}"
                )
            )
        )

    candidate_blocks.sort(key=lambda item: item[0], reverse=True)
    return [block for _, block in candidate_blocks[:max_blocks]]

def build_compact_solution_diff(diagnosi, student_files, solution_files, max_chars=5000):
    identifiers = extract_identifiers(diagnosi)
    mentioned_files = extract_file_mentions(diagnosi)
    preferred = []

    for file_name in mentioned_files:
        matched = lookup_file_content(student_files, file_name)
        if matched is not None:
            for key in student_files.keys():
                if lookup_file_content({key: student_files[key]}, file_name) is not None:
                    preferred.append(key)
                    break

    all_keys = sorted(set(student_files.keys()) | set(solution_files.keys()))
    changed_keys = []
    for key in all_keys:
        student_text = lookup_file_content(student_files, key) or ""
        solution_text = lookup_file_content(solution_files, key) or ""
        if student_text != solution_text:
            changed_keys.append(key)

    ordered_keys = []
    for key in preferred + changed_keys:
        if key not in ordered_keys:
            ordered_keys.append(key)

    if not ordered_keys:
        return "No structural difference between student files and solution files is visible."

    sections = []
    remaining = max_chars

    for key in ordered_keys:
        student_text = lookup_file_content(student_files, key)
        solution_text = lookup_file_content(solution_files, key)

        if student_text is None:
            section = f"FILE: {key}\nSTUDENT: file missing\nSOLUTION: file present"
            if len(section) <= remaining:
                sections.append(section)
                remaining -= len(section) + 2
            continue

        if solution_text is None:
            section = f"FILE: {key}\nSTUDENT: file present\nSOLUTION: file missing"
            if len(section) <= remaining:
                sections.append(section)
                remaining -= len(section) + 2
            continue

        if student_text == solution_text:
            continue

        for block in build_change_blocks(student_text, solution_text, key, identifiers=identifiers):
            if len(block) > remaining and sections:
                return "\n\n".join(sections)
            if len(block) <= remaining:
                sections.append(block)
                remaining -= len(block) + 2

    return "\n\n".join(sections) if sections else "Differences exist, but a compact diff could not be built."

def read_student_code(path):
    return build_repo_view(path)

def read_solution_code(exercise_name):
    ground_truth = Path(GROUND_TRUTH_DIR)
    if not ground_truth.exists():
        return {}
    solution_dir = ground_truth / exercise_name
    if solution_dir.exists() and solution_dir.is_dir():
        solution_files = {}
        for f in sorted(solution_dir.glob("**/*.c")):
            content = f.read_text(errors="ignore")
            solution_files[f.name] = content
            solution_files[f.relative_to(solution_dir).as_posix()] = content
        for f in sorted(solution_dir.glob("**/*.h")):
            content = f.read_text(errors="ignore")
            solution_files[f.name] = content
            solution_files[f.relative_to(solution_dir).as_posix()] = content
        return solution_files
    return {}

def run_primary_output_analysis(readme, program_output):
    prompt = prompt_output(readme, program_output)
    first = query_model(prompt, PRIMARY_MODEL, role="PRIMARY")

    # fallback/repair
    repaired = None

    if response_has_expected_fields(first, ["Output_Correct", "Output_Diagnosis"]):
        return first

    if first and first != "ERRORE_LLM":
        repaired = query_model(
            "Rewrite the following answer using exactly:\n"
            "Output_Correct: YES or NO\n"
            "Output_Diagnosis: <diagnosis>\n\n"
            f"Answer to rewrite:\n{first}",
            PRIMARY_MODEL,
            max_completion_tokens=120,
            role="PRIMARY",
        )

    if repaired and response_has_expected_fields(repaired, ["Output_Correct", "Output_Diagnosis"]):
        return repaired

    return coerce_structured_response(
        prompt,
        repaired or first,
        ["Output_Correct", "Output_Diagnosis"],
    )

def run_primary_code_analysis(readme, program_output, code):
    prompt = prompt_codice(readme, program_output, code)
    first = query_model(prompt, PRIMARY_MODEL, role="PRIMARY")

    # fallback/repair
    repaired = None

    if response_has_expected_fields(first, ["Code_Correct", "Code_Diagnosis"]):
        return first
    if first and first != "ERRORE_LLM":
            repaired = query_model(
                "Rewrite the following answer using exactly:\n"
                "Code_Correct: YES or NO\n"
                "Code_Diagnosis: <diagnosis>\n\n"
                f"Answer to rewrite:\n{first}",
                PRIMARY_MODEL,
                max_completion_tokens=140,
                role="PRIMARY",
            )
    if repaired and response_has_expected_fields(repaired, ["Code_Correct", "Code_Diagnosis"]):
        return repaired

    return coerce_structured_response(
        prompt,
        repaired or first,
        ["Code_Correct", "Code_Diagnosis"],
    )

def run_primary_correct_code_analysis(readme, program_output, code):
    prompt = prompt_codice_correct(readme, program_output, code)
    first = query_model(prompt, PRIMARY_MODEL, role="PRIMARY")

    repaired = None
    if response_has_expected_fields(first, ["Code_Correct", "Code_Diagnosis"]):
        return first
    if first and first != "ERRORE_LLM":
            repaired = query_model(
                "Rewrite the following answer using exactly:\n"
                "Code_Correct: YES or NO\n"
                "Code_Diagnosis: <diagnosis>\n\n"
                f"Answer to rewrite:\n{first}",
                PRIMARY_MODEL,
                max_completion_tokens=140,
                role="PRIMARY",
            )
    if repaired and response_has_expected_fields(repaired, ["Code_Correct", "Code_Diagnosis"]):
        return repaired

    return coerce_structured_response(
        prompt,
        repaired or first,
        ["Code_Correct", "Code_Diagnosis"],
    )

def run_primary_static_code_analysis(readme, code):
    prompt = prompt_codice_static(readme, code)
    first = query_model(prompt, PRIMARY_MODEL, role="PRIMARY")

    re
    if response_has_expected_fields(first, ["Code_Correct", "Code_Diagnosis"]):
        return first
    if first and first != "ERRORE_LLM":
            repaired = query_model(
                "Rewrite the following answer using exactly:\n"
                "Code_Correct: YES or NO\n"
                "Code_Diagnosis: <diagnosis>\n\n"
                f"Answer to rewrite:\n{first}",
                PRIMARY_MODEL,
                max_completion_tokens=140,
                role="PRIMARY",
            )
    if repaired and response_has_expected_fields(repaired, ["Code_Correct", "Code_Diagnosis"]):
        return repaired

    return coerce_structured_response(
        prompt,
        repaired or first,
        ["Code_Correct", "Code_Diagnosis"],
    )

# ================= PROMPT LLM =================

def prompt_output(readme, program_output):
    return f"""
Evaluate only the PROGRAM OUTPUT.

Check visible OS-trace invariants:
- actor/request identity
- request/reply or producer/consumer protocol coherence
- visible values and arithmetic
- counts, pairing, ordering, and completion

Rules:
- Mark NO only for a concrete mismatch visible in the output.
- If the output is empty, mark NO and state which interaction or phase is missing.
- Do not use code-level causes.
- Do not invent hidden requirements.
- Be conservative: if a central operation is not independently verifiable from the trace, do not overclaim that the output is correct.
- A YES answer requires direct visible support for the central externally observable result of the exercise, not just visible activity or eventual downstream consistency.

Exercise description:
{readme}

Program output:
{program_output}

Decision rules:
- If the output is empty, blank, or equivalent to "The program produced no output.", then Output_Correct = NO.
- If the visible trace contains timeout text, forced termination text, watchdog termination, or an unfinished run, then Output_Correct = NO even if some partial activity is visible.
- Missing messages, wrong counts, malformed exchanges, mismatched IDs/PIDs/request numbers, impossible ordering, or wrong computed values visible in the output imply Output_Correct = NO.
- Do not claim that counts, pairing, or ordering are correct unless the trace directly shows enough evidence to verify them.
- When the description or visible trace implies a fixed number of requests, replies, iterations, produced values, consumed values, recipients, or termination events, verify those counts explicitly from the trace before answering YES.
- If the trace shows repeated operations of the same family, check that the number of visible requests, replies, sends, receives, produces, consumes, reads, writes, or forwarded values is consistent with the visible protocol. If you cannot verify that consistency, prefer NO over YES.
- Mere suspicion is not enough.
- The diagnosis must describe the observable symptom only, not the possible code cause.
- Use the visible order of events as the order of observation. Do not repair an apparently wrong trace by assuming hidden reordering, delayed flushing, or a different unseen temporal order unless the trace explicitly states that.
- If the output is empty, explicitly state that no runtime trace is visible and mention the exercise-specific interaction that is missing, such as request/response, producer/consumer, sensor/collector, reader/writer, client/server, or another interaction named in the description.
- For empty output, do not stop at "no output"; say which externally visible phase is missing, for example no client/server request-response trace, no producer/consumer exchange, no reader/writer activity, no worker/service interaction, or no completion/termination phase.
- If the mismatch is about values, counts, ordering, or pairing, mention the concrete operation family involved.
- If an operation name visibly encodes arithmetic or protocol meaning, such as SOMMA/sum, product, request, reply, consume, or produce, use that meaning when judging visible value or trace mismatches.
- Do not reinterpret a client-visible field named `risultato` as a mere acknowledgment unless the trace explicitly labels it as ack/ok/status and not as an operation result.
- In request/reply style traces, each client-visible reply must be judged as the result of the immediately preceding request for the same actor, not as a generic protocol acknowledgment.
- When a request visibly carries operands, parameters, message ids, or payload values, check the corresponding visible reply or forwarded value against those exact visible inputs whenever the operation semantics make that check possible.
- If the trace gives enough information to validate values one by one, do that validation. A YES answer should mean that the visible exchanged values are individually consistent, not just globally plausible.
- If a later consume/receive/dequeue/read returns a meaningful value before the corresponding produce/send/enqueue/write phase is visibly established, do not use that later value as evidence that the earlier phase was correct.
- If a semantic operation such as SUM/PRODUCT receives a visible reply that conflicts with a later visible produced or consumed value in the same trace family, treat that as a concrete mismatch.
- If a request receives an immediate visible reply with a placeholder or semantically wrong value, and the meaningful result later appears as the outcome of a different operation such as consume/dequeue/read, treat that as a wrong request/reply association and mark NO.
- If several requests of the same family receive the same placeholder-looking reply, and meaningful values appear only later in a different phase of the trace, do not call the output correct: this is visible request/reply misassociation, not valid delayed confirmation.
- In request/reply traces, judge each client-visible reply against the request that immediately precedes it for the same actor; a later downstream result does not retroactively validate an earlier reply.
- If the only apparent evidence for correctness comes from a later phase of the trace, while the earlier reply itself is placeholder-like, under-informative, or semantically incompatible with the request, prefer NO.
- If a later phase appears before an earlier prerequisite phase in the visible trace, and no explicit initialization, preload, warm-start, or prior state is shown, prefer NO rather than assuming an unseen valid setup.
- If a server-side or worker-side log appears to compute the meaningful value only after a client has already received an incompatible reply, the output is still wrong from the client's point of view.
- Do not treat later queue contents, consume results, dequeue results, or worker logs as proof that an earlier RPC reply was correct.
- If the exercise shows one source stream being forwarded to multiple collectors/consumers, and the recipient traces show visibly different counts or duplicated/dropped values, mark NO.
- In fan-out, broadcast, or multi-consumer traces, compare the visible recipient streams with each other and with the visible source stream. If one recipient misses a value, duplicates a value, starts from a shifted value, or ends with an extra value, mark NO.
- When values are propagated across phases of the trace, verify that each visible downstream value is compatible with an earlier visible upstream value or operation result. If some exchanged values cannot be reconciled, mark NO.
- Do not infer correct forwarding merely from collector/consumer logs when the central forwarding phase is missing, incomplete, or not coherently connected to the visible source stream.
- If downstream recipients show data before the upstream source or central routing/processing phase is visibly established, do not infer a correct end-to-end trace from that ordering alone.
- If the trace names only peripheral actors while the central actor or central processing phase described by the exercise is entirely absent from the visible runtime trace, mark NO and report the missing phase.
- If multiple mismatches are visible, report the most central one first and optionally add one closely related consequence.
- If the trace shows concurrent interleaving and some operations cannot be matched back to a coherent global trace, do not mark the output as correct.
- If the trace does not directly validate a central semantic property of the interaction, avoid strong YES claims.
- If the trace validates only a subset of the protocol and leaves the central request/reply result ambiguous, prefer NO over a confident YES.
- Do not promote a merely plausible interpretation into YES when the same trace is also compatible with a broken request/reply, forwarding, routing, or completion behavior.
- If correctness would require assuming hidden buffering, omitted trace segments, or an implicit acknowledgment protocol that is not named in the visible output, answer NO.
- If correctness would require assuming hidden preloaded state, hidden earlier successful operations, or an unseen initial population of data structures that is not visible in the trace, answer NO.
- A YES diagnosis is allowed only when the visible trace directly supports the central semantic result of the exercise, the visible counts are consistent with the protocol, and the visible values that can be checked are actually correct.
- If Output_Correct = YES, the diagnosis must explicitly say that no concrete output mismatch is visible from the provided information.
- Prefer diagnoses shaped like a test failure report: identify the broken interaction first, then state whether the problem is missing trace, wrong values, wrong counts, wrong pairing, wrong ordering, or a missing phase of the observable protocol.
- Avoid generic formulas such as "the trace is missing" when a more specific statement is possible from the description and visible labels.
- Keep the diagnosis detailed but compact: maximum of 100 words.
- Write the diagnosis in English.
- Do not quote or refer to hidden tests, hidden assertions, or hidden ground truth.

Final format only:
Output_Correct: YES or NO
Output_Diagnosis: <detailed evidence-based diagnosis>
"""


def prompt_codice(readme, program_output, code):
    return f"""
Evaluate the C CODE.

Use only explicit requirements from the exercise and visible evidence from code/output.
Look for one primary defect using OS invariants:
- protocol matching
- ownership/lifetime
- synchronization policy
- placement/order of operations
- cleanup/termination
- forbidden primitive

Rules:
- Mark NO only for a concrete defect directly supported by the code.
- Preserve specialized policy names such as reader-writer or selective receive.
- A visible omission can count as evidence if the relevant code path is shown.
- If evidence is weak, answer YES.
- If the provided runtime output looks coherent and no failing symptom is visible in the prompt, answer NO only for an explicit, undeniable code violation.
- Do not invent hidden constraints.

Exercise description:
{readme}

Observed runtime/output:
{program_output}

Code:
{code}

Decision rules:
- Report one primary defect, not a list of possibilities.
- Report exactly one defect only. Do not mention two primary defects, firstly/secondly, or an auxiliary unrelated issue.
- Mention the exact function(s), variable(s), shared resource(s), or API call(s) involved when they are visible.
- Distinguish carefully between nearby defect families:
  * a missing critical section is not the same as the wrong synchronization policy
  * generic mutual exclusion is not the same as a reader-writer requirement
  * wrong parameter lifetime is not the same as missing free()
  * wrong message-type matching is not the same as a wrong payload value
- Do not claim a race condition unless unsynchronized concurrent accesses to the same shared state are explicitly visible in the code.
- Do not claim a missing pthread_join() unless the code can terminate before required work completes and no alternative waiting/synchronization is visible.
- Do not claim a missing critical section unless both the concurrent access and the unprotected operation are visible.
- If the code already shows mutexes, semaphores, condition variables, monitor procedures, or dedicated read/write functions, do not diagnose "missing synchronization primitives" unless the shown declarations and operations truly contain no synchronization mechanism for the relevant path.
- In reader-writer style code, if reader and writer procedures are already present, prefer diagnosing the wrong reader-writer policy or over-serialization of readers rather than claiming there is no synchronization at all.
- Do not diagnose a reader-writer defect as a generic mutex defect unless the code clearly shows that only ordinary mutual exclusion was required.
- Do not diagnose a queue-ID or selector mix-up merely because one variable stores or aliases another queue identifier; diagnose it only if the visible send/receive or type-selection sites are concretely inconsistent.
- Do not cite pseudocode labels, natural-language placeholders, or comments as code evidence unless they literally appear in the code.
- Do not infer exercise-specific obligations unless they are explicit in the description or directly visible in the code.
- Do not answer YES merely because one specific API name is absent. If the visible implementation of the relevant code path omits the required mechanism, selector, synchronization policy, cleanup step, or ownership pattern, that omission may itself justify NO.
- Do not diagnose generic error-handling defects such as missing return-value checks, missing errno checks, or missing validation unless the observed failure is about that path or the code makes that defect the central visible cause.
- When runtime feedback is only black-box and the code does not show one explicit violating statement or omission, prefer YES over a speculative NO.
- Only say that no concrete code is visible if the prompt genuinely does not contain line-numbered C source. When file blocks are shown, analyze those files instead of falling back to a visibility disclaimer.
- When possible, explain both the violated code pattern and the concrete consequence on the protocol/runtime.
- If Code_Correct = NO, the diagnosis must explicitly cite at least:
  * one file name exactly as it appears in the code context
  * one function name, API call, variable, or code fragment exactly as it appears in the code context
- Prefer references such as `FILE: server.c`, `function worker`, `pthread_create(...)`, `msgsnd(...)`, `msgrcv(...)`, or a short quoted code fragment with line numbers when available.
- If line numbers are visible in the context, include at least one relevant line number or short line-number range.
- Prefer a diagnosis that points to the exact line or statement where the required behavior is missing or where the wrong behavior is implemented.
- If a warning-like constraint can be instantiated concretely from the code, name both the violated requirement and the exact code site that violates it.
- For ownership/lifetime defects, cite both the use site and the allocation or passing site when possible.
- For protocol-matching defects, cite both sides of the mismatch when possible.
- For synchronization defects, cite both the protected operation and the visible locking or missing-locking context.
- If the runtime symptom is a wrong request/reply association, wrong operation result, or wrong visible protocol pairing, prefer a code defect that plausibly explains that central symptom instead of unrelated error-checking omissions.
- If Code_Correct = YES, the diagnosis must explicitly say that no concrete correctness bug is visible from the provided code and runtime context.
- The diagnosis must read like a precise code review finding, not a generic explanation.
- Keep the diagnosis detailed but focused: maximum of 100 words.
- Write the diagnosis in English.

Final format only:
Code_Correct: YES or NO
Code_Diagnosis: <one detailed evidence-based diagnosis>
"""


def prompt_codice_correct(readme, program_output, code):
    return f"""
Evaluate the C CODE in a case where the visible execution passed and no static warning is available.

Use only explicit requirements from the exercise and visible evidence from code/output.
Be very conservative: a passing execution is strong evidence for YES unless the code itself shows an explicit, undeniable violation.

Exercise description:
{readme}

Observed runtime/output:
{program_output}

Code:
{code}

Decision rules:
- Start from YES, not from suspicion.
- Mark NO only for one explicit correctness bug directly visible in the code.
- Do not speculate about hidden races, hidden deadlocks, hidden queue mix-ups, hidden lifetime bugs, or unobserved protocol failures.
- If mutexes, semaphores, condition variables, monitor procedures, or reader/writer functions are visible, do not call the defect "missing synchronization primitives" unless the shown path truly contains no synchronization mechanism at all.
- Do not diagnose a queue-ID or selector mix-up unless the visible send/receive or type-selection sites are concretely inconsistent.
- If Code_Correct = NO, cite at least one file name and one function, API, variable, or short code fragment exactly as visible in the code.
- If Code_Correct = YES, explicitly say that no concrete correctness bug is visible from the provided code and runtime context.
- Report one primary defect only, never multiple defects.
- Write the diagnosis in English, keep the diagnosis detailed but compact: maximum of 100 words.

Final format only:
Code_Correct: YES or NO
Code_Diagnosis: <one detailed evidence-based diagnosis>
"""


def prompt_codice_static(readme, code):
    return f"""
Perform static analysis of the C CODE.

Use only explicit exercise constraints and visible code.
Look for one structural defect using:
- lifetime/ownership
- synchronization policy
- scope/order of operations
- selector or routing logic
- forbidden primitive
- visible absence of a required mechanism in the shown code path

Rules:
- Mark NO only for a directly visible violation.
- Preserve specialized policy names such as reader-writer or selective receive.
- If the relevant code path is not visible or evidence is weak, answer YES.
- Do not invent hidden rules.

Exercise description:
{readme}

Code:
{code}

Decision rules:
- Report one primary static defect, not a list.
- Report exactly one defect only. Do not mention two primary defects, firstly/secondly, or an auxiliary unrelated issue.
- The diagnosis must point to the visible API/function/variable/block that violates the constraint.
- Do not report a missing pattern unless the relevant function or code block is actually shown.
- Ignore hypothetical runtime causes that are not directly visible in the code.
- Distinguish the violation class precisely: for example, wrong synchronization policy, wrong lifetime, wrong placement, wrong cleanup, wrong selector, or forbidden primitive.
- Do not collapse a specialized policy defect into a generic “missing mutex” diagnosis.
- If mutexes, semaphores, condition variables, monitor procedures, or dedicated read/write functions are already visible, do not diagnose "missing synchronization primitives" unless the shown declarations and operations truly contain no synchronization mechanism for the relevant path.
- In reader-writer style code, if reader and writer procedures are already present, prefer diagnosing the wrong reader-writer policy or over-serialization of readers rather than claiming there is no synchronization at all.
- Do not diagnose a queue-ID or selector mix-up merely because one variable stores or aliases another queue identifier; diagnose it only if the visible send/receive or type-selection sites are concretely inconsistent.
- Do not cite pseudocode labels, natural-language placeholders, or comments as code evidence unless they literally appear in the code.
- Do not answer YES merely because a concrete API call is missing from the text. If the shown implementation of the relevant file/function clearly omits the required mechanism or uses a simpler incompatible pattern, diagnose that omission as the primary static defect.
- Only say that no concrete code is visible if the prompt genuinely lacks line-numbered C source. When file blocks are shown, analyze those files instead of falling back to a visibility disclaimer.
- State first the violated constraint, then the exact code pattern that violates it.
- If Code_Correct = NO, the diagnosis must explicitly cite at least:
  * one file name exactly as it appears in the code context
  * one function name, API call, variable, or code fragment exactly as it appears in the code context
- Prefer references such as `FILE: server.c`, `function worker`, `pthread_create(...)`, `msgsnd(...)`, `msgrcv(...)`, or a short quoted code fragment with line numbers when available.
- If line numbers are visible in the context, include at least one relevant line number or short line-number range.
- Prefer a diagnosis that points to the exact line or statement where the required static pattern is missing or replaced by an incompatible one.
- For ownership/lifetime defects, cite both the use site and the allocation or passing site when possible.
- For protocol-matching defects, cite both sides of the mismatch when possible.
- For synchronization defects, cite both the protected operation and the visible locking or missing-locking context.
- If Code_Correct = YES, the diagnosis must explicitly say that no concrete static violation is visible from the provided code.
- The diagnosis must read like a precise static-analysis finding, not a generic explanation.
- Keep the diagnosis detailed but focused: maximum of 100 words.
- Write the diagnosis in English.

Final format only:
Code_Correct: YES or NO
Code_Diagnosis: <one detailed static diagnosis>
"""


def self_refine(prompt, first_response):
    if not first_response or first_response == "ERRORE_LLM":
        return first_response

    field_hint = "Keep the fields exactly as in the previous answer."
    if "Output_Correct" in prompt:
        field_hint = "Keep exactly these fields: Output_Correct and Output_Diagnosis."
    elif "Code_Correct" in prompt:
        field_hint = "Keep exactly these fields: Code_Correct and Code_Diagnosis."

    refine_prompt = f"""
Revise the previous answer for consistency and precision.

Previous answer:
{first_response}

Rules:
- {field_hint}
- Remove unsupported claims and generic filler.
- Keep the boolean field fully consistent with the diagnosis.
- If the boolean field is YES, explicitly say that no concrete mismatch or bug is visible from the provided information.
- If the boolean field is NO, keep one concrete issue only.
- Preserve exact file names, line numbers, function names, API names, variables, and short code fragments already present when they support the diagnosis.
- For output diagnoses with NO, prefer a test-like statement of the broken interaction, wrong value, wrong count, wrong pairing, wrong ordering, or missing phase.
- For code diagnoses with NO, prefer a precise code-review finding anchored to visible evidence.
- Write in English.

Final answer only:
"""
    refined = query_model(refine_prompt, PRIMARY_MODEL, max_completion_tokens=200, role="PRIMARY")
    if not refined or refined == "ERRORE_LLM":
        return first_response
    return refined


def coerce_structured_response(prompt, raw_response, expected_fields):
    if not raw_response or raw_response == "ERRORE_LLM":
        return ""

    refined = self_refine(prompt, raw_response)
    if response_has_expected_fields(refined, expected_fields):
        return refined

    candidate = refined or raw_response
    parsed = parse_response(candidate, expected_fields)

    verdict_field = expected_fields[0]
    diagnosis_field = expected_fields[1]
    verdict = parsed.get(verdict_field, "")
    diagnosis = normalize_diagnosis(parsed.get(diagnosis_field, ""))

    if verdict not in {"YES", "NO"} or not diagnosis:
        return ""

    lower = diagnosis.lower()

    if verdict_field == "Output_Correct":
        if verdict == "YES" and not any(p in lower for p in ["no concrete", "no visible", "no output mismatch", "aligns with the specification"]):
            diagnosis = f"No concrete output mismatch is visible from the provided information. {diagnosis}"
        return f"Output_Correct: {verdict}\nOutput_Diagnosis: {diagnosis}"

    if verdict == "YES" and not any(p in lower for p in ["no concrete", "no visible", "no correctness bug", "no static violation"]):
        diagnosis = f"No concrete correctness bug is visible from the provided code and runtime context. {diagnosis}"
    return f"Code_Correct: {verdict}\nCode_Diagnosis: {diagnosis}"


def prompt_giudice_output(diagnosi, errore_reale):
    return f"""
Grade an output diagnosis against the ground truth feedback.

Diagnosis:
{diagnosi}

Ground truth feedback:
{errore_reale}

Rules:
- Focus on the actual output behavior.
- Accept the diagnosis if it correctly identifies the real output problem.
- Accept the diagnosis if it correctly states that the output is correct **and the ground truth confirms the output is indeed correct**.
- Reject the diagnosis if it reports an output problem that does not exist, or claims the output is correct when it is actually wrong.
- Treat paraphrases of the actual output behavior as correct.
- If the ground truth is generic or indicates no failure, a diagnosis claiming the output is correct should be accepted only if the program output matches expectations.
- If the ground truth feedback does not name a concrete symptom, do not accept a diagnosis that invents a specific missing-output, wrong-value, wrong-pairing, or wrong-ordering claim.
- A diagnosis about missing output is correct only if the ground truth explicitly supports a missing or absent runtime trace.
- If the ground truth clearly says the execution is correct, accept a diagnosis saying that no concrete output mismatch is visible unless it adds an invented problem.
- Always compare the diagnosis with the concrete ground truth feedback, not only the textual form.

Final format only:
Diagnosis_Correct: YES or NO
"""


def prompt_giudice_codice(diagnosi, warnings, code_around, solution_code):
    warnings_text = ""
    if warnings:
        warnings_text = "\n".join(
            [f"- {w['file']}:{w['line']}: {w['message']}" for w in warnings]
        )
    return f"""
Grade a code diagnosis against the real defect.

Diagnosis:
{diagnosi}

Ground truth warnings:
{warnings_text}

Relevant student code snippets:
{code_around}

Reference solution snippets:
{solution_code}

Rules:
- Use warnings as the primary reference.
- Accept the diagnosis if it correctly identifies the real defect or violation.
- Accept the diagnosis if it correctly states that the code is correct and there are no real warnings or violations.
- Reject different mechanisms, resources, or synchronization errors not matching warnings.
- Keep nearby defect families distinct.
- If real code snippets and warnings are provided, a "no visible defect" diagnosis is NO only if a defect actually exists.
- If the warning names a specific mechanism or policy, a looser generic diagnosis is NO.
- If the diagnosis mixes two different defect candidates, alternative explanations, or an unrelated auxiliary issue, reject it unless they all refer to the same warning.

Final format only:
Diagnosis_Correct: YES or NO
"""


def prompt_giudice_codice_diff(diagnosi, feedback_text, compact_diff):
    return f"""
Grade a code diagnosis against the reference solution using a compact student-vs-solution diff.

Diagnosis:
{diagnosi}

Observed test feedback:
{feedback_text}

Compact student/solution diff:
{compact_diff}

Rules:
- Accept only if the diagnosis matches a concrete structural difference visible in the diff and consistent with the observed failure.
- The reference solution is not canonical: structural differences alone do not prove a defect.
- Accept the diagnosis if it correctly states that the code is correct and the diff does not show an explicit correctness violation.
- Do not reject the diagnosis if the code is functionally correct and the differences in the diff are superficial (variable names, loop order, formatting) and do not constitute a correctness defect.
- If the observed feedback says the submission is correct or reports no code warnings, prefer accepting a no-defect diagnosis unless the diff itself shows an undeniable violation.
- For failing submissions without warnings, accept a defect diagnosis only if the same concrete mechanism is visible in the diff; feedback alone is not enough to validate a speculative code cause.
- Reject diagnoses that point to a different mechanism, file, API, variable, or protocol mismatch than the visible student-vs-solution difference.
- Reject diagnoses that mention multiple unrelated defects, tentative alternatives, or "however/also/additionally" style backup theories.
- If the diagnosis cites a file, function, API, variable, or code fragment, it must be compatible with the diff.
- Do not invent hidden defects outside the provided diff.
- If the diff does not support the diagnosis, answer NO.

Final format only:
Diagnosis_Correct: YES or NO
"""


def prompt_giudice_codice_static(diagnosi, warnings):
    warnings_text = ""
    if warnings:
        warnings_text = "\n".join(
            [f"- {w['file']}:{w['line']}: {w['message']}" for w in warnings]
        )

    return f"""
Grade a static code diagnosis against the ground truth warnings.

Diagnosis:
{diagnosi}

Ground truth warnings:
{warnings_text}

Rules:
- Accept only the same concrete static defect or a clear paraphrase.
- Reject different defects, generic mismatches, or partial overlap.
- Keep mutual exclusion, reader-writer, lifetime, deallocation, selector, and payload errors distinct.
- If warnings are explicit, a "no visible code/no visible defect" diagnosis is NO.
- If the warning names a specific mechanism or policy, a looser generic diagnosis is NO.
- If multiple warnings exist, accept the diagnosis only if it clearly matches at least one concrete warning rather than a nearby but different defect family.

Final format only:
Diagnosis_Correct: YES or NO
"""

def normalize_diagnosis(diagnosi):
    text = compact_whitespace(clean_text(diagnosi))
    if not text:
        return ""
    text = re.sub(r"^(okay[, ]+let'?s\s+(look at|see)\s+(this problem|the problem|this)|let'?s\s+(look at|see)\s+(this problem|the problem|this))\s*", "", text, flags=re.IGNORECASE)
    text = re.sub(r"^the user provided\s+", "", text, flags=re.IGNORECASE)
    text = re.sub(r"\bprovided chunk findings\b", "provided information", text, flags=re.IGNORECASE)
    text = re.sub(r"\bchunk findings\b", "provided information", text, flags=re.IGNORECASE)
    text = re.sub(r"\ball chunks report NO_EVIDENCE\b", "no concrete mismatch is visible from the provided information", text, flags=re.IGNORECASE)
    text = re.sub(r"\ball chunks report NO_LOCAL_BUG\b", "no concrete bug is visible from the provided information", text, flags=re.IGNORECASE)
    text = re.sub(r"\bNO_EVIDENCE\b", "no concrete mismatch", text, flags=re.IGNORECASE)
    text = re.sub(r"\bNO_LOCAL_BUG\b", "no concrete bug", text, flags=re.IGNORECASE)
    text = re.sub(r"\bEVIDENCE\b", "concrete evidence", text, flags=re.IGNORECASE)
    text = re.sub(r"\bBUG\b", "concrete defect", text, flags=re.IGNORECASE)
    text = re.sub(r"\bchunks?\b", "provided information", text, flags=re.IGNORECASE)
    text = re.sub(r"\blocal scans?\b", "analysis", text, flags=re.IGNORECASE)
    text = re.sub(r"\binternal passes?\b", "analysis", text, flags=re.IGNORECASE)
    text = re.sub(r"\s*([,;])\s*", r"\1 ", text)
    text = re.sub(r"\s+\)", ")", text)
    text = re.sub(r"\(\s+", "(", text)
    text = re.sub(r"\s{2,}", " ", text)
    return text.strip()

def build_compile_output_diagnosis(program_output, compile_log):
    if program_output and program_output.strip() != "The program produced no output.":
        return (
            "The program does not produce a valid runtime trace because compilation fails before the executable can start. "
            "As a result, the required exchange of messages never begins."
        )

    return (
        "The program produces no output because compilation fails and no executable is generated. "
        "As a result, the required runtime trace is entirely missing."
    )

def build_compile_code_diagnosis(compile_log):
    errors = extract_compile_errors(compile_log)
    has_tbd = "/* TBD" in compile_log if compile_log else False

    if has_tbd and errors:
        return (
            "Compilation fails because the code still contains incomplete expressions or `/* TBD */` placeholders, "
            "so the compiler encounters invalid statements. "
            f"The concrete compiler errors are: {'; '.join(errors)}."
        )

    if errors:
        return (
            "Compilation fails because of concrete syntax or semantic errors that are directly visible in the code. "
            f"The compiler reports: {'; '.join(errors)}."
        )

    if compile_log and compile_log.strip():
        first_line = compile_log.strip().splitlines()[0].strip()
        return (
            "Compilation fails and the compiler reports a blocking error in the code. "
            f"First available message: {first_line}"
        )

    return (
        "Compilation fails, so the code cannot be executed. "
        "No more specific compiler error message is available."
    )


# ================= CLASSIFICAZIONE ERRORI =================

def classify_failure_category(feedback_text):
    """
    Classificazione deterministica basata sui messaggi dello script test.sh.
    """
    if not feedback_text:
        return "dynamic_failure"

    text = feedback_text.lower()

    mapping = {
        "l'esecuzione del programma è andata in crash": "crash",
        "l'esecuzione del programma è andata in timeout": "timeout",
        "è necessario deallocare le risorse ipc": "ipc_leak",
        "non è stato possibile compilare il programma": "compile_error",
        "terminata con codice di ritorno non-nullo": "dynamic_failure",
        "l'esecuzione non è corretta": "dynamic_failure",
        "anche se il programma esegue, sono stati riscontrati i seguenti difetti all'interno del codice": "static_failure",
        "congratulazioni, l'esercizio compila ed esegue correttamente": "correct",
    }

    for msg, category in mapping.items():
        if msg in text:
            return category

    return "dynamic_failure"

# ================= PARSING =================

YES_SET = {"YES", "Y", "Yes", "yes", "TRUE", "T", "t", "SI", "SÌ", "SI'", "si'"}
NO_SET = {"NO", "N", "n", "No", "no", "FALSE", "F"}

def normalize_bool(value):
    if not value:
        return ""

    v = value.strip()  # non facciamo upper su tutto

    # solo per confronto YES/NO, creiamo una versione maiuscola temporanea
    v_upper = v.upper()
    if v_upper in YES_SET:
        return "YES"
    if v_upper in NO_SET:
        return "NO"

    return v  # ritorni il testo originale senza maiuscolo


def clean_text(text):
    if not text:
        return ""

    # rimuove blocchi di reasoning non destinati all'output
    text = re.sub(r"<think>.*?</think>", "", text, flags=re.S | re.IGNORECASE)
    text = re.sub(r"</?think>", "", text, flags=re.IGNORECASE)

    # rimuove markdown
    text = re.sub(r"```.*?```", "", text, flags=re.S)

    # rimuove bullet
    text = re.sub(r"^\s*[-*]\s*", "", text, flags=re.M)

    return text.strip()

def compact_whitespace(text):
    if not text:
        return ""
    text = text.replace("\r", "\n")
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()

def code_diagnosis_has_visible_anchor(diagnosis, code):
    if not diagnosis or not code:
        return False

    code_lower = code.lower()
    file_hits = sum(1 for file_name in extract_file_mentions(diagnosis) if file_name.lower() in code_lower)
    identifiers = [ident for ident in extract_identifiers(diagnosis) if len(ident) >= 4]
    identifier_hits = sum(1 for ident in identifiers if ident.lower() in code_lower)
    api_hits = sum(
        1
        for api in ["pthread_create", "pthread_mutex", "msgsnd", "msgrcv", "fork", "wait", "malloc", "free"]
        if api in diagnosis.lower() and api in code_lower
    )

    return file_hits >= 1 or identifier_hits >= 2 or api_hits >= 1

def evidence_support_score(diagnosis, evidence_text):
    if not diagnosis or not evidence_text:
        return 0

    diagnosis_lower = diagnosis.lower()
    evidence_lower = evidence_text.lower()
    score = 0

    for file_name in extract_file_mentions(diagnosis):
        if file_name.lower() in evidence_lower:
            score += 3

    for ident in extract_identifiers(diagnosis):
        if ident.lower() in evidence_lower:
            score += 1

    for api in ["pthread_create", "pthread_cond_signal", "pthread_cond_broadcast", "pthread_mutex", "msgsnd", "msgrcv", "msgget", "fork", "wait", "malloc", "free"]:
        if api in diagnosis_lower and api in evidence_lower:
            score += 2

    return score

def fallback_judge_output(diag_output, feedback_text):
    text = (diag_output or "").lower()
    fb = (feedback_text or "").lower()

    if not diag_output:
        return "NO"

    if "no concrete mismatch" in text or "output is judged correct" in text or "appear to be present and correct" in text:
        if any(key in fb for key in ["errore", "non è corretta", "not correct", "wrong", "non corrisponde", "numero totale", "valore"]):
            return "NO"
        return "YES"

    score = 0
    for pair in [
        (["no output", "missing trace", "missing interaction"], ["no output", "non è stato possibile", "nessun output"]),
        (["wrong value", "incorrect value", "value mismatch", "sum"], ["valore", "wrong value", "errore nel valore"]),
        (["wrong count", "missing messages", "number of messages"], ["numero totale", "messaggi", "number of messages"]),
        (["wrong ordering", "wrong pairing", "mismatched"], ["ordine", "pair", "pid", "tipo"]),
    ]:
        if any(a in text for a in pair[0]) and any(b in fb for b in pair[1]):
            score += 1

    return "YES" if score > 0 else "NO"

def fallback_judge_code(diag_code, warnings=None, compact_diff="", code_around="", solution_code="", feedback_text=""):
    if not diag_code:
        return "NO"

    warnings = warnings or []
    evidence_parts = []
    if warnings:
        evidence_parts.extend(f"{w.get('file','')} {w.get('message','')}" for w in warnings)
    if code_around:
        evidence_parts.append(code_around)
    if solution_code:
        evidence_parts.append(solution_code)
    if compact_diff:
        evidence_parts.append(compact_diff)
    if feedback_text:
        evidence_parts.append(feedback_text)

    evidence_text = "\n".join(evidence_parts)
    score = evidence_support_score(diag_code, evidence_text)
    return "YES" if score >= 3 else "NO"


def judge_output_with_fallback(diag_output, feedback_text):
    judged = judge_yes_no(prompt_giudice_output(diag_output, feedback_text))
    return judged or fallback_judge_output(diag_output, feedback_text)


def judge_code_with_warning_fallback(diag_code, warnings, code_around, solution_code):
    judged = judge_yes_no(prompt_giudice_codice(diag_code, warnings, code_around, solution_code))
    return judged or fallback_judge_code(
        diag_code,
        warnings=warnings,
        code_around=code_around,
        solution_code=solution_code,
    )


def judge_code_with_diff_fallback(diag_code, feedback_text, compact_diff):
    judged = judge_yes_no(prompt_giudice_codice_diff(diag_code, feedback_text, compact_diff))
    return judged or fallback_judge_code(
        diag_code,
        compact_diff=compact_diff,
        feedback_text=feedback_text,
    )


def judge_code_static_with_fallback(diag_code, warnings):
    judged = judge_yes_no(prompt_giudice_codice_static(diag_code, warnings))
    return judged or fallback_judge_code(diag_code, warnings=warnings)


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

    text_upper = text.upper()  # maiuscolo solo per regex

    if re.search(r"\bYES\b", text_upper):
        return "YES"

    if re.search(r"\bNO\b", text_upper):
        return "NO"

    if re.search(r"\bINCORRECT\b|\bNOT CORRECT\b|\bUNSUPPORTED\b|\bDOES NOT MATCH\b", text_upper):
        return "NO"

    if re.search(r"\bCORRECT\b|\bSUPPORTED\b|\bMATCHES\b", text_upper):
        return "YES"

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

def response_has_expected_fields(text, expected_fields):
    if not text or text == "ERRORE_LLM":
        return False
    parsed = parse_response(text, expected_fields)
    for field in expected_fields:
        value = parsed.get(field, "")
        if field.endswith("_Correct"):
            if value not in {"YES", "NO"}:
                return False
        else:
            if not value:
                return False
    if "Output_Correct" in expected_fields and "Output_Diagnosis" in expected_fields:
        verdict = parsed.get("Output_Correct", "")
        diagnosis = normalize_diagnosis(parsed.get("Output_Diagnosis", ""))
        lower = diagnosis.lower()
        if not diagnosis or "<think" in lower or diagnosis.endswith(":"):
            return False
        if any(p in lower for p in ["okay, let's", "okay let's", "let's look at", "let us look at", "the user provided"]):
            return False
        if verdict == "YES" and not any(p in lower for p in ["no concrete", "no visible", "no output mismatch", "aligns with the specification"]):
            return False
        if verdict == "NO" and re.match(r"^no concrete (mismatch|output mismatch)\b", lower):
            return False
        if verdict == "NO" and not any(p in lower for p in ["missing", "wrong", "mismatch", "pair", "count", "order", "phase", "trace", "reply", "request", "value"]):
            return False
    if "Code_Correct" in expected_fields and "Code_Diagnosis" in expected_fields:
        verdict = parsed.get("Code_Correct", "")
        diagnosis = normalize_diagnosis(parsed.get("Code_Diagnosis", ""))
        lower = diagnosis.lower()
        if not diagnosis or "<think" in lower or diagnosis.endswith(":"):
            return False
        if any(p in lower for p in ["okay, let's", "okay let's", "let's look at", "let us look at", "the user provided"]):
            return False
        if verdict == "YES" and not any(p in lower for p in ["no concrete", "no visible", "no correctness bug", "no static violation"]):
            return False
        if verdict == "NO" and re.match(r"^no concrete (bug|correctness bug|static violation)\b", lower):
            return False
        if verdict == "NO" and re.search(r"\b(two|2)\s+primary defects\b|\bfirstly\b|\bsecondly\b", lower):
            return False
    return True

def judge_yes_no(prompt):
    def mark_unparseable(role):
        used = get_used_models(role)
        if used:
            ROLE_DISABLED_MODELS[role].add(used)

    binary_prompt = (
        "Return only YES or NO.\n"
        "Is the diagnosis semantically correct for the given judge task?\n\n"
        f"{prompt}"
    )
    for role, logical_model in [("JUDGE", JUDGE_MODEL), ("PRIMARY", PRIMARY_MODEL)]:
        binary = query_model(binary_prompt, logical_model, max_completion_tokens=6, role=role)
        value = extract_yes_no_anywhere(binary)
        if value in {"YES", "NO"}:
            return value
        if binary and binary != "ERRORE_LLM":
            mark_unparseable(role)

    repair_prompt = (
        "Return exactly one line in this format:\n"
        "Diagnosis_Correct: YES\n"
        "or\n"
        "Diagnosis_Correct: NO\n\n"
        f"Judge task:\n{prompt}"
    )
    for role, logical_model in [("JUDGE", JUDGE_MODEL), ("PRIMARY", PRIMARY_MODEL)]:
        repaired = query_model(repair_prompt, logical_model, max_completion_tokens=12, role=role)
        value = extract_field(repaired, "Diagnosis_Correct") or extract_yes_no_anywhere(repaired)
        if value in {"YES", "NO"}:
            return value
        if repaired and repaired != "ERRORE_LLM":
            mark_unparseable(role)
    return ""

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

    #print(query_model("Say hello", "mistralai/mistral-small-2603"))

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
            reset_model_usage()

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

            if test_ok and warnings:
                failure = "static_failure"
            else:
                failure = classify_failure_category(feedback_text)

            # =======================
            # ANALISI LLM
            # =======================
            readme = read_readme(exercise_dir)
            code = read_student_code(exercise_dir)
            student_files = get_student_files(exercise_dir)
            solution_files = {}

            output_corr = diag_output = code_corr = diag_code = judge_out_ok = judge_code_ok = ""

            compile_context = compile_log if compile_log.strip() else stderr

            # compile_error → diagnosi deterministica dai messaggi del compilatore
            if failure == "compile_error":
                output_corr = "NO"
                code_corr = "NO"
                diag_output = normalize_diagnosis(build_compile_output_diagnosis(program_out, compile_context))
                diag_code = normalize_diagnosis(build_compile_code_diagnosis(compile_context))

            # correct → LLM primario e giudici
            elif failure == "correct":
                # ===== LLM =====
                resp_output = run_primary_output_analysis(readme, program_out)
                resp_code = run_primary_correct_code_analysis(readme, program_out, code)

                fields_output = parse_response(resp_output, ["Output_Correct", "Output_Diagnosis"])
                fields_code = parse_response(resp_code, ["Code_Correct", "Code_Diagnosis"])

                output_corr = fields_output.get("Output_Correct", "")
                diag_output = fields_output.get("Output_Diagnosis", "")
                code_corr = fields_code.get("Code_Correct", "")
                diag_code = fields_code.get("Code_Diagnosis", "")

                if diag_output:
                    diag_output = normalize_diagnosis(diag_output)

                if diag_output:
                    judge_out_ok = judge_output_with_fallback(diag_output, feedback_text)

                if diag_code:
                    diag_code = normalize_diagnosis(diag_code)

                if diag_code and warnings:
                    solution_files = read_solution_code(exercise_dir.name)
                    snippets = []
                    for w in warnings:
                        file = w['file']
                        line = w['line']
                        student_content = lookup_file_content(student_files, file)
                        if student_content:
                            snippets.append(f"File: {file}, Line: {line}\n{extract_around(student_content, line)}")
                    code_around = '\n\n'.join(snippets) if snippets else code

                    sol_snippets = []
                    for w in warnings:
                        file = w['file']
                        line = w['line']
                        solution_content = lookup_file_content(solution_files, file)
                        if solution_content:
                            sol_snippets.append(f"File: {file}, Line: {line}\n{extract_around(solution_content, line)}")
                    solution_code = '\n\n'.join(sol_snippets) if sol_snippets else "\n".join(solution_files.values())
                    
                    judge_code_ok = judge_code_with_warning_fallback(diag_code, warnings, code_around, solution_code)
                elif diag_code:
                    solution_files = read_solution_code(exercise_dir.name)
                    compact_diff = build_compact_solution_diff(diag_code, student_files, solution_files, max_chars=3200)
                    judge_code_ok = judge_code_with_diff_fallback(diag_code, feedback_text, compact_diff)

            # dynamic / crash / timeout / ipc → LLM + giudici normali
            elif failure in ["dynamic_failure", "crash", "timeout", "ipc_leak"]:
                # ===== LLM =====
                resp_output = run_primary_output_analysis(readme, program_out)
                resp_code = run_primary_code_analysis(readme, program_out, code)

                fields_output = parse_response(resp_output, ["Output_Correct", "Output_Diagnosis"])
                fields_code = parse_response(resp_code, ["Code_Correct", "Code_Diagnosis"])

                output_corr = fields_output.get("Output_Correct", "")
                diag_output = fields_output.get("Output_Diagnosis", "")
                code_corr = fields_code.get("Code_Correct", "")
                diag_code = fields_code.get("Code_Diagnosis", "")

                if diag_output:
                    diag_output = normalize_diagnosis(diag_output)

                if diag_output:
                    judge_out_ok = judge_output_with_fallback(diag_output, feedback_text)

                if diag_code:
                    diag_code = normalize_diagnosis(diag_code)

                if diag_code and warnings:
                    solution_files = read_solution_code(exercise_dir.name)
                    snippets = []
                    for w in warnings:
                        file = w['file']
                        line = w['line']
                        student_content = lookup_file_content(student_files, file)
                        if student_content:
                            snippets.append(f"File: {file}, Line: {line}\n{extract_around(student_content, line)}")
                    code_around = '\n\n'.join(snippets) if snippets else code

                    sol_snippets = []
                    for w in warnings:
                        file = w['file']
                        line = w['line']
                        solution_content = lookup_file_content(solution_files, file)
                        if solution_content:
                            sol_snippets.append(f"File: {file}, Line: {line}\n{extract_around(solution_content, line)}")
                    solution_code = '\n\n'.join(sol_snippets) if sol_snippets else "\n".join(solution_files.values())
                    
                    judge_code_ok = judge_code_with_warning_fallback(diag_code, warnings, code_around, solution_code)
                elif diag_code:
                    solution_files = read_solution_code(exercise_dir.name)
                    compact_diff = build_compact_solution_diff(diag_code, student_files, solution_files, max_chars=3200)
                    judge_code_ok = judge_code_with_diff_fallback(diag_code, feedback_text, compact_diff)

            # static_failure → LLM static + giudice static
            elif failure == "static_failure":
                # ===== LLM =====
                resp_output = run_primary_output_analysis(readme, program_out)
                resp_code = run_primary_static_code_analysis(readme, code)

                fields_output = parse_response(resp_output, ["Output_Correct", "Output_Diagnosis"])
                fields_code = parse_response(resp_code, ["Code_Correct", "Code_Diagnosis"])

                output_corr = fields_output.get("Output_Correct", "")
                diag_output = fields_output.get("Output_Diagnosis", "")
                code_corr = fields_code.get("Code_Correct", "")
                diag_code = fields_code.get("Code_Diagnosis", "")

                if diag_output:
                    diag_output = normalize_diagnosis(diag_output)

                if diag_output:
                    judge_out_ok = judge_output_with_fallback(diag_output, feedback_text)

                if diag_code:
                    diag_code = normalize_diagnosis(diag_code)

                if diag_code:
                    snippets = []
                    for w in warnings:
                        file = w['file']
                        line = w['line']
                        student_content = lookup_file_content(student_files, file)
                        if student_content:
                            snippets.append(f"File: {file}, Line: {line}\n{extract_around(student_content, line)}")
                    code_around = '\n\n'.join(snippets) if snippets else code

                    judge_code_ok = judge_code_static_with_fallback(diag_code, warnings)

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
                    "primary_model": "meta-llama/llama-4-scout-17b-16e-instruct",
                    "judge_model": "meta-llama/llama-4-scout-17b-16e-instruct",
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
