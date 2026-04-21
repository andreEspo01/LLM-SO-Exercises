#!/bin/bash

source $(dirname "$0")/../../.test/test.sh

BINARY=minimo-mutua-esclusione
OUTPUT=/tmp/minimo.txt
TIMEOUT=30
MAKE_RULE=$BINARY
SKIPPED=0
ERROR_LOG=/tmp/error-log.txt


init_feedback "Esercizio calcolo parallelo su vettore condiviso, con mutua esclusione"


compile_and_run $BINARY $OUTPUT $TIMEOUT $MAKE_RULE


perl -n -e '
if(/\[FIGLIO\].*minimo\s+locale.*?(-?\d+)/i) { push @minimi_figli, $1; }
if(/Ricerca\s+del\s+minimo:\s+elementi\s+da\s+(\d+)\s+a\s+(\d+)/) { $intervalli{$1} = $2; }
if(/\[PADRE\].*valore\s+minimo\s+assoluto.*?(-?\d+)/i) { $minimo_padre = $1; $padre_trovato = 1; }
END {
if($#minimi_figli + 1 != 10) { print "Il numero di processi figli che stampa il minimo locale non corrisponde al totale atteso (10)\n"; exit(1); }
foreach $inizio (0, 1000, 2000, 3000, 4000, 5000, 6000, 7000, 8000, 9000) {
    if(!exists($intervalli{$inizio}) || $intervalli{$inizio} != $inizio + 999) {
        print "I parametri di ricerca del minimo non sono corretti per l intervallo ${inizio}-" . ($inizio + 999) . "\n";
        exit(1);
    }
}
if(!$padre_trovato) { print "Il processo padre non stampa il valore minimo assoluto\n"; exit(1); }
@ordinati = sort { $a <=> $b } @minimi_figli;
if($ordinati[0] != $minimo_padre) { print "Il valore minimo assoluto del padre non coincide con il minimo locale migliore dei figli\n"; exit(1); }
}
' $OUTPUT >${ERROR_LOG}

if [ $? -ne 0 ]
then
    colorize "${OUTPUT}" "${OUTPUT}.ansi.txt" "${OUTPUT}.html"

    ERR_MSG=$(cat ${ERROR_LOG})

    failure "L'esecuzione non e corretta: ${ERR_MSG}" "${OUTPUT}.html"
fi


static_analysis $TESTDIR/processi-mutua-esclusione.yml


success
