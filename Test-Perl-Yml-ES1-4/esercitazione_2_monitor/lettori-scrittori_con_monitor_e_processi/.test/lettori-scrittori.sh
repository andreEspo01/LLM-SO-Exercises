#!/bin/bash

source $(dirname "$0")/../../.test/test.sh

BINARY=meteo
OUTPUT=/tmp/output.txt
TIMEOUT=60
SKIPPED=0
ERROR_LOG=/tmp/error-log.txt


init_feedback "Esercizio lettori-scrittori"


compile_and_run $BINARY $OUTPUT $TIMEOUT


perl -n -e '
BEGIN { $val1=0; $val2=0; $val3="no"; }
if(/scrittura:\sTemperatura=(-?\d+),\sUmidit\S*=(\d+),\sPioggia=(\w+)/) { $val1=$1; $val2=$2; $val3=$3; }
if(/lettura:\sTemperatura=(-?\d+),\sUmidit\S*=(\d+),\sPioggia=(\w+)/) {
    if($1 != $val1 || $2 != $val2 || $3 ne $val3) {
        print "La lettura delle informazioni meteo non restituisce l ultimo stato scritto nel monitor\n";
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
