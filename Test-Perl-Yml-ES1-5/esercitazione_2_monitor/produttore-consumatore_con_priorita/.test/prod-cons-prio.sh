#!/bin/bash

source $(dirname "$0")/../../.test/test.sh

BINARY=start
OUTPUT=/tmp/output.txt
TIMEOUT=60
SKIPPED=0
ERROR_LOG=/tmp/error-log.txt


init_feedback "Esercizio produttore-consumatore con priorita, con processi"

compile_and_run $BINARY $OUTPUT $TIMEOUT


perl -n -e '
BEGIN { $counter=0; $coda1=0; $coda2=0; @produced=(); @consumed=(); $seen_wait=0; $seen_prod=0; $seen_cons=0; }
if(/Produttore\stipo\s(\d)\scon\spid\s\d+\saccede\sal\smonitor/) {
    $seen_wait++;
    if($1 == 1) { $coda1++; }
    else { $coda2++; }
}
if(/Produttore\stipo\s(\d)\scon\spid\s\d+\sha\sprodotto\s(\d+)/) {
    $seen_prod++;
    push @produced, $2;
    if($1 == 1) { $coda1--; }
    else {
        if($coda1 > 0) {
            print "Un produttore di tipo 2 produce mentre ci sono ancora produttori di tipo 1 in attesa\n";
            exit(1);
        }
        $coda2--;
    }
}
if(/Consumatore\scon\spid\s\d+\sha\sconsumato\s(\d+)/) { $seen_cons++; push @consumed, $1; }
if($counter > 3 || $counter < 0) { print "Il numero di elementi nel buffer esce dai limiti consentiti [0,3]\n"; exit(1); }
END {
if(!$seen_wait || !$seen_prod || !$seen_cons) {
    print "Il numero di valori prodotti non coincide con il numero di valori consumati\n";
    exit(1);
}
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
