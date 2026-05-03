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
from openai import AzureOpenAI, OpenAI
from collections import defaultdict, Counter

# ================= CONFIG =================

BASE_SUBMISSIONS_DIR = "/home/andre/esercitazione-1-semafori-submissions"
GROUND_TRUTH_DIR = "/home/andre/ground_truth_es1"
OLLAMA_URL = "http://localhost:11434/api/generate"

# Provider selection: "groq", "azure", or "local"
LLM_PROVIDER = os.getenv("LLM_PROVIDER", "groq").lower()

# ===== GROQ Configuration =====
# Modelli Groq
PRIMARY_MODEL = "meta-llama/llama-4-scout-17b-16e-instruct"  # modello principale per analisi
JUDGE_MODEL   = "meta-llama/llama-4-scout-17b-16e-instruct" # modello giudice per valutare la qualità delle diagnosi

# Gestione chiamate Groq multi-account, creando più chiavi API e ruotandole in caso di esaurimento token giornalieri o limiti di velocità
GROQ_API_KEYS = os.getenv("GROQ_API_KEYS", "").split(",")
GROQ_API_KEYS = [k.strip() for k in GROQ_API_KEYS if k.strip()]

if LLM_PROVIDER == "groq" and not GROQ_API_KEYS:
    raise RuntimeError("No GROQ_API_KEYS found. Set LLM_PROVIDER=azure or provide GROQ_API_KEYS")

CURRENT_KEY_INDEX = 0
DISABLED_KEYS = set()

# ===== AZURE OpenAI Configuration =====
AZURE_OPENAI_ENDPOINT = os.getenv("AZURE_OPENAI_ENDPOINT")
AZURE_OPENAI_API_KEY = os.getenv("AZURE_OPENAI_API_KEY")
AZURE_OPENAI_MODEL_DEPLOYMENT = os.getenv("AZURE_OPENAI_MODEL_DEPLOYMENT", "gpt-4o")

if LLM_PROVIDER == "azure":
    if not AZURE_OPENAI_ENDPOINT or not AZURE_OPENAI_API_KEY:
        raise RuntimeError("Azure OpenAI credentials not found. Set AZURE_OPENAI_ENDPOINT and AZURE_OPENAI_API_KEY")
    AZURE_CLIENT = AzureOpenAI(
        api_version="2024-12-01-preview",
        azure_endpoint=AZURE_OPENAI_ENDPOINT,
        api_key=AZURE_OPENAI_API_KEY
    )
else:
    AZURE_CLIENT = None

COMPILE_TIMEOUT = 120
TEST_TIMEOUT = 120
BASH_ANALYSIS_TIMEOUT = 900
BASH_ANALYSIS_SCRIPT = "/home/andre/Script-Bash-Only-Test-Es1.sh"
COMMIT_SELECTION_WINDOW = 4

LLM_CONNECT_TIMEOUT = 60
LLM_READ_TIMEOUT = 2000

OUTPUT_FILE = "risultati_es1.json"
LOG_SAMPLE_DIR = "experiment_logs"
LLM_CACHE_FILE = "llm_cache.json"

MAX_STUDENTS = None  # Per limitare il numero di studenti analizzati (None per tutti)

# File JSON con tutti i commit (per selezione proporzionale)
# Impostare a None per usare la selezione bash originale
ALL_COMMITS_JSON_FILE = "/home/andre/risultati_es1_tutti_commit_bash.json"  # es. "/home/andre/risultati_es1_tutti_commit_bash.json"

# Categorie per cui si fa solo analisi codice (no output LLM)
# (non compaiono nei grafici di output)
CODE_ONLY_CATEGORIES = {"timeout", "ipc_leak", "crash"}

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
    "Return exactly the requested fields. "
    "DO NOT use markdown formatting, backticks, or code blocks. Return plain text only."
)

JUDGE_SYSTEM_PROMPT = (
    "You are a strict semantic grader. "
    "Accept only diagnoses that match the same concrete symptom or defect as the ground truth. "
    "Reject generic, speculative, partially related, unsupported, or different diagnoses. "
    "When the ground truth is generic, do not promote it into a more specific diagnosis. "
    "When the ground truth says the submission is correct, accept concise no-defect diagnoses unless they invent a problem. "
    "Return exactly the requested field."
)

# ================= TOKEN TRACKING & COST CALCULATION =================
# Struttura globale per accumularei token per modelo
TOKEN_USAGE = {
    "PRIMARY": {"input": 0, "output": 0, "count": 0},
    "JUDGE": {"input": 0, "output": 0, "count": 0},
}

# Pricing per Azure OpenAI (USD per 1K token)
# Aggiornato con prezzi ufficiali GPT-5 2024
PRICING = {
    "gpt-4o": {
        "input": 0.005,  # $5 per 1M input token
        "output": 0.015  # $15 per 1M output token
    },
    "gpt-4-turbo": {
        "input": 0.01,   # $10 per 1M input token
        "output": 0.03   # $30 per 1M output token
    },
    "gpt-4": {
        "input": 0.03,   # $30 per 1M input token
        "output": 0.06   # $60 per 1M output token
    },
    # GPT-5 Series - Prezzi ufficiali 2025
    # Versione standard (Global) - Recommended
    "gpt-5": {
        "input": 0.00125,   # $1.25 per 1M input token
        "output": 0.01      # $10 per 1M output token
    },
    "gpt-5-2025-08-07": {  # Standard Global
        "input": 0.00125,   # $1.25 per 1M input token
        "output": 0.01      # $10 per 1M output token
    },
    "gpt-5-data-zone": {   # Data Zone (higher cost, lower latency)
        "input": 0.00138,   # $1.38 per 1M input token
        "output": 0.011     # $11 per 1M output token
    },
    "gpt-5-pro": {         # Pro version (highest quality)
        "input": 0.015,     # $15 per 1M input token
        "output": 0.12      # $120 per 1M output token
    },
    "gpt-5-codex": {       # Optimized for code
        "input": 0.00125,   # $1.25 per 1M input token
        "output": 0.01      # $10 per 1M output token
    },
    "gpt-5-mini": {        # Lightweight version (Fast & Cheap)
        "input": 0.00025,   # $0.25 per 1M input token
        "output": 0.002     # $2 per 1M output token
    },
    "gpt-5-mini-data-zone": {  # Mini with Data Zone
        "input": 0.00028,   # $0.28 per 1M input token
        "output": 0.0022    # $2.20 per 1M output token
    },
    "gpt-5-nano": {        # Ultra-lightweight (Fastest & Cheapest)
        "input": 0.00005,   # $0.05 per 1M input token
        "output": 0.0004    # $0.40 per 1M output token
    },
    "gpt-5-nano-data-zone": {  # Nano with Data Zone
        "input": 0.00006,   # $0.06 per 1M input token
        "output": 0.00044   # $0.44 per 1M output token
    },
    "gpt-5-chat": {        # Optimized for chat
        "input": 0.00125,   # $1.25 per 1M input token
        "output": 0.01      # $10 per 1M output token
    },
    # Groq è generalmente gratuito, ma lo tracciamo lo stesso
    "groq": {
        "input": 0.0,
        "output": 0.0
    }
}

def track_token_usage(role, input_tokens, output_tokens):
    """Accumula il token usage per ogni role (PRIMARY o JUDGE)"""
    global TOKEN_USAGE
    if role in TOKEN_USAGE:
        TOKEN_USAGE[role]["input"] += input_tokens
        TOKEN_USAGE[role]["output"] += output_tokens
        TOKEN_USAGE[role]["count"] += 1

def calculate_cost(model_name, input_tokens, output_tokens):
    """Calcola il costo in USD per una singola query"""
    if model_name not in PRICING:
        return 0.0
    
    pricing = PRICING[model_name]
    input_cost = (input_tokens / 1000) * pricing["input"]
    output_cost = (output_tokens / 1000) * pricing["output"]
    return input_cost + output_cost

def print_token_costs():
    """Stampa un riepilogo completo di token usati e costi"""
    global TOKEN_USAGE
    
    print("\n" + "="*70)
    print("TOKEN USAGE & COST SUMMARY")
    print("="*70)
    
    model_to_use = AZURE_OPENAI_MODEL_DEPLOYMENT if LLM_PROVIDER == "azure" else LLM_PROVIDER
    
    total_cost = 0.0
    for role, stats in TOKEN_USAGE.items():
        input_tokens = stats["input"]
        output_tokens = stats["output"]
        call_count = stats["count"]
        
        if call_count > 0:
            cost = calculate_cost(model_to_use, input_tokens, output_tokens)
            total_cost += cost
            
            avg_input = input_tokens // call_count if call_count > 0 else 0
            avg_output = output_tokens // call_count if call_count > 0 else 0
            
            print(f"\n[{role} MODEL]")
            print(f"  Calls:           {call_count}")
            print(f"  Total Input:     {input_tokens:,} tokens")
            print(f"  Total Output:    {output_tokens:,} tokens")
            print(f"  Total Tokens:    {input_tokens + output_tokens:,}")
            print(f"  Avg Input/Call:  {avg_input:,} tokens")
            print(f"  Avg Output/Call: {avg_output:,} tokens")
            print(f"  Cost:            ${cost:.4f} USD")
    
    print(f"\n[TOTAL]")
    print(f"  All Input Tokens:  {TOKEN_USAGE['PRIMARY']['input'] + TOKEN_USAGE['JUDGE']['input']:,}")
    print(f"  All Output Tokens: {TOKEN_USAGE['PRIMARY']['output'] + TOKEN_USAGE['JUDGE']['output']:,}")
    print(f"  Grand Total Cost:  ${total_cost:.4f} USD")
    print(f"  Provider:          {LLM_PROVIDER.upper()}")
    print(f"  Model:             {model_to_use}")
    print("="*70 + "\n")

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

CURRENT_MODEL_USAGE = {"PRIMARY": "meta-llama/llama-4-scout-17b-16e-instruct", "JUDGE": "meta-llama/llama-4-scout-17b-16e-instruct"}
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

def get_next_api_key():
    global CURRENT_KEY_INDEX

    for _ in range(len(GROQ_API_KEYS)):
        key = GROQ_API_KEYS[CURRENT_KEY_INDEX]
        CURRENT_KEY_INDEX = (CURRENT_KEY_INDEX + 1) % len(GROQ_API_KEYS)

        if key not in DISABLED_KEYS:
            return key

    raise Exception("ALL_KEYS_EXHAUSTED")

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

def llm_safe_call(fn, prompt, model, system_prompt, max_completion_tokens=None, role="PRIMARY"):
    """
    Wrapper per chiamate LLM sicure (Groq o Azure OpenAI)
    """
    MAX_RETRIES = 3
    retries = 0
    last_error = None

    while retries < MAX_RETRIES:
        try:
            if LLM_PROVIDER == "groq":
                api_key = get_next_api_key()
                return fn(prompt, model, system_prompt, api_key, role)
            else:  # azure
                return fn(prompt, model, system_prompt, None, role)

        except Exception as e:
            last_error = e
            msg = str(e)

            # Per Groq: TPD LIMIT
            if "tokens per day" in msg and LLM_PROVIDER == "groq":
                print(f"API key esaurita, passo alla prossima...")
                DISABLED_KEYS.add(api_key)
                retries += 1
                continue

            # PROMPT TOO LARGE
            if "Request too large" in msg or "reduce your message size" in msg:
                raise Exception(f"PROMPT_TOO_LARGE::{msg}")
            
            if "ALL_KEYS_EXHAUSTED" in str(e) and LLM_PROVIDER == "groq":
                print("Tutte le API key esaurite")
                return

            # RATE LIMIT BREVE (solo Groq)
            if LLM_PROVIDER == "groq":
                m = re.search(r"try again in ([0-9.]+)(ms|s)", msg)
                if m:
                    wait = float(m.group(1))
                    unit = m.group(2)
                    if unit == "ms":
                        wait = wait / 1000.0
                    if wait <= 30:
                        retries += 1
                        print(f"[RATE WAIT] sleeping {wait:.2f}s")
                        time.sleep(wait)
                        continue
                    else:
                        raise Exception(f"MODEL_RATE_LIMIT::{msg}")

            # Per Azure: se timeout, retry
            if "timeout" in msg.lower() and retries < MAX_RETRIES - 1:
                retries += 1
                wait_time = 2 ** retries  # exponential backoff
                print(f"[AZURE WAIT] Timeout, retrying in {wait_time}s...")
                time.sleep(wait_time)
                continue

            # Per Azure: altri errori possono essere riprova
            if LLM_PROVIDER == "azure" and retries < MAX_RETRIES - 1:
                if any(x in msg.lower() for x in ["connection", "error", "server"]):
                    retries += 1
                    wait_time = (retries + 1) * 2
                    print(f"[AZURE RETRY] Errore Azure, retry in {wait_time}s...")
                    time.sleep(wait_time)
                    continue

            # fallback è errore reale (non rientra in retry)
            raise

    # Se esce dal loop normalmente, è un errore
    raise Exception(f"EXHAUSTED_RETRIES: {last_error}")


def query_groq(prompt, model, system_prompt, api_key=None, role="PRIMARY"):
    """
    Interrogazione a Groq AI (aggiornata con endpoint corretto)
    """
    try:
        if api_key is None:
            api_key = get_next_api_key()

        headers = {
            "Authorization": f"Bearer {api_key}",
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

        # Estrazione token usage da Groq e tracciamento
        if "usage" in data:
            input_tokens = data["usage"].get("prompt_tokens", 0)
            output_tokens = data["usage"].get("completion_tokens", 0)
            track_token_usage(role, input_tokens, output_tokens)
            log(f"[GROQ-{role}] Input: {input_tokens}, Output: {output_tokens}, Total: {input_tokens + output_tokens}")
        else:
            log(f"[GROQ-{role}] No usage data in response")

        return data["choices"][0]["message"]["content"]

    except Exception as e:
        raise Exception(f"GROQ ERROR: {e}")


def query_azure_openai(prompt, model, system_prompt, api_key=None, role="PRIMARY"):
    """
    Interrogazione a Azure OpenAI (ChatGPT 4-o o altro modello)
    """
    try:
        if AZURE_CLIENT is None:
            raise Exception("Azure OpenAI client not initialized")

        response = AZURE_CLIENT.chat.completions.create(
            model=AZURE_OPENAI_MODEL_DEPLOYMENT,
            messages=[
                {
                    "role": "system",
                    "content": system_prompt,
                },
                {"role": "user", "content": prompt},
            ],
            temperature=0.0,
            max_tokens=4096,
            top_p=0.1
        )

        content = response.choices[0].message.content
        
        # Estrazione token usage da Azure e tracciamento
        if hasattr(response, 'usage') and response.usage:
            input_tokens = response.usage.prompt_tokens
            output_tokens = response.usage.completion_tokens
            track_token_usage(role, input_tokens, output_tokens)
            cost = calculate_cost(AZURE_OPENAI_MODEL_DEPLOYMENT, input_tokens, output_tokens)
            log(f"[AZURE-{role}] Input: {input_tokens}, Output: {output_tokens}, Total: {input_tokens + output_tokens}, Cost: ${cost:.6f}")
        else:
            log(f"[AZURE-{role}] No usage data available")
        
        return content

    except Exception as e:
        raise Exception(f"AZURE OPENAI ERROR: {e}")

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
    Interroga modelli LLM usando il provider configurato (Groq o Azure OpenAI).
    """
    try:
        if LLM_PROVIDER == "groq":
            if model not in {PRIMARY_MODEL, JUDGE_MODEL}:
                raise ValueError(f"Model {model} not supported in Groq configuration")
            
            system_prompt = system_prompt_for_role(role)
            response = llm_safe_call(
                query_groq,
                prompt,
                model,
                system_prompt,
                role=role
            )
        elif LLM_PROVIDER == "azure":
            # Per Azure, ignoriamo il model name da Groq e usiamo il deployment Azure
            system_prompt = system_prompt_for_role(role)
            response = llm_safe_call(
                query_azure_openai,
                prompt,
                AZURE_OPENAI_MODEL_DEPLOYMENT,
                system_prompt,
                role=role
            )
        else:
            raise ValueError(f"Unknown LLM_PROVIDER: {LLM_PROVIDER}")

        if not response:
            print(f"[WARNING] query_model returned empty response (role={role})")
            return "ERRORE_LLM"

        return response
    except Exception as e:
        print(f"[ERROR] query_model failed: {str(e)[:100]}")
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

BASE_TESTS_DIR = Path("/home/andre/so_esercitazione_1_semafori-main")

def inject_tests(student_dir, exercise_dir):
    """
    Copia solo i test specifici dell'esercizio nella cartella esercizio
    GARANTENDO che la .test sia pulita (no merge).
    """
    specific_src = BASE_TESTS_DIR / exercise_dir.name / ".test"
    exercise_test_dir = exercise_dir / ".test"

    # PULIZIA FORZATA della cartella esercizio
    if exercise_test_dir.exists():
        shutil.rmtree(exercise_test_dir)

    # COPIA test specifici dell'esercizio
    if specific_src.exists():
        shutil.copytree(specific_src, exercise_test_dir)

# ================= TEST DINAMICI MULTI-SCRIPT =================
def extract_shell_assignment(script_path: Path, variable_name: str, default: str = ""):
    try:
        content = script_path.read_text(encoding="utf-8", errors="ignore")
    except Exception:
        return default

    match = re.search(rf"(?m)^\s*{re.escape(variable_name)}=(.+?)\s*$", content)
    if not match:
        return default

    value = match.group(1).strip()
    if len(value) >= 2 and value[0] == value[-1] and value[0] in {"'", '"'}:
        value = value[1:-1]

    return value or default


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
    valid_scripts = {
    p.name for p in (BASE_TESTS_DIR / path.name / ".test").glob("*.sh")
    } if (BASE_TESTS_DIR / path.name / ".test").exists() else set()

    scripts = sorted([
        s for s in test_dir.glob("*.sh")
        if s.name in valid_scripts
    ])
    if not scripts:
        raise RuntimeError(f"Nessuno script .sh trovato in {test_dir}")

    feedback_file = "/tmp/feedback.md"

    all_results = []

    for script in sorted(scripts):
        output_file = extract_shell_assignment(script, "OUTPUT", "/tmp/output.txt")
        error_log = extract_shell_assignment(script, "ERROR_LOG", "/tmp/error-log.txt")
        script_content = script.read_text(encoding="utf-8", errors="ignore")
        expects_runtime_output = "compile_and_run" in script_content and "OUTPUT=" in script_content

        # Pulizia file temporanei
        for f in {feedback_file, output_file, error_log, "/tmp/output.txt", "/tmp/minimo.txt"}:
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
            explicit_pass = re.search(r"(?m)^\s*pass\s*$", lower_out) is not None
            ok = res.returncode == 0 and explicit_pass and "fail" not in lower_out

            # Legge l'output prodotto dal programma
            program_output = ""
            if os.path.exists(output_file):
                program_output = Path(output_file).read_text(errors="ignore").strip()
            has_runtime_output = bool(program_output.strip())
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
    
    # Estrai l'esercizio dal path
    exercise_dir_name = path.name  # es. "server_aggregatore_thread"
    
    # Mapping tra nomi directory e nomi nel feedback
    feedback_name_mapping = {
        "remote_procedure_call": "Esercizio remote procedure call",
        "server_aggregatore_thread": "Esercizio server aggregatore con thread",
        "un_primo_esempio_di_server_multithread": "Esercizio primo esempio di server multithread",
    }
    
    # Ottieni il nome dell'esercizio come appare nel feedback
    exercise_feedback_name = feedback_name_mapping.get(exercise_dir_name, f"Esercizio {exercise_dir_name.replace('_', ' ')}")

    # Funzione interna per rimuovere i nomi degli script
    def remove_script_names(text):
        if not text:
            return ""
        return re.sub(r"\[.*?\.sh\]\s*\n?", "", text)
    
    # Funzione per filtrare il feedback all'esercizio specifico
    def filter_feedback_by_exercise(feedback_text, feedback_name):
        """Estrae dal feedback SOLO la sezione per questo esercizio"""
        if not feedback_text:
            return ""
        # Dividi per "##" per ottenere sezioni
        sections = feedback_text.split("##")
        for section in sections:
            # Controlla se questo nome è in questa sezione
            if feedback_name.lower() in section.lower():
                # Ritorna questa sezione con il "##" ripristinato
                return "##" + section
        # Se non trova, ritorna il feedback originale per diagnosticare
        return feedback_text

    # caso 1: un solo script è comportamento identico a prima, ma pulito
    if len(all_results) == 1:
        r = all_results[0]
        feedback = remove_script_names(r["feedback"])
        feedback = filter_feedback_by_exercise(feedback, exercise_feedback_name)
        return (
            r["ok"],
            remove_script_names(r["script_out"]),
            remove_script_names(r["script_err"]),
            remove_script_names(r["program_output"]),
            feedback
        )

    # caso 2: più script è aggrega e poi pulisci
    all_ok = all(r["ok"] for r in all_results)

    all_stdout = "".join(r["script_out"] for r in all_results if r["script_out"])
    all_stderr = "".join(r["script_err"] for r in all_results if r["script_err"])
    all_program_output = "".join(r["program_output"] for r in all_results if r["program_output"])
    all_feedback = "".join(r["feedback"] for r in all_results if r["feedback"])

    # Rimuove tutti i prefissi [nome_script.sh]
    all_stdout = remove_script_names(all_stdout)
    all_stderr = remove_script_names(all_stderr)
    all_program_output = remove_script_names(all_program_output)
    all_feedback = remove_script_names(all_feedback)
    # Filtra il feedback per questo esercizio
    all_feedback = filter_feedback_by_exercise(all_feedback, exercise_feedback_name)

    return all_ok, all_stdout, all_stderr, all_program_output, all_feedback

def clean_feedback_for_json(feedback_text):
    if not feedback_text:
        return ""

    feedback_text = re.sub(r":[a-z_]+:", "", feedback_text)
    feedback_text = re.sub(r"<br/><pre>\s*</pre>", "", feedback_text, flags=re.S)
    feedback_text = re.sub(r"<br/><pre>.*?</pre>", "", feedback_text, flags=re.S)
    feedback_text = re.sub(r"<pre>\s*</pre>", "", feedback_text, flags=re.S)
    feedback_text = re.sub(r"<[^>]+>", "", feedback_text)
    feedback_text = feedback_text.replace("\r", "")
    feedback_text = re.sub(r"\n{3,}", "\n\n", feedback_text)
    feedback_text = feedback_text.strip()
    return feedback_text.strip()


def normalize_static_warnings(raw_warnings):
    if not raw_warnings:
        return []

    if isinstance(raw_warnings, list):
        return raw_warnings

    if isinstance(raw_warnings, str):
        try:
            parsed = json.loads(raw_warnings)
            return parsed if isinstance(parsed, list) else []
        except Exception:
            return []

    return []

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
        ["git", "checkout", "-q", commit_hash, "--", "."],
        cwd=repo_path,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL
    )

def checkout_head(repo_path):
    subprocess.run(
        ["git", "checkout", "-q", "HEAD", "--", "."],
        cwd=repo_path,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL
    )

def get_student_commit_candidates(student_dir, exercise_names, window=COMMIT_SELECTION_WINDOW):
    pathspecs = list(exercise_names) if exercise_names else ["."]
    try:
        res = subprocess.run(
            ["git", "rev-list", "HEAD", "--", *pathspecs],
            cwd=student_dir,
            capture_output=True,
            text=True,
            check=True
        )
        commits = [line.strip() for line in res.stdout.splitlines() if line.strip()]
    except Exception:
        commits = []

    if not commits:
        return ["HEAD"]

    if len(commits) == 1:
        return commits[:1]

    previous_first = commits[1:1 + window]
    return previous_first or commits[:1]

def run_bash_student_commit_analysis(student_dir, commit_hash):
    try:
        res = subprocess.run(
            [
                "bash",
                BASH_ANALYSIS_SCRIPT,
                "--single-student-commit",
                "--student-dir",
                str(student_dir),
                "--commit",
                commit_hash,
                "--quiet",
            ],
            capture_output=True,
            text=True,
            timeout=BASH_ANALYSIS_TIMEOUT,
            check=True,
        )
        stdout = res.stdout.strip()
        if not stdout:
            return []
        return json.loads(stdout)
    except Exception as e:
        log(f"[BASH ANALYSIS ERROR] student={student_dir.name} commit={commit_hash}: {e}")
        return []

def score_student_commit_candidate(candidate_results, correct_count, incorrect_count, rank):
    correct_hits = sum(1 for r in candidate_results if r.get("failure_category") == "correct")
    static_hits = sum(1 for r in candidate_results if r.get("failure_category") == "static_failure")
    incorrect_hits = len(candidate_results) - correct_hits

    need_more_correct = correct_count < incorrect_count
    preferred_hits = correct_hits if need_more_correct else incorrect_hits
    imbalance_after = abs((correct_count + correct_hits) - (incorrect_count + incorrect_hits))

    return (
        static_hits,
        -imbalance_after,
        preferred_hits,
        -rank,
        len(candidate_results),
    )

def select_student_commit(student_dir, pending_exercises, correct_count, incorrect_count):
    candidates = get_student_commit_candidates(student_dir, pending_exercises)
    evaluated = []
    required_exercises = set(pending_exercises)

    for rank, commit_hash in enumerate(candidates):
        candidate_results = run_bash_student_commit_analysis(student_dir, commit_hash)
        candidate_results = [r for r in candidate_results if r.get("exercise") in pending_exercises]
        covered_exercises = {r.get("exercise") for r in candidate_results}

        log(
            "       Candidato "
            f"{commit_hash[:12]}: "
            f"copertura={len(covered_exercises)}/{len(required_exercises)}, "
            f"static={sum(1 for r in candidate_results if r.get('failure_category') == 'static_failure')}, "
            f"correct={sum(1 for r in candidate_results if r.get('failure_category') == 'correct')}, "
            f"non_correct={sum(1 for r in candidate_results if r.get('failure_category') != 'correct')}"
        )

        if covered_exercises != required_exercises:
            continue

        score = score_student_commit_candidate(candidate_results, correct_count, incorrect_count, rank)
        evaluated.append((score, rank, commit_hash, candidate_results))

    if evaluated:
        evaluated.sort(reverse=True)
        _, _, selected_commit, selected_results = evaluated[0]
        return selected_commit, selected_results

    fallback_commit = "HEAD"
    fallback_results = run_bash_student_commit_analysis(student_dir, fallback_commit)
    fallback_results = [r for r in fallback_results if r.get("exercise") in pending_exercises]
    return fallback_commit, fallback_results


def load_all_commits_data(all_commits_json_file):
    """Carica il file JSON con tutti i commit."""
    if not all_commits_json_file:
        return []
    p = Path(all_commits_json_file)
    if not p.exists():
        return []
    with open(p, encoding="utf-8") as f:
        return json.load(f)


def select_student_commit_proportional(student_name, all_commits_data,
                                        pending_exercises, all_exercises,
                                        correct_count, incorrect_count,
                                        current_cat_counts=None):
    """
    Seleziona il commit ottimale per ogni esercizio dello studente,
    minimizzando la distanza L1 dalla distribuzione target (proporzionale
    a tutti_commit) su TUTTE le categorie.

    IMPORTANTE: commit diversi possono essere usati per esercizi diversi
    dello stesso studente. Questo permette una distribuzione proporzionale
    anche quando la maggior parte degli studenti ha solo commit con
    compile_failure su tutti gli esercizi contemporaneamente.

    Parametri:
    - current_cat_counts: Counter con la distribuzione corrente dei record
      già selezionati. Aggiornato dal chiamante dopo ogni record salvato.

    Ritorna: (None, [analysis_records]) dove analysis_records contiene
             1 record per esercizio (potenzialmente da commit diversi).
    """
    # Filtra i record dello studente
    student_records = [r for r in all_commits_data if r.get("student") == student_name]
    if not student_records:
        return None, []

    # Distribuzione target: proporzionale a tutti_commit
    global_cats = Counter(r["failure_category"] for r in all_commits_data)
    total_global = sum(global_cats.values())
    if total_global == 0:
        return None, []
    target_fractions = {cat: cnt / total_global for cat, cnt in global_cats.items()}

    # Distribuzione corrente
    if current_cat_counts is None:
        current_cat_counts = Counter()
        if correct_count > 0:
            current_cat_counts["correct"] = correct_count
        if incorrect_count > correct_count:
            current_cat_counts["compile_failure"] = incorrect_count - correct_count

    rare_cats = {"static_failure", "dynamic_failure", "timeout", "crash"}

    # Per ogni esercizio pending, scegli il commit ottimale
    # Raggruppa per (exercise, commit)
    by_ex_commit = defaultdict(lambda: defaultdict(list))
    for r in student_records:
        by_ex_commit[r["exercise"]][r["commit_analyzed"]].append(r)

    selected_records = []
    running_counts = Counter(current_cat_counts)  # copia locale per simulazione

    for exercise in pending_exercises:
        commits_for_ex = by_ex_commit.get(exercise, {})
        if not commits_for_ex:
            continue

        best_score = None
        best_record = None

        for commit, recs in commits_for_ex.items():
            # Prendi il record per questo esercizio da questo commit
            ex_recs = [r for r in recs if r.get("exercise") == exercise]
            if not ex_recs:
                continue
            rec = ex_recs[0]
            cat = rec.get("failure_category", "")

            # Calcola distanza L1 dopo aver aggiunto questo record
            new_counts = Counter(running_counts)
            new_counts[cat] += 1
            new_total = sum(new_counts.values())

            all_cats_set = set(list(target_fractions.keys()) + list(new_counts.keys()))
            l1_dist = sum(
                abs(new_counts.get(c, 0) / new_total - target_fractions.get(c, 0))
                for c in all_cats_set
            )
            rare_bonus = 1 if cat in rare_cats else 0
            score = (-l1_dist, rare_bonus)

            if best_score is None or score > best_score:
                best_score = score
                best_record = rec

        if best_record:
            selected_records.append(best_record)
            running_counts[best_record["failure_category"]] += 1

    if selected_records:
        # Ritorna None come commit (non c'è un commit unico) e i record selezionati
        return "MULTI_COMMIT", selected_records

    return None, []

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

def run_primary_code_analysis(readme, program_output, code, failure_category=None, output_diagnosis=""):
    prompt = prompt_codice(readme, program_output, code, failure_category=failure_category, output_diagnosis=output_diagnosis)
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
- A YES answer requires that the visible trace is consistent with the exercise protocol. It does not require exhaustive verification of every value if the overall structure is coherent.

Exercise description:
{readme}

Program output:
{program_output}

Decision rules:
- If the output is empty, blank, or equivalent to "The program produced no output.", then Output_Correct = NO.
- If the visible output contains "timeout" (or any equivalent timeout/termination message), then Output_Correct = NO.
- Missing messages, wrong counts, malformed exchanges, mismatched IDs/PIDs/request numbers, impossible ordering, or wrong computed values visible in the output imply Output_Correct = NO.
- The diagnosis must describe the observable symptom only, not the possible code cause.
- Use the visible order of events as the order of observation.
- In concurrent or multi-process traces, stdout interleaving by itself is not a protocol violation ONLY if each visible actor stream (per PID/role) is internally coherent and replies unambiguously reference their senders.
- When actor identity is visible, evaluate counts and duplicates per actor/role/PID namespace, not by raw message numbers alone.
- Do not infer a round-robin, routing, or balancing violation from interleaving alone UNLESS the visible reply identifiers explicitly show that messages were routed to wrong destinations.
- If the trace gives enough information to validate values one by one, explicitly recompute those values before claiming a mismatch. Do not rely on intuition or operation names alone for arithmetic checks.
- A later consume/receive/dequeue/read that reveals meaningful data does not by itself prove that an earlier produce/send/enqueue/store reply was wrong.
- Count the number of each operation family mentioned in the trace. If counts appear inconsistent with the visible protocol, mark NO with evidence.
- If the test feedback explicitly reports an incorrect execution or mismatch, treat this as a strong signal that Output_Correct should be NO.
- CONCURRENT LOG ORDER: In concurrent or multi-process/multi-thread systems, a server or worker may print its log entry after the client has already received and printed the reply. This is normal and does not constitute an ordering violation. Evaluate protocol correctness based on the logical sequence of operations (request sent, reply received), not on the physical order of log lines in stdout.
- DISPATCHER AUTHORITY: If a dispatcher, balancer, router, or aggregator log shows the correct distribution or forwarding of messages, accept that as evidence of correct routing. Do not require that the downstream recipients print their logs in the same order as the dispatcher's routing decisions.
- SIDE-EFFECTING OPERATIONS: For operations that produce, enqueue, store, or register a value (e.g., PRODUCI, send, enqueue, register), a reply value of 0 or a neutral acknowledgment is correct unless the exercise description explicitly states that the immediate reply must carry the produced payload. The produced value appearing in a later consume/dequeue/read operation is the expected behavior.
- PER-ACTOR COUNT TOLERANCE: In fan-out or broadcast scenarios where one source forwards to multiple consumers via a shared buffer or queue, individual consumers may receive slightly different counts due to scheduling. Do not mark NO solely because one consumer received one fewer value than another, unless the exercise explicitly requires each consumer to receive exactly the same count.
- LOCAL SEQUENCE NUMBERS: A receiver or server may assign its own local sequence numbers (0, 1, 2, 3...) to messages it receives. These local numbers are independent of the original message numbers assigned by the sender. Do not treat a mismatch between a receiver's local sequence number and the sender's original message number as a protocol violation.
- CONCURRENT MULTI-CLIENT REPLIES: When multiple clients send requests concurrently to the same server or registry, replies may arrive at each client in a different order than the requests were sent, due to scheduling. A reply is correct if it matches any pending request from that client, not necessarily the most recently sent one. Do not mark NO solely because a reply appears to match a different request than the immediately preceding one in the log.
- IDENTICAL REPEATED REQUESTS: If a client sends multiple requests with the same operands or parameters, receiving identical replies is correct and expected. Do not treat repeated identical responses as a protocol violation or as evidence of missing randomness, unless the exercise description explicitly requires distinct values for each request.
- LATE-STARTING CONSUMERS: In producer-consumer or fan-out scenarios, a consumer or collector that starts after the producer has already begun sending may miss the first few messages. This is a scheduling artifact, not a protocol error, unless the exercise explicitly requires all consumers to receive all messages from the beginning.
- AGGREGATE COUNT VERIFICATION: When verifying message counts in a routing or distribution scenario, verify the total count across all senders and all receivers, not the per-actor count in isolation. For example, if 2 clients each send 6 messages to a balancer that distributes to 3 servers, each server correctly receives 4 messages (12 total / 3 servers = 4 each). Do not mark NO because each server receives fewer messages than each client sent; verify that the total sent equals the total received.
- CONSUMA REPLY VALUE: In a producer-consumer RPC protocol, CONSUMA (consume) returns the value that was previously produced and stored in the buffer. The returned value is the stored payload, not a computed result. Do not mark NO because a CONSUMA reply returns a value that was produced by a previous PRODUCI call; this is the expected behavior. Only mark NO if the returned value does not match any previously produced value that should still be in the buffer.
- SPOTCHECK: For at least one complete request/reply cycle or producer/consumer pair, verify that operands/inputs match outputs/results using concrete visible values. If you cannot spotcheck even one cycle, explain which values cannot be verified.
- BALANCED JUDGMENT: If the trace shows the expected actors, the expected number of interactions, and at least one verifiable correct value exchange, mark YES even if not every single value can be independently verified. Do not require exhaustive verification when the overall structure is coherent.
- If the trace is structurally complete (all expected phases present, all actors visible, counts match) and no concrete mismatch is found, mark YES.
- If the trace is structurally complete but one specific value or pairing is concretely wrong, mark NO and identify that specific mismatch.
- Do not mark NO merely because the trace is concurrent and some values cannot be independently attributed to specific actors, unless the exercise explicitly requires per-actor attribution.
- If Output_Correct = YES, the diagnosis must explicitly say that no concrete output mismatch is visible and confirm that the trace structure is consistent with the exercise protocol.
- If Output_Correct = NO, identify the specific broken interaction: missing trace, wrong values, wrong counts, wrong pairing, wrong ordering, or unverifiable value flows.
- Keep the diagnosis detailed but compact: maximum of 100 words.
- Write the diagnosis in English.
- Do not quote or refer to hidden tests, hidden assertions, or hidden ground truth.

Final format only:
Output_Correct: YES or NO
Output_Diagnosis: <detailed evidence-based diagnosis>
"""


def prompt_codice(readme, program_output, code, failure_category=None, output_diagnosis=""):
    runtime_focus = ""
    if failure_category in {"dynamic_failure", "timeout", "ipc_leak", "crash"}:
        runtime_focus = f"""

Runtime-failure focus:
- The observed runtime failure category is: {failure_category}
- The current output diagnosis is:
{output_diagnosis or "No output diagnosis available."}
- In this case, do NOT look for a generic bug or a secondary static issue.
- Identify ONLY the code cause that best explains why the execution failed in that specific way.
- If output_diagnosis explicitly names a missing phase, wrong value, or protocol mismatch, prioritize finding the code statement that causes that specific symptom.
- First verify that the reported runtime symptom is grounded in an explicit contract from the exercise or visible trace.
- If the reported symptom depends on assuming that an immediate reply must carry a produced/computed payload, but that contract is not explicit, do not adopt that assumption as the target defect.
- If the code only shows unrelated issues that do not explain that runtime failure, answer YES rather than inventing a different NO diagnosis.
"""

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
- If evidence is weak and the observed output shows successful execution (complete protocol phases, no truncation), answer YES.
- Do not invent hidden constraints.

Exercise description:
{readme}

Observed runtime/output:
{program_output}
{runtime_focus}

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
- CROSS-CHECK OUTPUT: If the provided program_output shows incomplete/missing/wrong protocol phases (e.g., missing EXIT messages, incomplete BIND handshakes, truncated request/reply pairs), treat this as evidence of a code cause UNLESS the exercise explicitly allows partial execution or early termination. Do not answer YES when the output itself signals failure.
- Do not claim a race condition unless unsynchronized concurrent accesses to the same shared state are explicitly visible in the code.
- Do not claim a missing pthread_join() unless the code can terminate before required work completes and no alternative waiting/synchronization is visible.
- Do not claim a missing critical section unless both the concurrent access and the unprotected operation are visible.
- If the code already shows mutexes, semaphores, condition variables, monitor procedures, or dedicated read/write functions, do not diagnose "missing synchronization primitives" unless the shown declarations and operations truly contain no synchronization mechanism for the relevant path.
- In reader-writer style code, if reader and writer procedures are already present, prefer diagnosing the wrong reader-writer policy or over-serialization of readers rather than claiming there is no synchronization at all.
- Do not diagnose a reader-writer defect as a generic mutex defect unless the code clearly shows that only ordinary mutual exclusion was required.
- Do not diagnose a queue-ID or selector mix-up merely because one variable stores or aliases another queue identifier; diagnose it only if the visible send/receive or type-selection sites are concretely inconsistent.
- On a shared queue, mailbox, or channel used by multiple logical senders, receivers, or phases, check whether the visible selector/type/tag actually distinguishes the actors whose results are later attributed separately.
- Reusing the same selector/type/tag for replies from different logical sources on the same shared channel is a concrete protocol-matching defect when the receiver later treats the received values as coming from specific roles, processes, phases, or operations.
- Conversely, do not diagnose a shared-channel matching bug if the code visibly uses dedicated queues/channels or distinct selectors that already separate the logical sources.
- Do not cite pseudocode labels, natural-language placeholders, or comments as code evidence unless they literally appear in the code.
- Do not infer exercise-specific obligations unless they are explicit in the description or directly visible in the code.
- Do not answer YES merely because one specific API name is absent. If the visible implementation of the relevant code path omits the required mechanism, selector, synchronization policy, cleanup step, or ownership pattern, that omission may itself justify NO.
- Do not diagnose generic error-handling defects such as missing return-value checks, missing errno checks, or missing validation unless the observed failure is about that path or the code makes that defect the central visible cause.
- When runtime feedback is only black-box and the code does not show one explicit violating statement or omission, prefer YES over a speculative NO.
- For dynamic_failure, timeout, ipc_leak, or crash, use the provided output diagnosis as the target symptom and explain the concrete code cause of that failure, not a different secondary issue that could exist even if execution succeeded.
- For dynamic_failure, timeout, ipc_leak, or crash, do not use rule-style static findings or generic code smells as evidence unless they directly explain the observed runtime failure.
- For dynamic_failure, timeout, ipc_leak, or crash, if the code does not show a concrete cause for the observed runtime symptom, prefer YES over diagnosing a different unrelated bug.
- For dynamic_failure, timeout, ipc_leak, or crash, do not let a superficially coherent trace override a concrete main-path selector/routing ambiguity visible in the code.
- If the main success path visibly multiplexes multiple logical sources through one shared queue/channel without a discriminator that matches the later role-specific attribution, that is concrete evidence for NO even when the runtime trace looks arithmetically coherent.
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
- Do not diagnose a constant or zero reply field as a defect unless the exercise description or visible runtime symptom explicitly shows that this reply field must carry the produced or computed payload for that operation.
- For side-effecting operations such as produce, send, store, enqueue, or register, a later consume/read/dequeue revealing the value does not by itself prove that the earlier reply field is wrong.
- ERROR HANDLING RULE: Do NOT diagnose error-handling defects unless they directly cause the observed runtime failure:
  * Do not diagnose missing checks on malloc/calloc/queue-creation/thread-creation failures unless the test output shows the program actually crashed or produced wrong output due to that failure.
  * Do not diagnose memory leaks in error paths (e.g., "allocated but not freed if pthread_create fails") because the test suite does not induce these anomalous failure conditions.
  * Do not report missing error handling for resource allocation failures that do not occur during the visible runtime execution shown in the output.
  * Focus on defects that affect the main success path: synchronization, protocol correctness, resource lifetime in normal operation, and control flow.
  * Error handling quality is important for robustness but is outside the scope of dynamic correctness testing when anomalous failures are not triggered.
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
- CROSS-CHECK OUTPUT: If the provided program_output shows incomplete protocol phases, missing termination messages, truncated exchanges, or other structural problems (even if execution didn't hang), this may signal a code defect. Do not immediately default to YES if the output itself looks incomplete.
- Do not speculate about hidden races, hidden deadlocks, hidden queue mix-ups, hidden lifetime bugs, or unobserved protocol failures.
- If mutexes, semaphores, condition variables, monitor procedures, or reader/writer functions are visible, do not call the defect "missing synchronization primitives" unless the shown path truly contains no synchronization mechanism at all.
- Do not diagnose a queue-ID or selector mix-up unless the visible send/receive or type-selection sites are concretely inconsistent.
- If Code_Correct = NO, cite at least one file name and one function, API, variable, or short code fragment exactly as visible in the code.
- ERROR HANDLING RULE: Do NOT diagnose error-handling defects when the code is otherwise correct:
  * Do not report missing checks on malloc/calloc/queue-creation/thread-creation failures if the code executes successfully and the test suite passes.
  * Do not report memory leaks "if pthread_create fails" or "if malloc returns NULL" because these error paths are not exercised during the passing test execution.
  * Recognize that passing tests are evidence the resource allocation always succeeds in the tested scenarios; error-handling robustness is outside the scope of dynamic correctness testing.
  * Focus only on bugs that would cause observable wrong output or protocol violations in normal (successful resource allocation) execution.
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
- ERROR HANDLING RULE: Do NOT diagnose missing error-handling code as a structural defect:
  * Do not report missing checks on malloc/calloc/queue-creation/thread-creation failures unless they are concretely called in the analyzed code path during normal execution.
  * Do not report memory leaks "if pthread_create fails" or "if malloc returns NULL" because failure paths are not exercised in normal usage.
  * Do not diagnose missing error handling on resource allocation failures unless the test suite evidence or code context shows that these failures are triggered.
  * Focus on structural defects that affect normal (success-path) execution: synchronization policy, lifetime/ownership in success paths, scope/order violations in main control flow.
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
- Do not collapse a specialized policy defect into a generic 'missing mutex' diagnosis.
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


def prompt_giudice_output(diagnosi, output_ground_truth):
    return f"""
Grade an output diagnosis against the ground truth about the visible execution/output.

Diagnosis:
{diagnosi}

Ground truth about output:
{output_ground_truth}

Rules:
- Focus on semantic alignment: does the diagnosis capture the essence of the same failure?
- Accept the diagnosis if it correctly identifies a type of output problem that matches the ground truth failure.
- Accept the diagnosis if it correctly states that the output is correct and the ground truth confirms correct output.
- Reject only if the diagnosis contradicts the ground truth or claims a different category of failure.
- Treat detailed diagnoses as enrichments of generic ground truth. If ground truth says "execution incorrect" but does not detail why, a diagnosis identifying the specific type of error (wrong value, missing interaction, wrong pairing, wrong count) is acceptable.
- Paraphrases and different framings of the same symptom are correct.
- If the diagnosis states that "the program produced no output," it is correct whenever the ground truth indicates failure during execution, even if ground truth is generic.
- If the ground truth says output is correct, accept a diagnosis saying no mismatch is visible unless the diagnosis adds a different invented problem.
- Briefly explain why the diagnosis matches or does not match the output ground truth.

Final format only:
Judge_Motivation: <short reason>
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
- Prefer semantic equivalence over exact textual matching across different levels of abstraction.
- Accept the diagnosis if it identifies the same defect mechanism, even if phrased differently or at a different architectural level.
- A diagnosis identifying a root cause or prerequisite condition for the warned defect should be accepted if causally related.
  * Example: If warning says "readers must read concurrently" and diagnosis says "threads are not created," accept if the absence of threads directly prevents the concurrent reading.
  * Counter-example: If diagnosis identifies a completely different code path, reject.
- Line numbers are not authoritative; a diagnosis valid even if it refers to a different line within the same mechanism.
- Accept correct statements that the code is sound if no real warnings exist.
- Reject diagnoses that confuse different defect families (e.g., lifetime vs. synchronization, selector vs. protocol) unless clearly stating why they co-occur.
- A high-level warning paired with concrete detailed diagnosis is acceptable if details stay within the same defect family.
- Do not reject because the diagnosis goes deeper or offers a causal explanation; accept if the causal chain is sound.

Final format only:
Judge_Motivation: <short reason>
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
Rules:
- Accept the diagnosis if it correctly states that the code is correct and the diff does not show an explicit correctness violation.
- Accept only if the diagnosis matches a concrete structural difference visible in the diff and consistent with the observed failure.
- The reference solution is not canonical: structural differences alone do not prove a defect.
- Do not reject the diagnosis if the code is functionally correct and the differences in the diff are superficial (variable names, loop order, formatting) and do not constitute a correctness defect.
- If the observed feedback says the submission is correct or reports no code warnings, prefer accepting a no-defect diagnosis unless the diff itself shows an undeniable violation.
- For failing submissions without warnings, accept a defect diagnosis only if the same concrete mechanism is visible in the diff; feedback alone is not enough to validate a speculative code cause.
- If the ground truth context is high-level, extra consistent detail in the diagnosis is acceptable when it remains compatible with the visible diff.
- Reject diagnoses that point to a different mechanism, file, API, variable, or protocol mismatch than the visible student-vs-solution difference.
- Reject diagnoses that mention multiple unrelated defects, tentative alternatives, or "however/also/additionally" style backup theories.
- If the diagnosis cites a file, function, API, variable, or code fragment, it must be compatible with the diff.
- Do not invent hidden defects outside the provided diff.
- If the diff does not support the diagnosis, answer NO.
- For timeout, crash, or ipc_leak failures: if no output diagnosis is available, evaluate the code diagnosis against the diff and feedback alone. Accept the diagnosis if it identifies a plausible mechanism (deadlock, missing cleanup, wrong synchronization) that is compatible with the observed failure category and visible in the diff. Do not require an output diagnosis to validate a code-level finding for these categories.
- For timeout failures: accept diagnoses that identify blocking operations, missing signals, or deadlock-prone patterns visible in the diff, even without a specific output trace.
- For ipc_leak failures: accept diagnoses that identify missing IPC resource deallocation visible in the diff.
- For crash failures: accept diagnoses that identify null pointer dereference, invalid memory access, or uninitialized variable patterns visible in the diff.

Final format only:
Judge_Motivation: <short reason>
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
- Accept if the diagnosis identifies the same underlying defect mechanism, even if at different levels of abstraction.
- Prefer semantic equivalence over textual matching. Synchronization, lifetime, selector, and protocol errors should be evaluated by mechanism, not exact terminology.
- A diagnosis identifying a root cause or prerequisite for the warned defect is acceptable if causally related.
  * Example: If warning concerns concurrent access and diagnosis identifies missing synchronization primitive, accept if that primitive would enable the concurrent access.
  * Counter-example: If the warned defect and diagnosis operate on entirely different code structures, reject.
- Line numbers are not authoritative; a diagnosis valid if it refers to the same logical code region or mechanism.
- If multiple warnings exist, the diagnosis should address at least one. If it clearly addresses one while missing others, judge based on the addressed warning.
- High-level warnings with concrete diagnosis details are acceptable when details stay within the same defect family.
- Reject only if the diagnosis invents a different defect family or fundamentally contradicts the warning.

Final format only:
Judge_Motivation: <short reason>
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

# ================= PARSING =================

YES_SET = {"YES", "Y", "Yes", "yes", "TRUE", "T", "t", "SI", "Sì", "SI'", "si'"}
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

    # rimuove markdown code blocks (con o senza linguaggio specificato)
    text = re.sub(r"```\w*\n(.*?)\n```", r"\1", text, flags=re.S | re.IGNORECASE)
    text = re.sub(r"```(.*?)```", r"\1", text, flags=re.S)

    # rimuove backtick rimanenti
    text = text.replace("```", "")
    text = text.replace("`", "")

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


def build_output_ground_truth_for_judge(failure, feedback_text):
    if failure in {"correct", "static_failure"}:
        return (
            "The visible execution/output is correct. "
            "Ignore any code-only or static-analysis defects mentioned elsewhere."
        )
    return feedback_text

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


def judge_output_with_fallback(diag_output, failure, feedback_text):
    output_ground_truth = build_output_ground_truth_for_judge(failure, feedback_text)
    judged = judge_diagnosis(prompt_giudice_output(diag_output, output_ground_truth))
    if judged.get("Diagnosis_Correct") in {"YES", "NO"}:
        return judged
    fallback = fallback_judge_output(diag_output, output_ground_truth)
    return {
        "Diagnosis_Correct": fallback,
        "Judge_Motivation": "Fallback heuristic based on the output ground truth context and the diagnosis wording.",
    }


def judge_code_with_warning_fallback(diag_code, warnings, code_around, solution_code):
    judged = judge_diagnosis(prompt_giudice_codice(diag_code, warnings, code_around, solution_code))
    if judged.get("Diagnosis_Correct") in {"YES", "NO"}:
        return judged
    return {
        "Diagnosis_Correct": fallback_judge_code(
            diag_code,
            warnings=warnings,
            code_around=code_around,
            solution_code=solution_code,
        ),
        "Judge_Motivation": "Fallback heuristic based on warning-level evidence and code anchors.",
    }


def judge_code_with_diff_fallback(diag_code, feedback_text, compact_diff):
    judged = judge_diagnosis(prompt_giudice_codice_diff(diag_code, feedback_text, compact_diff))
    if judged.get("Diagnosis_Correct") in {"YES", "NO"}:
        return judged
    return {
        "Diagnosis_Correct": fallback_judge_code(
            diag_code,
            compact_diff=compact_diff,
            feedback_text=feedback_text,
        ),
        "Judge_Motivation": "Fallback heuristic based on the compact diff and observed failure feedback.",
    }


def judge_code_static_with_fallback(diag_code, warnings):
    judged = judge_diagnosis(prompt_giudice_codice_static(diag_code, warnings))
    if judged.get("Diagnosis_Correct") in {"YES", "NO"}:
        return judged
    return {
        "Diagnosis_Correct": fallback_judge_code(diag_code, warnings=warnings),
        "Judge_Motivation": "Fallback heuristic based on the static warnings and diagnosis anchors.",
    }


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

            if field in ["Output_Diagnosis", "Code_Diagnosis", "Judge_Motivation"]:
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


def judge_response_has_expected_fields(text):
    if not text or text == "ERRORE_LLM":
        return False
    parsed = parse_response(text, ["Judge_Motivation", "Diagnosis_Correct"])
    return parsed.get("Diagnosis_Correct", "") in {"YES", "NO"} and bool(parsed.get("Judge_Motivation", "").strip())

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

def judge_diagnosis(prompt):
    def mark_unparseable(role):
        used = get_used_models(role)
        if used:
            ROLE_DISABLED_MODELS[role].add(used)

    for role, logical_model in [("JUDGE", JUDGE_MODEL), ("PRIMARY", PRIMARY_MODEL)]:
        judged = query_model(prompt, logical_model, max_completion_tokens=220, role=role)
        if judge_response_has_expected_fields(judged):
            parsed = parse_response(judged, ["Judge_Motivation", "Diagnosis_Correct"])
            parsed["Judge_Motivation"] = compact_whitespace(parsed.get("Judge_Motivation", ""))
            return parsed
        if judged and judged != "ERRORE_LLM":
            mark_unparseable(role)

    repair_prompt = (
        "Rewrite the following judge answer using exactly this format:\n"
        "Judge_Motivation: <short reason>\n"
        "Diagnosis_Correct: YES or NO\n\n"
        f"Judge task:\n{prompt}"
    )
    for role, logical_model in [("JUDGE", JUDGE_MODEL), ("PRIMARY", PRIMARY_MODEL)]:
        repaired = query_model(repair_prompt, logical_model, max_completion_tokens=140, role=role)
        if judge_response_has_expected_fields(repaired):
            parsed = parse_response(repaired, ["Judge_Motivation", "Diagnosis_Correct"])
            parsed["Judge_Motivation"] = compact_whitespace(parsed.get("Judge_Motivation", ""))
            return parsed
        if repaired and repaired != "ERRORE_LLM":
            mark_unparseable(role)
    return {"Diagnosis_Correct": "", "Judge_Motivation": ""}

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
    prefix = "esercitazione-1-semafori-"
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
    
    log("=" * 60)
    log(f"LLM Provider: {LLM_PROVIDER.upper()}")
    if LLM_PROVIDER == "groq":
        log(f"Model: {PRIMARY_MODEL}")
        log(f"Available API keys: {len(GROQ_API_KEYS)}")
    elif LLM_PROVIDER == "azure":
        log(f"Model Deployment: {AZURE_OPENAI_MODEL_DEPLOYMENT}")
        log(f"Endpoint: {AZURE_OPENAI_ENDPOINT}")
    log("=" * 60)

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
    static_failure_count = sum(1 for r in results if r.get("failure_category") == "static_failure")
    incorrect_count = len(results) - correct_count
    # Distribuzione corrente per selezione proporzionale multi-categoria
    current_cat_counts = Counter(r.get("failure_category", "") for r in results)

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
        delivered_exercises = [exercise_dir.name for exercise_dir in exercise_dirs]

        pending_exercises = [
            exercise_dir.name
            for exercise_dir in exercise_dirs
            if (student_name, exercise_dir.name) not in already_done
        ]

        if not pending_exercises:
            log("    Tutti gli esercizi sono gia' analizzati")
            continue

        log(f"    Selezione commit unico per studente...")

        # Selezione proporzionale se ALL_COMMITS_JSON_FILE è impostato
        _all_commits_data = load_all_commits_data(ALL_COMMITS_JSON_FILE)
        if _all_commits_data:
            selected_commit, selected_analysis = select_student_commit_proportional(
                student_name,
                _all_commits_data,
                delivered_exercises,
                [d.name for d in BASE_TESTS_DIR.iterdir() if d.is_dir() and not d.name.startswith(".")],
                correct_count,
                incorrect_count,
                current_cat_counts=current_cat_counts,
            )
            if not selected_commit:
                log(f"    Nessun commit proporzionale trovato, uso selezione bash")
                selected_commit, selected_analysis = select_student_commit(
                    student_dir, delivered_exercises, correct_count, incorrect_count
                )
        else:
            selected_commit, selected_analysis = select_student_commit(
                student_dir,
                delivered_exercises,
                correct_count,
                incorrect_count
            )

        analysis_by_exercise = {
            item["exercise"]: item
            for item in selected_analysis
        }

        if selected_commit == "MULTI_COMMIT":
            # Selezione per-esercizio: i dati bash sono già nel selected_analysis
            # Non serve checkout perché leggiamo il codice al momento dell'analisi
            log(f"    Commit per-esercizio: "
                f"{set(r['commit_analyzed'][:8] for r in selected_analysis)}")
        elif selected_commit == "HEAD":
            checkout_head(student_dir)
        else:
            checkout_commit(student_dir, selected_commit)

        log(f"    Commit selezionato: {selected_commit}")

        for j, exercise_dir in enumerate(exercise_dirs, start=1):

            if (student_name, exercise_dir.name) in already_done:
                log(f"    ({j}/{total_ex}) {exercise_dir.name} - GIA' ANALIZZATO")
                continue

            log(f"    ({j}/{total_ex}) Esercizio: {exercise_dir.name}")
            reset_model_usage()
            analysis_record = analysis_by_exercise.get(exercise_dir.name)
            if not analysis_record:
                log(f"       Nessun risultato Bash per {exercise_dir.name}, salto")
                continue

            compile_ok = bool(analysis_record.get("compile_success"))
            test_ok = bool(analysis_record.get("test_success"))
            stdout = analysis_record.get("stdout", "") or ""
            stderr = analysis_record.get("stderr", "") or ""
            feedback_text = clean_feedback_for_json(analysis_record.get("test_feedback", "") or "")
            program_out = analysis_record.get("program_output", "") or "The program produced no output."
            warnings = normalize_static_warnings(analysis_record.get("static_warnings", []))
            failure = analysis_record.get("failure_category") or classify_failure_category(feedback_text)
            if failure in ["dynamic_failure", "crash", "timeout", "ipc_leak"]:
                warnings = []
            compile_log = stderr if not compile_ok else ""

            log(f"       Analisi Bash: categoria={failure}, compile={'OK' if compile_ok else 'FAIL'}, test={'PASS' if test_ok else 'FAIL'}, warnings={len(warnings)}")
            
            # =======================
            # ANALISI LLM
            # =======================
            # Per MULTI_COMMIT: checkout del commit specifico per questo esercizio
            if selected_commit == "MULTI_COMMIT" and analysis_record:
                ex_commit = analysis_record.get("commit_analyzed", "")
                if ex_commit:
                    checkout_commit(student_dir, ex_commit)
            readme = read_readme(exercise_dir)
            code = read_student_code(exercise_dir)
            student_files = get_student_files(exercise_dir)
            solution_files = {}

            output_corr = diag_output = code_corr = diag_code = judge_out_ok = judge_code_ok = ""
            judge_out_motivation = judge_code_motivation = ""

            compile_context = compile_log if compile_log.strip() else stderr

            if failure == "compile_failure":
                log(f"       Categoria: COMPILE_FAILURE")
                output_corr = "NO"
                code_corr = "NO"
                diag_output = ""
                diag_code = ""

            # correct è LLM primario e giudici
            elif failure == "correct":
                log(f"       Categoria: CORRECT")
                # ===== LLM =====
                log(f"       [LLM] Analisi Output...")
                resp_output = run_primary_output_analysis(readme, program_out)
                log(f"       [LLM] Output:")
                
                log(f"       [LLM] Analisi Codice (correct mode)...")
                resp_code = run_primary_correct_code_analysis(readme, program_out, code)
                log(f"       [LLM] Codice:")

                fields_output = parse_response(resp_output, ["Output_Correct", "Output_Diagnosis"])
                fields_code = parse_response(resp_code, ["Code_Correct", "Code_Diagnosis"])

                output_corr = fields_output.get("Output_Correct", "")
                diag_output = fields_output.get("Output_Diagnosis", "")
                code_corr = fields_code.get("Code_Correct", "")
                diag_code = fields_code.get("Code_Diagnosis", "")

                if diag_output:
                    diag_output = normalize_diagnosis(diag_output)

                if diag_output:
                    judge_out = judge_output_with_fallback(diag_output, failure, feedback_text)
                    judge_out_ok = judge_out.get("Diagnosis_Correct", "")
                    judge_out_motivation = judge_out.get("Judge_Motivation", "")

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
                    
                    judge_code = judge_code_with_warning_fallback(diag_code, warnings, code_around, solution_code)
                    judge_code_ok = judge_code.get("Diagnosis_Correct", "")
                    judge_code_motivation = judge_code.get("Judge_Motivation", "")
                elif diag_code:
                    solution_files = read_solution_code(exercise_dir.name)
                    compact_diff = build_compact_solution_diff(diag_code, student_files, solution_files, max_chars=3200)
                    judge_code = judge_code_with_diff_fallback(diag_code, feedback_text, compact_diff)
                    judge_code_ok = judge_code.get("Diagnosis_Correct", "")
                    judge_code_motivation = judge_code.get("Judge_Motivation", "")

            # dynamic / crash / timeout / ipc è LLM + giudici normali
            elif failure in ["dynamic_failure", "crash", "timeout", "ipc_leak"]:
                log(f"       Categoria: {failure.upper()}")

                # Per timeout/ipc_leak/crash: solo analisi codice (no output LLM)
                # (non compaiono nei grafici di output)
                if failure not in CODE_ONLY_CATEGORIES:
                    # ===== LLM Output =====
                    log(f"       [LLM] Analisi Output...")
                    resp_output = run_primary_output_analysis(readme, program_out)
                    log(f"       [LLM] Output:")

                    fields_output = parse_response(resp_output, ["Output_Correct", "Output_Diagnosis"])

                    output_corr = fields_output.get("Output_Correct", "")
                    diag_output = fields_output.get("Output_Diagnosis", "")

                    if diag_output:
                        diag_output = normalize_diagnosis(diag_output)

                    if diag_output:
                        judge_out = judge_output_with_fallback(diag_output, failure, feedback_text)
                        judge_out_ok = judge_out.get("Diagnosis_Correct", "")
                        judge_out_motivation = judge_out.get("Judge_Motivation", "")

                log(f"       [LLM] Analisi Codice...")
                resp_code = run_primary_code_analysis(
                    readme,
                    program_out,
                    code,
                    failure_category=failure,
                    output_diagnosis=diag_output,
                )
                log(f"       [LLM] Codice:")

                fields_code = parse_response(resp_code, ["Code_Correct", "Code_Diagnosis"])
                code_corr = fields_code.get("Code_Correct", "")
                diag_code = fields_code.get("Code_Diagnosis", "")

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
                    
                    judge_code = judge_code_with_warning_fallback(diag_code, warnings, code_around, solution_code)
                    judge_code_ok = judge_code.get("Diagnosis_Correct", "")
                    judge_code_motivation = judge_code.get("Judge_Motivation", "")
                elif diag_code:
                    solution_files = read_solution_code(exercise_dir.name)
                    compact_diff = build_compact_solution_diff(diag_code, student_files, solution_files, max_chars=3200)
                    judge_code = judge_code_with_diff_fallback(diag_code, feedback_text, compact_diff)
                    judge_code_ok = judge_code.get("Diagnosis_Correct", "")
                    judge_code_motivation = judge_code.get("Judge_Motivation", "")

            # static_failure è LLM static + giudice static
            elif failure == "static_failure":
                log(f"       Categoria: STATIC_FAILURE (avvisi: {len(warnings)})")
                # ===== LLM =====
                log(f"       [LLM] Analisi Output...")
                resp_output = run_primary_output_analysis(readme, program_out)
                log(f"       [LLM] Output:")
                
                log(f"       [LLM] Analisi Statica Codice...")
                resp_code = run_primary_static_code_analysis(readme, code)
                log(f"       [LLM] Codice Statico:")

                fields_output = parse_response(resp_output, ["Output_Correct", "Output_Diagnosis"])
                fields_code = parse_response(resp_code, ["Code_Correct", "Code_Diagnosis"])

                output_corr = fields_output.get("Output_Correct", "")
                diag_output = fields_output.get("Output_Diagnosis", "")
                code_corr = fields_code.get("Code_Correct", "")
                diag_code = fields_code.get("Code_Diagnosis", "")

                if diag_output:
                    diag_output = normalize_diagnosis(diag_output)

                if diag_output:
                    judge_out = judge_output_with_fallback(diag_output, failure, feedback_text)
                    judge_out_ok = judge_out.get("Diagnosis_Correct", "")
                    judge_out_motivation = judge_out.get("Judge_Motivation", "")

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

                    judge_code = judge_code_static_with_fallback(diag_code, warnings)
                    judge_code_ok = judge_code.get("Diagnosis_Correct", "")
                    judge_code_motivation = judge_code.get("Judge_Motivation", "")

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
                    "commit_analyzed": analysis_record.get("commit_analyzed", selected_commit) if selected_commit == "MULTI_COMMIT" else selected_commit,
                    "failure_category": failure,
                    "primary_model": "gpt-4o",
                    "judge_model": "gpt-4o",
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
                    "judge_Output_Motivation": judge_out_motivation,
                    "judge_Code_Correct": judge_code_ok,
                    "judge_Code_Motivation": judge_code_motivation
                }

            results.append(result)
            already_done.add((student_name, exercise_dir.name))
            save_results(results)
            if failure == "correct":
                correct_count += 1
            else:
                incorrect_count += 1
            if failure == "static_failure":
                static_failure_count += 1
            current_cat_counts[failure] += 1

    log("FINISHED")
    print_token_costs()


if __name__ == "__main__":
    main()

