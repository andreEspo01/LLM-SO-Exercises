#!/bin/bash

source $(dirname "$0")/../../.test/test.sh

BINARY=start
OUTPUT=/tmp/output.txt
TIMEOUT=240
SKIPPED=0
ERROR_LOG=/tmp/error-log.txt


init_feedback "Esercizio simulazione disco, con monitor"

compile_and_run $BINARY $OUTPUT $TIMEOUT


perl -n -e '
BEGIN {
    %produced=();
    %consumed=();
    @produced_slots=();
    @consumed_slots=();
}
sub validate_slots {
    my ($slots_ref, $msg) = @_;
    my %counts = ();
    for my $slot (@{$slots_ref}) {
        if($slot < 0 || $slot > 9) {
            print $msg . "\n";
            exit(1);
        }
        $counts{$slot}++;
    }
    my $n = scalar(@{$slots_ref});
    my $q = int($n / 10);
    my $r = $n % 10;
    for my $slot (0..9) {
        my $expected = $q + ($slot < $r ? 1 : 0);
        if(($counts{$slot} || 0) != $expected) {
            print $msg . "\n";
            exit(1);
        }
    }
}
if(/Richiesta\sUtente:\sposizione=(\d+),\sprocesso=(\d+)/) { push @{$produced{$2}}, $1; }
if(/Prelevo\srichiesta:\sposizione=(\d+),\sprocesso=(\d+)/) { push @{$consumed{$2}}, $1; }
if(/Produzione\sin\s(?:testa|coda):\s(\d+)/) { push @produced_slots, $1; }
if(/Consumazione\sin\s(?:coda|testa):\s(\d+)/) { push @consumed_slots, $1; }
END {
if(!@produced_slots || !@consumed_slots) { print "La produzione nel vettore circolare non avviene nella posizione di testa attesa\n"; exit(1); }
if(scalar(keys %produced) != scalar(keys %consumed)) { print "Il numero di processi che producono richieste non coincide con il numero di processi da cui il disco preleva richieste\n"; exit(1); }
foreach $pid (keys %produced) {
    if(!exists($consumed{$pid})) { print "Non risultano prelievi per il processo $pid\n"; exit(1); }
    if($#{$produced{$pid}} != $#{$consumed{$pid}}) { print "Il numero di richieste prodotte e prelevate per il processo $pid non coincide\n"; exit(1); }
    for $i (0..$#{$produced{$pid}}) {
        if($produced{$pid}[$i] != $consumed{$pid}[$i]) {
            print "La richiesta in posizione $i del processo $pid non viene prelevata nello stesso ordine in cui e stata inserita\n";
            exit(1);
        }
    }
}
validate_slots(\@produced_slots, "La produzione nel vettore circolare non avviene nella posizione di testa attesa");
validate_slots(\@consumed_slots, "La consumazione nel vettore circolare non avviene nella posizione di coda attesa");
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
