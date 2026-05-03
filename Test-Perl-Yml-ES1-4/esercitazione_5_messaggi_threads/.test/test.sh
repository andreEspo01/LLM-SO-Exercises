#!/bin/bash

ipcclean() {
    ipcs -q | awk '($2~/^[0-9]+$/) { system("ipcrm -q " $2) }'
    ipcs -m | awk '($2~/^[0-9]+$/) { system("ipcrm -m " $2) }'
    ipcs -s | awk '($2~/^[0-9]+$/) { system("ipcrm -s " $2) }'
}

failure() {

    ipcclean

    FEEDBACK+=":x: L'esercizio non è ancora stato svolto correttamente.\n"
    FEEDBACK+=":warning: $1 :warning:\n"

    printf "$FEEDBACK" >> $FEEDBACKFILE_PATH


    # More detailed feedback
    if [ $# -eq 2 ]
    then
        cat $2 >> $FEEDBACKFILE_PATH
    fi


    echo "fail"
    exit 1
}

format_semgrep_json() {

    JSON=$1

    OUTPUT_FILE=/tmp/semgrep_formatted.md

    printf "\n\n" > $OUTPUT_FILE

    NUM_RESULTS=`jq '.results|length' $JSON`

    for I in $(seq 0 $((${NUM_RESULTS}-1)))
    do
        printf "<i>" >> $OUTPUT_FILE
        jq -r ".results[$I].extra.message" $JSON >> $OUTPUT_FILE
        printf "</i>\n" >> $OUTPUT_FILE
        printf "(codice errore: "$(jq -r ".results[$I].check_id" $JSON)")\n" >> $OUTPUT_FILE
        printf "\n\n\`\`\`\n" >> $OUTPUT_FILE
        jq -r ".results[$I].extra.lines" $JSON >> $OUTPUT_FILE
        printf "\n\`\`\`\n\n\n\n" >> $OUTPUT_FILE
    done

    echo ${OUTPUT_FILE}
}


function compile_and_run() {

    BINARY=$1
    OUTPUT=$2
    TIMEOUT=$3
    MAKE_RULE=$4

    cd $SOURCEDIR

    if ! make ${MAKE_RULE} >/dev/null;
    then
        failure "Non è stato possibile compilare il programma"
    fi



    rm -f $OUTPUT
    ipcclean
 
    IPC_BEFORE=$(ipcs | grep -c "0x")
 
  
    if command -v unbuffer >/dev/null 2>&1
    then
        unbuffer timeout -v $TIMEOUT ./$BINARY > $OUTPUT 2>&1
    elif command -v stdbuf >/dev/null 2>&1
    then
        stdbuf -oL -eL timeout -v $TIMEOUT ./$BINARY > $OUTPUT 2>&1
    else
        timeout -v $TIMEOUT ./$BINARY > $OUTPUT 2>&1
    fi
 
    STATUS=$?
 
    if [[ $STATUS != 0 ]];
    then
 
	if [[ $STATUS == 139 ]];
    	then
		failure "L'esecuzione del programma è andata in crash"
	else
		if [[ $STATUS == 124 ]];
		then
			failure "L'esecuzione del programma è andata in timeout"
		else
			failure "L'esecuzione del programma è terminata con codice di ritorno non-nullo"
		fi
	fi
    fi
 
    cd - > /dev/null

    validate_output "$OUTPUT"
 
    IPC_AFTER=$(ipcs | grep -c "0x")
 
    if [[ $IPC_BEFORE != $IPC_AFTER ]]
    then
        failure "È necessario deallocare le risorse IPC al termine della esecuzione"
    fi

}


function validate_output() {

    OUTPUT=$1

    if [ ! -f "$OUTPUT" ] || [ ! -s "$OUTPUT" ] || ! grep -q '[^[:space:]]' "$OUTPUT"; then
        failure "L'esecuzione del programma non produce alcun output visibile"
    fi

    if grep -qi "errore\|error\|permission denied\|no such file\|operation not permitted" "$OUTPUT"; then
        failure "Il programma contiene messaggi di errore di runtime"
    fi
}


# https://unix.stackexchange.com/a/426817
shopt -s nullglob

function static_analysis() {

    CONFIG_FILES=("$@")

    if [ ${#CONFIG_FILES[@]} -eq 0 ]
    then
        CONFIG_FILES=($TESTDIR/*.yml)
    fi


    JSON_SEMGREP=/tmp/semgrep.json

    for CONFIG in "${CONFIG_FILES[@]}"
    do

        SOURCEPATH=$SOURCEDIR/$(basename $CONFIG .yml)".c"
        SOURCE=$(basename $SOURCEPATH)


        PREPROCESSED=$SOURCEDIR/$(basename $SOURCE .c)".preprocessed.c"
        cp $SOURCEPATH $PREPROCESSED


        # Pre-process the source file (#define, #include)

        cd $SOURCEDIR

        PREPROCESSOR=../.test/preprocessor.pl

        $PREPROCESSOR $PREPROCESSED

        cd - > /dev/null


        # Run semgrep

        env NO_COLOR=1 semgrep --error --quiet  --json --max-lines-per-finding 50 --config $CONFIG $PREPROCESSED -o $JSON_SEMGREP
	
        if [ $? -ne 0 ]
        then

            #SEMGREP_MD=$(format_semgrep_json "$JSON_SEMGREP")

            rm $PREPROCESSED

            failure "Anche se il programma esegue, sono stati riscontrati i seguenti difetti all'interno del codice ($SOURCE)"

        fi

        rm $PREPROCESSED

    done
}



function success() {

    FEEDBACK+=":white_check_mark: Congratulazioni, l'esercizio compila ed esegue correttamente, e non è stato riscontrato nessuno degli errori frequenti nel codice :tada:\n"

    printf "$FEEDBACK" >> $FEEDBACKFILE_PATH

    echo "pass"
    exit 0
}


function skipped() {

    FEEDBACK+=":fast_forward: La verifica automatica è stata disattivata per questo esercizio\n"

    printf "$FEEDBACK" >> $FEEDBACKFILE_PATH

    echo "pass"
    exit 0
}


function init_feedback() {

    MSG=$1

    FEEDBACK="\n## $MSG\n\n"

    if [[ $SKIPPED != 0 ]]
    then
        skipped
    fi
}


function colorize() {

    OUTPUT=$1
    OUTPUT_COLOR_ANSI=$2
    OUTPUT_COLOR_HTML=$3

    echo "<br/><pre>" > ${OUTPUT_COLOR_HTML}

    cat $OUTPUT | grcat $SCRIPTDIR/so-highlight.conf > ${OUTPUT_COLOR_ANSI}

    cat $OUTPUT_COLOR_ANSI | perl -p -e 's/^\x1b\[[0-9;]*m//; s/\x1b\[0m(.*?)\x1b\[0m/<b>$1<\/b>/g; s/\x1b\[[0-9;]*m//g;' >> ${OUTPUT_COLOR_HTML}

    echo "</pre>" >> ${OUTPUT_COLOR_HTML}
}


export TESTDIR="$(realpath $(dirname "$0"))"
export SOURCEDIR=$TESTDIR/..
export SCRIPTDIR=$SOURCEDIR/../.test

export FEEDBACKFILE_PATH=/tmp/feedback.md
export FEEDBACK=

export SKIPPED=0
