# ================= PROMPT LLM =================
def prompt_output(readme, program_output):
    return f"""
You are analyzing the runtime output of a C program from an Operating Systems exercise.

Important context:
- The program may be correct. Only point out issues if you are reasonably sure.
- In concurrent programs, the order of printed messages may vary and still be correct.
- You currently only have access to program output, no code.
- There could be startup messages (e.g., process creation logs).

Exercise description:
{readme}

Program output:
{program_output}

Task:
Determine whether the observed output is consistent with a correct program execution.

You MUST check for the following types of issues:

1. Missing or incomplete output:
   - Expected messages not printed
   - Program stops prematurely or produces no output

2. Inconsistent or incorrect behavior:
   - Values that do not match expected logic
   - Contradictions within the output

3. Ordering and coordination issues:
   - Unexpected ordering of operations (only if it violates logical constraints)
   - Interleaving that suggests lack of coordination

4. Repetition or duplication:
   - Messages repeated unexpectedly
   - Operations executed multiple times when they should not

Guidelines:
- Empty or missing output may indicate deadlock, crash, or logic issue, but do not assume incorrectness without evidence.
- Focus on the behavior reflected in the output, including potential issues with thread execution or message ordering.
- Do NOT speculate about the code; base your reasoning only on the output.
- Do NOT speculate about internal coordination (threads, processes) unless directly observable from output.

Respond exactly in this format:

Output_Correct: Yes or No
Output_Diagnosis: <max 3 lines, describe the observed issue based only on output>
"""

def prompt_codice(readme, program_output, code):
    return f"""
You are reviewing C code from an Operating Systems exercise.

IMPORTANT:
- Even if program output appears correct, the code may contain hidden bugs.
- You must actively search for structural and logical issues.
- The program may be correct.
- If you do NOT find a clear and high-confidence bug directly in the code → Code_Correct: Yes

Exercise description:
{readme}

Program output:
{program_output}

Student code:
{code}

Task:
Determine whether the code contains correctness issues.

You MUST check for the following categories of problems:

1. Resource management:
   - Memory allocated but never freed
   - Incorrect allocation or lifetime of data structures
   - Use of stack variables where persistent memory is required

2. Synchronization and concurrency:
   - Shared data accessed without proper protection
   - Missing or incorrect synchronization
   - Overly restrictive synchronization reducing concurrency

3. Control flow and logic:
   - Incorrect loop conditions or termination logic
   - Missing checks or incorrect branching

4. Communication and coordination:
   - Incorrect use of inter-process or inter-thread communication
   - Mismatch between send/receive logic
   - Missing identification or filtering of messages/resources

5. API misuse:
   - Incorrect use of system or library calls
   - Missing error checks or wrong parameters

Guidelines:
- Do NOT mark the code as incorrect for minor issues (e.g., potential memory leaks, missing free, style issues) unless they clearly affect correctness in this exercise.
- Mark the code as incorrect ONLY if there is a concrete bug that can cause:
  - wrong results
  - deadlocks
  - race conditions affecting correctness
  - incorrect synchronization logic
- You MUST reference specific variables, functions, or code fragments.
- Do not justify correctness unless you have checked all categories above.

Respond exactly in this format:

Code_Correct: Yes or No
Code_Diagnosis: <max 4 lines, MUST reference code elements like variables/functions/code fragments and explain the issue>
"""

def prompt_codice_static(readme, code):
    return f"""
You are reviewing C code from an Operating Systems exercise.

IMPORTANT:
- You must actively search for structural and logical issues.

Exercise description:
{readme}

Student code:
{code}

Task:
Determine whether the code contains correctness issues.

You MUST check for the following categories of problems:

1. Resource management:
   - Memory allocated but never freed
   - Incorrect allocation or lifetime of data structures
   - Use of stack variables where persistent memory is required

2. Synchronization and concurrency:
   - Shared data accessed without proper protection
   - Missing or incorrect synchronization
   - Overly restrictive synchronization reducing concurrency

3. Control flow and logic:
   - Incorrect loop conditions or termination logic
   - Missing checks or incorrect branching

4. Communication and coordination:
   - Incorrect use of inter-process or inter-thread communication
   - Mismatch between send/receive logic
   - Missing identification or filtering of messages/resources

5. API misuse:
   - Incorrect use of system or library calls
   - Missing error checks or wrong parameters

Guidelines:
- If ANY suspicious pattern appears, consider the code incorrect.
- You MUST reference specific variables, functions, or code fragments.
- Do not justify correctness unless you have checked all categories above.

If the code clearly appears correct, answer YES.
Otherwise answer NO.

Respond exactly in this format:

Code_Correct: Yes or No
Code_Diagnosis: <max 4 lines, MUST reference code elements like variables/functions/code fragments and explain the issue>
"""

# ================= PROMPT GIUDICE =================

def prompt_giudice_output(diagnosi, errore_reale):
    return f"""
You are evaluating a diagnosis generated by another LLM regarding a C program.

LLM diagnosis:
{diagnosi}

Real error from tests:
{errore_reale}

Guidelines:
- The diagnosis was produced by an AI model (LLM); consider that the model may be imprecise.
- Consider the diagnosis CORRECT if it identifies runtime or output problems consistent with observed behavior.
- Consider the diagnosis INCORRECT if it claims correctness despite evident issues, ignores key symptoms, or references unrelated problems.
- Focus only on patterns visible in the program output, such as missing output, duplicated output, logical inconsistencies, or ordering issues.
- Do not penalize the diagnosis for mentioning expected variations due to concurrency, randomness, or scheduling.
- If the diagnosis identifies a potential issue with no output produced by the program, consider it CORRECT.

Respond exactly in this format:

Diagnosis_Correct: Yes or No
"""

def prompt_giudice_codice(diagnosi, warnings, code_around, solution_code):
    warnings_text = ""
    if warnings:
        warnings_text = "\nSTATIC ANALYSIS WARNINGS:\n" + "\n".join(
            [f"- {w['file']}:{w['line']}: {w['message']}" for w in warnings]
        )

    return f"""
You are evaluating the quality of a diagnosis produced by another LLM for a C program.

LLM diagnosis:
{diagnosi}

{warnings_text}

Student code (relevant excerpt):
{code_around}

Reference solution (for context):
{solution_code}

Guidelines:
- The diagnosis was produced by an AI model (LLM); consider that it may make mistakes.
- Consider the diagnosis CORRECT if it identifies code issues consistent with the static analysis warnings or evident bugs.
- Focus on whether the mentioned variables, functions, or code fragments actually correspond to potential problems.
- Consider the diagnosis INCORRECT if it ignores warnings, claims correctness despite issues, or references unrelated code.

Respond exactly in this format:

Diagnosis_Correct: Yes or No
"""

def prompt_giudice_codice_static(diagnosi, warnings):
    return f"""
You are evaluating the quality of a diagnosis produced by another LLM for a C program based on static analysis.

LLM diagnosis:
{diagnosi}

Static analysis warnings:
{warnings}

Guidelines:
- The diagnosis was produced by an AI model (LLM); it may miss or misinterpret issues.
- Consider the diagnosis CORRECT if it highlights issues consistent with the static analysis warnings, including specific variables, function calls, or code fragments.
- Consider the diagnosis INCORRECT if it claims correctness despite warnings, ignores key variables/functions, or references unrelated code.
- Consider the diagnosis INCORRECT if it fails to identify clear issues indicated by the static analysis warnings.

Respond exactly in this format:

Diagnosis_Correct: Yes or No
"""