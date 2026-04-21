#!/bin/bash

source $(dirname "$0")/../../.test/test.sh

BINARY=programma
OUTPUT=/tmp/output.txt
TIMEOUT=30
SKIPPED=0
ERROR_LOG=/tmp/error-log.txt


init_feedback "Esercizio registro distribuito"

compile_and_run $BINARY $OUTPUT $TIMEOUT


perl -n -e '
if(/Server:\sInvio\smessaggio\sBIND\s\(id_server=(\d+),\sid_coda=(\d+)\)/) { $server{$1} = $2; }
if(/Registro:\sRicevuto\smessaggio\sBIND\s\(id_server=(\d+),\sid_coda=(\d+)\)/) {
    if(!exists($server{$1}) || $server{$1} != $2) { print "Il registro riceve un messaggio BIND incoerente rispetto a quello inviato dal server $1\n"; exit(1); }
}
if(/Registro:\sInvio\smessaggio\sdi\srisposta\s\(id_server=(\d+),\sid_coda=(\d+)\)/) {
    if($server{$1} != $2) { print "La risposta del registro al server $1 contiene una coda diversa da quella registrata\n"; exit(1); }
}
if(/Client:\sInvio\smessaggio\sSERVICE\s\(id_server=(\d+),\sid_coda=(\d+),\svalore=(\d+)\)/) { push @requests, $3; }
if(/Server:\sRicevuto\smessaggio\sSERVICE\s\(id_server=(\d+),\svalore=(\d+)\)/) {
    if(!exists($server{$1})) { print "Un server riceve una richiesta SERVICE senza essere stato registrato correttamente\n"; exit(1); }
    push @received, $2;
    $total++;
}
if(/Server:\sRicevuto\smessaggio\sEXIT\s\(id_server=(\d+)\)/) { $exit{$1} = 1; }
END {
if(!exists($exit{1}) || !exists($exit{2})) { print "Non tutti i server ricevono il messaggio di terminazione EXIT atteso\n"; exit(1); }
if($#requests != $#received) { print "Il numero di richieste SERVICE inviate dal client non coincide con quello ricevuto dai server\n"; exit(1); }
@s1 = sort @requests;
@s2 = sort @received;
for $i (0..$#s1) {
    if($s1[$i] != $s2[$i]) {
        print "I valori delle richieste SERVICE ricevute dai server non coincidono con quelli inviati dal client\n";
        exit(1);
    }
}
if($total < 9) { print "Il numero totale di richieste SERVICE elaborate e inferiore al minimo atteso (9)\n"; exit(1); }
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
