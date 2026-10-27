# Grammar-Constrained Decoding in LLMs
## The Hidden Layer Between Model Output and Your Response

**Prerequisite:** You already understand the basic inference pipeline:

```
Prompt → Tokenize → Embedding → Transformer → Logits → Softmax(T) → Sample(seed) → Token
```

This document covers what happens when you add **one extra step** to that pipeline
that **guarantees** the output follows a specific structure (valid JSON, valid XML,
valid anything).

---

## 1. The Problem: LLMs Generate Text, Not Structure

LLMs are trained to predict the next token. They're very good at generating
text that *looks like* valid JSON, but they have no built-in guarantee.

```
You ask:  "Generate a JSON config with mode=dual"

LLM might output (95% of the time):
  {"mode": "dual"}                    ✅ Valid JSON

LLM might output (5% of the time):
  {"mode": "dual"                     ❌ Missing closing brace
  {"mode": "dual",}                   ❌ Trailing comma
  Here's the JSON: {"mode": "dual"}   ❌ Extra text before JSON
  {"mode": True}                      ❌ Python boolean, not JSON
```

For code generation, config files, API responses — that 5% failure rate is unacceptable.

**The solution: Don't fix bad output. Prevent it from being generated in the first place.**

---

## 2. The Updated Pipeline

Grammar-constrained decoding adds ONE step between softmax and sampling:

```
╔═══════════════════════════════════════════════════════════════════════╗
║  💡 AHA MOMENT: The Updated Pipeline                                  ║
╠═══════════════════════════════════════════════════════════════════════╣
║                                                                        ║
║  BEFORE (standard generation):                                         ║
║                                                                        ║
║    Transformer → Logits → Softmax(T) → Sample(seed) → Token           ║
║                                                                        ║
║                                                                        ║
║  AFTER (grammar-constrained generation):                               ║
║                                                                        ║
║    Transformer → Logits → Softmax(T) → GRAMMAR MASK → Sample → Token  ║
║                                              ↑                         ║
║                                       (new step added)                 ║
║                                       (not part of model)              ║
║                                       (applied by serving software)    ║
║                                       (works with ANY model)           ║
║                                                                        ║
║  The tap (model)      → doesn't know the filter exists                 ║
║  The water (logits)   → flows the same way regardless                  ║
║  The filter (grammar) → removes what's not wanted                      ║
║  The output           → clean, guaranteed valid                        ║
║                                                                        ║
╚═══════════════════════════════════════════════════════════════════════╝
```

**What the grammar mask does:** Before sampling, it checks which tokens would
produce valid output according to the grammar rules. Invalid tokens get their
probability set to zero. The model literally *cannot* generate them.

---

## 3. How the Grammar Mask Works — Complete Token-by-Token Trace

Let's generate `{"mode":"dual"}` with a grammar that enforces this structure.

The grammar says:
- Output must be a JSON object
- Only key allowed is "mode"
- Only values allowed are "dual", "ipv4", or "ipv6"

### Token 1: Start of output

```
Model produces logits for ALL 50,000 tokens in vocabulary:

  "{"     → probability 85%  (model knows JSON starts with {)
  "Hello" → probability 3%
  "The"   → probability 2%
  "["     → probability 1%
  ...other tokens share remaining 9%

Grammar check: "What tokens are valid at position 0?"
  Answer: Only "{" — JSON object must start with open brace

Apply mask:
  "{"     → 85%  ✅ KEEP
  "Hello" → 3%   ❌ → 0%
  "The"   → 2%   ❌ → 0%
  "["     → 1%   ❌ → 0%
  everything else → 0%

Renormalize (must sum to 100%):
  "{"     → 100%

Selected token: "{"       (no choice — it's the only option)
```

### Token 2: After `{`

```
Model logits say:
  '"'   → 70%   (model expects a quoted key next)
  ' '   → 20%   (whitespace)
  '}'   → 5%    (close empty object)
  'a'   → 3%
  ...

Grammar check: "After '{', what's valid?"
  Answer: '"' to start the key "mode", or whitespace before the key

Apply mask:
  '"'   → 70%  ✅ KEEP
  ' '   → 20%  ✅ KEEP (whitespace before key is valid JSON)
  '}'   → 5%   ❌ → 0%  (can't close — "mode" is required by schema)
  'a'   → 3%   ❌ → 0%

Renormalize:
  '"'   → 78%
  ' '   → 22%

Selected: '"'
```

### Token 3: After `{"`

```
Grammar check: "What can follow the opening quote of the key?"
  Answer: Only "m" — because the only allowed key is "mode"

Everything except "m" → 0%

Selected: "m"    (100% — no other option)
```

### Tokens 4-7: Completing the key and colon

```
Token 4: "o"    (forced — spelling "mode")
Token 5: "d"    (forced)
Token 6: "e"    (forced)
Token 7: '"'    (forced — closing quote of key)
Token 8: ":"    (forced — colon after key)
```

### Token 9: Start of value — This Is Where It Gets Interesting

```
Model logits say:
  ' '       → 15%
  '"'       → 60%
  '1'       → 8%
  'true'    → 5%
  ...

Grammar check: "After ':', what's valid for the value?"
  Schema says mode must be one of: "dual", "ipv4", "ipv6"
  So the value must start with '"' (it's a string from an enum)

Apply mask:
  '"'       → 60%  ✅ KEEP
  ' '       → 15%  ✅ KEEP (whitespace before value is valid)
  '1'       → 8%   ❌ → 0%  (not a valid enum value)
  'true'    → 5%   ❌ → 0%  (not a valid enum value)

Selected: '"'
```

### Token 10: First Character of the Enum Value

```
Model logits say:
  "d" → 50%   (could start "dual")
  "i" → 30%   (could start "ipv4" or "ipv6")
  "a" → 8%
  "x" → 2%
  ...

Grammar check: "Which characters can start a valid enum value?"
  "dual" starts with "d"
  "ipv4" starts with "i"
  "ipv6" starts with "i"
  Answer: Only "d" or "i" are valid

Apply mask:
  "d" → 50%  ✅ KEEP
  "i" → 30%  ✅ KEEP
  "a" → 8%   ❌ → 0%
  "x" → 2%   ❌ → 0%

Renormalize:
  "d" → 62.5%
  "i" → 37.5%

Selected: "d"   (probabilistic — temperature and seed affect this choice!)
```

### Remaining Tokens

```
Token 11: "u"   (forced — only "dual" starts with "du")
Token 12: "a"   (forced)
Token 13: "l"   (forced)
Token 14: '"'   (forced — closing quote of value)
Token 15: "}"   (forced — schema has no more keys, must close)
```

### Final Output: `{"mode":"dual"}`

**Guaranteed valid. Impossible to produce anything else that violates the schema.**

---

## 4. The Model Knows NOTHING About Any of This

This is worth emphasizing:

```
╔═══════════════════════════════════════════════════════════════════════╗
║  💡 AHA MOMENT: The Model Knows NOTHING About Grammar                 ║
╠═══════════════════════════════════════════════════════════════════════╣
║                                                                        ║
║  What the model sees and produces:                                     ║
║                                                                        ║
║    Input tokens: [Generate, config, for, dual, mode]                   ║
║    Output logits: [3.2, -1.5, 7.8, 0.4, ...] × 50,000 values         ║
║                                                                        ║
║    That's it. Same logits whether grammar masking is on or off.        ║
║                                                                        ║
║  What the model does NOT know:                                         ║
║    ✗ That a grammar exists                                             ║
║    ✗ That some of its tokens are being blocked                         ║
║    ✗ That its probabilities are being modified                         ║
║    ✗ What JSON Schema is                                               ║
║    ✗ That the output will be parsed as JSON                            ║
║                                                                        ║
║  The model produces the SAME logits regardless.                        ║
║  The grammar mask is applied OUTSIDE the model by serving software.    ║
║                                                                        ║
╚═══════════════════════════════════════════════════════════════════════╝
```

---

## 5. What Is a Grammar? (It's Just Rules Written as Text)

```
╔═══════════════════════════════════════════════════════════════════════╗
║  💡 AHA MOMENT: Grammar Is Just Plain Text Rules                      ║
╠═══════════════════════════════════════════════════════════════════════╣
║                                                                        ║
║  A grammar is a set of rules describing what character sequences       ║
║  are valid. That's ALL it is — a document describing patterns.         ║
║                                                                        ║
║  It's NOT:                                                             ║
║    ✗ A neural network                                                  ║
║    ✗ Part of the model                                                 ║
║    ✗ A special programming language                                    ║
║    ✗ Something that needs compilation                                  ║
║                                                                        ║
║  It IS:                                                                ║
║    ✓ A plain text file with rules                                      ║
║    ✓ Like regex, but for structured documents                          ║
║    ✓ Convertible between many notations (BNF, GBNF, JSON Schema)      ║
║    ✓ Universal — same concept since the 1950s                          ║
║                                                                        ║
╚═══════════════════════════════════════════════════════════════════════╝
```

### The Notation: BNF / EBNF / GBNF

The most common way to write grammars uses **BNF (Backus-Naur Form)**, invented
in the 1950s for describing programming language syntax.

```
# BNF rules for simple math expressions like "3+7"

digit    ::= '0' | '1' | '2' | '3' | '4' | '5' | '6' | '7' | '8' | '9'
operator ::= '+'
expr     ::= digit operator digit
```

**How to read this:**
- `digit ::= '0' | '1' | ...`  means "a digit is defined as '0' OR '1' OR '2'..."
- `::=` means "is defined as"
- `|` means "or"
- `expr ::= digit operator digit` means "an expression is: a digit, then an operator, then a digit"

**Valid outputs:** `0+0`, `3+7`, `9+1`
**Invalid outputs:** `3+`, `++7`, `33+7`, `hello`

### GBNF (Used by llama.cpp) — Same Concept, Slightly Different Syntax

```
# GBNF grammar for a simple JSON object

root       ::= "{" ws members ws "}"
members    ::= pair ("," ws pair)*
pair       ::= ws string ws ":" ws value ws
string     ::= "\"" [a-zA-Z_]+ "\""
value      ::= string | number | "true" | "false"
number     ::= [0-9]+
ws         ::= [ \t\n]*
```

Extra notation:
- `[a-zA-Z_]+` means "one or more letters or underscores"
- `[ \t\n]*` means "zero or more spaces, tabs, or newlines"
- `("," ws pair)*` means "zero or more repetitions of comma + whitespace + pair"

### JSON Schema — A Grammar in Disguise

When you write a JSON Schema:

```json
{
  "properties": {
    "mode": {"enum": ["dual", "ipv4", "ipv6"]}
  }
}
```

This is **also a grammar**. It describes the same thing as GBNF rules — just
in a different notation. The serving software converts it to grammar rules
internally.

### Different Notations, Same Concept

```
╔═══════════════════════════════════════════════════════════════════════╗
║ Notation     │ Used By           │ Example                           ║
╠══════════════╪═══════════════════╪═══════════════════════════════════╣
║ BNF          │ Academic papers   │ <digit> ::= "0" | "1" | "2"      ║
║ EBNF         │ Standards (ISO)   │ digit = "0" | "1" | "2" ;        ║
║ GBNF         │ llama.cpp         │ digit ::= [0-9]                   ║
║ Regex        │ Outlines/vLLM     │ [0-9]                             ║
║ JSON Schema  │ OpenAI/Anthropic  │ {"type":"integer"}                ║
║ PEG          │ Some parsers      │ digit <- [0-9]                    ║
║ ANTLR        │ Java parsers      │ digit : [0-9] ;                   ║
╚═══════════════════════════════════════════════════════════════════════╝

ALL of these describe the same thing: rules for what's valid.
ALL of them can be converted to a state machine.
The format doesn't matter — the concept is identical.
```

### Grammar Can Describe ANY Structured Output, Not Just JSON

```
# Grammar for SQL queries:
root ::= "SELECT " columns " FROM " table_name

# Grammar for Python function signatures:
root ::= "def " func_name "(" params "):"

# Grammar for XML tags:
root ::= "<" tag_name ">" content "</" tag_name ">"

# Grammar for CSV:
root ::= header "\n" rows
```

JSON is just the most common use case for LLMs.

---

## 6. From Grammar to State Machine — Where "State" Comes From

You might look at grammar rules and think: "These are just patterns. Where do
states come in?" The answer: **states emerge when you read input character by character.**

### Grammar Rules Have No State

```
digit    ::= '0' | '1' | '2' | '3'
operator ::= '+'
expr     ::= digit operator digit
```

These are just rules. No state here. But the moment you start **reading**
(or generating) characters one at a time, you need to track where you are.

### State = "Where Am I in the Rules Right Now?"

Reading the input `3+7`:

```
I have read NOTHING yet.
  Grammar says: expr starts with digit
  digit can be: '0','1','2','3'
  So valid next characters: {0, 1, 2, 3}

  ← THIS IS STATE 0: "expecting first digit"

I read '3'.
  '3' matches digit. First part of expr done.
  Grammar says: after digit comes operator
  operator can be: '+'
  So valid next characters: {+}

  ← THIS IS STATE 1: "got first digit, expecting operator"

I read '+'.
  '+' matches operator. Second part done.
  Grammar says: after operator comes digit
  So valid next characters: {0, 1, 2, 3}

  ← THIS IS STATE 2: "got operator, expecting second digit"

I read '7'.
  '7' matches digit. Expression complete.
  No more characters expected.

  ← THIS IS STATE 3: "DONE"
```

**The "state" is simply: "where am I in the grammar rules as I process characters?"**

```
╔═══════════════════════════════════════════════════════════════════════╗
║  💡 AHA MOMENT: State = "Where Am I Right Now?"                       ║
╠═══════════════════════════════════════════════════════════════════════╣
║                                                                        ║
║  Grammar rules themselves have NO state.                               ║
║  State EMERGES when you process characters one at a time.              ║
║                                                                        ║
║  It's just a bookmark:                                                 ║
║    "I've seen '3' and '+' so far.                                      ║
║     According to the grammar, I now need a digit."                     ║
║                                                                        ║
║  A state machine is just the grammar drawn as a flowchart:             ║
║                                                                        ║
║    Grammar rules (text)  ═══►  State machine (flowchart)               ║
║    Human-readable              Computer-executable                     ║
║    Same thing, different format.                                       ║
║                                                                        ║
╚═══════════════════════════════════════════════════════════════════════╝
```

### The State Machine Is Just a Diagram of All Possible Paths

Take the grammar and draw ALL possible paths through it:

```
Grammar: expr ::= digit '+' digit
         digit ::= '0' | '1' | '2' | '3'

State Machine:

   STATE 0              STATE 1            STATE 2             STATE 3
   "need digit"         "need +"           "need digit"        "DONE"

      ○ ────'0'────→ ○ ────'+'────→ ○ ────'0'────→ ◉
      │ ────'1'────→ │              │ ────'1'────→ ◉
      │ ────'2'────→ │              │ ────'2'────→ ◉
      │ ────'3'────→ │              │ ────'3'────→ ◉

   Any other character at ANY state → INVALID
```

**A state machine is just another way to REPRESENT the same grammar.**
One is for humans to read (text rules). One is for computers to execute fast (flowchart).

```
Grammar (text rules)  ═══ converts to ═══►  State Machine (flowchart)

Both describe EXACTLY the same thing.
```

### State Machine for JSON: `{"mode":"dual"}`

```
STATE 0 (Start):
  Valid: '{'
  Read '{' → go to STATE 1

STATE 1 (After {, expecting key):
  Valid: '"', whitespace
  Read '"' → go to STATE 2

STATE 2 (Inside key string):
  Valid: letters (building key name)
  Read 'm','o','d','e' → stay in STATE 2
  Read '"' → go to STATE 3 (key complete)

STATE 3 (After key, expecting colon):
  Valid: ':'
  Read ':' → go to STATE 4

STATE 4 (After colon, expecting value):
  Valid: '"' (start of string value)
  Read '"' → go to STATE 5

STATE 5 (Inside value string):
  Valid: letters from enum values
  Read 'd','u','a','l' → stay in STATE 5
  Read '"' → go to STATE 6 (value complete)

STATE 6 (After value, expecting comma or end):
  Valid: ',', '}'
  Read '}' → go to STATE 7

STATE 7: DONE ✅
```

**At every state, only certain characters are valid. That's the mask.**

---

## 7. The Tokenizer Problem — And How It's Solved

Here's where it gets tricky. The grammar works at the **character** level,
but the LLM generates **tokens**, which can be multi-character.

### The Problem

Different models split the same text into different tokens:

```
The word "model":

  Llama 3 tokenizer:    "model"           → 1 token  [ID: 2746]
  GPT-2 tokenizer:      "mod" + "el"      → 2 tokens [ID: 4666, 417]
  Some other tokenizer:  "m" + "odel"      → 2 tokens [ID: 76, 8234]
```

The grammar says "next valid characters are m-o-d-e-l" but the model doesn't
generate individual characters — it generates tokens like "mod" or "model".

### The Solution: Check Every Token Against the Grammar

The serving software has access to the tokenizer. For each token in the
vocabulary, it checks: "Would this token's characters be valid according to
the grammar's current state?"

```
Grammar state: expecting the string "model" (0 characters consumed so far)

Server scans ALL tokens in vocabulary:

  Token "m"       → matches "model"[0]       → ✅ ALLOW (1 char consumed)
  Token "mo"      → matches "model"[0:2]     → ✅ ALLOW (2 chars consumed)
  Token "mod"     → matches "model"[0:3]     → ✅ ALLOW (3 chars consumed)
  Token "mode"    → matches "model"[0:4]     → ✅ ALLOW (4 chars consumed)
  Token "model"   → matches "model"[0:5]     → ✅ ALLOW (all 5 chars consumed)
  Token "models"  → "model" matches but "s" extra → check if "s" valid next
                    → grammar says NO → ❌ BLOCK
  Token "a"       → doesn't match "m"        → ❌ BLOCK
  Token "the"     → doesn't match "m"        → ❌ BLOCK
  Token "hello"   → doesn't match "m"        → ❌ BLOCK
```

Then suppose the model picks "mod" (highest probability among allowed tokens):

```
Grammar advances: 3 characters consumed, expecting "el" next

Server scans ALL tokens again:

  Token "el"      → matches remaining "el"   → ✅ ALLOW (completes "model")
  Token "e"       → matches "el"[0]          → ✅ ALLOW (1 more char)
  Token "a"       → doesn't match "e"        → ❌ BLOCK
  Token "model"   → doesn't match "el"       → ❌ BLOCK
```

Model picks "el". Grammar advances: "model" complete, move to next rule.

### The Grammar Is Portable, the Token Mask Is Not

```
Same grammar + different tokenizer = different token masks = same final output

Grammar: "output must be 'hello'"

  Llama tokenizer:  allows tokens ["hello"]
  GPT-2 tokenizer:  allows tokens ["hel", "lo"] or ["hell", "o"] or ["hello"]
  
  Both produce the same output: "hello"
  But the MASK is different because the TOKENS are different.

The grammar describes CHARACTER patterns → universal.
The token mask depends on the TOKENIZER → model-specific.
The serving software bridges the two.
```

### Precomputation: Why This Doesn't Slow Down Generation

Scanning 50,000+ tokens against the grammar at every step would be slow.
So the serving software **precomputes** the masks:

```
STARTUP (one-time cost):
  For each possible grammar state:
    For each token in vocabulary:
      Would this token be valid here? → store YES/NO

  Result: a lookup table
    State 0 → [token_123, token_456, token_789, ...]  (allowed token IDs)
    State 1 → [token_234, token_567, ...]
    State 2 → [token_345, ...]
    ...

DURING GENERATION (per token, very fast):
  Current state = State 1
  Allowed tokens = lookup_table[State 1]  ← instant lookup, no scanning
  Apply mask
  Sample
```

This is why OpenAI can do grammar-constrained generation with minimal latency overhead.

---

## 8. The Compiler Connection — States Were Always There

If you've worked with compilers or parsers, you already know state machines —
you just didn't call them that.

### How a Compiler Reads `a = 1 + 2`

#### Phase 1: Lexer (Character → Tokens) — Uses States

```
Input: a = 1 + 2
       ↑
       Start

Char 'a':   State IDLE → letter found → State READING_NAME, buffer="a"
Char ' ':   State READING_NAME → space found → name complete!
            Emit token: NAME("a"), back to State IDLE
Char '=':   State IDLE → operator → Emit token: EQUALS
Char ' ':   State IDLE → skip whitespace
Char '1':   State IDLE → digit → State READING_NUMBER, buffer="1"
Char ' ':   State READING_NUMBER → number complete!
            Emit token: NUMBER(1), back to State IDLE
Char '+':   Emit token: PLUS
Char ' ':   skip
Char '2':   State READING_NUMBER → buffer="2" → end of input
            Emit token: NUMBER(2)

Result: [NAME("a"), EQUALS, NUMBER(1), PLUS, NUMBER(2)]
```

**The lexer tracked states: IDLE → READING_NAME → IDLE → READING_NUMBER → ...**

#### Phase 2: Parser (Tokens → Tree) — Also Uses States

```
Grammar: assignment ::= NAME '=' expression
         expression ::= NUMBER (('+' | '-') NUMBER)*

Token NAME("a"):    State EXPECT_STATEMENT → found NAME → State IN_ASSIGNMENT
Token EQUALS:       State IN_ASSIGNMENT → found '=' → State EXPECT_EXPRESSION
Token NUMBER(1):    State EXPECT_EXPRESSION → found NUMBER → State HAVE_TERM
Token PLUS:         State HAVE_TERM → found '+' → State EXPECT_NEXT_TERM
Token NUMBER(2):    State EXPECT_NEXT_TERM → found NUMBER → expression complete

Result: AST
  Assign
  ├── target: Name("a")
  └── value: BinOp
             ├── left: Number(1)
             ├── op: Add
             └── right: Number(2)
```

**The parser also tracked states: EXPECT_STATEMENT → IN_ASSIGNMENT → EXPECT_EXPRESSION → ...**

#### Why This Matters

States were always the mechanism for checking grammar — in compilers,
in JSON parsers, in regex engines, everywhere. The LLM grammar constraint
uses the **exact same concept**, just in the opposite direction:

```
╔═══════════════════════════════════════════════════════════════════════╗
║  💡 AHA MOMENT: Compiler vs LLM — Same Machine, Opposite Direction    ║
╠═══════════════════════════════════════════════════════════════════════╣
║                                                                        ║
║  Compiler:                                                             ║
║    Read EXISTING text → track state → "Is this valid?"                 ║
║    (validation — checking AFTER the fact)                              ║
║                                                                        ║
║  LLM with grammar:                                                     ║
║    GENERATE new text → track state → "Only allow valid tokens"         ║
║    (constrained generation — enforcing DURING the process)             ║
║                                                                        ║
║  Same state machine. Same grammar rules. Two different uses.           ║
║                                                                        ║
║  Compiler = Grammar police checking your driver's license              ║
║             "Let me see your document. Is it valid?"                   ║
║                                                                        ║
║  LLM + Grammar = Grammar police PRINTING the license                  ║
║             "I will only print characters that make a valid license."  ║
║                                                                        ║
╚═══════════════════════════════════════════════════════════════════════╝
```

---

## 9. Structured Output APIs — How Different Platforms Implement This

You don't need to write grammars or build state machines yourself.
Modern APIs handle the entire pipeline internally.

### What Happens When You Use OpenAI's Structured Output

```
You send:
  response_format = {
    "type": "json_schema",
    "json_schema": {
      "strict": true,
      "schema": your_json_schema
    }
  }

OpenAI's server does (internally, you never see this):

  1. Parse your JSON Schema
  2. Convert schema → grammar rules
  3. Build Finite State Machine from grammar
  4. Precompute token masks using GPT-4o's tokenizer
  5. During generation: for each token → look up mask → filter → sample

You get back: guaranteed-valid JSON matching your schema.
```

### How Different Platforms Handle It

```
╔═══════════════════════════════════════════════════════════════════════╗
║ Platform          │ What You Provide   │ What It Does Internally      ║
╠═══════════════════╪════════════════════╪══════════════════════════════╣
║ OpenAI API        │ JSON Schema        │ Schema → grammar → FSM      ║
║                   │ (response_format)  │ → precomputed token masks   ║
║                   │                    │ (proprietary, never visible) ║
║                   │                    │                              ║
║ Anthropic API     │ JSON Schema        │ Same concept, proprietary    ║
║                   │ (tool input_schema)│ implementation               ║
║                   │                    │                              ║
║ llama.cpp         │ GBNF grammar       │ Grammar → FSM → token masks ║
║ (local)           │ OR JSON Schema     │ (open source, you can read   ║
║                   │                    │  the code)                   ║
║                   │                    │                              ║
║ vLLM (local)      │ JSON Schema        │ Schema → regex → FSM        ║
║                   │ (guided_json)      │ (uses Outlines library)     ║
║                   │                    │                              ║
║ Ollama (local)    │ format: "json"     │ Basic JSON syntax only       ║
║                   │                    │ NOT schema-enforced          ║
╚═══════════════════════════════════════════════════════════════════════╝
```

### The Conversion Chain — All Roads Lead to FSM

Regardless of what you provide, the software converts it to the same thing:

```
JSON Schema  ──→  Parse schema
                  Extract structure, types, enums
                  Convert to grammar rules
                  Build FSM  ───────────────────────┐
                                                    │
GBNF Grammar ──→  Parse grammar rules               ├──→ Precompute token masks
                  Build FSM  ───────────────────────┤    using model's tokenizer
                                                    │
Regex        ──→  Parse regex                        │    ──→ Use masks during
                  Convert to FSM ───────────────────┘         generation
```

**All input formats end up as an FSM. The FSM is what actually runs during generation.**

### Strict Mode: The Guarantee

When you set `strict: True` (OpenAI) or use tool_choice (Anthropic),
the API **guarantees** schema compliance:

```
With strict: True:
  ✅ 100% valid JSON syntax      (impossible to generate broken JSON)
  ✅ 100% matches schema          (impossible to have wrong keys/types)
  ✅ All enums enforced            (impossible to use invalid enum values)
  ✅ Required fields present       (impossible to omit them)

This is NOT "99% reliable" or "best effort."
This is MATHEMATICALLY GUARANTEED by the constrained decoding algorithm.
Invalid tokens have probability = 0. They cannot be selected.
```

---

## 10. Where Everything Lives

A common misconception is that grammar is "part of the model" or requires
special model training. It doesn't.

```
╔═══════════════════════════════════════════════════════════════════════╗
║ Component              │ Where It Lives       │ Part of Model?        ║
╠════════════════════════╪══════════════════════╪═══════════════════════╣
║ Model weights          │ .gguf / .safetensors │ YES (frozen)          ║
║ Tokenizer              │ Shipped with model   │ YES                   ║
║ Temperature             │ Serving software     │ NO (post-processing) ║
║ Seed                    │ Serving software     │ NO (post-processing) ║
║ Grammar / Schema        │ Your API request     │ NO (external input)  ║
║ Grammar → FSM converter│ Serving software     │ NO (software feature)║
║ Token mask              │ Serving software     │ NO (computed per-run)║
║ Sampling logic          │ Serving software     │ NO (post-processing) ║
╚═══════════════════════════════════════════════════════════════════════╝

The model:   "I produce logits. That's all I do. I don't know about grammar."
The server:  "I take those logits, apply temperature, apply grammar mask,
              then sample. The model doesn't know I'm doing this."
```

Grammar masking works with **ANY** model that produces logits. You don't need
a special model. You don't need to retrain anything. The same Llama 3.1 8B model
works with or without grammar constraints — the constraint is applied externally.

---

## 11. Practical Implications — When to Use What

### The Decision Matrix

```
╔═══════════════════════════════════════════════════════════════════════╗
║ Approach                      │ When to Use                          ║
╠═══════════════════════════════╪══════════════════════════════════════╣
║ Structured Output API         │ You need guaranteed valid JSON/XML   ║
║ (response_format, tool_use)   │ You're using OpenAI/Anthropic/vLLM  ║
║                               │ You have a JSON Schema              ║
║                               │                                     ║
║ GBNF Grammar                  │ You're using llama.cpp directly     ║
║                               │ You need a format JSON Schema       ║
║                               │   can't describe                    ║
║                               │                                     ║
║ Detailed Prompt               │ Your API doesn't support structured ║
║ (no grammar constraint)       │   output                            ║
║                               │ You need flexibility beyond schema  ║
║                               │                                     ║
║ Template Engine               │ Input is already structured          ║
║ (no LLM at all)               │ Patterns are fully enumerable       ║
║                               │ You need 100% speed and zero cost   ║
╚═══════════════════════════════════════════════════════════════════════╝
```

### What You Should Actually Write (Minimal Code)

**If using OpenAI:**

```python
response = openai.chat.completions.create(
    model="gpt-4o",
    messages=[
        {"role": "system", "content": "Generate device config from precondition."},
        {"role": "user", "content": precondition_text}
    ],
    response_format={
        "type": "json_schema",
        "json_schema": {"strict": True, "schema": your_schema}
    }
)
data = json.loads(response.choices[0].message.content)
# Guaranteed valid. No validation code needed.
```

**If using Anthropic Claude:**

```python
response = anthropic.messages.create(
    model="claude-sonnet-4-20250514",
    messages=[{"role": "user", "content": precondition_text}],
    tools=[{
        "name": "generate_config",
        "description": "Generate device config",
        "input_schema": your_schema
    }],
    tool_choice={"type": "tool", "name": "generate_config"}
)
data = response.content[0].input  # Already a dict
```

**If using llama.cpp locally:**

```python
response = llm.create_chat_completion(
    messages=[{"role": "user", "content": precondition_text}],
    response_format={"type": "json_object", "schema": your_schema}
)
data = json.loads(response['choices'][0]['message']['content'])
```

**In all cases:** The schema does the structural enforcement. Your prompt only needs
to handle the *semantic* part (what values to fill in, what's relevant, etc.).

### What Goes in the Schema vs the Prompt

```
Schema Handles (Automatic Enforcement):
  ✅ Which keys exist
  ✅ Data types (string, number, boolean)
  ✅ Required vs optional fields
  ✅ Enum values (allowed options)
  ✅ Array constraints (min/max items)
  ✅ Nesting structure
  → The model CANNOT violate any of these

Prompt Handles (Semantic Understanding):
  ✅ "Include only relevant keys"
  ✅ "Infer 2 LAN clients from precondition"
  ✅ "Map 'dual mode' to eRouter_Provisioning_mode: 'dual'"
  ✅ "Minimal config — omit what's not needed"
  → The model uses its language understanding for these
```

---

## 12. Summary — The Complete Updated Mental Model

### Before This Document (What You Knew)

```
Prompt → Tokenize → Embedding → Transformer → Logits → Softmax(T) → Sample(seed) → Token
```

### After This Document (What You Know Now)

```
Prompt → Tokenize → Embedding → Transformer → Logits → Softmax(T) → Grammar Mask → Sample(seed) → Token
                                                                          ↑
                                                                    optional step
                                                                    not part of model
                                                                    applied by server
                                                                    works with ANY model

Where the grammar mask comes from:

  You provide: JSON Schema (or GBNF grammar, or regex)
       ↓
  Server converts to: Grammar rules (if not already in that format)
       ↓
  Server builds: Finite State Machine (FSM)
       ↓
  Server precomputes: Token masks per FSM state
                      (using the model's specific tokenizer)
       ↓
  During generation: At each token step, look up current FSM state
                     → get precomputed mask → filter probabilities
                     → only valid tokens survive → sample
       ↓
  Output: Guaranteed to match your schema/grammar
```

### Visual Summary — The Complete Picture

```
╔═══════════════════════════════════════════════════════════════════════╗
║                     THE COMPLETE PICTURE                               ║
╠═══════════════════════════════════════════════════════════════════════╣
║                                                                        ║
║  What YOU provide:         JSON Schema (portable, universal)           ║
║                                   │                                    ║
║                                   ▼                                    ║
║  Server converts to:       Grammar rules (GBNF, regex, etc.)          ║
║                                   │                                    ║
║                                   ▼                                    ║
║  Server builds:            Finite State Machine (FSM)                  ║
║                                   │                                    ║
║  Server combines with:     Tokenizer (model-specific)                  ║
║                                   │                                    ║
║                                   ▼                                    ║
║  Server precomputes:       Token masks per FSM state                   ║
║                            (which token IDs are valid at each state)   ║
║                                   │                                    ║
║                                   ▼                                    ║
║  During generation:        Model → logits → softmax → MASK → sample   ║
║                                                        ↑               ║
║                                               precomputed mask         ║
║                                               (instant lookup)         ║
║                                                                        ║
╠═══════════════════════════════════════════════════════════════════════╣
║                                                                        ║
║  KEY INSIGHT:                                                          ║
║  - Grammar is CHARACTER-level (works with any tokenizer)               ║
║  - Token mask is TOKEN-level (model-specific, precomputed)             ║
║  - Model has NO knowledge of any of this                               ║
║  - FSM is the universal internal representation                        ║
║  - JSON Schema is the universal INPUT format                           ║
║                                                                        ║
╚═══════════════════════════════════════════════════════════════════════╝
```

### Key Facts to Remember

```
1. Grammar is NOT inside the model. It's applied by the serving software.

2. Grammar is written in plain text (BNF/GBNF/JSON Schema).
   Different notations, same concept.

3. Grammar describes CHARACTER patterns. The serving software
   translates between characters and tokens using the tokenizer.

4. The same grammar works with any model. The token masks are
   model-specific (because tokenizers differ), but the grammar is universal.

5. State = "where am I in the rules right now?"
   States emerge when you process characters one at a time.
   Compilers use them. JSON parsers use them. LLM grammar masking uses them.
   Same concept everywhere.

6. State machines are just grammars drawn as flowcharts.
   Grammar rules (text) = State machine (diagram) = same thing, different format.

7. Structured output APIs (OpenAI, Anthropic, vLLM) handle the entire
   grammar → FSM → token mask pipeline for you.
   You just provide a JSON Schema. They do the rest.

8. When using structured output APIs, your prompt can be SHORT.
   The schema enforces structure. The prompt provides semantic guidance.
   You don't need 500-word instruction manuals about JSON formatting.
```

---

## Appendix: Terminology Quick Reference

| Term | What It Means |
|------|---------------|
| Grammar | Text rules describing valid patterns (like BNF rules) |
| GBNF | Grammar format used by llama.cpp (plain text file) |
| BNF | Backus-Naur Form — academic grammar notation from 1950s |
| FSM | Finite State Machine — grammar rules as a flowchart |
| State | "Where am I in the rules?" — tracks progress through grammar |
| Token mask | List of which token IDs are valid at current grammar state |
| Constrained decoding | Using grammar mask during generation to prevent invalid tokens |
| Structured output | API feature that uses constrained decoding with JSON Schema |
| Logits | Raw scores from the model (before softmax, before masking) |
| Serving software | The program that runs the model (llama.cpp, vLLM, OpenAI's servers) |
