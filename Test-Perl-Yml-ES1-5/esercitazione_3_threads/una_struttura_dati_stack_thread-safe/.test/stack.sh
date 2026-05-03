#!/bin/bash

source $(dirname "$0")/../../.test/test.sh

BINARY=stack
OUTPUT=/tmp/output.txt
TIMEOUT=60
SKIPPED=0
ERROR_LOG=/tmp/error-log.txt


init_feedback "Esercizio struttura dati thread-safe"

compile_and_run $BINARY $OUTPUT $TIMEOUT


perl -n -e '
BEGIN { @elementi=(); $num_elementi=0; }
if(/Inserimento:\s(\d+)/) {
    push @elementi, $1;
    $num_elementi++;
}
if(/Prelievo:\s(\d+)/) {
    if($num_elementi == 0) {
        print "E stato effettuato un prelievo da uno stack vuoto\n";
        exit(1);
    }
    $prod = pop @elementi;
    if($prod != $1) {
        print "Il valore prelevato non rispetta la politica LIFO dello stack\n";
        exit(1);
    }
    $num_elementi--;
}
if($num_elementi < 0 || $num_elementi > 4) { print "Il numero di elementi nello stack esce dai limiti consentiti [0,4]\n"; exit(1); }
END {
if($#elementi >= 0) {
    print "Al termine dell esecuzione lo stack non risulta vuoto\n";
    exit(1);
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
