#!/usr/bin/env python3
"""
Analisi statica su tutti i commit delle esercitazioni.

Per ogni esercitazione e ogni ruleset produce un file JSON:
  /home/andre/risultati_esN_static_<ruleset>.json

Il formato è identico a risultati_esN_tutti_commit_bash.json,
con l'aggiunta del campo "ruleset" e dei campi di analisi statica.

Uso:
  python3 analisi_statica_tutti_commit.py [--exercise 1 2 3 4 5] \
      [--ruleset semgrep_standard semgrep_0xdea sonarqube_community] \
      [--limit-records N] [--no-update-rules]
"""

import argparse
import base64
import hashlib
import json
import re
import shutil
import subprocess
import sys
import tempfile
import time
import urllib.parse
import urllib.request
from collections import Counter
from datetime import datetime
from pathlib import Path


# ============================================================
# CONFIGURAZIONE
# ============================================================

OUTPUT_DIR = Path("/home/andre")

ALL_COMMITS_JSON_FILES = {
    1: Path("/home/andre/risultati_es1_tutti_commit_bash.json"),
    2: Path("/home/andre/risultati_es2_tutti_commit_bash.json"),
    3: Path("/home/andre/risultati_es3_tutti_commit_bash.json"),
    4: Path("/home/andre/risultati_es4_tutti_commit_bash.json"),
    5: Path("/home/andre/risultati_es5_tutti_commit_bash.json"),
}

SUBMISSIONS_DIRS = {
    1: Path("/home/andre/esercitazione-1-semafori-submissions"),
    2: Path("/home/andre/esercitazione-2-monitor-submissions"),
    3: Path("/home/andre/esercitazione-3-threads-submissions"),
    4: Path("/home/andre/esercitazione-4-messaggi-submissions"),
    5: Path("/home/andre/esercitazione-5-server-multithread-submissions"),
}

EXERCISE_TITLES = {
    1: "Es.1 Semafori",
    2: "Es.2 Monitor",
    3: "Es.3 Threads",
    4: "Es.4 Messaggi",
    5: "Es.5 Server Multithread",
}

RULES_CACHE_DIR = Path.home() / ".cache" / "tesi-static-rules"

RULESETS = {
    "semgrep_standard": {
        "analyzer": "semgrep",
        "repo_url": "https://github.com/semgrep/semgrep-rules.git",
        "repo_branch": "develop",
        "repo_dir_name": "semgrep-rules",
        "config_subdir": "c/lang/security",
        "description": "Semgrep Community Edition rules for C security",
    },
    "semgrep_0xdea": {
        "analyzer": "semgrep",
        "repo_url": "https://github.com/0xdea/semgrep-rules.git",
        "repo_branch": "main",
        "repo_dir_name": "0xdea-semgrep-rules",
        "config_subdir": "rules/c",
        "description": "0xdea additional Semgrep rules for C",
    },
    "sonarqube_community": {
        "analyzer": "sonarqube",
        "description": "SonarQube Community con supporto sonar-cxx quando disponibile",
    }
}


# Rules that produce noise regardless of context and are filtered out
# in post-processing (they are also deactivated in the SonarQube profile,
# but old cached issues may still appear).
SONAR_NOISE_RULES = {
    "cxx:ParsingErrorRecovery",
    "cxx:ParsingError",
    "cxx:TooLongLine",
    "cxx:TooManyStatementsPerLine",
    "cppcheck:unknown",
    "cppcheck:unmatchedSuppression",
    "cppcheck:checkersReport",
    "cppcheck:internalAstError",   # cppcheck internal error, not a real bug
}


# ============================================================
# UTILITY
# ============================================================

def log(msg):
    print(f"[{datetime.now().strftime('%H:%M:%S')}] {msg}", flush=True)


def run_command(cmd, cwd=None, check=True):
    completed = subprocess.run(cmd, cwd=cwd, capture_output=True, text=True)
    if check and completed.returncode != 0:
        raise RuntimeError(
            f"Command failed ({completed.returncode}): {' '.join(str(x) for x in cmd)}\n"
            f"STDOUT:\n{completed.stdout}\nSTDERR:\n{completed.stderr}"
        )
    return completed


def load_json(path: Path):
    with path.open("r", encoding="utf-8") as f:
        return json.load(f)


def save_json(path: Path, data):
    tmp = Path(str(path) + ".tmp")
    with tmp.open("w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=4)
    tmp.replace(path)
    log(f"Salvato: {path} ({len(data)} record)")


# ============================================================
# GESTIONE REGOLE
# ============================================================

def ensure_rules_repo(ruleset_name: str, update_repo: bool = True):
    ruleset = RULESETS[ruleset_name]
    if ruleset["analyzer"] != "semgrep":
        return None

    RULES_CACHE_DIR.mkdir(parents=True, exist_ok=True)
    repo_dir = RULES_CACHE_DIR / ruleset["repo_dir_name"]
    branch   = ruleset["repo_branch"]

    if not repo_dir.exists():
        log(f"Clono regole {ruleset_name}...")
        run_command(["git", "clone", "--depth", "1", "--branch", branch,
                     ruleset["repo_url"], str(repo_dir)])
    elif update_repo:
        log(f"Aggiorno regole {ruleset_name}...")
        run_command(["git", "-C", str(repo_dir), "fetch", "origin", branch, "--depth", "1"])
        run_command(["git", "-C", str(repo_dir), "checkout", branch])
        run_command(["git", "-C", str(repo_dir), "reset", "--hard", f"origin/{branch}"])

    config_dir = repo_dir / ruleset["config_subdir"]
    if not config_dir.exists():
        raise FileNotFoundError(f"Config dir non trovata per {ruleset_name}: {config_dir}")
    return config_dir


# ============================================================
# GESTIONE REPO STUDENTI
# ============================================================

def build_repo_map(submissions_dir: Path):
    return [p for p in submissions_dir.iterdir() if p.is_dir()]


def resolve_student_repo(student: str, repo_dirs):
    matches = [p for p in repo_dirs if p.name.endswith(student)]
    if len(matches) == 1:
        return matches[0]
    if not matches:
        raise FileNotFoundError(f"Nessuna cartella trovata per lo studente {student}")
    raise RuntimeError(f"Ambiguità per lo studente {student}: {[p.name for p in matches]}")


def git_path_exists(repo_dir: Path, commit: str, tree_path: str) -> bool:
    r = run_command(
        ["git", "-C", str(repo_dir), "cat-file", "-e", f"{commit}:{tree_path}"],
        check=False,
    )
    return r.returncode == 0


def export_snapshot(repo_dir: Path, commit: str, exercise: str, dest: Path) -> bool:
    dest.mkdir(parents=True, exist_ok=True)
    if not git_path_exists(repo_dir, commit, exercise):
        return False

    archive = subprocess.Popen(
        ["git", "-C", str(repo_dir), "archive", commit, exercise],
        stdout=subprocess.PIPE, stderr=subprocess.PIPE
    )
    tar = subprocess.run(
        ["tar", "-x", "-C", str(dest)],
        stdin=archive.stdout, capture_output=True
    )
    if archive.stdout:
        archive.stdout.close()
    archive_stderr = archive.communicate()[1]

    if archive.returncode != 0 or tar.returncode != 0:
        raise RuntimeError(
            f"Errore git archive/tar per {repo_dir} {commit} {exercise}\n"
            f"git stderr: {archive_stderr.decode('utf-8', errors='replace') if archive_stderr else ''}\n"
            f"tar stderr: {tar.stderr.decode('utf-8', errors='replace') if tar.stderr else ''}"
        )
    return True


# ============================================================
# ANALISI SEMGREP / SONARQUBE
# ============================================================

def parse_semgrep_output(stdout: str, base_dir: Path):
    payload = json.loads(stdout or "{}")
    warnings = []
    for result in payload.get("results", []):
        result_path = Path(result.get("path", ""))
        try:
            rel = result_path.relative_to(base_dir).as_posix()
        except ValueError:
            rel = result_path.as_posix()
        # Normalizza rule_id: rimuove il prefisso del path della cache locale
        # es. "cache.tesi-static-rules.0xdea-semgrep-rules.rules.c.raptor-foo"
        # -> "raptor-foo"  (ultima componente dopo l'ultimo punto che non è parte del nome)
        raw_rule_id = result.get("check_id", "<unknown>")
        # Semgrep usa '.' come separatore di namespace; l'ultimo segmento è il nome della regola
        rule_id = raw_rule_id.split(".")[-1] if "." in raw_rule_id else raw_rule_id
        warnings.append({
            "rule_id":      rule_id,
            "rule_id_full": raw_rule_id,
            "file":         rel,
            "line":         result.get("start", {}).get("line", 0),
            "message":      result.get("extra", {}).get("message", ""),
            "severity":     result.get("extra", {}).get("severity", ""),
        })
    return warnings


def run_semgrep(config_dir: Path, target_dir: Path):
    completed = run_command(
        ["semgrep", "--json", "--quiet", "--error", "--metrics=off",
         "--no-git-ignore", "--config", str(config_dir), str(target_dir)],
        check=False,
    )
    if completed.returncode not in {0, 1}:
        raise RuntimeError(
            f"Semgrep failed on {target_dir}\n"
            f"STDOUT:\n{completed.stdout}\nSTDERR:\n{completed.stderr}"
        )
    return parse_semgrep_output(completed.stdout, target_dir)


def run_sonarqube(_target_dir: Path):
    raise NotImplementedError("Usare run_sonarqube_scan")


def load_sonar_settings():
    bashrc = (Path.home() / ".bashrc").read_text(encoding="utf-8", errors="replace")
    token_match = re.search(r'export SONAR_TOKEN="([^"]+)"', bashrc)
    host_match = re.search(r'export SONAR_HOST_URL="([^"]+)"', bashrc)
    return {
        "token": token_match.group(1) if token_match else "",
        "host_url": host_match.group(1).rstrip("/") if host_match else "",
    }


def find_sonar_scanner():
    direct = shutil.which("sonar-scanner")
    if direct:
        return direct

    # Use rglob to search recursively inside ~/sonarqube-*/bin/
    candidates = sorted(
        str(path)
        for sq_dir in Path.home().glob("sonarqube-*/bin/")
        for path in sq_dir.rglob("sonar-scanner")
        if path.is_file() and path.stat().st_mode & 0o111
    )
    if candidates:
        return candidates[-1]
    return None


def make_sonar_project_key(exercise_number: int, record: dict):
    raw = "|".join([
        f"es{exercise_number}",
        record.get("student", ""),
        record.get("exercise", ""),
        record.get("commit_analyzed", ""),
    ])
    digest = hashlib.sha1(raw.encode("utf-8")).hexdigest()[:16]
    return f"tesi:es{exercise_number}:{digest}"


def make_sonar_project_name(exercise_number: int, record: dict):
    student = re.sub(r"[^A-Za-z0-9._-]+", "-", record.get("student", ""))[:30]
    exercise = re.sub(r"[^A-Za-z0-9._-]+", "-", record.get("exercise", ""))[:40]
    return f"tesi_es{exercise_number}_{student}_{exercise}"[:120]


def sonar_auth_header(token: str):
    return "Basic " + base64.b64encode(f"{token}:".encode("utf-8")).decode("ascii")


def sonar_api_get_json(url: str, token: str):
    request = urllib.request.Request(url)
    request.add_header("Authorization", sonar_auth_header(token))
    with urllib.request.urlopen(request, timeout=30) as response:
        return json.loads(response.read().decode("utf-8"))


def sonar_api_post(url: str, token: str, data=None):
    encoded = None
    if data is not None:
        encoded = urllib.parse.urlencode(data).encode("utf-8")
    request = urllib.request.Request(url, data=encoded, method="POST")
    request.add_header("Authorization", sonar_auth_header(token))
    with urllib.request.urlopen(request, timeout=30) as response:
        return response.read().decode("utf-8")


def parse_report_task(report_task_path: Path):
    info = {}
    for line in report_task_path.read_text(encoding="utf-8", errors="replace").splitlines():
        if "=" in line:
            key, value = line.split("=", 1)
            info[key] = value
    return info


def wait_for_ce_task(task_url: str, token: str, timeout_seconds: int = 300):
    deadline = time.time() + timeout_seconds
    while time.time() < deadline:
        payload = sonar_api_get_json(task_url, token)
        task = payload.get("task", {})
        status = task.get("status", "")
        if status in {"SUCCESS", "FAILED", "CANCELED"}:
            return task
        time.sleep(2)
    raise TimeoutError(f"Timeout in attesa del task SonarQube: {task_url}")


def fetch_all_sonar_issues(host_url: str, token: str, project_key: str):
    issues = []
    page = 1
    page_size = 500

    while True:
        params = urllib.parse.urlencode({
            "componentKeys": project_key,
            "statuses": "OPEN,CONFIRMED,REOPENED",   # exclude CLOSED/RESOLVED
            "ps": page_size,
            "p": page,
        })
        payload = sonar_api_get_json(f"{host_url}/api/issues/search?{params}", token)
        current = payload.get("issues", [])
        issues.extend(current)
        paging = payload.get("paging", {})
        total = paging.get("total", len(issues))
        if len(issues) >= total or not current:
            break
        page += 1
    return issues


def normalize_sonar_issues(issues):
    normalized = []
    for issue in issues:
        component = issue.get("component", "")
        file_part = component.split(":", 1)[1] if ":" in component else component
        normalized.append({
            "rule_id": issue.get("rule", "<unknown>"),
            "rule_id_full": issue.get("rule", "<unknown>"),
            "file": file_part,
            "line": ((issue.get("textRange") or {}).get("startLine")) or 0,
            "message": issue.get("message", ""),
            "severity": issue.get("severity", ""),
            "type": issue.get("type", ""),
        })
    return normalized


def cleanup_sonar_project(host_url: str, token: str, project_key: str):
    try:
        sonar_api_post(f"{host_url}/api/projects/delete", token, {"project": project_key})
    except Exception:
        pass



def run_cppcheck_report(target_dir: Path) -> Path:
    """Run cppcheck on target_dir and return path to XML report (or None on failure)."""
    report_path = target_dir / "cppcheck-report.xml"
    cmd = [
        "cppcheck",
        "--enable=warning,performance,portability,information",
        "--inconclusive",
        "--std=c11",
        "--xml", "--xml-version=2",
        "--suppress=missingIncludeSystem",
        "--suppress=missingInclude",
        "--suppress=unmatchedSuppression",
        "--suppress=checkersReport",
        str(target_dir),
    ]
    r = subprocess.run(cmd, capture_output=True, text=True)
    # cppcheck writes XML to stderr
    if r.stderr.strip():
        report_path.write_text(r.stderr, encoding="utf-8")
        return report_path
    return None


def run_clangtidy_report(target_dir: Path) -> Path:
    """
    Run clang-tidy with concurrency and static-analysis checks on all .c files.
    Returns path to the log file in sonar-cxx native format (or None on failure).
    Focuses on: concurrency-*, clang-analyzer-unix.*, clang-analyzer-security.*
    """
    c_files = sorted(target_dir.rglob("*.c"))
    if not c_files:
        return None

    report_path = target_dir / "clang-tidy-report.log"
    lines = []

    # Focus on checks relevant to concurrent C programs using semaphores/processes
    checks = ",".join([
        "concurrency-*",
        "clang-analyzer-unix.*",
        "clang-analyzer-security.*",
        "clang-analyzer-core.*",
        "clang-analyzer-deadcode.*",
    ])

    for c_file in c_files:
        cmd = [
            "clang-tidy",
            f"--checks=-*,{checks}",
            str(c_file),
            "--",
            "-std=c11",
            f"-I{target_dir}",
        ]
        r = subprocess.run(cmd, capture_output=True, text=True, cwd=target_dir)
        output = r.stdout + r.stderr
        # Filter out lines that are just notes/context (not actual warnings)
        filtered = []
        for line in output.splitlines():
            if ": warning:" in line or ": error:" in line or ": note:" in line:
                filtered.append(line)
        if filtered:
            lines.extend(filtered)

    if lines:
        report_path.write_text("\n".join(lines), encoding="utf-8")
        return report_path
    return None

def run_sonarqube_scan(target_dir: Path, exercise_number: int, record: dict):
    settings = load_sonar_settings()
    scanner = find_sonar_scanner()

    if not scanner:
        return [], "skipped_missing_cli", "Binario sonar-scanner non trovato", {}
    if not settings["token"] or not settings["host_url"]:
        return [], "skipped_missing_auth", "SONAR_TOKEN o SONAR_HOST_URL mancanti in ~/.bashrc", {}

    project_key = make_sonar_project_key(exercise_number, record)
    project_name = make_sonar_project_name(exercise_number, record)

    # Run sub-analyzers to generate external reports
    cppcheck_report  = run_cppcheck_report(target_dir)
    clangtidy_report = run_clangtidy_report(target_dir)

    cmd = [
        scanner,
        f"-Dsonar.projectKey={project_key}",
        f"-Dsonar.projectName={project_name}",
        f"-Dsonar.projectBaseDir={target_dir}",
        "-Dsonar.sources=.",
        "-Dsonar.sourceEncoding=UTF-8",
        "-Dsonar.scm.disabled=true",
        # Force CXX language so the sonar-cxx plugin analyses .c/.h files
        "-Dsonar.language=cxx",
        "-Dsonar.cxx.file.suffixes=.c,.h,.cpp,.hpp,.cc,.hh,.cxx,.hxx",
        # External cppcheck report
        f"-Dsonar.cxx.cppcheck.reportPaths={cppcheck_report or ''}",
        # External clang-tidy report
        f"-Dsonar.cxx.clangTidy.reportPaths={clangtidy_report or ''}",
        f"-Dsonar.token={settings['token']}",
        f"-Dsonar.host.url={settings['host_url']}",
    ]

    completed = run_command(cmd, cwd=target_dir, check=False)
    if completed.returncode != 0:
        message = (
            f"SonarScanner failed ({completed.returncode})\n"
            f"STDOUT:\n{completed.stdout[-4000:]}\nSTDERR:\n{completed.stderr[-4000:]}"
        )
        return [], "failed_scanner", message, {
            "project_key": project_key,
            "project_name": project_name,
        }

    report_task = target_dir / ".scannerwork" / "report-task.txt"
    if not report_task.exists():
        return [], "failed_missing_report", "report-task.txt non trovato dopo sonar-scanner", {
            "project_key": project_key,
            "project_name": project_name,
        }

    task_info = parse_report_task(report_task)
    task = wait_for_ce_task(task_info["ceTaskUrl"], settings["token"])
    if task.get("status") != "SUCCESS":
        cleanup_sonar_project(settings["host_url"], settings["token"], project_key)
        return [], f"failed_ce_{task.get('status', 'unknown').lower()}", json.dumps(task, ensure_ascii=False), {
            "project_key": project_key,
            "project_name": project_name,
            "dashboard_url": task_info.get("dashboardUrl", ""),
            "ce_task_id": task.get("id", ""),
            "ce_task_url": task_info.get("ceTaskUrl", ""),
        }

    issues = fetch_all_sonar_issues(settings["host_url"], settings["token"], project_key)
    warnings = normalize_sonar_issues(issues)
    no_supported_languages = ("0 languages detected" in completed.stdout
                              or "No files to analyze" in completed.stdout)
    cleanup_sonar_project(settings["host_url"], settings["token"], project_key)

    status = "completed_no_supported_languages" if no_supported_languages else "completed"
    error = "Nessun linguaggio supportato rilevato da SonarQube per questo snapshot" if no_supported_languages else ""
    return warnings, status, error, {
        "project_key": project_key,
        "project_name": project_name,
        "dashboard_url": task_info.get("dashboardUrl", ""),
        "ce_task_id": task.get("id", ""),
        "ce_task_url": task_info.get("ceTaskUrl", ""),
        "analysis_id": task.get("analysisId", ""),
    }

# ============================================================
# ANALISI DI UN SINGOLO RECORD
# ============================================================

def analyze_record(exercise_number: int, record: dict, repo_dir: Path, ruleset_name: str, config_dir) -> dict:
    """
    Prende un record da risultati_esN_tutti_commit_bash.json,
    esegue l'analisi statica e restituisce il record arricchito.

    Campi aggiunti rispetto all'originale:
      - ruleset:              nome del ruleset applicato
      - analysis_status:      "completed" | "skipped_*"
      - analysis_error:       messaggio di errore (vuoto se OK)
      - static_warnings:      lista di warning trovati (sostituisce il campo originale)
      - static_warning_count: numero di warning
      - warning_rule_ids:     lista ordinata degli ID regola trovati
    """
    exercise = record["exercise"]
    commit   = record["commit_analyzed"]

    # Copia tutti i campi originali tranne static_warnings (verrà sostituito)
    result = {k: v for k, v in record.items() if k != "static_warnings"}
    result["ruleset"] = ruleset_name

    # Usa /home/andre come base per le dir temporanee:
    # semgrep 1.56.0 non riesce ad accedere a directory in /tmp su WSL
    with tempfile.TemporaryDirectory(prefix="tesi_static_", dir="/home/andre") as tmp:
        tmp_path = Path(tmp)
        exported = export_snapshot(repo_dir, commit, exercise, tmp_path)

        if not exported:
            result.update({
                "analysis_status":      "skipped_missing_path_in_commit",
                "analysis_error":       f"Percorso {exercise} non presente nel commit {commit[:8]}",
                "static_warnings":      [],
                "static_warning_count": 0,
                "warning_rule_ids":     [],
            })
            return result

        target_dir = tmp_path / exercise
        c_files = sorted(p for p in target_dir.rglob("*")
                         if p.is_file() and p.suffix.lower() in {".c", ".h"})

        if not c_files:
            result.update({
                "analysis_status":      "skipped_no_c_files",
                "analysis_error":       "Nessun file .c/.h trovato nello snapshot",
                "static_warnings":      [],
                "static_warning_count": 0,
                "warning_rule_ids":     [],
            })
            return result

        analyzer = RULESETS[ruleset_name]["analyzer"]
        if analyzer == "semgrep":
            warnings        = run_semgrep(config_dir, target_dir)
            status, error, extra = "completed", "", {}
        elif analyzer == "sonarqube":
            warnings, status, error, extra = run_sonarqube_scan(target_dir, exercise_number, record)
        else:
            warnings, status, error, extra = run_codeql_scan(target_dir)

        # Post-processing: filter noise rules (always, regardless of compile status)
        warnings = [
            w for w in warnings
            if w.get("rule_id") not in SONAR_NOISE_RULES
        ]

        result.update({
            "analysis_status":      status,
            "analysis_error":       error,
            "static_warnings":      warnings,
            "static_warning_count": len(warnings),
            "warning_rule_ids":     sorted({w.get("rule_id", "<unknown>") for w in warnings}),
        })
        result.update(extra)
        return result


# ============================================================
# ANALISI DI UN'ESERCITAZIONE
# ============================================================

def output_path(exercise_number: int, ruleset_name: str) -> Path:
    return OUTPUT_DIR / f"risultati_es{exercise_number}_static_{ruleset_name}.json"


def analyze_exercise(exercise_number: int, ruleset_name: str,
                     limit_records: int = None, update_rules: bool = True):

    input_json  = ALL_COMMITS_JSON_FILES[exercise_number]
    submissions = SUBMISSIONS_DIRS[exercise_number]
    out_path    = output_path(exercise_number, ruleset_name)

    log(f"{'='*60}")
    log(f"ES{exercise_number} ({EXERCISE_TITLES[exercise_number]}) - {ruleset_name}")
    log(f"Input:  {input_json}")
    log(f"Output: {out_path}")

    records = load_json(input_json)
    if limit_records:
        records = records[:limit_records]
    log(f"Record totali: {len(records)}")

    # Resume: carica risultati parziali se il file esiste già
    already_done = set()
    existing = []
    if out_path.exists():
        try:
            existing = load_json(out_path)
            rerunnable_statuses = set()
            analyzer = RULESETS[ruleset_name]["analyzer"]
            if analyzer in {"sonarqube", "codeql"}:
                rerunnable_statuses = {
                    "completed_no_supported_languages",
                    "skipped_missing_cli",
                    "skipped_missing_auth",
                    "skipped_unimplemented",
                    "failed_scanner",
                    "failed_missing_report",
                    "failed_ce_failed",
                    "failed_ce_canceled",
                    "failed_database_create",
                    "failed_database_analyze",
                    "failed_missing_sarif",
                }
                existing = [
                    r for r in existing
                    if r.get("analysis_status") not in rerunnable_statuses
                ]
            already_done = {
                (r["student"], r["exercise"], r["commit_analyzed"])
                for r in existing
                if r.get("analysis_status") not in rerunnable_statuses
            }
            log(f"Resume: {len(existing)} record già presenti, {len(records) - len(already_done)} da fare")
        except Exception:
            existing = []

    config_dir = ensure_rules_repo(ruleset_name, update_repo=update_rules)
    repo_dirs  = build_repo_map(submissions)

    results = list(existing)
    errors  = []
    n_total = len(records)
    n_done  = len(already_done)

    for i, record in enumerate(records, 1):
        key = (record["student"], record["exercise"], record["commit_analyzed"])
        if key in already_done:
            continue

        try:
            repo_dir = resolve_student_repo(record["student"], repo_dirs)
            analyzed = analyze_record(exercise_number, record, repo_dir, ruleset_name, config_dir)
            results.append(analyzed)
            already_done.add(key)
            n_done += 1
        except Exception as e:
            log(f"  ERRORE {record['student']}/{record['exercise']} {record['commit_analyzed'][:8]}: {e}")
            errors.append((record["student"], record["exercise"], str(e)))

        # Salva progressivamente ogni 50 record nuovi
        if (n_done % 50 == 0) or i == n_total:
            save_json(out_path, results)
            log(f"  Progresso: {i}/{n_total} processati, {n_done} completati, {len(errors)} errori")

    # Salvataggio finale
    save_json(out_path, results)

    # Riepilogo
    warn_counts = Counter(r.get("static_warning_count", 0) > 0 for r in results)
    log(f"Completato ES{exercise_number} - {ruleset_name}:")
    log(f"  Record totali:  {len(results)}")
    log(f"  Con warning:    {warn_counts[True]}")
    log(f"  Senza warning:  {warn_counts[False]}")
    log(f"  Errori:         {len(errors)}")
    if errors:
        for s, e, msg in errors[:5]:
            log(f"    {s}/{e}: {msg}")
    return results


# ============================================================
# MAIN
# ============================================================

def parse_args():
    parser = argparse.ArgumentParser(
        description="Analisi statica su tutti i commit delle esercitazioni"
    )
    parser.add_argument(
        "--exercise", nargs="+", type=int,
        choices=sorted(ALL_COMMITS_JSON_FILES.keys()),
        default=sorted(ALL_COMMITS_JSON_FILES.keys()),
        help="Esercitazioni da analizzare (default: tutte)",
    )
    parser.add_argument(
        "--ruleset", nargs="+",
        choices=sorted(RULESETS.keys()),
        default=sorted(RULESETS.keys()),
        help="Ruleset da applicare (default: tutti e 3)",
    )
    parser.add_argument(
        "--limit-records", type=int, default=None,
        help="Limita il numero di record per esercitazione (smoke test)",
    )
    parser.add_argument(
        "--no-update-rules", action="store_true",
        help="Non aggiorna i repository delle regole se già in cache",
    )
    return parser.parse_args()


def main():
    args = parse_args()

    log("=" * 60)
    log("ANALISI STATICA TUTTI COMMIT")
    log(f"Esercitazioni: {args.exercise}")
    log(f"Ruleset:       {args.ruleset}")
    log(f"Output dir:    {OUTPUT_DIR}")
    log("=" * 60)

    for ex in args.exercise:
        for rs in args.ruleset:
            analyze_exercise(
                ex, rs,
                limit_records=args.limit_records,
                update_rules=not args.no_update_rules,
            )

    log("FINISHED")


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        print(f"Errore fatale: {exc}", file=sys.stderr)
        sys.exit(1)
