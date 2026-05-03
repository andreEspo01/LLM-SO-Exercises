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
BEGIN {
    %client_rts=(); %server_rts=();
    %server_ok=(); %client_ok=();
    %client_send_queue=(); %client_send=(); %server_msg=();
    $client_rts_total=0; $server_rts_total=0; $ok_total=0; $client_send_total=0; $server_msg_total=0;
}
if(/\[(\d+)\]\sClient:\sinvio\srequest-to-send(?:,\stype=(\d+))?/) {
    if(defined($2) && $1 != $2) {
        print "Il client riceve un ok-to-send con campo tipo errato, che non coincide con il PID del client che lo ha richiesto\n";
        exit(1);
    }
    $client_rts{$1}++;
    $client_rts_total++;
}
if(/\[\d+\]\sServer:\sricevuto\srequest-to-send,\s\w+?=(\d+)/) {
    $server_rts{$1}++;
    $server_rts_total++;
}
if(/\[\d+\]\sServer:\sinvio\sok-to-send,\stype=(\d+),\sid_coda=(\d+)/) {
    $server_ok{"$1|$2"}++;
    $ok_total++;
}
if(/\[(\d+)\]\sClient:\sricevuto\sok-to-send.*\stype=(\d+),\sid_coda=(\d+)/) {
    if($1 != $2) {
        print "Il client riceve un ok-to-send con campo tipo errato, che non coincide con il PID del client che lo ha richiesto\n";
        exit(1);
    }
    $client_ok{"$2|$3"}++;
}
if(/\[\d+\]\sClient:\sinvio\smessaggio,\scoda=(\d+),\stype=(\d+),\svalore=(\d+)/) {
    $client_send_queue{"$2|$1"}++;
    $client_send{"$2|$3"}++;
    $client_send_total++;
}
if(/\[\d+\]\sServer:\sricevuto\smessaggio,\stype=(\d+),\svalore=(\d+)/) {
    $server_msg{"$1|$2"}++;
    $server_msg_total++;
}
END {
    if($client_rts_total < 8 || $server_rts_total < 8 || $ok_total < 8 || $client_send_total < 8 || $server_msg_total < 8) {
        print "Il server riceve un messaggio con campo tipo non coerente con il PID del client, oppure con un valore incoerente rispetto a quello inviato dal client\n";
        exit(1);
    }
    for $pid (keys %client_rts) {
        if(($server_rts{$pid} || 0) != $client_rts{$pid}) {
            print "Il server riceve una request-to-send con campo tipo errato, che non coincide con il PID di alcun client\n";
            exit(1);
        }
    }
    for $pid (keys %server_rts) {
        if(($client_rts{$pid} || 0) != $server_rts{$pid}) {
            print "Il server riceve una request-to-send con campo tipo errato, che non coincide con il PID di alcun client\n";
            exit(1);
        }
    }
    for $key (keys %server_ok) {
        if(($client_ok{$key} || 0) != $server_ok{$key}) {
            print "Il client riceve un identificativo di coda diverso da quello inviato dal server\n";
            exit(1);
        }
    }
    for $key (keys %client_ok) {
        if(($server_ok{$key} || 0) != $client_ok{$key} || ($client_send_queue{$key} || 0) != $client_ok{$key}) {
            print "Il client riceve un identificativo di coda diverso da quello inviato dal server\n";
            exit(1);
        }
    }
    for $key (keys %client_send) {
        if(($server_msg{$key} || 0) != $client_send{$key}) {
            print "Il server riceve un messaggio con campo tipo non coerente con il PID del client, oppure con un valore incoerente rispetto a quello inviato dal client\n";
            exit(1);
        }
    }
    for $key (keys %server_msg) {
        if(($client_send{$key} || 0) != $server_msg{$key}) {
            print "Il server riceve un messaggio con campo tipo non coerente con il PID del client, oppure con un valore incoerente rispetto a quello inviato dal client\n";
            exit(1);
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


validate_output $OUTPUT


static_analysis

success

