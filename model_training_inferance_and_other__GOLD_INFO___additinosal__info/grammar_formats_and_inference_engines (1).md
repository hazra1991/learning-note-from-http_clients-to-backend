# Grammar Beyond JSON — And Writing Your Own
## Can Grammar Constraints Be Used for Things Other Than JSON? Can You Write Your Own?

**Prerequisite:** You've read the main grammar-constrained decoding guide and understand
that grammar masking is applied by the **serving software**, not the model itself.

---

## Can Grammar Constraints Be Used Beyond JSON?

**YES, absolutely.** JSON is just the most common use case, but grammar-constrained
decoding works for ANY structured output.

### What's Actually Supported Today

```
╔═══════════════════════════════════════════════════════════════════════╗
║ Output Format        │ OpenAI  │ Anthropic │ llama.cpp │ vLLM        ║
╠══════════════════════╪═════════╪═══════════╪═══════════╪═════════════╣
║ JSON (via schema)    │ ✅ Yes  │ ✅ Yes    │ ✅ Yes    │ ✅ Yes      ║
║ Custom grammar       │ ❌ No   │ ❌ No     │ ✅ Yes    │ ✅ Yes      ║
║ Regex pattern        │ ❌ No   │ ❌ No     │ ❌ No     │ ✅ Yes      ║
╚═══════════════════════════════════════════════════════════════════════╝
```

**OpenAI and Anthropic:** Only accept JSON Schema. You cannot provide custom grammars.
Their APIs are locked down — they convert JSON Schema to grammar internally, but
they don't expose the grammar layer to you.

**llama.cpp:** Accepts GBNF grammar files directly. You can write grammar for
ANYTHING — SQL, Python, XML, CSV, whatever you can describe as rules.

**vLLM:** Accepts JSON Schema and raw regex patterns through the Outlines library.

---

## Can You Write Your Own Grammar?

**YES — but only on llama.cpp and vLLM.** Not on OpenAI or Anthropic.

### Why Only Some Engines?

Because the inference engine is just software. It has a **parser** — a piece of
code that reads a specific grammar format. If the engine doesn't have a parser
for your format, it can't use it.

```
llama.cpp source code includes:
  ├── grammar-parser.cpp    ← code that reads GBNF files
  └── sampling.cpp          ← code that applies the grammar mask

  It knows how to:
    1. Read GBNF syntax (::=, |, [], etc.)
    2. Convert GBNF rules → state machine
    3. Use state machine to mask tokens

  If you gave it raw JSON Schema instead of GBNF:
    "I don't know what this is."
    (Unless someone added a JSON Schema parser too — which they did later!)


OpenAI's server code (proprietary, you never see it) includes:
  ├── json_schema_parser    ← code that reads JSON Schema
  └── constrained_sampler   ← code that applies the grammar mask

  It knows how to:
    1. Read JSON Schema syntax (properties, enum, type, etc.)
    2. Convert JSON Schema → their internal grammar format
    3. Use that to mask tokens

  If you gave it GBNF:
    "I don't know what this is. I only accept JSON Schema."
```

This is no different from any other software:

```
Python interpreter:  understands .py,   not .java
Java compiler:       understands .java, not .py
Web browser:         understands HTML,  not Python
llama.cpp:           understands GBNF,  not OpenAI's format
OpenAI API:          understands JSON Schema, not GBNF
```

Each tool has parsers for the formats its developers chose to implement. That's all.

**If tomorrow someone adds a GBNF parser to OpenAI's server** → then OpenAI would
accept GBNF too. If someone adds a JSON Schema parser to llama.cpp → then llama.cpp
accepts JSON Schema too (which actually happened — newer versions DO accept JSON Schema
and convert it to GBNF internally).

---

## Writing Your Own Grammar — How It Actually Works

Grammar is written in **GBNF (GGML Backus-Naur Form)** for llama.cpp. It's a plain
text file with rules. Let me walk you through writing one from scratch.

### The Syntax — 5 Things to Know

```
1.  rule_name ::= pattern
    This defines a rule. "rule_name is defined as pattern."

2.  "exact text"
    Matches this exact text. "hello" matches only the word hello.

3.  rule_a | rule_b
    OR. Matches rule_a or rule_b.

4.  [a-zA-Z0-9]
    Character class. Any single character from this set.

5.  pattern*    zero or more repetitions
    pattern+    one or more repetitions
    pattern?    zero or one (optional)
```

That's it. Five things. Everything else is built from these.

### Example 1: Math Expression Grammar (Simplest Possible)

**Goal:** Force the model to output only things like `3+7`, `1+9`, `0+5`

```
# math.gbnf

digit    ::= [0-9]
operator ::= "+"
root     ::= digit operator digit
```

**How to read this:**
- `digit` is any character from 0 to 9
- `operator` is the literal character `+`
- `root` is: one digit, then one operator, then one digit
- `root` is special — it's where generation starts (the entry point)

**Valid outputs:** `0+0`, `3+7`, `9+1`
**Invalid outputs:** `3+`, `hello`, `33+7` (two digits not allowed for first number)

**Let's make it better — allow multi-digit numbers:**

```
# math_v2.gbnf

number   ::= [0-9]+
operator ::= "+" | "-" | "*" | "/"
root     ::= number " " operator " " number
```

Now `+` means "one or more" digits, and we allow `+`, `-`, `*`, `/`.

**Valid outputs:** `42 + 7`, `100 / 3`, `999 * 0`

### Example 2: SQL Query Grammar

**Goal:** Force the model to output only valid SELECT queries.

```
# sql.gbnf

root        ::= "SELECT " columns " FROM " table where_clause ";"

columns     ::= column ("," " " column)*

column      ::= [a-zA-Z_]+

table       ::= [a-zA-Z_]+

where_clause ::= "" | " WHERE " condition

condition   ::= column " " comparator " " value

comparator  ::= "=" | ">" | "<" | ">=" | "<="

value       ::= "'" [a-zA-Z0-9_ ]+ "'" | [0-9]+
```

**How to read the tricky parts:**
- `("," " " column)*` means: zero or more repetitions of (comma, space, column name).
  So `name` is valid, `name, age` is valid, `name, age, email` is valid.
- `"" | " WHERE " condition` means: either nothing OR " WHERE " followed by a condition.
- `"'" [a-zA-Z0-9_ ]+ "'"` means: a single-quoted string.

**Valid outputs:**
```sql
SELECT name FROM users;
SELECT name, age FROM users WHERE age > 25;
SELECT email, name FROM customers WHERE country = 'US';
```

**Invalid outputs (blocked by grammar):**
```sql
DROP TABLE users;              ← grammar doesn't have DROP rule
SELECT * FROM users;           ← grammar doesn't allow *, only column names
SELECT name FROM users WHERE;  ← grammar requires condition after WHERE
```

### Example 3: Python Function Signature Grammar

**Goal:** Force the model to output only valid Python function definitions.

```
# python_func.gbnf

root        ::= "def " func_name "(" params ")" return_hint ":\n"

func_name   ::= [a-z_]+

params      ::= "" | param (", " param)*

param       ::= [a-z_]+ ": " type_hint

type_hint   ::= "str" | "int" | "float" | "bool" | "list" | "dict" | "None"

return_hint ::= "" | " -> " type_hint
```

**Valid outputs:**
```python
def calculate_total(price: float, quantity: int) -> float:
def process_data(input: list, verbose: bool) -> dict:
def reset():
```

### Example 4: YAML-Like Config Grammar

```
# config.gbnf

ws      ::= [ \t]*
newline ::= "\n"

root    ::= pair (newline pair)*

pair    ::= key ":" ws value

key     ::= [a-zA-Z_]+

value   ::= [a-zA-Z0-9_./ -]+
```

**Valid outputs:**
```yaml
mode: dual
country: US
firmware: v2.3.1
path: /opt/config/main
```

### Example 5: Your Device Config as Custom Grammar (Instead of JSON)

```
# device_config.gbnf

root    ::= "[device]\n" model_line mode_line optional_lines

model_line ::= "model = " [A-Z0-9_]+ "\n"

mode_line  ::= "mode = " mode_value "\n"

mode_value ::= "dual" | "ipv4" | "ipv6" | "disabled"

optional_lines ::= (sku_line | country_line | lan_line)*

sku_line     ::= "sku = " ("abc" | "efg") "\n"

country_line ::= "country = " [A-Z][A-Z] "\n"

lan_line     ::= "lan_clients = " [0-9] "\n"
```

**Valid output:**
```ini
[device]
model = DEMO_X1
mode = dual
sku = abc
country = US
lan_clients = 2
```

You could then parse this INI-like format in your code — no JSON needed.

---

## The Internal Conversion — All Roads Lead to FSM

Regardless of what format you provide, every engine converts it to the same thing
internally:

```
OpenAI:
  JSON Schema → (proprietary parser) → FSM → token masks

Anthropic:
  JSON Schema → (proprietary parser) → FSM → token masks

llama.cpp:
  GBNF grammar → (GBNF parser) → FSM → token masks
  JSON Schema  → (JSON Schema parser) → GBNF → FSM → token masks

vLLM + Outlines:
  JSON Schema → (Outlines) → regex → FSM → token masks
  Regex       → (Outlines) → FSM → token masks

ALL ROADS LEAD TO FSM.
The input format is just the front door. The engine inside is the same.
```

---

## Why OpenAI/Anthropic Don't Expose Custom Grammar

Honest assessment:

**Practical:** JSON Schema covers 99% of what users need. Most people want
structured JSON output, not custom SQL grammars.

**Safety:** Custom grammars could potentially be used to probe model behavior
in ways that haven't been fully analyzed.

**Simplicity:** One input format = simpler API, easier documentation, fewer
support tickets about broken grammars.

---

## What If You Need Non-JSON Output on OpenAI/Anthropic?

**Workaround: Generate JSON, then convert in your code.**

```
Want SQL?
  LLM → JSON Schema → {"table": "users", "columns": ["name"], "where": "age > 25"}
  Your code converts → SELECT name FROM users WHERE age > 25;

Want YAML?
  LLM → JSON Schema → {"mode": "dual", "country": "US"}
  Your code converts → yaml.dump(json_output)

Want XML?
  LLM → JSON Schema → {"tag": "config", "value": "..."}
  Your code converts → <config>...</config>

Want custom format?
  LLM → JSON Schema → structured dict
  Your code converts → whatever format you need
```

Less elegant than a direct grammar, but works on every platform.

---

## What About Code Generation? Do Coding Models Use Grammar Masking?

**Honest answer: NO. They are NOT using grammar masking for code generation.**

When Claude Code, GPT-4, Copilot, or any coding model generates Python/JavaScript/etc.,
they're doing **plain text generation with no grammar constraints**.

```
Code generation today:

  Prompt → Transformer → Logits → Softmax(T) → Sample → Token

  No grammar mask. No FSM. No constrained decoding.
  The model just generates text and HOPES it's valid code.
```

**That's why LLMs sometimes generate code with syntax errors.** There's no grammar
enforcing valid Python/Java/SQL. The model relies entirely on patterns learned
during training.

### Why Not? It Seems Obvious to Use Grammar for Code

You'd think: "Python has a grammar. Just use it to constrain generation." But it's
not that simple.

**Reason 1: Programming Language Grammars Are MASSIVE**

```
Your JSON Schema grammar:     ~20 rules, ~50 states in FSM
Python's full grammar:        ~200 rules, thousands of states in FSM
JavaScript's grammar:         ~300 rules
C++ grammar:                  ~500+ rules, extremely complex
```

The FSM for a full programming language would have **tens of thousands of states**.
Precomputing token masks for every state × every token in vocabulary becomes
extremely expensive.

```
JSON FSM:     ~50 states × 128,000 tokens = ~6 million checks     (fast)
Python FSM:   ~10,000 states × 128,000 tokens = ~1.3 billion checks (slow)
```

**Reason 2: Code Requires SEMANTIC Validity, Not Just Syntax**

Valid Python syntax:
```python
def foo(x: int) -> str:
    return x + "hello"
```

This is **syntactically perfect** — a grammar would allow it. But it's
**semantically broken** — you can't add an int and a string. Grammar can't
catch this because:

- Grammar doesn't know `x` is an `int`
- Grammar doesn't know `+` between `int` and `str` is invalid
- Grammar doesn't track variable types across lines

**Most real code bugs are semantic, not syntactic.**

**Reason 3: Code Is Context-Dependent in Ways Grammar Can't Express**

```python
# Line 1: define a variable
my_list = [1, 2, 3]

# Line 50: use that variable
result = my_list.append(4)
```

A grammar would need to "remember" that `my_list` was defined on line 1 to know
it's valid on line 50. But grammars (and FSMs) are **memoryless** — they only know
the current state, not the history of all variable definitions.

```
Grammar (context-free):   "Is this line syntactically valid on its own?"
Type checker (context):   "Given everything defined above, is this line valid?"

Grammar can check:   def foo(x):        ← valid syntax
Grammar can't check: foo(1, 2, 3)       ← is foo defined? does it take 3 args?
```

**Reason 4: LLMs Are Already Very Good at Code Syntax**

```
Error types in LLM-generated code:

  Syntax errors:     ~2%    (missing bracket, wrong indentation)
  Logic errors:      ~30%   (wrong algorithm, off-by-one, wrong condition)
  API misuse:        ~20%   (wrong function name, wrong arguments)
  Type errors:       ~15%   (passing string where int expected)
  Missing imports:   ~10%   (forgot to import a library)

Grammar masking would only fix the 2% syntax errors.
The other 98% of errors are beyond what grammar can catch.
```

The cost-benefit doesn't justify it.

**Reason 5: Code Generation Needs Flexibility**

When writing code, the model needs to:
- Invent variable names (grammar can't predict these)
- Choose between many valid approaches
- Write comments (free-form text mixed with code)
- Use libraries the grammar doesn't know about

A strict grammar would **over-constrain** the model.

### What Code-Generating Tools Actually Do Instead

**Generate and validate** — this is what Claude Code, Copilot, and every coding
assistant does:

```
LLM generates code (no grammar)
    ↓
Run linter / type checker on output
    ↓
If errors found → send errors back to LLM → "fix this"
    ↓
Repeat until valid or give up
```

### Could Grammar Masking Be Used for Code in the Future?

**Maybe for LIMITED cases:**

```
Possible future uses:
  ✅ Force valid JSON/YAML/TOML config files    (already done)
  ✅ Force valid SQL queries                      (llama.cpp can do this now)
  ✅ Force valid regex patterns                   (small grammar, feasible)
  ✅ Force valid function signatures              (limited scope, feasible)

  ❌ Force valid entire Python programs           (too complex, too expensive)
  ❌ Force semantically correct code              (grammar can't do this)
  ❌ Force logically correct algorithms           (grammar can't do this)
```

There's active research — projects like **Synchromesh** and **PICARD** (for SQL
generation) use grammar constraints for specific code formats. But full programming
language grammar masking during generation is not practical today.

---

## Summary

```
Grammar masking CONCEPT:     Universal, works for any structured output
Grammar FORMAT accepted:     Depends on which inference engine you use

For JSON output:     Any platform works (OpenAI, Anthropic, llama.cpp, vLLM)
For custom formats:  llama.cpp (write GBNF) or vLLM (write regex)
For OpenAI/Anthropic: JSON Schema only — convert in your code for other formats
For code generation: NOT used — generate freely, validate after with linter

Writing GBNF grammar:
  - Plain text file with rules
  - 5 syntax elements: ::= (define), "" (literal), | (or), [] (char class), */+/? (repeat)
  - "root" rule is the entry point
  - Save as .gbnf file, pass to llama.cpp
  - Works with ANY model — grammar masking is model-independent

Why grammar isn't used for code:
  - Programming language grammars are too large (thousands of FSM states)
  - Most code bugs are semantic, not syntactic (grammar can't help)
  - Code is context-dependent (grammar is context-free)
  - LLMs rarely make syntax errors anyway (~2%)
  - Code tools use generate → lint → fix loop instead

The inference engine is just software with parsers for specific formats.
llama.cpp has a GBNF parser. OpenAI has a JSON Schema parser. Same concept,
different front doors. All convert to FSM internally.
```
