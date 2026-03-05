#------------------------------------------------------------------
#PROMPT(25/02/2026)

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

