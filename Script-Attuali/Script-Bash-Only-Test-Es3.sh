#!/bin/bash

# Script bash completo: analizza TUTTI i commit, compila, testa, analisi statica semgrep
# Salva risultati JSON

BASE_DIR="/home/andre/esercitazione-3-threads-submissions"
TESTS_DIR="/home/andre/so_esercitazione_3_threads-main"
OUTPUT_FILE="/home/andre/risultati_es3_tutti_commit_bash.json"
MODE="batch"
QUIET_MODE="false"
SINGLE_STUDENT_DIR=""
SINGLE_COMMIT=""
SINGLE_OUTPUT_FILE=""

EXERCISES=("lettori-scrittori_su_piu_oggetti_monitor" "produttore-consumatore_con_priorita" "una_struttura_dati_stack_thread-safe")

TOTAL_COMMITS=0
TOTAL_COMPILED=0
TOTAL_TESTS_PASSED=0
RECORDS_SAVED=0

# ==================== HELPER FUNCTIONS ====================

while [ $# -gt 0 ]; do
    case "$1" in
        --single-student-commit)
            MODE="single_student_commit"
            ;;
        --student-dir)
            SINGLE_STUDENT_DIR="$2"
            shift
            ;;
        --commit)
            SINGLE_COMMIT="$2"
            shift
            ;;
        --output-file)
            SINGLE_OUTPUT_FILE="$2"
            shift
            ;;
        --quiet)
            QUIET_MODE="true"
            ;;
    esac
    shift
done

get_student_name() {
    basename "$1" | sed 's/esercitazione-3-threads-//'
}

get_test_script_name() {
    case "$1" in
        "lettori-scrittori_su_piu_oggetti_monitor")
            echo "lettori-scrittori.sh"
        ;;
        "produttore-consumatore_con_priorita")
            echo "prod-cons-prio.sh"
        ;;
        "una_struttura_dati_stack_thread-safe")
            echo "stack.sh"
        ;;
        *)
            echo ""
            ;;
    esac
}

build_json_record() {
    local student="$1"
    local exercise="$2"
    local commit="$3"
    local compile_success="$4"
    local test_success="$5"
    local failure_category="$6"
    local stdout="$7"
    local stderr="$8"
    local test_feedback="$9"
    local program_output="${10}"
    local static_warnings="${11}"

    if ! printf '%s' "${static_warnings:-[]}" | jq empty >/dev/null 2>&1; then
        static_warnings='[]'
    fi

    jq -cn \
        --arg student "$student" \
        --arg exercise "$exercise" \
        --arg commit "$commit" \
        --arg failure_category "$failure_category" \
        --arg stdout "$stdout" \
        --arg stderr "$stderr" \
        --arg test_feedback "$test_feedback" \
        --arg program_output "$program_output" \
        --argjson compile_success "$compile_success" \
        --argjson test_success "$test_success" \
        --argjson static_warnings "$static_warnings" \
        '{
            student: $student,
            exercise: $exercise,
            commit_analyzed: $commit,
            failure_category: $failure_category,
            compile_success: $compile_success,
            test_success: $test_success,
            stdout: $stdout,
            stderr: $stderr,
            test_feedback: $test_feedback,
            program_output: $program_output,
            static_warnings: $static_warnings
        }' 2>/dev/null
}

init_results_file() {
    if [ ! -f "$OUTPUT_FILE" ] || [ ! -s "$OUTPUT_FILE" ]; then
        echo "[]" > "$OUTPUT_FILE"
        return
    fi

    if ! jq -e 'type == "array"' "$OUTPUT_FILE" >/dev/null 2>&1; then
        local backup_file="${OUTPUT_FILE}.invalid.$(date +%s).bak"
        if mv "$OUTPUT_FILE" "$backup_file" 2>/dev/null; then
            echo "JSON output non valido, creato backup: $backup_file" >&2
        else
            rm -f "$OUTPUT_FILE"
            echo "JSON output non valido, file rigenerato da zero." >&2
        fi
        echo "[]" > "$OUTPUT_FILE"
    fi
}

clean_feedback() {
    local text="$1"
    text=$(printf '%s' "$text" | perl -0pe '
        s/:[a-z_]+://g;
        s/<br\/><pre>\s*<\/pre>//gis;
        s/<br\/><pre>.*?<\/pre>//gis;
        s/<pre>\s*<\/pre>//gis;
        s/<[^>]+>//g;
        s/\r//g;
    ' 2>/dev/null || printf '%s' "$text")
    text=$(printf '%s' "$text" | sed -e 's/^[[:space:]]*//' -e 's/[[:space:]]*$//')
    text=$(printf '%s' "$text" | awk 'BEGIN{blank=0} { if ($0 ~ /^[[:space:]]*$/) { if (!blank) print ""; blank=1 } else { print; blank=0 } }')
    text=$(printf '%s' "$text" | perl -0pe 's/^\s+//; s/\s+$//')
    echo "$text"
}

sync_test_dir() {
    local exercise="$1"
    local source_test_dir="$TESTS_DIR/$exercise/.test"

    if [ ! -d "$source_test_dir" ]; then
        return
    fi

    mkdir -p ".test"
    find ".test" -mindepth 1 -maxdepth 1 -exec rm -rf {} + 2>/dev/null || true
    cp -a "$source_test_dir/." ".test/" 2>/dev/null || true
}

sync_shared_test_dir() {
    local student_root="$1"
    local source_shared_test_dir="$TESTS_DIR/.test"
    local target_shared_test_dir="$student_root/.test"

    if [ ! -d "$source_shared_test_dir" ]; then
        return
    fi

    mkdir -p "$target_shared_test_dir"
    find "$target_shared_test_dir" -mindepth 1 -maxdepth 1 -exec rm -rf {} + 2>/dev/null || true
    cp -a "$source_shared_test_dir/." "$target_shared_test_dir/" 2>/dev/null || true
}

# Esegui analisi statica con semgrep (come il Python)
run_static_analysis() {
    local exercise_path="$1"
    local test_dir="$exercise_path/.test"
    local shared_test_dir
    shared_test_dir="$(dirname "$exercise_path")/.test"

    if [ ! -d "$test_dir" ]; then
        return
    fi

    local yml_files=$(find "$test_dir" -maxdepth 1 -name "*.yml" -type f | sort 2>/dev/null)
    if [ -z "$yml_files" ]; then
        return
    fi

    local warnings_json='[]'

    for yml_file in $yml_files; do
        local c_filename=$(basename "$yml_file" .yml)
        local c_file="$exercise_path/${c_filename}.c"

        if [ ! -f "$c_file" ]; then
            continue
        fi

        local preprocessed="$exercise_path/${c_filename}.preprocessed.c"
        cp "$c_file" "$preprocessed" 2>/dev/null || continue

        local preprocessor="$shared_test_dir/preprocessor.pl"
        if [ -f "$preprocessor" ]; then
            perl "$preprocessor" "$preprocessed" 2>/dev/null || true
        fi

        if command -v semgrep >/dev/null 2>&1; then
            local semgrep_json_file
            local semgrep_status=0
            local file_warnings="[]"
            semgrep_json_file=$(mktemp)

            env NO_COLOR=1 semgrep --json --max-lines-per-finding 50 \
                --config "$yml_file" "$preprocessed" > "$semgrep_json_file" 2>/dev/null
            semgrep_status=$?

            if [ -s "$semgrep_json_file" ]; then
                file_warnings=$(jq -c --arg file "${c_filename}.c" '
                    [
                        .results[]? | {
                            file: $file,
                            line: (.start.line // 0),
                            message: (.extra.message // "")
                        }
                    ]
                ' "$semgrep_json_file" 2>/dev/null)

                if [ -n "$file_warnings" ] && printf '%s' "$file_warnings" | jq empty >/dev/null 2>&1; then
                    warnings_json=$(jq -cn \
                        --argjson base "$warnings_json" \
                        --argjson extra "$file_warnings" \
                        '$base + $extra' 2>/dev/null)
                fi
            fi

            rm -f "$semgrep_json_file" 2>/dev/null || true
        fi

        rm -f "$preprocessed" 2>/dev/null || true
    done

    if ! printf '%s' "$warnings_json" | jq empty >/dev/null 2>&1; then
        return
    fi

    printf '%s\n' "$warnings_json"
}

feedback_suggests_static_only() {
    local feedback_text="$1"
    printf '%s' "$feedback_text" | grep -q "difetti all'interno del codice"
}

has_obvious_runtime_failure() {
    local program_output="$1"
    local test_feedback="$2"
    local test_stderr="$3"
    local combined

    if [ "$program_output" = "The program produced no output." ]; then
        return 0
    fi

    combined=$(printf '%s\n%s\n%s\n' "$program_output" "$test_feedback" "$test_stderr")

    if printf '%s' "$combined" | grep -Eiq \
        'Errore exec|Errore execl|Errore msgrcv|Errore msgsnd|Identifier removed|No such file or directory|Segmentation fault|core dumped|Aborted|Assertion|Errore creazione|cannot execute|Permission denied'; then
        return 0
    fi

    return 1
}

# Salva record JSON in modo sicuro usando jq per escaping e append
save_json_result() {
    local record
    record=$(build_json_record "$@")

    if [ -z "$record" ]; then
        local student="$1"
        local exercise="$2"
        local commit="$3"
        echo "Error building JSON record: $student / $exercise / $commit" >&2
        return
    fi

    init_results_file

    # Aggiungi il record all'array in modo atomico, senza lasciare il file vuoto su errore
    local tmp_output
    tmp_output=$(mktemp) || {
        echo "Error creating temp file: $student / $exercise / $commit" >&2
        return
    }

    if jq --argjson record "$record" '. += [$record]' "$OUTPUT_FILE" > "$tmp_output" 2>/dev/null; then
        mv "$tmp_output" "$OUTPUT_FILE"
        ((RECORDS_SAVED++))
        echo "Saved: $student / $exercise / $commit" >&2
    else
        rm -f "$tmp_output"
        echo "Error saving: $student / $exercise / $commit" >&2
    fi
}

analyze_exercise_once() {
    local student_name="$1"
    local exercise="$2"
    local commit="$3"
    local exercise_path="$4"
    local student_root
    student_root=$(dirname "$exercise_path")

    [ -d "$exercise_path" ] || return 1
    sync_shared_test_dir "$student_root"
    cd "$exercise_path" 2>/dev/null || return 1

    sync_test_dir "$exercise"

    local compile_ok="false"
    local compile_log=""
    local compile_status="F"
    local program_output="The program produced no output."

    local compile_result
    compile_result=$(make -s 2>&1)
    local make_exit=$?

    if [ $make_exit -eq 0 ]; then
        TOTAL_COMPILED=$((TOTAL_COMPILED + 1))
        compile_ok="true"
        compile_status="C"
        compile_log=""
    else
        compile_ok="false"
        compile_log="$compile_result"
    fi

    local static_warnings="[]"
    local has_static_warnings="false"

    local test_ok="false"
    local test_feedback=""
    local test_stdout=""
    local test_stderr=""
    local test_status="?"
    local test_script_name
    test_script_name=$(get_test_script_name "$exercise")

    if [ -n "$test_script_name" ] && [ -f ".test/$test_script_name" ]; then
        rm -f /tmp/feedback.md /tmp/output.txt /tmp/error-log.txt /tmp/test_stderr.txt 2>/dev/null || true

        test_stdout=$(cd ".test" && bash "$test_script_name" 2>/tmp/test_stderr.txt)
        local test_exit=$?
        test_stderr=$(cat /tmp/test_stderr.txt 2>/dev/null || echo "")

        if [ -f /tmp/feedback.md ]; then
            test_feedback=$(cat /tmp/feedback.md)
        fi

        if [ -f /tmp/output.txt ]; then
            local output_content
            output_content=$(cat /tmp/output.txt 2>/dev/null)
            if [ -z "${output_content// }" ]; then
                program_output="The program produced no output."
            else
                program_output="$output_content"
            fi
        fi

        if [ $test_exit -eq 0 ] && echo "$test_stdout" | grep -q "^pass$"; then
            test_ok="true"
            TOTAL_TESTS_PASSED=$((TOTAL_TESTS_PASSED + 1))
            test_status="P"
        else
            test_ok="false"
            test_status="F"
        fi
    fi

    local failure_category
    failure_category=$(classify_failure "$compile_ok" "$test_ok" "false" "/tmp/feedback.md")

    local runtime_obviously_broken="false"
    if has_obvious_runtime_failure "$program_output" "$test_feedback" "$test_stderr"; then
        runtime_obviously_broken="true"
    fi

    local should_run_static="false"
    if [ "$compile_ok" = "true" ]; then
        if [ "$test_ok" = "true" ]; then
            should_run_static="true"
        elif feedback_suggests_static_only "$test_feedback" && [ "$runtime_obviously_broken" = "false" ]; then
            should_run_static="true"
        fi
    fi

    if [ "$should_run_static" = "true" ]; then
        static_warnings=$(run_static_analysis "$exercise_path")
        if [ "$static_warnings" != "[]" ] && [ -n "$static_warnings" ]; then
            has_static_warnings="true"
            failure_category="static_failure"
        fi
    fi

    if [ "$runtime_obviously_broken" = "true" ]; then
        if [ "$failure_category" = "correct" ] || [ "$failure_category" = "static_failure" ]; then
            failure_category="dynamic_failure"
        fi
        if [ "$test_ok" = "true" ]; then
            test_ok="false"
        fi
        if [ "$failure_category" != "static_failure" ]; then
            static_warnings="[]"
            has_static_warnings="false"
        fi
    fi

    local output_stderr output_stdout output_feedback
    if [ "$compile_ok" = "false" ]; then
        output_stderr="$compile_log"
        output_stdout="fail"
        output_feedback="Il programma non è stato compilato."
    else
        output_stderr="$test_stderr"
        output_stdout="$test_stdout"
        output_feedback="$test_feedback"
    fi

    local output_feedback_clean
    output_feedback_clean=$(clean_feedback "$output_feedback")

    local record
    record=$(build_json_record \
        "$student_name" "$exercise" "$commit" "$compile_ok" "$test_ok" \
        "$failure_category" "$output_stdout" "$output_stderr" "$output_feedback_clean" "$program_output" "$static_warnings")
    
    printf '%s\n' "$record"
}

analyze_single_student_commit_mode() {
    if [ -z "$SINGLE_STUDENT_DIR" ] || [ -z "$SINGLE_COMMIT" ]; then
        echo "[]" 
        return 1
    fi

    local student_name
    student_name=$(get_student_name "$SINGLE_STUDENT_DIR")
    local snapshot_dir
    snapshot_dir=$(mktemp -d /home/andre/es5-single-commit.XXXXXX)
    local record_file
    record_file=$(mktemp)

    if ! git -C "$SINGLE_STUDENT_DIR" worktree add --detach "$snapshot_dir" "$SINGLE_COMMIT" >/dev/null 2>&1; then
        rm -rf "$snapshot_dir" "$record_file"
        echo "[]"
        return 1
    fi

    # Sync shared .test directory once for the snapshot
    sync_shared_test_dir "$snapshot_dir"

    for exercise in "${EXERCISES[@]}"; do
        local exercise_path="$snapshot_dir/$exercise"
        [ -d "$exercise_path" ] || continue

        # Sync exercise-specific .test files
        cd "$exercise_path" 2>/dev/null || continue
        sync_test_dir "$exercise"
        cd - >/dev/null

        local record
        record=$(analyze_exercise_once "$student_name" "$exercise" "$SINGLE_COMMIT" "$exercise_path")
        if [ -n "$record" ]; then
            printf '%s\n' "$record" >> "$record_file"
        fi
    done

    local final_json="[]"
    if [ -s "$record_file" ]; then
        final_json=$(jq -s '.' "$record_file" 2>/dev/null || echo "[]")
    fi

    if [ -n "$SINGLE_OUTPUT_FILE" ]; then
        printf '%s\n' "$final_json" > "$SINGLE_OUTPUT_FILE"
    fi

    printf '%s\n' "$final_json"

    git -C "$SINGLE_STUDENT_DIR" worktree remove --force "$snapshot_dir" >/dev/null 2>&1 || rm -rf "$snapshot_dir"
    rm -f "$record_file"
}

# Classifica il fallimento leggendo il feedback dello script di test
classify_failure() {
    local compile_ok="$1"
    local test_ok="$2"
    local has_warnings="$3"
    local feedback_file="$4"
    
    # Se non c'è file feedback, usa logica semplice
    if [ ! -f "$feedback_file" ]; then
        if [ "$compile_ok" = "false" ]; then
            echo "compile_failure"
        elif [ "$test_ok" = "true" ] && [ "$has_warnings" = "true" ]; then
            echo "static_failure"
        elif [ "$test_ok" = "true" ]; then
            echo "correct"
        else
            echo "dynamic_failure"
        fi
        return
    fi
    
    # Leggi il feedback per estrarre la categoria
    local feedback=$(cat "$feedback_file")
    
    # Controlla crash (exit code 139)
    if echo "$feedback" | grep -q "crash"; then
        echo "crash"
        return
    fi
    
    # Controlla timeout (exit code 124)
    if echo "$feedback" | grep -q "timeout"; then
        echo "timeout"
        return
    fi
    
    # Controlla IPC leak
    if echo "$feedback" | grep -q "deallocare le risorse IPC"; then
        echo "ipc_leak"
        return
    fi
    
    # Controlla compile failure
    if [ "$compile_ok" = "false" ] || echo "$feedback" | grep -q "compilare"; then
        echo "compile_failure"
        return
    fi
    
    # Controlla static failure (semgrep)
    if echo "$feedback" | grep -q "difetti all'interno del codice"; then
        echo "static_failure"
        return
    fi
    
    # Controlla success
    if echo "$feedback" | grep -q "Congratulazioni"; then
        echo "correct"
        return
    fi
    
    # Default: dynamic_failure se test fallisce, correct altrimenti
    if [ "$test_ok" = "true" ] && [ "$has_warnings" = "true" ]; then
        echo "static_failure"
    elif [ "$test_ok" = "true" ]; then
        echo "correct"
    else
        echo "dynamic_failure"
    fi
}

run_batch_mode() {
    echo "==========================================="
    echo "BASH COMPLETE ANALYSIS - All Students"
    echo "Compile + Test + Static Analysis (Semgrep)"
    echo "JSON output: $OUTPUT_FILE"
    echo "==========================================="
    echo ""

    init_results_file

    TOTAL_STUDENTS=0

    for student_dir in $(ls -d "$BASE_DIR"/esercitazione-3-threads-* 2>/dev/null | sort); do
        TOTAL_STUDENTS=$((TOTAL_STUDENTS + 1))
        student_name=$(get_student_name "$student_dir")
        echo "[Student $TOTAL_STUDENTS] $student_name"
        
        for exercise in "${EXERCISES[@]}"; do
            exercise_path="$student_dir/$exercise"
            
            if [ ! -d "$exercise_path" ]; then
                continue
            fi
            
            echo "  Exercise: $exercise"
            cd "$exercise_path" 2>/dev/null || continue
            
            commits=$(git rev-list --reverse main -- . 2>/dev/null)
            
            if [ -z "$commits" ]; then
                echo "    [No commits for this exercise]"
                continue
            fi
            
            commit_counter=0
            for commit in $commits; do
                commit_counter=$((commit_counter + 1))
                TOTAL_COMMITS=$((TOTAL_COMMITS + 1))
                compile_ok="false"
                test_ok="false"
                
                git checkout -q "$commit" 2>/dev/null
                if [ $? -ne 0 ]; then
                    continue
                fi

                record=$(analyze_exercise_once "$student_name" "$exercise" "$commit" "$exercise_path")
                if [ -n "$record" ]; then
                    compile_ok=$(printf '%s' "$record" | jq -r '.compile_success')
                    test_ok=$(printf '%s' "$record" | jq -r '.test_success')
                    save_json_result \
                        "$(printf '%s' "$record" | jq -r '.student')" \
                        "$(printf '%s' "$record" | jq -r '.exercise')" \
                        "$(printf '%s' "$record" | jq -r '.commit_analyzed')" \
                        "$compile_ok" \
                        "$test_ok" \
                        "$(printf '%s' "$record" | jq -r '.failure_category')" \
                        "$(printf '%s' "$record" | jq -r '.stdout')" \
                        "$(printf '%s' "$record" | jq -r '.stderr')" \
                        "$(printf '%s' "$record" | jq -r '.test_feedback')" \
                        "$(printf '%s' "$record" | jq -r '.program_output')" \
                        "$(printf '%s' "$record" | jq -c '.static_warnings')"
                fi
                
                local compile_status="F"
                local test_status="F"
                [ "$compile_ok" = "true" ] && compile_status="C"
                [ "$test_ok" = "true" ] && test_status="P"
                echo -n "    $commit_counter: [$compile_status/$test_status]"
                
                if [ $((commit_counter % 10)) -eq 0 ]; then
                    echo " ($commit_counter)"
                else
                    echo -n " "
                fi
            done
            
            git checkout main -q 2>/dev/null
            echo ""
            echo "    [Total: $commit_counter commits analyzed]"
        done
        
        echo ""
    done

    echo "==========================================="
    echo "COMPLETE ANALYSIS FINISHED:"
    echo "  Total students: $TOTAL_STUDENTS"
    echo "  Total commits: $TOTAL_COMMITS"
    echo "  Compiled: $TOTAL_COMPILED"
    echo "  Tests passed: $TOTAL_TESTS_PASSED"
    echo "  Records saved: $RECORDS_SAVED"
    echo "  JSON file: $OUTPUT_FILE"
    echo "==========================================="
}

if [ "$MODE" = "single_student_commit" ]; then
    analyze_single_student_commit_mode
else
    run_batch_mode
fi


