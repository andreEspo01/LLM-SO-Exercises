PRIMARY_SYSTEM_PROMPT = (
    "You analyze student C solutions for Operating Systems exercises. "
    "Use only the provided evidence. "
    "Do not invent hidden requirements, hidden expected values, invisible code paths, or unsupported causes. "
    "Prefer conservative, evidence-based judgments. "
    "Do not overclaim correctness from partial traces, later side effects, or loosely related code details. "
    "Keep the boolean field and diagnosis consistent. "
    "Write diagnoses in English, using at most 100 words. "
    "Return exactly the requested fields. "
    "DO NOT use markdown formatting, backticks, or code blocks. Return plain text only."
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
- A YES answer requires that the visible trace is consistent with the exercise protocol. It does not require exhaustive verification of every value if the overall structure is coherent.

Exercise description:
{readme}

Program output:
{program_output}

Decision rules:
- If the output is empty, blank, or equivalent to "The program produced no output.", then Output_Correct = NO.
- If the visible output contains "timeout" (or any equivalent timeout/termination message), then Output_Correct = NO.
- Missing messages, wrong counts, malformed exchanges, mismatched IDs/PIDs/request numbers, impossible ordering, or wrong computed values visible in the output imply Output_Correct = NO.
- The diagnosis must describe the observable symptom only, not the possible code cause.
- Use the visible order of events as the order of observation.
- In concurrent or multi-process traces, stdout interleaving by itself is not a protocol violation ONLY if each visible actor stream (per PID/role) is internally coherent and replies unambiguously reference their senders.
- When actor identity is visible, evaluate counts and duplicates per actor/role/PID namespace, not by raw message numbers alone.
- Do not infer a round-robin, routing, or balancing violation from interleaving alone UNLESS the visible reply identifiers explicitly show that messages were routed to wrong destinations.
- If the trace gives enough information to validate values one by one, explicitly recompute those values before claiming a mismatch. Do not rely on intuition or operation names alone for arithmetic checks.
- A later consume/receive/dequeue/read that reveals meaningful data does not by itself prove that an earlier produce/send/enqueue/store reply was wrong.
- Count the number of each operation family mentioned in the trace. If counts appear inconsistent with the visible protocol, mark NO with evidence.
- If the test feedback explicitly reports an incorrect execution or mismatch, treat this as a strong signal that Output_Correct should be NO.
- CONCURRENT LOG ORDER: In concurrent or multi-process/multi-thread systems, a server or worker may print its log entry after the client has already received and printed the reply. This is normal and does not constitute an ordering violation. Evaluate protocol correctness based on the logical sequence of operations (request sent, reply received), not on the physical order of log lines in stdout.
- DISPATCHER AUTHORITY: If a dispatcher, balancer, router, or aggregator log shows the correct distribution or forwarding of messages, accept that as evidence of correct routing. Do not require that the downstream recipients print their logs in the same order as the dispatcher's routing decisions.
- SIDE-EFFECTING OPERATIONS: For operations that produce, enqueue, store, or register a value (e.g., PRODUCI, send, enqueue, register), a reply value of 0 or a neutral acknowledgment is correct unless the exercise description explicitly states that the immediate reply must carry the produced payload. The produced value appearing in a later consume/dequeue/read operation is the expected behavior.
- PER-ACTOR COUNT TOLERANCE: In fan-out or broadcast scenarios where one source forwards to multiple consumers via a shared buffer or queue, individual consumers may receive slightly different counts due to scheduling. Do not mark NO solely because one consumer received one fewer value than another, unless the exercise explicitly requires each consumer to receive exactly the same count.
- LOCAL SEQUENCE NUMBERS: A receiver or server may assign its own local sequence numbers (0, 1, 2, 3...) to messages it receives. These local numbers are independent of the original message numbers assigned by the sender. Do not treat a mismatch between a receiver's local sequence number and the sender's original message number as a protocol violation.
- CONCURRENT MULTI-CLIENT REPLIES: When multiple clients send requests concurrently to the same server or registry, replies may arrive at each client in a different order than the requests were sent, due to scheduling. A reply is correct if it matches any pending request from that client, not necessarily the most recently sent one. Do not mark NO solely because a reply appears to match a different request than the immediately preceding one in the log.
- IDENTICAL REPEATED REQUESTS: If a client sends multiple requests with the same operands or parameters, receiving identical replies is correct and expected. Do not treat repeated identical responses as a protocol violation or as evidence of missing randomness, unless the exercise description explicitly requires distinct values for each request.
- LATE-STARTING CONSUMERS: In producer-consumer or fan-out scenarios, a consumer or collector that starts after the producer has already begun sending may miss the first few messages. This is a scheduling artifact, not a protocol error, unless the exercise explicitly requires all consumers to receive all messages from the beginning.
- AGGREGATE COUNT VERIFICATION: When verifying message counts in a routing or distribution scenario, verify the total count across all senders and all receivers, not the per-actor count in isolation. For example, if 2 clients each send 6 messages to a balancer that distributes to 3 servers, each server correctly receives 4 messages (12 total / 3 servers = 4 each). Do not mark NO because each server receives fewer messages than each client sent; verify that the total sent equals the total received.
- CONSUMA REPLY VALUE: In a producer-consumer RPC protocol, CONSUMA (consume) returns the value that was previously produced and stored in the buffer. The returned value is the stored payload, not a computed result. Do not mark NO because a CONSUMA reply returns a value that was produced by a previous PRODUCI call; this is the expected behavior. Only mark NO if the returned value does not match any previously produced value that should still be in the buffer.
- SPOTCHECK: For at least one complete request/reply cycle or producer/consumer pair, verify that operands/inputs match outputs/results using concrete visible values. If you cannot spotcheck even one cycle, explain which values cannot be verified.
- BALANCED JUDGMENT: If the trace shows the expected actors, the expected number of interactions, and at least one verifiable correct value exchange, mark YES even if not every single value can be independently verified. Do not require exhaustive verification when the overall structure is coherent.
- If the trace is structurally complete (all expected phases present, all actors visible, counts match) and no concrete mismatch is found, mark YES.
- If the trace is structurally complete but one specific value or pairing is concretely wrong, mark NO and identify that specific mismatch.
- Do not mark NO merely because the trace is concurrent and some values cannot be independently attributed to specific actors, unless the exercise explicitly requires per-actor attribution.
- If Output_Correct = YES, the diagnosis must explicitly say that no concrete output mismatch is visible and confirm that the trace structure is consistent with the exercise protocol.
- If Output_Correct = NO, identify the specific broken interaction: missing trace, wrong values, wrong counts, wrong pairing, wrong ordering, or unverifiable value flows.
- Keep the diagnosis detailed but compact: maximum of 100 words.
- Write the diagnosis in English.
- Do not quote or refer to hidden tests, hidden assertions, or hidden ground truth.

Final format only:
Output_Correct: YES or NO
Output_Diagnosis: <detailed evidence-based diagnosis>
"""


def prompt_codice(readme, program_output, code, failure_category=None, output_diagnosis=""):
    runtime_focus = ""
    if failure_category in {"dynamic_failure", "timeout", "ipc_leak", "crash"}:
        runtime_focus = f"""

Runtime-failure focus:
- The observed runtime failure category is: {failure_category}
- The current output diagnosis is:
{output_diagnosis or "No output diagnosis available."}
- In this case, do NOT look for a generic bug or a secondary static issue.
- Identify ONLY the code cause that best explains why the execution failed in that specific way.
- If output_diagnosis explicitly names a missing phase, wrong value, or protocol mismatch, prioritize finding the code statement that causes that specific symptom.
- First verify that the reported runtime symptom is grounded in an explicit contract from the exercise or visible trace.
- If the reported symptom depends on assuming that an immediate reply must carry a produced/computed payload, but that contract is not explicit, do not adopt that assumption as the target defect.
- If the code only shows unrelated issues that do not explain that runtime failure, answer YES rather than inventing a different NO diagnosis.
"""

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
- If evidence is weak and the observed output shows successful execution (complete protocol phases, no truncation), answer YES.
- Do not invent hidden constraints.

Exercise description:
{readme}

Observed runtime/output:
{program_output}
{runtime_focus}

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
- CROSS-CHECK OUTPUT: If the provided program_output shows incomplete/missing/wrong protocol phases (e.g., missing EXIT messages, incomplete BIND handshakes, truncated request/reply pairs), treat this as evidence of a code cause UNLESS the exercise explicitly allows partial execution or early termination. Do not answer YES when the output itself signals failure.
- Do not claim a race condition unless unsynchronized concurrent accesses to the same shared state are explicitly visible in the code.
- Do not claim a missing pthread_join() unless the code can terminate before required work completes and no alternative waiting/synchronization is visible.
- Do not claim a missing critical section unless both the concurrent access and the unprotected operation are visible.
- If the code already shows mutexes, semaphores, condition variables, monitor procedures, or dedicated read/write functions, do not diagnose "missing synchronization primitives" unless the shown declarations and operations truly contain no synchronization mechanism for the relevant path.
- In reader-writer style code, if reader and writer procedures are already present, prefer diagnosing the wrong reader-writer policy or over-serialization of readers rather than claiming there is no synchronization at all.
- Do not diagnose a reader-writer defect as a generic mutex defect unless the code clearly shows that only ordinary mutual exclusion was required.
- Do not diagnose a queue-ID or selector mix-up merely because one variable stores or aliases another queue identifier; diagnose it only if the visible send/receive or type-selection sites are concretely inconsistent.
- On a shared queue, mailbox, or channel used by multiple logical senders, receivers, or phases, check whether the visible selector/type/tag actually distinguishes the actors whose results are later attributed separately.
- Reusing the same selector/type/tag for replies from different logical sources on the same shared channel is a concrete protocol-matching defect when the receiver later treats the received values as coming from specific roles, processes, phases, or operations.
- Conversely, do not diagnose a shared-channel matching bug if the code visibly uses dedicated queues/channels or distinct selectors that already separate the logical sources.
- Do not cite pseudocode labels, natural-language placeholders, or comments as code evidence unless they literally appear in the code.
- Do not infer exercise-specific obligations unless they are explicit in the description or directly visible in the code.
- Do not answer YES merely because one specific API name is absent. If the visible implementation of the relevant code path omits the required mechanism, selector, synchronization policy, cleanup step, or ownership pattern, that omission may itself justify NO.
- Do not diagnose generic error-handling defects such as missing return-value checks, missing errno checks, or missing validation unless the observed failure is about that path or the code makes that defect the central visible cause.
- When runtime feedback is only black-box and the code does not show one explicit violating statement or omission, prefer YES over a speculative NO.
- For dynamic_failure, timeout, ipc_leak, or crash, use the provided output diagnosis as the target symptom and explain the concrete code cause of that failure, not a different secondary issue that could exist even if execution succeeded.
- For dynamic_failure, timeout, ipc_leak, or crash, do not use rule-style static findings or generic code smells as evidence unless they directly explain the observed runtime failure.
- For dynamic_failure, timeout, ipc_leak, or crash, if the code does not show a concrete cause for the observed runtime symptom, prefer YES over diagnosing a different unrelated bug.
- For dynamic_failure, timeout, ipc_leak, or crash, do not let a superficially coherent trace override a concrete main-path selector/routing ambiguity visible in the code.
- If the main success path visibly multiplexes multiple logical sources through one shared queue/channel without a discriminator that matches the later role-specific attribution, that is concrete evidence for NO even when the runtime trace looks arithmetically coherent.
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
- Do not diagnose a constant or zero reply field as a defect unless the exercise description or visible runtime symptom explicitly shows that this reply field must carry the produced or computed payload for that operation.
- For side-effecting operations such as produce, send, store, enqueue, or register, a later consume/read/dequeue revealing the value does not by itself prove that the earlier reply field is wrong.
- ERROR HANDLING RULE: Do NOT diagnose error-handling defects unless they directly cause the observed runtime failure:
  * Do not diagnose missing checks on malloc/calloc/queue-creation/thread-creation failures unless the test output shows the program actually crashed or produced wrong output due to that failure.
  * Do not diagnose memory leaks in error paths (e.g., "allocated but not freed if pthread_create fails") because the test suite does not induce these anomalous failure conditions.
  * Do not report missing error handling for resource allocation failures that do not occur during the visible runtime execution shown in the output.
  * Focus on defects that affect the main success path: synchronization, protocol correctness, resource lifetime in normal operation, and control flow.
  * Error handling quality is important for robustness but is outside the scope of dynamic correctness testing when anomalous failures are not triggered.
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
- CROSS-CHECK OUTPUT: If the provided program_output shows incomplete protocol phases, missing termination messages, truncated exchanges, or other structural problems (even if execution didn't hang), this may signal a code defect. Do not immediately default to YES if the output itself looks incomplete.
- Do not speculate about hidden races, hidden deadlocks, hidden queue mix-ups, hidden lifetime bugs, or unobserved protocol failures.
- If mutexes, semaphores, condition variables, monitor procedures, or reader/writer functions are visible, do not call the defect "missing synchronization primitives" unless the shown path truly contains no synchronization mechanism at all.
- Do not diagnose a queue-ID or selector mix-up unless the visible send/receive or type-selection sites are concretely inconsistent.
- If Code_Correct = NO, cite at least one file name and one function, API, variable, or short code fragment exactly as visible in the code.
- ERROR HANDLING RULE: Do NOT diagnose error-handling defects when the code is otherwise correct:
  * Do not report missing checks on malloc/calloc/queue-creation/thread-creation failures if the code executes successfully and the test suite passes.
  * Do not report memory leaks "if pthread_create fails" or "if malloc returns NULL" because these error paths are not exercised during the passing test execution.
  * Recognize that passing tests are evidence the resource allocation always succeeds in the tested scenarios; error-handling robustness is outside the scope of dynamic correctness testing.
  * Focus only on bugs that would cause observable wrong output or protocol violations in normal (successful resource allocation) execution.
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
- ERROR HANDLING RULE: Do NOT diagnose missing error-handling code as a structural defect:
  * Do not report missing checks on malloc/calloc/queue-creation/thread-creation failures unless they are concretely called in the analyzed code path during normal execution.
  * Do not report memory leaks "if pthread_create fails" or "if malloc returns NULL" because failure paths are not exercised in normal usage.
  * Do not diagnose missing error handling on resource allocation failures unless the test suite evidence or code context shows that these failures are triggered.
  * Focus on structural defects that affect normal (success-path) execution: synchronization policy, lifetime/ownership in success paths, scope/order violations in main control flow.
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
- Do not collapse a specialized policy defect into a generic 'missing mutex' diagnosis.
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

def prompt_giudice_output(diagnosi, output_ground_truth):
    return f"""
Grade an output diagnosis against the ground truth about the visible execution/output.

Diagnosis:
{diagnosi}

Ground truth about output:
{output_ground_truth}

Rules:
- Focus on semantic alignment: does the diagnosis capture the essence of the same failure?
- Accept the diagnosis if it correctly identifies a type of output problem that matches the ground truth failure.
- Accept the diagnosis if it correctly states that the output is correct and the ground truth confirms correct output.
- Reject only if the diagnosis contradicts the ground truth or claims a different category of failure.
- Treat detailed diagnoses as enrichments of generic ground truth. If ground truth says "execution incorrect" but does not detail why, a diagnosis identifying the specific type of error (wrong value, missing interaction, wrong pairing, wrong count) is acceptable.
- Paraphrases and different framings of the same symptom are correct.
- If the diagnosis states that "the program produced no output," it is correct whenever the ground truth indicates failure during execution, even if ground truth is generic.
- If the ground truth says output is correct, accept a diagnosis saying no mismatch is visible unless the diagnosis adds a different invented problem.
- Briefly explain why the diagnosis matches or does not match the output ground truth.

Final format only:
Judge_Motivation: <short reason>
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
- Prefer semantic equivalence over exact textual matching across different levels of abstraction.
- Accept the diagnosis if it identifies the same defect mechanism, even if phrased differently or at a different architectural level.
- A diagnosis identifying a root cause or prerequisite condition for the warned defect should be accepted if causally related.
  * Example: If warning says "readers must read concurrently" and diagnosis says "threads are not created," accept if the absence of threads directly prevents the concurrent reading.
  * Counter-example: If diagnosis identifies a completely different code path, reject.
- Line numbers are not authoritative; a diagnosis valid even if it refers to a different line within the same mechanism.
- Accept correct statements that the code is sound if no real warnings exist.
- Reject diagnoses that confuse different defect families (e.g., lifetime vs. synchronization, selector vs. protocol) unless clearly stating why they co-occur.
- A high-level warning paired with concrete detailed diagnosis is acceptable if details stay within the same defect family.
- Do not reject because the diagnosis goes deeper or offers a causal explanation; accept if the causal chain is sound.

Final format only:
Judge_Motivation: <short reason>
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
Rules:
- Accept the diagnosis if it correctly states that the code is correct and the diff does not show an explicit correctness violation.
- Accept only if the diagnosis matches a concrete structural difference visible in the diff and consistent with the observed failure.
- The reference solution is not canonical: structural differences alone do not prove a defect.
- Do not reject the diagnosis if the code is functionally correct and the differences in the diff are superficial (variable names, loop order, formatting) and do not constitute a correctness defect.
- If the observed feedback says the submission is correct or reports no code warnings, prefer accepting a no-defect diagnosis unless the diff itself shows an undeniable violation.
- For failing submissions without warnings, accept a defect diagnosis only if the same concrete mechanism is visible in the diff; feedback alone is not enough to validate a speculative code cause.
- If the ground truth context is high-level, extra consistent detail in the diagnosis is acceptable when it remains compatible with the visible diff.
- Reject diagnoses that point to a different mechanism, file, API, variable, or protocol mismatch than the visible student-vs-solution difference.
- Reject diagnoses that mention multiple unrelated defects, tentative alternatives, or "however/also/additionally" style backup theories.
- If the diagnosis cites a file, function, API, variable, or code fragment, it must be compatible with the diff.
- Do not invent hidden defects outside the provided diff.
- If the diff does not support the diagnosis, answer NO.
- For timeout, crash, or ipc_leak failures: if no output diagnosis is available, evaluate the code diagnosis against the diff and feedback alone. Accept the diagnosis if it identifies a plausible mechanism (deadlock, missing cleanup, wrong synchronization) that is compatible with the observed failure category and visible in the diff. Do not require an output diagnosis to validate a code-level finding for these categories.
- For timeout failures: accept diagnoses that identify blocking operations, missing signals, or deadlock-prone patterns visible in the diff, even without a specific output trace.
- For ipc_leak failures: accept diagnoses that identify missing IPC resource deallocation visible in the diff.
- For crash failures: accept diagnoses that identify null pointer dereference, invalid memory access, or uninitialized variable patterns visible in the diff.

Final format only:
Judge_Motivation: <short reason>
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
- Accept if the diagnosis identifies the same underlying defect mechanism, even if at different levels of abstraction.
- Prefer semantic equivalence over textual matching. Synchronization, lifetime, selector, and protocol errors should be evaluated by mechanism, not exact terminology.
- A diagnosis identifying a root cause or prerequisite for the warned defect is acceptable if causally related.
  * Example: If warning concerns concurrent access and diagnosis identifies missing synchronization primitive, accept if that primitive would enable the concurrent access.
  * Counter-example: If the warned defect and diagnosis operate on entirely different code structures, reject.
- Line numbers are not authoritative; a diagnosis valid if it refers to the same logical code region or mechanism.
- If multiple warnings exist, the diagnosis should address at least one. If it clearly addresses one while missing others, judge based on the addressed warning.
- High-level warnings with concrete diagnosis details are acceptable when details stay within the same defect family.
- Reject only if the diagnosis invents a different defect family or fundamentally contradicts the warning.

Final format only:
Judge_Motivation: <short reason>
Diagnosis_Correct: YES or NO
"""
