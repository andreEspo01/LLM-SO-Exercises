#!/bin/bash

source $(dirname "$0")/../../.test/test.sh

BINARY=start
OUTPUT=/tmp/output.txt
TIMEOUT=30
SKIPPED=0
ERROR_LOG=/tmp/error-log.txt


init_feedback "Esercizio load balancing"

compile_and_run $BINARY $OUTPUT $TIMEOUT


perl -n -e '
BEGIN { %pid=(); $cur_server=0; $sent=0; $received=0; }
if(/Client\s(\d+):\sinvio\smessaggio\snumero\s(\d+)/) { $pid{$1}++; $sent++; }
if(/Balancer:\sricezione\smessaggio\sdal\sprocesso\s(\d+),\sinvio\sal\sserver\s(\d)/) {
    if(!exists($pid{$1})) { print "Il balancer riceve un messaggio da un client che non ha effettuato alcun invio\n"; exit(1); }
    if($2 != $cur_server + 1) { print "Il balancer non distribuisce i messaggi con politica round-robin sul server atteso\n"; exit(1); }
    $cur_server = ($cur_server + 1) % 3;
}
if(/Server\s\d+:\sricezione\smessaggio\snumero\s\d+\sdal\sprocesso\s(\d+)/) {
    if(!exists($pid{$1})) { print "Un server riceve un messaggio da un client sconosciuto al balancer\n"; exit(1); }
    $received++;
}
END {
if($sent != $received) { print "Il numero di messaggi inviati dai client non coincide con quello ricevuto dai server\n"; exit(1); }
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
