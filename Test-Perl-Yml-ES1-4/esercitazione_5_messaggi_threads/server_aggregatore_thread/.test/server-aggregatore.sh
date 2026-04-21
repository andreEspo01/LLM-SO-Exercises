#!/bin/bash

source $(dirname "$0")/../../.test/test.sh

BINARY=programma
OUTPUT=/tmp/output.txt
TIMEOUT=60
SKIPPED=0
ERROR_LOG=/tmp/error-log.txt


init_feedback "Esercizio server aggregatore con thread"

compile_and_run $BINARY $OUTPUT $TIMEOUT


perl -n -e '
if(/Sensore:\sInvio\svalore=(\d+)/) { push @sensore, $1; }
if(/Aggregatore:\sRicevuto\svalore=(\d+)/) { push @aggregatore, $1; }
if(/Aggregatore:\sScrittura\svalore=(\d+)/) { push @scritture, $1; }
if(/Aggregatore:\sLettura\svalore=(\d+)/) { push @letture, $1; if($letture[$#letture] != $scritture[$#scritture]) { print "Il valore letto non corrisponde allo ultimo valore scritto.\n"; exit(1); } }
if(/Collettore:\sRicevuto\svalore=(\d+)/) { push @collettore, $1; }
END{
if($#sensore +1 != 10) { exit(1); }
if($#aggregatore +1 != 10) { exit(1); }
foreach $i(0..$#sensore) { if($sensore[$i]!=$aggregatore[$i]) { print "Il valore inviato dal sensore non corrisponde al valore ricevuto dallo aggregatore.\n"; exit(1); } }
if($#letture +1 != 30) { print "Il numero totale di letture non corrisponde al totale atteso (30).\n"; exit(1); }
if($#collettore +1 != 30) { print "Il numero totale di ricezioni dei collettori non corrisponde al totale atteso (30).\n"; exit(1); }
@letture_sort=sort(@letture);
@collettore_sort=sort(@collettore);
foreach $i(0..$#letture) { if($letture_sort[$i]!=$collettore_sort[$i]) { print "Il valore letto dallo aggregatore non corrisponde al valore ricevuto dal collettore.\n"; exit(1); } }
}
' $OUTPUT >${ERROR_LOG}

if [ $? -ne 0 ]
then

    colorize "${OUTPUT}" "${OUTPUT}.ansi.txt" "${OUTPUT}.html"

    ERR_MSG=$(cat ${ERROR_LOG})

    failure "L'esecuzione non è corretta: ${ERR_MSG}" "${OUTPUT}.html"
fi


static_analysis


success


