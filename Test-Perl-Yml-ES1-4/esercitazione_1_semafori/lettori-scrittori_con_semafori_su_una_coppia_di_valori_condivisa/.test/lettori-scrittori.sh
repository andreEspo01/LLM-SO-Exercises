#!/bin/bash

source $(dirname "$0")/../../.test/test.sh

BINARY=main_padre
OUTPUT=/tmp/output.txt
TIMEOUT=30
SKIPPED=0
ERROR_LOG=/tmp/error-log.txt


init_feedback "Esercizio lettori-scrittori"


compile_and_run $BINARY $OUTPUT $TIMEOUT


perl -n -e '
BEGIN { $val1=0; $val2=0; }
if(/Scrittura\sbuffer:\sval1=(\d+),\sval2=(\d+)/) { $val1=$1; $val2=$2; }
if(/Lettura\sbuffer:\sval1=(\d+),\sval2=(\d+)/) {
    if($1 != $val1 || $2 != $val2) {
        print "La lettura del buffer non restituisce l ultima coppia di valori scritta\n";
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
