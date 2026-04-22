#!/bin/bash

source $(dirname "$0")/../../.test/test.sh

BINARY=main
OUTPUT=/tmp/output.txt
TIMEOUT=30
SKIPPED=0
ERROR_LOG=/tmp/error-log.txt


init_feedback "Esercizio server sincroni multipli"

compile_and_run $BINARY $OUTPUT $TIMEOUT


perl -n -e '
BEGIN { %msg=(); }
if(/\[(\d+)\]\sClient:\sinvio\srequest-to-send/) { $msg{$1} = {}; }
if(/\[\d+\]\sServer:\sricevuto\srequest-to-send,\s\w+?=(\d+)/) {
    if(!exists($msg{$1})) {
        print "Il server riceve una request-to-send con campo tipo errato, che non coincide con il PID di alcun client\n";
        exit(1);
    }
}
if(/\[\d+\]\sServer:\sinvio\sok-to-send,\stype=(\d+),\sid_coda=(\d+)/) { $msg{$1}{"coda"} = $2; }
if(/\[(\d+)\]\sClient:\sricevuto\sok-to-send.*\stype=(\d+),\sid_coda=(\d+)/) {
    if($1 != $2) {
        print "Il client riceve un ok-to-send con campo tipo errato, che non coincide con il PID del client che lo ha richiesto\n";
        exit(1);
    }
    if(!exists($msg{$2}) || $msg{$2}{"coda"} != $3) {
        print "Il client riceve un identificativo di coda diverso da quello inviato dal server\n";
        exit(1);
    }
}
if(/\[\d+\]\sClient:\sinvio\smessaggio,\scoda=(\d+),\stype=(\d+),\svalore=(\d+)/) { $msg{$2}{"val"} = $3; }
if(/\[\d+\]\sServer:\sricevuto\smessaggio,\stype=(\d+),\svalore=(\d+)/) {
    if(!exists($msg{$1}) || $msg{$1}{"val"} != $2) {
        print "Il server riceve un messaggio con campo tipo non coerente con il PID del client, oppure con un valore incoerente rispetto a quello inviato dal client\n";
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

