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
BEGIN {
    @p1ops=(); @p2ops=(); @p3ops=(); @p4ops=(); @p5ops=(); @p6ops=();
    @p1mid=(); @p3mid=();
    @p2res=(); @p3res=(); @p4res=(); @p5res=(); @p6res=();
}
if(/\[P1\]\sOPERANDI:\sa=(\d+),\sb=(\d+),\sc=(\d+),\sd=(\d+),\se=(\d+),\sf=(\d+),\sg=(\d+),\sh=(\d+)/) {
    push @p1ops, [$1,$2,$3,$4,$5,$6,$7,$8];
}
if(/\[P2\]\sOPERANDI:\sa=(\d+),\sb=(\d+)/) { push @p2ops, [$1,$2]; }
if(/\[P3\]\sOPERANDI:\sc=(\d+),\sd=(\d+),\se=(\d+),\sf=(\d+)/) { push @p3ops, [$1,$2,$3,$4]; }
if(/\[P4\]\sOPERANDI:\sg=(\d+),\sh=(\d+)/) { push @p4ops, [$1,$2]; }
if(/\[P5\]\sOPERANDI:\sc=(\d+),\sd=(\d+)/) { push @p5ops, [$1,$2]; }
if(/\[P6\]\sOPERANDI:\se=(\d+),\sf=(\d+)/) { push @p6ops, [$1,$2]; }
if(/\[P2\]\sRISULTATO:\s(\d+)/) { push @p2res, $1; }
if(/\[P3\]\sRISULTATO:\s(\d+)/) { push @p3res, $1; }
if(/\[P4\]\sRISULTATO:\s(\d+)/) { push @p4res, $1; }
if(/\[P5\]\sRISULTATO:\s(\d+)/) { push @p5res, $1; }
if(/\[P6\]\sRISULTATO:\s(\d+)/) { push @p6res, $1; }
if(/\[P3\]\sRISULTATI\sINTERMEDI:\sr4=(\d+),\sr5=(\d+)/) { push @p3mid, [$1,$2]; }
if(/\[P1\]\sRISULTATI\sINTERMEDI:\sr1=(\d+),\sr2=(\d+),\sr3=(\d+)/) { push @p1mid, [$1,$2,$3]; }
END {
    if(@p1ops < 3 || @p2ops < 3 || @p3ops < 3 || @p4ops < 3 || @p5ops < 3 || @p6ops < 3 || @p1mid < 3 || @p3mid < 3) {
        print "P1 non riceve i risultati intermedi r1, r2 e r3 corretti\n"; exit(1);
    }
    if(@p1ops != @p2ops || @p1ops != @p3ops || @p1ops != @p4ops || @p3ops != @p5ops || @p3ops != @p6ops) {
        print "P1 non riceve i risultati intermedi r1, r2 e r3 corretti\n"; exit(1);
    }
    for $i (0..$#p1ops) {
        $src = $p1ops[$i];
        $dst = $p2ops[$i];
        if($dst->[0] != $src->[0] || $dst->[1] != $src->[1]) { print "P2 non riceve gli operandi a e b corretti da P1\n"; exit(1); }
        $dst = $p3ops[$i];
        if($dst->[0] != $src->[2] || $dst->[1] != $src->[3] || $dst->[2] != $src->[4] || $dst->[3] != $src->[5]) { print "P3 non riceve gli operandi c, d, e e f corretti da P1\n"; exit(1); }
        $dst = $p4ops[$i];
        if($dst->[0] != $src->[6] || $dst->[1] != $src->[7]) { print "P4 non riceve gli operandi g e h corretti da P1\n"; exit(1); }
    }
    for $i (0..$#p5ops) {
        $src = $p3ops[$i];
        $dst = $p5ops[$i];
        if($dst->[0] != $src->[0] || $dst->[1] != $src->[1]) { print "P5 non riceve gli operandi c e d corretti da P1\n"; exit(1); }
        $dst = $p6ops[$i];
        if($dst->[0] != $src->[2] || $dst->[1] != $src->[3]) { print "P3 non riceve gli operandi c, d, e e f corretti da P1\n"; exit(1); }
    }
    if(@p5res != @p6res || @p3mid != @p5res) {
        print "P3 non riceve i risultati intermedi r4 e r5 corretti\n"; exit(1);
    }
    for $i (0..$#p3mid) {
        $mid = $p3mid[$i];
        if($mid->[0] != $p5res[$i] || $mid->[1] != $p6res[$i]) { print "P3 non riceve i risultati intermedi r4 e r5 corretti\n"; exit(1); }
    }
    if(@p2res != @p3res || @p2res != @p4res || @p1mid != @p2res) {
        print "P1 non riceve i risultati intermedi r1, r2 e r3 corretti\n"; exit(1);
    }
    for $i (0..$#p1mid) {
        $mid = $p1mid[$i];
        if($mid->[0] != $p2res[$i] || $mid->[1] != $p3res[$i] || $mid->[2] != $p4res[$i]) { print "P1 non riceve i risultati intermedi r1, r2 e r3 corretti\n"; exit(1); }
    }
}
' $OUTPUT >${ERROR_LOG}

if [ $? -ne 0 ]
then
    colorize "${OUTPUT}" "${OUTPUT}.ansi.txt" "${OUTPUT}.html"

    ERR_MSG=$(cat ${ERROR_LOG})

    failure "L'esecuzione non e corretta: ${ERR_MSG}" "${OUTPUT}.html"
fi


validate_output $OUTPUT


static_analysis

success
