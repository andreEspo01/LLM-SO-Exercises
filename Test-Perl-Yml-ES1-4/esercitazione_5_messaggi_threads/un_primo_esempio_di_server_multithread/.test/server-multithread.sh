#!/bin/bash

source $(dirname "$0")/../../.test/test.sh

BINARY=Start
OUTPUT=/tmp/output.txt
TIMEOUT=60
SKIPPED=0
ERROR_LOG=/tmp/error-log.txt


init_feedback "Esercizio primo esempio di server multithread"

compile_and_run $BINARY $OUTPUT $TIMEOUT


perl -n -e '
if(/Richiesta\s(\d+)\sInviata\s\((\d+),\s(\d+)\)\s\[PID=(\d+)\]/) { $n=$1; $op1=$2; $op2=$3; $pid=$4; $req{$pid}[$n]=[$op1,$op2]; $requests++; }
if(/Risposta\s(\d+)\sRicevuta\s\((\d+)\)\s\[PID=(\d+)\]/) { $n=$1; $r=$2; $pid=$3; if(! exists($req{$pid}[$n])) { print "Il valore del messaggio di risposta $n del processo $pid non corrisponde ad un messaggio di richiesta\n"; exit(1); } $resp{$pid}[$n]=$r; $responses++; }
END {
if($requests!=15 || $responses!=15 || keys(%req)!=3 || keys(%resp)!=3) { print "Il numero di messaggi di richiesta e di risposta non corrisponde al totale atteso (15)\n"; exit(1); }
foreach $pid(keys(%req)) { for $n(0..4) { if(!exists($resp{$pid})){ print "Messaggio di risposta non trovato al messaggio di richiesta del processo $pid\n"; exit(1);} ($op1,$op2) = @{$req{$pid}[$n]}; $r=$resp{$pid}[$n]; if($op1*$op2 != $r) { print "Il valore del messaggio di risposta non corrisponde agli operandi del messaggio di richiesta\n"; exit(1); } } } }
' $OUTPUT >${ERROR_LOG}

if [ $? -ne 0 ]
then

    colorize "${OUTPUT}" "${OUTPUT}.ansi.txt" "${OUTPUT}.html"

    ERR_MSG=$(cat ${ERROR_LOG})

    failure "L'esecuzione non è corretta: ${ERR_MSG}" "${OUTPUT}.html"
fi


static_analysis


success


