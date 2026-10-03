# BFCL-Modified

BFCL-Modified is the Berkeley Function Calling Leaderboard (BFCL, the `berkeley-function-call-leaderboard/`
folder of [ShishirPatil/gorilla](https://github.com/ShishirPatil/gorilla)) at commit
`6ea57973c7a6097fd7c5915698c54c17c5b1b6c8`, with three changes to how a model is scored. GQLLM-Compression
keeps it for its model test harness.

Scores produced with it are named **BFCL-Modified**. They are not comparable with the published BFCL
leaderboard, because rules that the published numbers apply are relaxed in the three situations below.
Datasets, ground truth, prompts, every other checker and every other handler are the upstream ones.

## Why

BFCL scores a model as failing in three situations where the model did what was asked:

1. The endpoint's serving stack does not parse the model's own tool-call syntax, so the call arrives as text
   in the reply's `content` and BFCL sees a reply without any call. In a multi-turn task BFCL then stops the
   step at that reply.
2. The function's own description asks for a value in a form such as `'New York, NY'`, the model gives
   `'Chennai, India'`, and the ground truth accepts only `'Chennai'` (`live_simple_98-58-0`).
3. The model writes a typographic apostrophe (U+2019) where the text it works from, and the ground truth, has
   the plain one (U+0027). In `multi_turn_long_context_35` the model writes the output of `diff` into a file and
   one apostrophe differs; BFCL's state check compares the file's content exactly. BFCL's own question data uses
   both forms (U+2019 occurs 121 times in its question files).

## Change 1: a tool call returned as text is credited

Applies to every handler that uses `OpenAICompletionsHandler._query_FC` and `_parse_query_response_FC`
unchanged (the OpenAI-compatible function-calling path).

A reply with no structured `tool_calls` is credited as a call when its text **ends** with a call to a tool the
request offered, with literal arguments. What comes before the call stays as the message's text. These forms
are read:

| Form | Example |
|---|---|
| a Python call list, or a single call | `[get_weather(city="Oslo"), get_time(zone="CET")]` |
| JSON with `name` and `arguments` or `parameters`, as an object or a list, also the OpenAI `function` nesting | `{"name": "get_weather", "arguments": {"city": "Oslo"}}` |
| the `functools` and `[TOOL_CALLS]` prefixes | `functools[{"name": ...}]` |
| `<tool_call>` tags | `<tool_call>{"name": ...}</tool_call>` |
| any of these inside one closed code fence | a ```` ```json ```` block |

Not credited: prose that mentions a call, a call followed by more text, a tool the request did not offer
(a dotted spelling of an underscored name counts), positional arguments, names or expressions as arguments,
`**kwargs`, sets, and malformed JSON. No judgement is made about intent: a call that is well formed and ends
the reply is a call, and BFCL's own checker then scores it like any structured call.

The credited call is set where BFCL reads a call, and the message kept for the conversation is the plain
dict BFCL's handlers record for a structured call, so a multi-turn task continues. A structured call always
wins. The result row of a task carries `text_calls_credited` (how many of its replies were credited) and
`text_calls_original` (the first few of those replies as received), and the log line `[BFCL-Modified]
credited a call returned as text` is printed for each.

Files: `bfcl_eval/model_handler/text_calls.py` (new, pure functions) and
`bfcl_eval/model_handler/api_inference/openai_completion.py`.

## Change 2: an accepted answer followed by a qualifier

In `string_checker` and in the string values of `dict_checker`, a value passes when its leading
comma-separated parts, taken from the first onward, are an accepted answer and something follows them.
`'Chennai, India'` and `'Chennai, Tamil Nadu, India'` pass for `'Chennai'`; `'Boston, MA, USA'` passes for
`'Boston, MA'`. These still fail for `'Chennai'`: `'Delhi, India'`, `'India, Chennai'` and `'Chennai India'`.
BFCL's own standardisation (case, spaces and punctuation) applies first and is unchanged.

The rule does not know geography, so `'Paris, Texas'` passes for `'Paris'`. It is not applied to the items of
a list, nor to the state checks of multi-turn tasks.

File: `bfcl_eval/eval_checker/ast_eval/ast_checker.py` (function `matches_with_qualifier`).

## Change 3: a typographic apostrophe is read as the plain one

The typographic apostrophe (U+2019), the left single quotation mark (U+2018) and the modifier letter
apostrophe (U+02BC) are read as the plain apostrophe (U+0027) wherever the checkers compare text. The characters
are named in one place, `bfcl_eval/eval_checker/apostrophes.py`.

| Where | How |
|---|---|
| Single-turn answers: `standardize_string` in `ast_checker.py` | applied to the model's value and to every accepted answer before BFCL's own standardisation, so strings, dict values, list items and Change 2 all see it |
| Agentic answers: `standardize_string` in `agentic_checker.py` | the same |
| Multi-turn state: `_compare_instances` in `multi_turn_checker.py` | an attribute that differs is compared again on copies of both sides in which every string, at any depth, has its apostrophes straightened; the state passes only if the copies are equal |
| Multi-turn responses: `response_checker` in `multi_turn_checker.py` | the execution results are compared again the same way when the first comparison fails |

Nothing else is read as an apostrophe (not the grave accent, the prime or double quotes), and a difference that is
more than the apostrophe still fails. What the model sent is never rewritten: the tools run with exactly the
characters the model wrote, so a file it names with a typographic apostrophe is still found by its own later
calls, and only the comparison with the ground truth ignores the difference.

Files: `bfcl_eval/eval_checker/apostrophes.py` (new), `ast_eval/ast_checker.py`, `agentic_eval/agentic_checker.py`
and `multi_turn_eval/multi_turn_checker.py`, all under `bfcl_eval/eval_checker/`.

## Checked

- BFCL's own `ast_checker` on `live_simple_98-58-0`: `'Chennai'` and `'Chennai, India'` pass, `'Delhi, India'`
  and `'India, Chennai'` fail.
- BFCL's own `multi_turn_checker` and file-system backend on `multi_turn_long_context_35`, with a model that
  echoes the diff exactly as the ground truth does: with one or with all three of the task's apostrophes
  written as U+2019 the task fails on `multi_turn:instance_state_mismatch` without Change 3 and passes with
  it; with a word dropped as well it fails either way.
- Re-evaluating the stored result files of model runs with the changed checkers flipped no verdict: 19 runs
  (120 category results) after Change 2 and 21 runs (133) with all three changes, so the rules matter only
  where a model gives a qualified value or writes the typographic character.
- Change 1 was run against a live endpoint whose replies carry calls as text; the credited calls were
  executed, the conversation went on, and the tasks that still failed did so on BFCL's own state checks.
