#!/bin/bash

source $(dirname "$0")/../../.test/test.sh

BINARY=start
OUTPUT=/tmp/output.txt
TIMEOUT=240
SKIPPED=0
ERROR_LOG=/tmp/error-log.txt


init_feedback "Esercizio simulazione disco, con monitor"

compile_and_run $BINARY $OUTPUT $TIMEOUT


perl -n -e '
BEGIN { $counter=0; %produced=(); %consumed=(); $ptr_testa=0; $ptr_coda=0; }
if(/Richiesta\sUtente:\sposizione=(\d+),\sprocesso=(\d+)/) { push @{$produced{$2}}, $1; }
if(/Prelevo\srichiesta:\sposizione=(\d+),\sprocesso=(\d+)/) { push @{$consumed{$2}}, $1; }
if(/Produzione\sin\stesta:\s(\d+)/) {
    $counter++;
    if($1 != $ptr_testa) { print "La produzione nel vettore circolare non avviene nella posizione di testa attesa\n"; exit(1); }
    $ptr_testa = ($ptr_testa + 1) % 10;
}
if(/Consumazione\sin\scoda:\s(\d+)/) {
    $counter--;
    if($1 != $ptr_coda) { print "La consumazione nel vettore circolare non avviene nella posizione di coda attesa\n"; exit(1); }
    $ptr_coda = ($ptr_coda + 1) % 10;
}
if($counter > 10 || $counter < 0) { print "Il numero di richieste presenti nel vettore circolare esce dai limiti consentiti [0,10]\n"; exit(1); }
END {
if(scalar(keys %produced) != scalar(keys %consumed)) { print "Il numero di processi che producono richieste non coincide con il numero di processi da cui il disco preleva richieste\n"; exit(1); }
foreach $pid (keys %produced) {
    if(!exists($consumed{$pid})) { print "Non risultano prelievi per il processo $pid\n"; exit(1); }
    if($#{$produced{$pid}} != $#{$consumed{$pid}}) { print "Il numero di richieste prodotte e prelevate per il processo $pid non coincide\n"; exit(1); }
    for $i (0..$#{$produced{$pid}}) {
        if($produced{$pid}[$i] != $consumed{$pid}[$i]) {
            print "La richiesta in posizione $i del processo $pid non viene prelevata nello stesso ordine in cui e stata inserita\n";
            exit(1);
        }
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
