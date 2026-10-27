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
