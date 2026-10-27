# Finite State Machines — A Reference That Actually Makes Sense

---

## The one-line version

An FSM is a system that knows **where it is**, knows **what moves are legal from there**, and **refuses everything else**. That's it. The power is entirely in the refusal.

---

## Pipeline vs FSM — nail this first

This distinction is the most important thing in this document. Get it wrong and you'll reach for the wrong tool every time.

### A pipeline is a conveyor belt

The sequence is fixed. Always forward. Failure means retry-in-place or bail — it never redirects control to a different step.

```
  ┌─────────┐     ┌─────────┐     ┌─────────┐     ┌─────────┐     ┌─────────┐
  │ Step 1A │ ──▶ │ Step 1B │ ──▶ │ Step 4  │ ──▶ │ Step 5  │ ──▶ │ Step 6  │
  └─────────┘     └─────────┘     └─────────┘     └─────────┘     └─────────┘
                                                        │
                                                   fails? Step 6
                                                   fixes it locally.
                                                   Still fails? Output
                                                   with TODOs. Done.
                                                   Never goes back to 1B.
```

> "Wait — but what if Step 5 produces bad output and I need more research?" 
> That's a pipeline *with a retry loop inside Step 5*. Control never leaves Step 5 — it loops internally then either succeeds or gives up. The sequence 1A→1B→4→5→6 never changes. That's still a pipeline.

### An FSM is a system where outcome decides destination

The machine sits in a state. An event arrives. Based on *which state it's in right now*, it decides where to go — and that can be anywhere. Back, sideways, to a terminal, to an earlier state. The sequence is not fixed.

```
                        event("blocked")
  ┌──────────────┐ ◀────────────────────── ┌──────────────┐
  │     IDLE     │                          │ RESEARCHING  │
  └──────────────┘                          └──────────────┘
         │                                         ▲
         │ event("start")                          │ event("retry")
         ▼                                         │
  ┌──────────────┐    event("tests_fail")   ┌──────────────┐
  │   BUILDING   │ ──────────────────────▶  │    FAILED    │
  └──────────────┘                          └──────────────┘
         │
         │ event("build_done")
         ▼
  ┌──────────────┐
  │   TESTING    │ ── event("cancel") ──▶  ILLEGAL ✗
  └──────────────┘                         machine refuses this cold.
                                           TESTING has no "cancel" transition.
```

Every arrow above is a different kind of move:

```
  [RESEARCHING] + event("blocked")    → [IDLE]          ← went BACKWARDS
  [BUILDING]    + event("tests_fail") → [FAILED]        ← jumped SIDEWAYS
  [FAILED]      + event("retry")      → [RESEARCHING]   ← jumped to EARLIER state
  [TESTING]     + event("cancel")     → ILLEGAL ✗       ← machine REFUSES this
```

> "So the FSM doesn't just move forward — it can go anywhere the table allows?"
> Exactly. And it can go *nowhere* if the table doesn't allow it. That refusal is what makes it powerful.

**The test:** does the *outcome* of a step change *which step runs next* — not just whether to retry, but where control actually goes? Yes → FSM. Sequence always the same, failure just retries in place → pipeline.

---

## What an FSM is made of

Four things. Only four. Everything else is built on top of these.

```
  ┌───────────────────────────────────────────────────────────────────┐
  │                                                                   │
  │   STATES      Where the machine can be. Always exactly one.       │
  │               "IDLE", "PAID", "FAILED" — these are your states.  │
  │                                                                   │
  │   EVENTS      Signals that arrive and ask the machine to move.    │
  │               "pay", "ship", "cancel", "retry" — these are        │
  │               events. They don't move anything on their own.      │
  │               The machine decides if it will act on them.         │
  │                                                                   │
  │   TRANSITIONS The legal (state + event) → next-state table.      │
  │               This table IS the machine. Everything is here.      │
  │                                                                   │
  │   CONTEXT     Data riding shotgun through all states.             │
  │               order_id, payment_id, tracking_id — lives here.    │
  │                                                                   │
  └───────────────────────────────────────────────────────────────────┘
```

The core is just a table lookup. That's genuinely all it is:

```python
TRANSITIONS = {
    "PENDING":   { "pay":     "PAID",      "cancel": "CANCELLED" },
    "PAID":      { "ship":    "SHIPPED",   "refund": "REFUNDING" },
    "SHIPPED":   { "deliver": "DELIVERED", "return": "RETURNING" },
    "DELIVERED": { "refund":  "REFUNDING"                        },
    "CANCELLED": {},    # terminal — nothing leaves here
    "REFUNDING": {},    # terminal
}
```

> "Wait, that's just a dictionary. Where's the machine?"
> That dictionary *is* the machine. You look up current state → look up event → get next state. If it's not in the table, it's illegal. The machine is the constraint, not the code.

When `"pay"` arrives and the machine is in `"PENDING"`:
```
  TRANSITIONS["PENDING"]["pay"]  →  "PAID"   ✓  move happens
  TRANSITIONS["PAID"]["pay"]     →  KeyError  ✗  illegal, raise
  TRANSITIONS["CANCELLED"]["pay"] → KeyError  ✗  illegal, raise
```

Same event. Three different states. Three different outcomes. That's the whole idea.

---

## The self-loop — one state, many exits

A state doesn't have to move forward. It can have many transitions out — including one back to itself.

> "So a state can just... stay where it is?"
> Yes. A self-loop is a transition where next-state == current-state. The machine moves, processes the event, and lands right back where it started.

Take a string lexer reading `"hello\"world"` character by character. The state `IN_STRING` has four possible exits depending on what arrives:

```
                          any regular char
                       ┌─────────────────────┐
                       │                     │  (self-loop — keep collecting)
                       ▼                     │
  ┌───────┐  "   ┌───────────┐  \   ┌────────┴──┐
  │ START │ ───▶ │ IN_STRING │ ───▶ │  ESCAPE   │
  └───────┘      └───────────┘      └───────────┘
                       │                 │
                       │  "              │ any char (goes back)
                       ▼                 └──────────────▶ IN_STRING
                  ┌────────┐
                  │  DONE  │
                  └────────┘
                       
                  (newline → ERROR, dead state, no way out)
```

Same state `IN_STRING`. Four completely different outcomes:

```
  char   classify    state before   state after    what happened
  ──────────────────────────────────────────────────────────────
  "      QUOTE       START          IN_STRING      entered string
  h      CHAR        IN_STRING      IN_STRING      ← self-loop
  e      CHAR        IN_STRING      IN_STRING      ← self-loop
  l      CHAR        IN_STRING      IN_STRING      ← self-loop
  \      BACKSLASH   IN_STRING      ESCAPE         jumped out temporarily
  "      QUOTE       ESCAPE         IN_STRING      jumped back, quote is literal now
  w      CHAR        IN_STRING      IN_STRING      ← self-loop resumes
  "      QUOTE       IN_STRING      DONE           terminal ✓
```

> "The ESCAPE state only exists for one character and then disappears back. What's the point of making it a state?"
> That's the insight. Being in `ESCAPE` *is* the information that "the next character is literal." You don't need a boolean flag `is_escaping = True`. The state carries that memory for free. State IS memory.

The machine has zero memory of *what* characters it collected — only *where it is* right now. `IN_STRING` doesn't know about `h`, `e`, `l`, `l`, `o`. It just knows it's inside a string. That's the FSM's fundamental limit — and its fundamental efficiency.

---

## Guards — the table says yes, but should it?

The table tells you if a transition *exists*. A guard tells you if it should *fire right now*.

> "So what's the difference between an illegal event and a blocked guard?"
> Illegal event: the transition doesn't exist in the table at all. Ship from CANCELLED → KeyError.
> Blocked guard: the transition exists, but a runtime condition says not yet. Ship from PAID when inventory=0 → guard blocks it. Machine stays in PAID.

```
  Event "ship" arrives. Machine is in PAID.

  Step 1 — table lookup:
  ┌──────────────────────────────────────────┐
  │ TRANSITIONS["PAID"]["ship"] → exists ✓   │
  └──────────────────────────────────────────┘
                    │
                    ▼
  Step 2 — guard check:
  ┌──────────────────────────────────────────┐
  │ guard: inventory > 0 ?                   │
  │                                          │
  │   inventory = 3  →  True  →  MOVE ✓     │
  │   inventory = 0  →  False →  STAY ✗     │
  └──────────────────────────────────────────┘
```

```python
TRANSITIONS = {
    "PAID": {
        "ship": Transition(
            target  = "SHIPPED",
            guard   = lambda ctx: ctx["inventory"] > 0   # blocked if out of stock
        ),
        "refund": Transition(target="REFUNDING"),
    },
    "DELIVERED": {
        "refund": Transition(
            target  = "REFUNDING",
            guard   = lambda ctx: days_since(ctx["delivered_at"]) <= 30  # return window
        ),
    },
}
```

The guard reads context. The table is static. Guards are runtime. That's the separation.

---

## Side effects — what happens on entry and exit

States can carry behavior, not just identity. When you enter a state, something runs. When you leave, something runs. This is where FSMs connect to the real world.

```python
State("PAID",
    on_enter = lambda ctx: [
        warehouse.queue_pick(ctx["order_id"]),       # tell warehouse to pick items
        email.send(ctx["user"], "payment_confirmed") # notify user
    ],
    on_exit = lambda ctx: audit_log.write(ctx)       # log when leaving
)
```

The machine entering `PAID` *causes things to happen*. You don't call `warehouse.queue_pick` from outside — the machine does it because it entered a state. Your application code just sends the event. The machine handles what that means.

---

## Context — the data riding shotgun

State tells you *where* the machine is. Context tells you *what it knows* while it's there.

```
  State: SHIPPED
  Context: {
    order_id:    "ORD-9921",
    tracking_id: "UPS-4421-XZ",
    shipped_at:  "2024-01-15T09:00:00Z",
    user_email:  "user@example.com"
  }
```

Context accumulates as events fire. The `pay` event adds `payment_id` to context. The `ship` event adds `tracking_id`. Guards read context. Side effects read context. The machine itself only cares about state — but everything built on top of it reads context.

---

## Where FSMs actually live (not just UI)

FSMs predate the web by decades. UI is the most visible use case, not the most important one.

**TCP — your OS runs this for every network socket**
```
  ┌────────┐          ┌────────┐         ┌──────────┐
  │ CLOSED │ ───────▶ │ LISTEN │ ───────▶ │ SYN_RCVD │
  └────────┘          └────────┘         └──────────┘
       ▲                                       │
       │                                       ▼
  ┌────────────┐      ┌──────────────┐   ┌─────────────┐
  │  TIME_WAIT │ ◀─── │  FIN_WAIT_1  │ ◀ │ ESTABLISHED │
  └────────────┘      └──────────────┘   └─────────────┘

  Every TCP connection in your OS is one instance of this machine.
  Millions of instances. Running in kernel space. Right now.
```

**Lexer — how a compiler reads 123.45e-6**
```
  char:   1       2       3       .       4       5       e       -       6
          │       │       │       │       │       │       │       │       │
  START ──▶ INT ──▶ INT ──▶ INT ──▶ DOT ──▶ FRAC ──▶ FRAC ──▶ E ──▶ SIGN ──▶ EXP

  EXP is an accept state → valid float. No regex. One dict lookup per character.
```

**Game AI — enemy that reacts**
```
  ┌──────┐  sees player  ┌───────┐  close enough  ┌────────┐
  │ IDLE │ ────────────▶ │ CHASE │ ──────────────▶ │ ATTACK │
  └──────┘               └───────┘                 └────────┘
     ▲                       ▲                          │
     │                       │   lost sight             │ player dies
     │                       └──────────────────────    ▼
     │                                             ┌──────┐
     └─────────────────────────────────────────────│ IDLE │
                          area clear               └──────┘
```

**Document approval workflow**
```
  ┌───────┐      ┌───────────┐      ┌─────────────┐      ┌──────────┐
  │ DRAFT │ ────▶│ SUBMITTED │ ────▶│ UNDER_REVIEW│ ────▶│ APPROVED │
  └───────┘      └───────────┘      └─────────────┘      └──────────┘
      ▲                                    │
      │                                    │ rejected
      │            ┌───────────┐           │
      └────────────│  REJECTED │ ◀─────────┘
        revise     └───────────┘
        and        (back to DRAFT — this is what makes it an FSM,
        resubmit    not a pipeline)
```

**Kubernetes pod lifecycle**
```
  ┌─────────┐      ┌─────────┐      ┌───────────┐
  │ Pending │ ────▶│ Running │ ────▶│ Succeeded │
  └─────────┘      └─────────┘      └───────────┘
       ▲                │
       │                │ crash
       │                ▼
       │           ┌────────┐
       └───────────│ Failed │  (restart policy fires → back to Pending)
        restart    └────────┘
```

**Embedded / firmware — traffic light**

The entire control logic of a traffic light is an FSM with a timer as the event source. There is no other code. The FSM is the program.

```
  ┌──────┐  timer  ┌───────┐  timer  ┌────────┐  timer
  │  RED │ ──────▶ │ GREEN │ ──────▶ │ YELLOW │ ──────▶ back to RED
  └──────┘         └───────┘         └────────┘
```

---

## The structure in code — the minimal working version

```python
TRANSITIONS = {
    "A": { "x": "B", "y": "C" },
    "B": { "x": "B", "z": "D" },   # x is a self-loop
    "C": { "z": "D"            },
    "D": {}                          # terminal
}

class FSM:
    def __init__(self, initial):
        self.state   = initial
        self.context = {}

    def send(self, event, payload=None):
        legal = TRANSITIONS.get(self.state, {})

        if event not in legal:
            raise ValueError(f"Illegal: {event!r} from {self.state!r}")

        self.state = legal[event]
        if payload:
            self.context.update(payload)
        return self.state
```

That's the whole idea. The table is the machine. `send` is the interface. The raise is the value.

---

## What FSM solves that if/else doesn't

Without FSM, state is scattered across booleans:

```python
# This is chaos. These get out of sync.
is_paid = True
is_shipped = False
is_cancelled = False
is_refunding = True    # wait — paid AND refunding AND not shipped?
                       # is this even a valid combination?
```

With FSM, there is one variable and it's always valid:

```python
state = "REFUNDING"    # that's it. one thing. always legal.
```

You cannot be in two states at once. You cannot reach an invalid combination. The table defines every legal state and every legal transition. Anything outside the table is rejected before it can corrupt state.

---

## The one question that tells you when to use it

**Does the outcome of a step change which step runs next — not just whether to retry, but where control goes?**

If yes: FSM.

If the flow is always the same sequence and failure just means retry-in-place or bail out: pipeline. Don't add an FSM. It'll be overhead with no payoff.

The moment you catch yourself writing:
```python
if failed and was_paid:
    go_to_refunding()
elif failed and not was_paid:
    go_to_cancelled()
elif succeeded and has_inventory:
    go_to_shipped()
elif succeeded and not has_inventory:
    go_to_backorder()
```

— that's an FSM trying to be born inside your if-else. Let it out.

---

## Quick reference

```
Term          What it is
──────────────────────────────────────────────────────────────
State         Where the machine is right now. Always exactly one.
Event         A signal that arrives and potentially triggers a move.
Transition    A legal (state, event) → next-state mapping in the table.
Guard         A condition that must be true for a transition to fire.
Self-loop     A transition where next-state == current-state.
Context       Data that travels with the machine. Guards and side effects read it.
on_enter      Code that runs when a state is entered.
on_exit       Code that runs when a state is left.
Accept state  A state where input ending here is valid (lexers).
Dead state    A terminal state with no outgoing transitions.
```

---

*If you remember one thing: the machine knows where it is, the table says what's legal, and everything outside the table gets refused. That refusal is the entire point.*
