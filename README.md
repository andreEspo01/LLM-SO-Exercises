# LLM per la valutazione automatizzata di esercizi di Sistemi Operativi

Questa repository contiene i materiali relativi al progetto di tesi magistrale in Ingegneria Informatica, corso di *Software Security*. L'obiettivo del progetto è sperimentare l'uso di modelli di linguaggio (LLM) per la correzione automatica degli esercizi di sistemi operativi, estendendo il lavoro già svolto con l'analisi statica tramite **Semgrep**.

## Contesto

Il progetto parte da un approccio consolidato basato su analisi statica personalizzata:  
- Per ogni esercizio vengono definite regole specifiche con Semgrep.  
- Si identificano errori difficili da rilevare con semplici casi di test, come race condition o protocolli produttore-consumatore non corretti.  
- Gli studenti caricano i propri esercizi su GitHub Classroom, e GitHub Actions automatizza la valutazione, restituendo un feedback immediato.

L'estensione proposta consiste nell'usare **LLM** per analizzare il codice degli studenti e fornire diagnosi automatiche, confrontando output, comportamento dinamico e suggerimenti per la correzione.

## Esperimento 1.0

L'esperimento corrente riguarda l'esercitazione 5 (threads) ed è strutturato come segue:

1. Il modello riceve:
   - Il testo della traccia
   - Il codice dello studente

2. Il codice dello studente viene eseguito, generando un output.

3. Il LLM giudica la correttezza:
   - Coerenza tra output e traccia
   - Identificazione del problema reale (diagnosi testuale)
   - Segnalazione del punto del codice dove si verifica l'errore (con LLM giudice)

4. L'esito è diviso in:
   - **Esecuzione corretta (output)**
   - **Codice corretto**

5. Il giudice riceve l'output dei test (dinamici e statici).

6. Analisi separata per ogni esercizio, tenendo traccia della vera causa del malfunzionamento:
   - Fallimento test dinamico
   - Fallimento analisi statica

- L'obiettivo è dimostrare come LLM possa integrare le tecniche di analisi statica e dinamica per migliorare la valutazione automatizzata di esercizi complessi.
