# Grammar vs Schema — Syntax vs Structure
## Does Grammar Validate Structure, or Just Syntax?

**Prerequisite:** You understand what grammar and state machines are from the main guide.

---

## The Question

Take this YAML grammar:

```
ws       ::= [ \t]*
newline  ::= "\n"
string   ::= [a-zA-Z0-9_ ]+
indent   ::= "    "

root     ::= pair (newline pair)*

pair     ::= key ":" ws value
           | key ":" newline indented_pairs

key      ::= [a-zA-Z_]+
value    ::= string

indented_pairs ::= indent pair (newline indent pair)*
```

This grammar says: "A pair is a key, colon, value. Optionally indented pairs under it."

**Valid output A (correct):**
```yaml
board:
    mode: dual
    name: some name
```

**Valid output B (also passes grammar, but WRONG structure):**
```yaml
board:
    mode: dual
name: some name
```

Both are syntactically valid YAML. Both match the grammar. But they mean
completely different things:

```
Output A:
  board:
    mode: dual       ← mode is INSIDE board
    name: some name  ← name is INSIDE board

Output B:
  board:
    mode: dual       ← mode is INSIDE board
  name: some name    ← name is at ROOT level, NOT inside board
```

**Does the grammar catch this?**

**NO. It doesn't.**

---

## Why Grammar Can't Catch This

Grammar only checks **syntax** (is the text well-formed?) not **semantics**
(does it mean the right thing?).

```
Grammar checks:                          Schema checks:
  ✅ "Is there a colon after the key?"     ✅ "Is 'mode' inside 'board'?"
  ✅ "Are indents using spaces?"           ✅ "Is 'mode' one of [dual, ipv4]?"
  ✅ "Is the value a valid string?"        ✅ "Is 'name' required or optional?"
  ✅ "Is the structure well-formed?"       ✅ "Are there unexpected keys?"

  ❌ "Is 'name' inside 'board'?"           Grammar can't do this
  ❌ "Is 'mode' a valid enum value?"       Grammar CAN do this (with effort)
  ❌ "Is 'board' required?"                Grammar CAN do this (with effort)
```

---

## The Three Levels of Validation

```
Level 1: SYNTAX (Grammar handles this)
  "Is the text well-formed?"

  ✅  board:\n    mode: dual
  ❌  board  mode :: dual         ← broken syntax


Level 2: STRUCTURE (Grammar can PARTIALLY handle this)
  "Are the right keys in the right places?"

  ✅  board:\n    mode: dual      ← mode inside board
  ❌  board:\n  mode: dual        ← wrong indent (2 spaces vs 4)

  Grammar CAN enforce this IF you write very specific rules
  (see below)


Level 3: SEMANTICS (Grammar CANNOT handle this)
  "Do the values make sense together?"

  ❌  "If mode is ipv4, then ipv4_address is required"
  ❌  "lan_clients array must have exactly 2 elements"
  ❌  "country must be a valid ISO country code"

  This requires a schema validator (JSON Schema, Pydantic, etc.)
```

---

## Can You Write a Grammar That Enforces Structure?

**Yes, but it gets ugly fast.** You'd have to hardcode the exact structure:

```
# This grammar FORCES "name" to be inside "board"

root  ::= "board:" newline board_body

board_body ::= indent "mode: " mode_value newline indent "name: " string

mode_value ::= "dual" | "ipv4" | "ipv6"

string  ::= [a-zA-Z0-9_ ]+
indent  ::= "    "
newline ::= "\n"
```

Now `name` at root level is **impossible** — the grammar only allows it after
an indent inside `board_body`.

**But look what happened:** You basically hardcoded your entire schema into the
grammar. Every key, every nesting level, every allowed value — all written out
explicitly in grammar rules.

**This is exactly what JSON Schema does, just in a different format:**

```json
{
  "properties": {
    "board": {
      "properties": {
        "mode": {"enum": ["dual", "ipv4", "ipv6"]},
        "name": {"type": "string"}
      }
    }
  }
}
```

**Same constraints. Different notation.**

---

## So Does Grammar Get Converted to Schema?

**No. It's the other way around.**

```
JSON Schema → converted to → Grammar → converted to → FSM

Grammar does NOT get converted to JSON Schema.
JSON Schema gets converted to grammar.
```

**Why this direction?**

JSON Schema is **higher level** — it describes structure and constraints declaratively.
Grammar is **lower level** — it describes character-by-character patterns.
FSM is **lowest level** — it's the actual machine that runs during generation.

```
High level:    JSON Schema    "mode must be one of [dual, ipv4, ipv6]"
                    ↓
Mid level:     Grammar        mode_value ::= "dual" | "ipv4" | "ipv6"
                    ↓
Low level:     FSM            State 5: allow 'd' or 'i', block everything else
```

You CAN write grammar directly (skipping JSON Schema), but then YOU are doing
the work that the JSON Schema → Grammar converter does automatically.

---

## The Honest Comparison

```
╔═══════════════════════════════════════════════════════════════════════╗
║                    Grammar vs Schema                                   ║
╠═══════════════════════════════════════════════════════════════════════╣
║                        │ Grammar (GBNF)    │ Schema (JSON Schema)    ║
╠════════════════════════╪═══════════════════╪═════════════════════════╣
║ Checks syntax          │ ✅ Yes            │ ✅ Yes                  ║
║ Checks structure       │ ⚠️  Only if you   │ ✅ Yes (automatic)      ║
║                        │    hardcode it     │                         ║
║ Checks value types     │ ⚠️  Manually      │ ✅ Yes (automatic)      ║
║ Checks enums           │ ⚠️  Manually      │ ✅ Yes (automatic)      ║
║ Checks conditionals    │ ❌ Very hard      │ ✅ Yes (if/then/else)   ║
║ Works for non-JSON     │ ✅ Yes            │ ❌ No (JSON only)       ║
║ Easy to write          │ ⚠️  Gets complex  │ ✅ Declarative          ║
║ Maintenance            │ ⚠️  Fragile       │ ✅ Structured           ║
╚═══════════════════════════════════════════════════════════════════════╝
```

---

## Real-World Example: Why Code Generation Doesn't Use Grammar

This is the best example of grammar's limitations. You'd think: "Python has a
grammar. Just use it to constrain code generation. Problem solved."

**Honest answer: NO coding tool does this today.** Claude Code, GPT-4, Copilot —
they all generate code with **no grammar constraints at all**.

```
Code generation today:

  Prompt → Transformer → Logits → Softmax(T) → Sample → Token

  No grammar mask. No FSM. No constrained decoding.
  The model just generates text and HOPES it's valid code.
```

**That's why LLMs sometimes generate code with syntax errors.** So why not fix it
with grammar masking?

### Reason 1: Programming Language Grammars Are MASSIVE

```
JSON Schema grammar:     ~20 rules, ~50 states in FSM
Python's full grammar:   ~200 rules, thousands of states in FSM
JavaScript's grammar:    ~300 rules
C++ grammar:             ~500+ rules, extremely complex
```

Precomputing token masks becomes extremely expensive:

```
JSON FSM:     ~50 states × 128,000 tokens = ~6 million checks     (fast)
Python FSM:   ~10,000 states × 128,000 tokens = ~1.3 billion checks (slow)
```

### Reason 2: Code Bugs Are Semantic, Not Syntactic

Valid Python syntax:
```python
def foo(x: int) -> str:
    return x + "hello"
```

**Syntactically perfect** — a grammar would allow it. **Semantically broken** —
you can't add an int and a string. Grammar can't catch this because grammar doesn't
track types, variable definitions, or function signatures across lines.

```
Error types in LLM-generated code:

  Syntax errors:     ~2%    (missing bracket, wrong indentation)
  Logic errors:      ~30%   (wrong algorithm, off-by-one)
  API misuse:        ~20%   (wrong function name, wrong arguments)
  Type errors:       ~15%   (passing string where int expected)
  Missing imports:   ~10%   (forgot to import a library)

Grammar masking would only fix the 2% syntax errors.
The other 98% are beyond what grammar can catch.
```

### Reason 3: Code Is Context-Dependent (Grammar Is Context-Free)

```python
# Line 1: define a variable
my_list = [1, 2, 3]

# Line 50: use that variable
result = my_list.append(4)
```

A grammar would need to "remember" that `my_list` was defined on line 1 to know
it's valid on line 50. But grammars and FSMs are **memoryless** — they only know
the current state, not the history of all variable definitions.

```
Grammar (context-free):   "Is this line syntactically valid on its own?"
Type checker (context):   "Given everything defined above, is this line valid?"

Grammar can check:   def foo(x):        ← valid syntax
Grammar can't check: foo(1, 2, 3)       ← is foo defined? does it take 3 args?
```

### Reason 4: Code Needs Flexibility

The model needs to invent variable names, choose between many valid approaches,
write comments (free-form text mixed with code), and use libraries the grammar
doesn't know about. A strict grammar would **over-constrain** the model.

### What Code Tools Actually Do Instead

**Generate and validate** — this is what every coding assistant does:

```
LLM generates code (no grammar constraints)
    ↓
Run linter / type checker on output
    ↓
If errors found → send errors back to LLM → "fix this"
    ↓
Repeat until valid or give up
```

### Could Grammar Work for Code in the Future?

**For limited, small-scope cases — yes:**

```
  ✅ Force valid SQL queries           (llama.cpp can do this now)
  ✅ Force valid regex patterns         (small grammar, feasible)
  ✅ Force valid function signatures    (limited scope, feasible)
  ✅ Force valid config files           (already done with JSON Schema)

  ❌ Force valid entire Python programs (too complex, too expensive)
  ❌ Force semantically correct code    (grammar fundamentally can't do this)
  ❌ Force logically correct algorithms (grammar fundamentally can't do this)
```

**This is the clearest example of the grammar vs schema distinction:**
Grammar handles syntax. Semantic correctness requires something more.

---

## Bottom Line

**Grammar = syntax checker.** It knows "is this text well-formed?" but not
"does this text mean the right thing?"

**Schema = syntax + structure + constraints.** It knows "is this text well-formed
AND does it have the right keys in the right places with the right values?"

**For JSON output:** Use JSON Schema. It gets converted to grammar automatically,
giving you both syntax AND structure enforcement for free.

**For non-JSON output:** You CAN write grammar, but you have to manually encode
all the structural constraints yourself — which is basically reinventing JSON Schema
in grammar notation. At that point, it's often easier to just generate JSON and
convert to your target format in code.

**For code generation:** Grammar masking isn't used because most code bugs are
semantic (grammar can't help), programming language grammars are too large,
and code is context-dependent. Coding tools use a generate → lint → fix loop instead.
