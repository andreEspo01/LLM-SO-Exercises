#!/bin/bash

source $(dirname "$0")/../../.test/test.sh

BINARY=main-padre
OUTPUT=/tmp/output.txt
TIMEOUT=30
SKIPPED=0
ERROR_LOG=/tmp/error-log.txt


init_feedback "Esercizio coppia di buffer"


compile_and_run $BINARY $OUTPUT $TIMEOUT


perl -n -e '
BEGIN { $counter=0; @produced=(); @consumed=(); }
if(/Prodotto\sil\svalore\s(\d+)/) { $counter++; push @produced, $1; }
if(/Consumato\sil\svalore\s(\d+)/) { $counter--; push @consumed, $1; }
if($counter > 2 || $counter < 0) { print "Il numero di elementi presenti nella coppia di buffer esce dai limiti consentiti [0,2]\n"; exit(1); }
END {
if($#produced != $#consumed) { print "Il numero di valori prodotti non coincide con il numero di valori consumati\n"; exit(1); }
for $i (0..$#produced) {
    if($produced[$i] != $consumed[$i]) {
        print "Il valore consumato in posizione $i non coincide con il valore prodotto nella stessa posizione\n";
        exit(1);
    }
}
}
' $OUTPUT >${ERROR_LOG}

if [ $? -ne 0 ]
then
    colorize "${OUTPUT}" "${OUTPUT}.ansi.txt" "${OUTPUT}.html"

    ERR_MSG=$(cat ${ERROR_LOG})

    failure "L'esecuzione non e corretta: ${ERR_MSG}" "${OUTPUT}.html"
fi


static_analysis


success
