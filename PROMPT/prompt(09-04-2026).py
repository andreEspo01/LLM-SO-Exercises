PRIMARY_SYSTEM_PROMPT = (
    "You analyze student C solutions for Operating Systems exercises. "
    "Use only the provided evidence. "
    "Do not invent hidden requirements, hidden expected values, invisible code paths, or unsupported causes. "
    "Prefer conservative, evidence-based judgments. "
    "Do not overclaim correctness from partial traces, later side effects, or loosely related code details. "
    "Keep the boolean field and diagnosis consistent. "
    "Write diagnoses in English, using at most 100 words. "
    "Return exactly the requested fields."
)

JUDGE_SYSTEM_PROMPT = (
    "You are a strict semantic grader. "
    "Accept only diagnoses that match the same concrete symptom or defect as the ground truth. "
    "Reject generic, speculative, partially related, unsupported, or different diagnoses. "
    "When the ground truth is generic, do not promote it into a more specific diagnosis. "
    "When the ground truth says the submission is correct, accept concise no-defect diagnoses unless they invent a problem. "
    "Return exactly the requested field."
)

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
- A YES answer requires direct visible support for the central externally observable result of the exercise, not just visible activity or eventual downstream consistency.

Exercise description:
{readme}

Program output:
{program_output}

Decision rules:
- If the output is empty, blank, or equivalent to "The program produced no output.", then Output_Correct = NO.
- If the visible trace contains timeout text, forced termination text, watchdog termination, or an unfinished run, then Output_Correct = NO even if some partial activity is visible.
- Missing messages, wrong counts, malformed exchanges, mismatched IDs/PIDs/request numbers, impossible ordering, or wrong computed values visible in the output imply Output_Correct = NO.
- Do not claim that counts, pairing, or ordering are correct unless the trace directly shows enough evidence to verify them.
- When the description or visible trace implies a fixed number of requests, replies, iterations, produced values, consumed values, recipients, or termination events, verify those counts explicitly from the trace before answering YES.
- If the trace shows repeated operations of the same family, check that the number of visible requests, replies, sends, receives, produces, consumes, reads, writes, or forwarded values is consistent with the visible protocol. If you cannot verify that consistency, prefer NO over YES.
- Mere suspicion is not enough.
- The diagnosis must describe the observable symptom only, not the possible code cause.
- Use the visible order of events as the order of observation. Do not repair an apparently wrong trace by assuming hidden reordering, delayed flushing, or a different unseen temporal order unless the trace explicitly states that.
- If the output is empty, explicitly state that no runtime trace is visible and mention the exercise-specific interaction that is missing, such as request/response, producer/consumer, sensor/collector, reader/writer, client/server, or another interaction named in the description.
- For empty output, do not stop at "no output"; say which externally visible phase is missing, for example no client/server request-response trace, no producer/consumer exchange, no reader/writer activity, no worker/service interaction, or no completion/termination phase.
- If the mismatch is about values, counts, ordering, or pairing, mention the concrete operation family involved.
- If an operation name visibly encodes arithmetic or protocol meaning, such as SOMMA/sum, product, request, reply, consume, or produce, use that meaning when judging visible value or trace mismatches.
- Do not reinterpret a client-visible field named `risultato` as a mere acknowledgment unless the trace explicitly labels it as ack/ok/status and not as an operation result.
- In request/reply style traces, each client-visible reply must be judged as the result of the immediately preceding request for the same actor, not as a generic protocol acknowledgment.
- When a request visibly carries operands, parameters, message ids, or payload values, check the corresponding visible reply or forwarded value against those exact visible inputs whenever the operation semantics make that check possible.
- If the trace gives enough information to validate values one by one, do that validation. A YES answer should mean that the visible exchanged values are individually consistent, not just globally plausible.
- If a later consume/receive/dequeue/read returns a meaningful value before the corresponding produce/send/enqueue/write phase is visibly established, do not use that later value as evidence that the earlier phase was correct.
- If a semantic operation such as SUM/PRODUCT receives a visible reply that conflicts with a later visible produced or consumed value in the same trace family, treat that as a concrete mismatch.
- If a request receives an immediate visible reply with a placeholder or semantically wrong value, and the meaningful result later appears as the outcome of a different operation such as consume/dequeue/read, treat that as a wrong request/reply association and mark NO.
- If several requests of the same family receive the same placeholder-looking reply, and meaningful values appear only later in a different phase of the trace, do not call the output correct: this is visible request/reply misassociation, not valid delayed confirmation.
- In request/reply traces, judge each client-visible reply against the request that immediately precedes it for the same actor; a later downstream result does not retroactively validate an earlier reply.
- If the only apparent evidence for correctness comes from a later phase of the trace, while the earlier reply itself is placeholder-like, under-informative, or semantically incompatible with the request, prefer NO.
- If a later phase appears before an earlier prerequisite phase in the visible trace, and no explicit initialization, preload, warm-start, or prior state is shown, prefer NO rather than assuming an unseen valid setup.
- If a server-side or worker-side log appears to compute the meaningful value only after a client has already received an incompatible reply, the output is still wrong from the client's point of view.
- Do not treat later queue contents, consume results, dequeue results, or worker logs as proof that an earlier RPC reply was correct.
- If the exercise shows one source stream being forwarded to multiple collectors/consumers, and the recipient traces show visibly different counts or duplicated/dropped values, mark NO.
- In fan-out, broadcast, or multi-consumer traces, compare the visible recipient streams with each other and with the visible source stream. If one recipient misses a value, duplicates a value, starts from a shifted value, or ends with an extra value, mark NO.
- When values are propagated across phases of the trace, verify that each visible downstream value is compatible with an earlier visible upstream value or operation result. If some exchanged values cannot be reconciled, mark NO.
- Do not infer correct forwarding merely from collector/consumer logs when the central forwarding phase is missing, incomplete, or not coherently connected to the visible source stream.
- If downstream recipients show data before the upstream source or central routing/processing phase is visibly established, do not infer a correct end-to-end trace from that ordering alone.
- If the trace names only peripheral actors while the central actor or central processing phase described by the exercise is entirely absent from the visible runtime trace, mark NO and report the missing phase.
- If multiple mismatches are visible, report the most central one first and optionally add one closely related consequence.
- If the trace shows concurrent interleaving and some operations cannot be matched back to a coherent global trace, do not mark the output as correct.
- If the trace does not directly validate a central semantic property of the interaction, avoid strong YES claims.
- If the trace validates only a subset of the protocol and leaves the central request/reply result ambiguous, prefer NO over a confident YES.
- Do not promote a merely plausible interpretation into YES when the same trace is also compatible with a broken request/reply, forwarding, routing, or completion behavior.
- If correctness would require assuming hidden buffering, omitted trace segments, or an implicit acknowledgment protocol that is not named in the visible output, answer NO.
- If correctness would require assuming hidden preloaded state, hidden earlier successful operations, or an unseen initial population of data structures that is not visible in the trace, answer NO.
- A YES diagnosis is allowed only when the visible trace directly supports the central semantic result of the exercise, the visible counts are consistent with the protocol, and the visible values that can be checked are actually correct.
- If Output_Correct = YES, the diagnosis must explicitly say that no concrete output mismatch is visible from the provided information.
- Prefer diagnoses shaped like a test failure report: identify the broken interaction first, then state whether the problem is missing trace, wrong values, wrong counts, wrong pairing, wrong ordering, or a missing phase of the observable protocol.
- Avoid generic formulas such as "the trace is missing" when a more specific statement is possible from the description and visible labels.
- Keep the diagnosis detailed but compact: maximum of 100 words.
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
- Do not diagnose generic error-handling defects such as missing return-value checks, missing errno checks, or missing validation unless the observed failure is about that path or the code makes that defect the central visible cause.
- When runtime feedback is only black-box and the code does not show one explicit violating statement or omission, prefer YES over a speculative NO.
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
- Keep the diagnosis detailed but focused: maximum of 100 words.
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
- Write the diagnosis in English, keep the diagnosis detailed but compact: maximum of 100 words.

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
- Keep the diagnosis detailed but focused: maximum of 100 words.
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
    refined = query_model(refine_prompt, PRIMARY_MODEL, max_completion_tokens=200, role="PRIMARY")
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
- Focus on the actual output behavior.
- Accept the diagnosis if it correctly identifies the real output problem.
- Accept the diagnosis if it correctly states that the output is correct **and the ground truth confirms the output is indeed correct**.
- Reject the diagnosis if it reports an output problem that does not exist, or claims the output is correct when it is actually wrong.
- Treat paraphrases of the actual output behavior as correct.
- If the ground truth is generic or indicates no failure, a diagnosis claiming the output is correct should be accepted only if the program output matches expectations.
- If the ground truth feedback does not name a concrete symptom, do not accept a diagnosis that invents a specific missing-output, wrong-value, wrong-pairing, or wrong-ordering claim.
- A diagnosis about missing output is correct only if the ground truth explicitly supports a missing or absent runtime trace.
- If the ground truth clearly says the execution is correct, accept a diagnosis saying that no concrete output mismatch is visible unless it adds an invented problem.
- Always compare the diagnosis with the concrete ground truth feedback, not only the textual form.

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
- Accept the diagnosis if it correctly identifies the real defect or violation.
- Accept the diagnosis if it correctly states that the code is correct and there are no real warnings or violations.
- Reject different mechanisms, resources, or synchronization errors not matching warnings.
- Keep nearby defect families distinct.
- If real code snippets and warnings are provided, a "no visible defect" diagnosis is NO only if a defect actually exists.
- If the warning names a specific mechanism or policy, a looser generic diagnosis is NO.
- If the diagnosis mixes two different defect candidates, alternative explanations, or an unrelated auxiliary issue, reject it unless they all refer to the same warning.

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
- The reference solution is not canonical: structural differences alone do not prove a defect.
- Accept the diagnosis if it correctly states that the code is correct and the diff does not show an explicit correctness violation.
- Do not reject the diagnosis if the code is functionally correct and the differences in the diff are superficial (variable names, loop order, formatting) and do not constitute a correctness defect.
- If the observed feedback says the submission is correct or reports no code warnings, prefer accepting a no-defect diagnosis unless the diff itself shows an undeniable violation.
- For failing submissions without warnings, accept a defect diagnosis only if the same concrete mechanism is visible in the diff; feedback alone is not enough to validate a speculative code cause.
- Reject diagnoses that point to a different mechanism, file, API, variable, or protocol mismatch than the visible student-vs-solution difference.
- Reject diagnoses that mention multiple unrelated defects, tentative alternatives, or "however/also/additionally" style backup theories.
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
- If multiple warnings exist, accept the diagnosis only if it clearly matches at least one concrete warning rather than a nearby but different defect family.

Final format only:
Diagnosis_Correct: YES or NO
"""