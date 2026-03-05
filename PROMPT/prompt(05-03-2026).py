#------------------------------------------------------------------
#PROMPT(05/03/2026)

# ================= PROMPT LLM PRIMARIO DINAMICO =================
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


# ================= PROMPT LLM PRIMARIO STATICO =================

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


# ================= PROMPT GIUDICE =================
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