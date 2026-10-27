# Structured Output — Tokens, Context Window & Cost
## Does Grammar Masking Use More Tokens? Is the Schema Part of the Prompt?

**Prerequisite:** You understand grammar-constrained decoding, FSMs, and how
inference engines convert JSON Schema into token masks.

---

## The Key Misconception: "Generate → Check → Regenerate"

**WRONG understanding:**

```
Model generates token "hello"
    → grammar says invalid
    → throw away
    → model generates AGAIN
    → gets "{"
    → grammar says valid
    → keep it
```

**CORRECT understanding:**

```
Model produces probabilities for ALL 50,000 tokens simultaneously:
  "{"     = 85%
  "hello" = 3%
  "the"   = 2%
  ...

Grammar mask applied BEFORE selecting:
  "{"     = 85%    ✅ keep
  "hello" = 0%     ❌ blocked (was 3%, now 0%)
  "the"   = 0%     ❌ blocked

Renormalize:
  "{"     = 100%

Select "{"  ← done, ONE step, no retry
```

There's no "generate → check → regenerate" loop. The filtering happens on the
**probability distribution**, not on generated tokens. It's like removing options
from a menu before the customer orders — not serving food and taking it back.

---

## Does the Schema Consume Tokens?

**NO.** The schema is NOT part of the prompt. It's a separate API parameter.

```
Your API call:

  messages: [
    {"role": "system", "content": "Generate config"}      ← tokens charged
    {"role": "user", "content": "dual mode, 2 LAN..."}    ← tokens charged
  ]
  response_format: {
    "json_schema": {"schema": your_schema}                 ← NOT charged
  }

The schema is NOT tokenized.
It's NOT fed into the transformer.
It's processed by the serving software to build the FSM.
You pay ZERO extra input tokens for the schema.
```

---

## Is the Context Window Affected?

**NO.** The schema, grammar, FSM, and token masks all live OUTSIDE the context window.

```
Your context window (e.g., 128K tokens for GPT-4o):

  ┌─────────────────────────────────────────┐
  │ System prompt tokens                     │ ← counts against window
  │ User message tokens                      │ ← counts against window
  │ Previous conversation tokens             │ ← counts against window
  │ Generated output tokens                  │ ← counts against window
  │                                          │
  │ JSON Schema in response_format           │ ← does NOT count
  │ Grammar / FSM                            │ ← does NOT exist in window
  │ Token masks                              │ ← does NOT exist in window
  └─────────────────────────────────────────┘

The schema lives in the serving software's memory, not the model's input.
```

---

## What Actually Costs What

```
╔═══════════════════════════════════════════════════════════════════════╗
║ Component              │ Input Tokens?  │ Output Tokens? │ Latency?  ║
╠════════════════════════╪════════════════╪════════════════╪═══════════╣
║ System prompt          │ ✅ Yes         │ -              │ -         ║
║ User message           │ ✅ Yes         │ -              │ -         ║
║ JSON Schema            │ ❌ No          │ ❌ No          │ ⚠️ Small  ║
║ (response_format)      │ (not in prompt)│                │ (FSM build)║
║                        │                │                │           ║
║ Generated JSON output  │ -              │ ✅ Yes         │ Normal    ║
║ Grammar mask overhead  │ ❌ No          │ ❌ No          │ ⚠️ Tiny   ║
║ (per-token lookup)     │                │                │ (~0.1ms)  ║
╚═══════════════════════════════════════════════════════════════════════╝

Total extra cost of using structured output:
  Extra tokens:  ~0 (negligible)
  Extra latency: ~50-200ms one-time FSM build + ~0.1ms per token lookup
  Extra money:   ~0 (you might even SAVE money — see below)
```

---

## Why You Actually SAVE Tokens With Structured Output

Without structured output, your prompt needs all the formatting rules:

```
WITHOUT structured output (prompt does everything):

  SYSTEM PROMPT (~700 tokens):
    "You are a JSON config generator...
     Rules:
     1. Always include environment_def, board, model...
     2. Do not invent keys...
     3. If field says SEE ENUM, pick from enum...
     4. Produce minimal valid JSON...
     5. Include nested keys only to required depth...
     [... 20 more rules about JSON formatting]"
```

With structured output, the schema handles all of that:

```
WITH structured output (schema handles structure):

  SYSTEM PROMPT (~30 tokens):
    "Generate minimal device config. Include only relevant keys."

  SCHEMA (separate parameter, 0 tokens):
    response_format: {"json_schema": {"schema": your_schema}}
```

**You just saved ~670 input tokens per API call.** Over thousands of calls,
that's significant cost savings.

---

## Summary

```
Schema is NOT part of the prompt         → 0 extra input tokens
Schema does NOT affect context window    → no capacity lost
Grammar mask does NOT regenerate tokens  → filtering happens BEFORE selection
Grammar mask adds ~0.1ms per token       → negligible latency
FSM build adds ~50-200ms per request     → one-time cost, barely noticeable

Net effect: You likely SAVE tokens and money because your prompt
can be much shorter when the schema handles structural enforcement.

Prompt engineering is still needed for:
  - Which keys to include (semantic understanding)
  - What values to infer from context
  - Business logic the schema can't express

Prompt engineering is NOT needed for:
  - Valid JSON syntax (grammar guarantees this)
  - Correct key names (schema enforces this)
  - Valid enum values (schema enforces this)
  - Required fields present (schema enforces this)
  - Correct data types (schema enforces this)
```
