PRIMARY_SYSTEM_PROMPT = (
    "You analyze student C solutions for Operating Systems exercises. "
    "Use only the provided evidence. "
    "Do not invent hidden requirements, hidden expected values, invisible code paths, or unsupported causes. "
    "Prefer conservative, evidence-based judgments. "
    "Keep the boolean field and diagnosis consistent. "
    "Write diagnoses in English. "
    "Return exactly the requested fields."
)

JUDGE_SYSTEM_PROMPT = (
    "You are a strict semantic grader. "
    "Accept only diagnoses that match the same concrete symptom or defect as the ground truth. "
    "Reject generic, speculative, partially related, or different diagnoses. "
    "Return exactly the requested field."
)

def prompt_output_chunk(readme, output_chunk, chunk_index, chunk_total):
    return f"""
Analyze chunk {chunk_index}/{chunk_total} of a longer program trace.
This is a local pass, not the final verdict.

Exercise description:
{readme}

Trace chunk:
{output_chunk}

Rules:
- Report only mismatches that are concretely visible in this chunk.
- If no concrete local mismatch is visible, say so.
- If a visible operation name encodes meaning such as sum, product, produce, consume, request, or reply, use that meaning.
- If the trace shows a semantic operation such as sum/product and the visible reply for that operation is inconsistent with the later visible value produced or consumed for the same interaction family, report evidence.
- If a request gets an immediate visible reply but the meaningful result later appears as the outcome of a different operation family, treat that as a wrong request/reply association.
- Mention concrete actors, values, request types, or trace phases when visible.
- Write in English.

Final format only:
Chunk_Result: EVIDENCE or NO_EVIDENCE
Chunk_Findings: <one or two sentences>
"""

def prompt_output_synthesis(readme, chunk_findings):
    return f"""
Combine local findings from all chunks of the same full program trace.
Together, they cover the whole output.

Exercise description:
{readme}

Chunk findings:
{chunk_findings}

Rules:
- If any chunk finding shows a concrete visible mismatch, the final answer must be Output_Correct = NO.
- If all chunk findings say that no concrete mismatch is visible, answer YES.
- For empty or missing traces, state which runtime interaction or protocol phase is missing.
- Treat a later produced/consumed value as evidence of mismatch if an earlier request/reply pair for a different operation family already exposed the wrong visible result.
- Prefer a diagnosis shaped like a test failure report: broken interaction first, then wrong value, wrong count, wrong pairing, wrong ordering, or missing phase.
- The final diagnosis must read as a normal full-trace analysis and must not mention chunks, chunk findings, local scans, internal passes, EVIDENCE, or NO_EVIDENCE.
- Write in English.

Final format only:
Output_Correct: YES or NO
Output_Diagnosis: <detailed evidence-based diagnosis>
"""

def prompt_code_chunk(readme, program_output, code_chunk, chunk_index, chunk_total, static_mode=False, correct_mode=False):
    task = "static analysis" if static_mode else "code analysis"
    extra_rule = (
        "- The visible execution passed and no warning is available here, so flag a bug only if the violation is explicit and undeniable in the shown code.\n"
        if correct_mode else ""
    )
    return f"""
Perform a local {task} pass on chunk {chunk_index}/{chunk_total} of a larger C codebase.
This is a local scan, not the final verdict.

Exercise description:
{readme}

Observed runtime/output:
{program_output if not static_mode else "N/A"}

Code chunk:
{code_chunk}

Rules:
- Find at most one concrete defect that is directly visible in this chunk.
- If this chunk shows no concrete local defect, say so.
- Preserve specialized policy names such as reader-writer, selective receive, producer-consumer, or one reply per client.
- Cite exact file names, line numbers, functions, APIs, variables, or short code fragments when visible.
- A visible omission in the shown implementation can count as evidence if the relevant code path is present.
- Do not use visibility disclaimers when real line-numbered C source is shown.
{extra_rule}- If locking/waiting primitives or dedicated read/write monitor procedures are already visible, do not call the defect "missing synchronization primitives" unless the shown code truly contains no synchronization mechanism for that path.
- Write in English.

Final format only:
Chunk_Result: BUG or NO_LOCAL_BUG
Chunk_Defect_Class: <short class or NONE>
Chunk_Evidence: <one or two sentences>
"""

def prompt_code_synthesis(readme, program_output, chunk_findings, static_mode=False, correct_mode=False):
    analysis_kind = "static" if static_mode else "code"
    output_block = "" if static_mode else f"\nObserved runtime/output:\n{program_output}\n"
    conservative_rule = (
        "- Because this case already passed execution and no static warnings are available here, answer NO only for an explicit, undeniable violation directly visible in the code.\n"
        if correct_mode else ""
    )
    return f"""
Combine local findings from all chunks of the same full C codebase.
Together, they cover the whole submitted code.

Exercise description:
{readme}
{output_block}
Chunk findings:
{chunk_findings}

Rules:
- Choose one primary defect only if at least one chunk finding contains concrete evidence.
- If no chunk finding contains a concrete bug, answer YES.
- Do not report multiple bugs; reject chunk findings that list several unrelated issues and keep only the strongest single defect.
- Preserve the most specific defect class supported by the findings; do not downgrade reader-writer to generic mutex, heap-allocated thread parameters to generic synchronization, or selective receive to generic message mismatch.
- If locking, waiting, monitor, or reader/writer primitives are already visible in the findings, do not summarize the defect as "missing synchronization primitives".
- Do not diagnose a queue-ID or selector mix-up unless the findings show the actual mismatched send/receive or type-selection sites.
- If the runtime symptom is a wrong request/reply association or wrong operation result, prefer a code defect that can explain that protocol mismatch rather than unrelated error handling omissions.
{conservative_rule}- In correct cases, do not overrule successful execution with speculation.
- If the final answer is NO, cite concrete file names, lines, functions, APIs, variables, or code fragments from the chunk findings.
- Do not say that no code is visible; the chunks already cover the whole codebase.
- The final diagnosis must read as a normal full-code analysis and must not mention chunks, chunk findings, local scans, internal passes, BUG, EVIDENCE, or NO_LOCAL_BUG.
- Write in English.

Final format only:
Code_Correct: YES or NO
Code_Diagnosis: <one detailed {analysis_kind} diagnosis>
"""

# ================= PROMPT LLM =================

def prompt_output(readme, program_output):
    return f"""
Evaluate only the PROGRAM OUTPUT.

Check visible OS-trace invariants:
- actor/request identity
- request/reply or producer/consumer protocol coherence
- visible values and arithmetic
- counts, pairing, ordering, and completion

Rules:
- Mark NO only for a concrete mismatch visible in the output.
- If the output is empty, mark NO and state which interaction or phase is missing.
- Do not use code-level causes.
- Do not invent hidden requirements.
- Be conservative: if a central operation is not independently verifiable from the trace, do not overclaim that the output is correct.

Exercise description:
{readme}

Program output:
{program_output}

Decision rules:
- If the output is empty, blank, or equivalent to "The program produced no output.", then Output_Correct = NO.
- Missing messages, wrong counts, malformed exchanges, mismatched IDs/PIDs/request numbers, impossible ordering, or wrong computed values visible in the output imply Output_Correct = NO.
- Mere suspicion is not enough.
- The diagnosis must describe the observable symptom only, not the possible code cause.
- If the output is empty, explicitly state that no runtime trace is visible and mention the exercise-specific interaction that is missing, such as request/response, producer/consumer, sensor/collector, reader/writer, client/server, or another interaction named in the description.
- For empty output, do not stop at "no output"; say which externally visible phase is missing, for example no client/server request-response trace, no producer/consumer exchange, no reader/writer activity, no worker/service interaction, or no completion/termination phase.
- If the mismatch is about values, counts, ordering, or pairing, mention the concrete operation family involved.
- If an operation name visibly encodes arithmetic or protocol meaning, such as SOMMA/sum, product, request, reply, consume, or produce, use that meaning when judging visible value or trace mismatches.
- If a semantic operation such as SUM/PRODUCT receives a visible reply that conflicts with a later visible produced or consumed value in the same trace family, treat that as a concrete mismatch.
- If a request receives an immediate visible reply with a placeholder or semantically wrong value, and the meaningful result later appears as the outcome of a different operation such as consume/dequeue/read, treat that as a wrong request/reply association and mark NO.
- In RPC-like traces, judge each client-visible reply against the request that immediately precedes it for the same actor; a later consumer-style result does not retroactively validate an earlier RPC reply.
- If multiple mismatches are visible, report the most central one first and optionally add one closely related consequence.
- If the trace shows concurrent interleaving and some operations cannot be matched back to a coherent global trace, do not mark the output as correct.
- If the trace does not directly validate a central semantic property of the interaction, avoid strong YES claims.
- If Output_Correct = YES, the diagnosis must explicitly say that no concrete output mismatch is visible from the provided information.
- Prefer diagnoses shaped like a test failure report: identify the broken interaction first, then state whether the problem is missing trace, wrong values, wrong counts, wrong pairing, wrong ordering, or a missing phase of the observable protocol.
- Avoid generic formulas such as "the trace is missing" when a more specific statement is possible from the description and visible labels.
- Keep the diagnosis detailed but compact: 2 to 4 sentences, maximum 5 lines.
- Write the diagnosis in English.
- Do not quote or refer to hidden tests, hidden assertions, or hidden ground truth.

Final format only:
Output_Correct: YES or NO
Output_Diagnosis: <detailed evidence-based diagnosis>
"""


def prompt_codice(readme, program_output, code):
    return f"""
Evaluate the C CODE.

Use only explicit requirements from the exercise and visible evidence from code/output.
Look for one primary defect using OS invariants:
- protocol matching
- ownership/lifetime
- synchronization policy
- placement/order of operations
- cleanup/termination
- forbidden primitive

Rules:
- Mark NO only for a concrete defect directly supported by the code.
- Preserve specialized policy names such as reader-writer or selective receive.
- A visible omission can count as evidence if the relevant code path is shown.
- If evidence is weak, answer YES.
- If the provided runtime output looks coherent and no failing symptom is visible in the prompt, answer NO only for an explicit, undeniable code violation.
- Do not invent hidden constraints.

Exercise description:
{readme}

Observed runtime/output:
{program_output}

Code:
{code}

Decision rules:
- Report one primary defect, not a list of possibilities.
- Report exactly one defect only. Do not mention two primary defects, firstly/secondly, or an auxiliary unrelated issue.
- Mention the exact function(s), variable(s), shared resource(s), or API call(s) involved when they are visible.
- Distinguish carefully between nearby defect families:
  * a missing critical section is not the same as the wrong synchronization policy
  * generic mutual exclusion is not the same as a reader-writer requirement
  * wrong parameter lifetime is not the same as missing free()
  * wrong message-type matching is not the same as a wrong payload value
- Do not claim a race condition unless unsynchronized concurrent accesses to the same shared state are explicitly visible in the code.
- Do not claim a missing pthread_join() unless the code can terminate before required work completes and no alternative waiting/synchronization is visible.
- Do not claim a missing critical section unless both the concurrent access and the unprotected operation are visible.
- If the code already shows mutexes, semaphores, condition variables, monitor procedures, or dedicated read/write functions, do not diagnose "missing synchronization primitives" unless the shown declarations and operations truly contain no synchronization mechanism for the relevant path.
- In reader-writer style code, if reader and writer procedures are already present, prefer diagnosing the wrong reader-writer policy or over-serialization of readers rather than claiming there is no synchronization at all.
- Do not diagnose a reader-writer defect as a generic mutex defect unless the code clearly shows that only ordinary mutual exclusion was required.
- Do not diagnose a queue-ID or selector mix-up merely because one variable stores or aliases another queue identifier; diagnose it only if the visible send/receive or type-selection sites are concretely inconsistent.
- Do not cite pseudocode labels, natural-language placeholders, or comments as code evidence unless they literally appear in the code.
- Do not infer exercise-specific obligations unless they are explicit in the description or directly visible in the code.
- Do not answer YES merely because one specific API name is absent. If the visible implementation of the relevant code path omits the required mechanism, selector, synchronization policy, cleanup step, or ownership pattern, that omission may itself justify NO.
- Only say that no concrete code is visible if the prompt genuinely does not contain line-numbered C source. When file blocks are shown, analyze those files instead of falling back to a visibility disclaimer.
- When possible, explain both the violated code pattern and the concrete consequence on the protocol/runtime.
- If Code_Correct = NO, the diagnosis must explicitly cite at least:
  * one file name exactly as it appears in the code context
  * one function name, API call, variable, or code fragment exactly as it appears in the code context
- Prefer references such as `FILE: server.c`, `function worker`, `pthread_create(...)`, `msgsnd(...)`, `msgrcv(...)`, or a short quoted code fragment with line numbers when available.
- If line numbers are visible in the context, include at least one relevant line number or short line-number range.
- Prefer a diagnosis that points to the exact line or statement where the required behavior is missing or where the wrong behavior is implemented.
- If a warning-like constraint can be instantiated concretely from the code, name both the violated requirement and the exact code site that violates it.
- For ownership/lifetime defects, cite both the use site and the allocation or passing site when possible.
- For protocol-matching defects, cite both sides of the mismatch when possible.
- For synchronization defects, cite both the protected operation and the visible locking or missing-locking context.
- If the runtime symptom is a wrong request/reply association, wrong operation result, or wrong visible protocol pairing, prefer a code defect that plausibly explains that central symptom instead of unrelated error-checking omissions.
- If Code_Correct = YES, the diagnosis must explicitly say that no concrete correctness bug is visible from the provided code and runtime context.
- The diagnosis must read like a precise code review finding, not a generic explanation.
- Keep the diagnosis detailed but focused: 2 to 4 sentences, maximum 5 lines.
- Write the diagnosis in English.

Final format only:
Code_Correct: YES or NO
Code_Diagnosis: <one detailed evidence-based diagnosis>
"""


def prompt_codice_correct(readme, program_output, code):
    return f"""
Evaluate the C CODE in a case where the visible execution passed and no static warning is available.

Use only explicit requirements from the exercise and visible evidence from code/output.
Be very conservative: a passing execution is strong evidence for YES unless the code itself shows an explicit, undeniable violation.

Exercise description:
{readme}

Observed runtime/output:
{program_output}

Code:
{code}

Decision rules:
- Start from YES, not from suspicion.
- Mark NO only for one explicit correctness bug directly visible in the code.
- Do not speculate about hidden races, hidden deadlocks, hidden queue mix-ups, hidden lifetime bugs, or unobserved protocol failures.
- If mutexes, semaphores, condition variables, monitor procedures, or reader/writer functions are visible, do not call the defect "missing synchronization primitives" unless the shown path truly contains no synchronization mechanism at all.
- Do not diagnose a queue-ID or selector mix-up unless the visible send/receive or type-selection sites are concretely inconsistent.
- If Code_Correct = NO, cite at least one file name and one function, API, variable, or short code fragment exactly as visible in the code.
- If Code_Correct = YES, explicitly say that no concrete correctness bug is visible from the provided code and runtime context.
- Report one primary defect only, never multiple defects.
- Write the diagnosis in English.

Final format only:
Code_Correct: YES or NO
Code_Diagnosis: <one detailed evidence-based diagnosis>
"""


def prompt_codice_static(readme, code):
    return f"""
Perform static analysis of the C CODE.

Use only explicit exercise constraints and visible code.
Look for one structural defect using:
- lifetime/ownership
- synchronization policy
- scope/order of operations
- selector or routing logic
- forbidden primitive
- visible absence of a required mechanism in the shown code path

Rules:
- Mark NO only for a directly visible violation.
- Preserve specialized policy names such as reader-writer or selective receive.
- If the relevant code path is not visible or evidence is weak, answer YES.
- Do not invent hidden rules.

Exercise description:
{readme}

Code:
{code}

Decision rules:
- Report one primary static defect, not a list.
- Report exactly one defect only. Do not mention two primary defects, firstly/secondly, or an auxiliary unrelated issue.
- The diagnosis must point to the visible API/function/variable/block that violates the constraint.
- Do not report a missing pattern unless the relevant function or code block is actually shown.
- Ignore hypothetical runtime causes that are not directly visible in the code.
- Distinguish the violation class precisely: for example, wrong synchronization policy, wrong lifetime, wrong placement, wrong cleanup, wrong selector, or forbidden primitive.
- Do not collapse a specialized policy defect into a generic “missing mutex” diagnosis.
- If mutexes, semaphores, condition variables, monitor procedures, or dedicated read/write functions are already visible, do not diagnose "missing synchronization primitives" unless the shown declarations and operations truly contain no synchronization mechanism for the relevant path.
- In reader-writer style code, if reader and writer procedures are already present, prefer diagnosing the wrong reader-writer policy or over-serialization of readers rather than claiming there is no synchronization at all.
- Do not diagnose a queue-ID or selector mix-up merely because one variable stores or aliases another queue identifier; diagnose it only if the visible send/receive or type-selection sites are concretely inconsistent.
- Do not cite pseudocode labels, natural-language placeholders, or comments as code evidence unless they literally appear in the code.
- Do not answer YES merely because a concrete API call is missing from the text. If the shown implementation of the relevant file/function clearly omits the required mechanism or uses a simpler incompatible pattern, diagnose that omission as the primary static defect.
- Only say that no concrete code is visible if the prompt genuinely lacks line-numbered C source. When file blocks are shown, analyze those files instead of falling back to a visibility disclaimer.
- State first the violated constraint, then the exact code pattern that violates it.
- If Code_Correct = NO, the diagnosis must explicitly cite at least:
  * one file name exactly as it appears in the code context
  * one function name, API call, variable, or code fragment exactly as it appears in the code context
- Prefer references such as `FILE: server.c`, `function worker`, `pthread_create(...)`, `msgsnd(...)`, `msgrcv(...)`, or a short quoted code fragment with line numbers when available.
- If line numbers are visible in the context, include at least one relevant line number or short line-number range.
- Prefer a diagnosis that points to the exact line or statement where the required static pattern is missing or replaced by an incompatible one.
- For ownership/lifetime defects, cite both the use site and the allocation or passing site when possible.
- For protocol-matching defects, cite both sides of the mismatch when possible.
- For synchronization defects, cite both the protected operation and the visible locking or missing-locking context.
- If Code_Correct = YES, the diagnosis must explicitly say that no concrete static violation is visible from the provided code.
- The diagnosis must read like a precise static-analysis finding, not a generic explanation.
- Keep the diagnosis detailed but focused: 2 to 4 sentences, maximum 5 lines.
- Write the diagnosis in English.

Final format only:
Code_Correct: YES or NO
Code_Diagnosis: <one detailed static diagnosis>
"""


def self_refine(prompt, first_response):
    if not first_response or first_response == "ERRORE_LLM":
        return first_response

    field_hint = "Keep the fields exactly as in the previous answer."
    if "Output_Correct" in prompt:
        field_hint = "Keep exactly these fields: Output_Correct and Output_Diagnosis."
    elif "Code_Correct" in prompt:
        field_hint = "Keep exactly these fields: Code_Correct and Code_Diagnosis."

    refine_prompt = f"""
Revise the previous answer for consistency and precision.

Previous answer:
{first_response}

Rules:
- {field_hint}
- Remove unsupported claims and generic filler.
- Keep the boolean field fully consistent with the diagnosis.
- If the boolean field is YES, explicitly say that no concrete mismatch or bug is visible from the provided information.
- If the boolean field is NO, keep one concrete issue only.
- Preserve exact file names, line numbers, function names, API names, variables, and short code fragments already present when they support the diagnosis.
- For output diagnoses with NO, prefer a test-like statement of the broken interaction, wrong value, wrong count, wrong pairing, wrong ordering, or missing phase.
- For code diagnoses with NO, prefer a precise code-review finding anchored to visible evidence.
- Write in English.

Final answer only:
"""
    refined = query_model(refine_prompt, PRIMARY_MODEL, max_completion_tokens=200)
    if not refined or refined == "ERRORE_LLM":
        return first_response
    return refined


def prompt_giudice_output(diagnosi, errore_reale):
    return f"""
Grade an output diagnosis against the ground truth feedback.

Diagnosis:
{diagnosi}

Ground truth feedback:
{errore_reale}

Rules:
- Focus on the actual failure description, not template text.
- Accept only the same concrete output problem or a clear paraphrase.
- Reject different symptoms, code causes, or unsupported details.
- If the ground truth is generic, accept a concrete visible anomaly consistent with the failed execution.

Final format only:
Diagnosis_Correct: YES or NO
"""


def prompt_giudice_codice(diagnosi, warnings, code_around, solution_code):
    warnings_text = ""
    if warnings:
        warnings_text = "\n".join(
            [f"- {w['file']}:{w['line']}: {w['message']}" for w in warnings]
        )

    return f"""
Grade a code diagnosis against the real defect.

Diagnosis:
{diagnosi}

Ground truth warnings:
{warnings_text}

Relevant student code snippets:
{code_around}

Reference solution snippets:
{solution_code}

Rules:
- Use warnings as the primary reference.
- Accept only the same concrete defect or violated invariant.
- Reject different mechanisms, resources, or synchronization errors.
- Keep nearby defect families distinct.
- If real code snippets and warnings are provided, a "no visible code/no visible defect" diagnosis is NO.
- If the warning names a specific mechanism or policy, a looser generic diagnosis is NO.

Final format only:
Diagnosis_Correct: YES or NO
"""


def prompt_giudice_codice_diff(diagnosi, feedback_text, compact_diff):
    return f"""
Grade a code diagnosis against the reference solution using a compact student-vs-solution diff.

Diagnosis:
{diagnosi}

Observed test feedback:
{feedback_text}

Compact student/solution diff:
{compact_diff}

Rules:
- Accept only if the diagnosis matches a concrete structural difference visible in the diff and consistent with the observed failure.
- Reject diagnoses that point to a different mechanism, file, API, variable, or protocol mismatch than the visible student-vs-solution difference.
- If the diagnosis cites a file, function, API, variable, or code fragment, it must be compatible with the diff.
- Do not invent hidden defects outside the provided diff.
- If the diff does not support the diagnosis, answer NO.

Final format only:
Diagnosis_Correct: YES or NO
"""


def prompt_giudice_codice_static(diagnosi, warnings):
    warnings_text = ""
    if warnings:
        warnings_text = "\n".join(
            [f"- {w['file']}:{w['line']}: {w['message']}" for w in warnings]
        )

    return f"""
Grade a static code diagnosis against the ground truth warnings.

Diagnosis:
{diagnosi}

Ground truth warnings:
{warnings_text}

Rules:
- Accept only the same concrete static defect or a clear paraphrase.
- Reject different defects, generic mismatches, or partial overlap.
- Keep mutual exclusion, reader-writer, lifetime, deallocation, selector, and payload errors distinct.
- If warnings are explicit, a "no visible code/no visible defect" diagnosis is NO.
- If the warning names a specific mechanism or policy, a looser generic diagnosis is NO.

Final format only:
Diagnosis_Correct: YES or NO
"""