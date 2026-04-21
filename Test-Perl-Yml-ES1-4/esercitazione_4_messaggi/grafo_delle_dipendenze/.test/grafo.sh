#!/bin/bash

source $(dirname "$0")/../../.test/test.sh

BINARY=start
OUTPUT=/tmp/output.txt
TIMEOUT=30
SKIPPED=0
ERROR_LOG=/tmp/error-log.txt


init_feedback "Esercizio grafo delle dipendenze"

compile_and_run $BINARY $OUTPUT $TIMEOUT


perl -n -e '
if(/\[P1\]\sOPERANDI:\sa=(\d+),\sb=(\d+),\sc=(\d+),\sd=(\d+),\se=(\d+),\sf=(\d+),\sg=(\d+),\sh=(\d+)/) { ($a,$b,$c,$d,$e,$f,$g,$h)=($1,$2,$3,$4,$5,$6,$7,$8); }
if(/\[P2\]\sOPERANDI:\sa=(\d+),\sb=(\d+)/) {
    if($1 != $a || $2 != $b) { print "P2 non riceve gli operandi a e b corretti da P1\n"; exit(1); }
}
if(/\[P3\]\sOPERANDI:\sc=(\d+),\sd=(\d+),\se=(\d+),\sf=(\d+)/) {
    if($1 != $c || $2 != $d || $3 != $e || $4 != $f) { print "P3 non riceve gli operandi c, d, e e f corretti da P1\n"; exit(1); }
}
if(/\[P4\]\sOPERANDI:\sg=(\d+),\sh=(\d+)/) {
    if($1 != $g || $2 != $h) { print "P4 non riceve gli operandi g e h corretti da P1\n"; exit(1); }
}
if(/\[P5\]\sOPERANDI:\sc=(\d+),\sd=(\d+)/) {
    if($1 != $c || $2 != $d) { print "P5 non riceve gli operandi c e d corretti da P1\n"; exit(1); }
}
if(/\[P2\]\sRISULTATO:\s(\d+)/) { $r1=$1; }
if(/\[P3\]\sRISULTATO:\s(\d+)/) { $r2=$1; }
if(/\[P4\]\sRISULTATO:\s(\d+)/) { $r3=$1; }
if(/\[P5\]\sRISULTATO:\s(\d+)/) { $r4=$1; }
if(/\[P6\]\sRISULTATO:\s(\d+)/) { $r5=$1; }
if(/\[P3\]\sRISULTATI\sINTERMEDI:\sr4=(\d+),\sr5=(\d+)/) {
    if($1 != $r4 || $2 != $r5) { print "P3 non riceve i risultati intermedi r4 e r5 corretti\n"; exit(1); }
}
if(/\[P1\]\sRISULTATI\sINTERMEDI:\sr1=(\d+),\sr2=(\d+),\sr3=(\d+)/) {
    if($1 != $r1 || $2 != $r2 || $3 != $r3) { print "P1 non riceve i risultati intermedi r1, r2 e r3 corretti\n"; exit(1); }
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
