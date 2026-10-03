# BFCL-Modified

BFCL-Modified is the Berkeley Function Calling Leaderboard (BFCL, the `berkeley-function-call-leaderboard/`
folder of [ShishirPatil/gorilla](https://github.com/ShishirPatil/gorilla)) at commit
`6ea57973c7a6097fd7c5915698c54c17c5b1b6c8`, with two changes to how a model is scored. GQLLM-Compression
keeps it for its model test harness.

Scores produced with it are named **BFCL-Modified**. They are not comparable with the published BFCL
leaderboard, because two rules that the published numbers apply are relaxed in the two situations below.
Datasets, ground truth, prompts, every other checker and every other handler are the upstream ones.

## Why

BFCL scores a model as failing in two situations where the model did what was asked:

1. The endpoint's serving stack does not parse the model's own tool-call syntax, so the call arrives as text
   in the reply's `content` and BFCL sees a reply without any call. In a multi-turn task BFCL then stops the
   step at that reply.
2. The function's own description asks for a value in a form such as `'New York, NY'`, the model gives
   `'Chennai, India'`, and the ground truth accepts only `'Chennai'` (`live_simple_98-58-0`).

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

## Checked

- BFCL's own `ast_checker` on `live_simple_98-58-0`: `'Chennai'` and `'Chennai, India'` pass, `'Delhi, India'`
  and `'India, Chennai'` fail.
- Re-evaluating the stored result files of 19 model runs (120 category results) with the changed checker
  flipped no verdict, so the rule matters only where a model gives a qualified value.
- Change 1 was run against a live endpoint whose replies carry calls as text; the credited calls were
  executed, the conversation went on, and the tasks that still failed did so on BFCL's own state checks.
