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
BEGIN {
    @writes = ("0|0|no");
    %reader_states = ();
}
if(/scrittura:\sTemperatura=(-?\d+),\sUmidit\S*=(\d+),\sPioggia=(\w+)/) {
    push @writes, join("|", $1, $2, $3);
}
if(/<(\d+)>\slettura:\sTemperatura=(-?\d+),\sUmidit\S*=(\d+),\sPioggia=(\w+)/) {
    push @{$reader_states{$1}}, join("|", $2, $3, $4);
}
END {
if(!keys %reader_states) {
    print "La lettura delle informazioni meteo non restituisce l ultimo stato scritto nel monitor\n";
    exit(1);
}
foreach $pid (keys %reader_states) {
    my $cursor = 0;
    foreach my $state (@{$reader_states{$pid}}) {
        my $matched = 0;
        for(my $i = $cursor; $i <= $#writes; $i++) {
            if($writes[$i] eq $state) {
                $cursor = $i;
                $matched = 1;
                last;
            }
        }
        if(!$matched) {
            print "La lettura delle informazioni meteo non restituisce l ultimo stato scritto nel monitor\n";
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
