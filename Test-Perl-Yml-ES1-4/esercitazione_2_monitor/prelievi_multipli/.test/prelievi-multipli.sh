#!/bin/bash

source $(dirname "$0")/../../.test/test.sh

BINARY=prodcons
OUTPUT=/tmp/output.txt
TIMEOUT=30
SKIPPED=0
ERROR_LOG=/tmp/error-log.txt


init_feedback "Esercizio prelievi multipli"

compile_and_run $BINARY $OUTPUT $TIMEOUT


perl -n -e '
BEGIN { $counter=0; @produced=(); @consumed=(); %consumer_state=(); }
if(/Produzione:\sval=(\d+)/) { $counter++; push @produced, $1; }
if(/\[(\d+)\]\sIngresso\sconsumatore/) { $consumer_state{$1} = 0; }
if(/\[(\d+)\]\sPrima\sconsumazione:\sval_1=(\d+)/) {
    if(!exists($consumer_state{$1}) || $consumer_state{$1} != 0) { print "La prima consumazione avviene senza che siano disponibili almeno due elementi nel buffer\n"; exit(1); }
    $consumer_state{$1} = 1;
    $counter--;
    push @consumed, $2;
}
if(/\[(\d+)\]\sSeconda\sconsumazione:\sval_2=(\d+)/) {
    if(!exists($consumer_state{$1}) || $consumer_state{$1} != 1) { print "La prima consumazione avviene senza che siano disponibili almeno due elementi nel buffer\n"; exit(1); }
    $consumer_state{$1} = 2;
    $counter--;
    push @consumed, $2;
}
if(/\[(\d+)\]\sUscita\sconsumatore/) {
    if(!exists($consumer_state{$1}) || $consumer_state{$1} != 2) { print "La prima consumazione avviene senza che siano disponibili almeno due elementi nel buffer\n"; exit(1); }
    delete $consumer_state{$1};
}
if($counter > 10) { print "Il numero di elementi nel buffer esce dai limiti consentiti [0,10]\n"; exit(1); }
END {
if(!@produced || !@consumed) { print "Il numero di valori prodotti non coincide con il numero di valori consumati\n"; exit(1); }
for $pid (keys %consumer_state) {
    if($consumer_state{$pid} != 2) { print "La prima consumazione avviene senza che siano disponibili almeno due elementi nel buffer\n"; exit(1); }
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
