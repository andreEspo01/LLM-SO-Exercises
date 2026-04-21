#!/bin/bash

source $(dirname "$0")/../../.test/test.sh

BINARY=start
OUTPUT=/tmp/output.txt
TIMEOUT=60
SKIPPED=0
ERROR_LOG=/tmp/error-log.txt


init_feedback "Esercizio lettori-scrittori su piu oggetti monitor"


compile_and_run $BINARY $OUTPUT $TIMEOUT


perl -n -e '
BEGIN { @val=(); }
if(/Scrittura:\sstazione=(\d+),\sid_treno=(\d+)/) { $val[$2] = $1; }
if(/Lettura:\sstazione=(\d+),\sid_treno=(\d+)/) {
    if($1 != $val[$2]) {
        print "La lettura del treno $2 non restituisce l ultima stazione scritta\n";
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
