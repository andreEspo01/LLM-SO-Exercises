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