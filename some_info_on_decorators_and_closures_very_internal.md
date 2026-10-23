# Python Closures & Decorators — How They Actually Work

A personal reference for when the "how does the inner function still see the outer variable?" doubt comes back.

---

## 1. The core doubt

```python
>>> def fun(f):
...     def inner(val):
...         print(f)
...         print(val)
...     return inner
...
>>> fun(1)
<function fun.<locals>.inner at 0x7962e55523e0>
>>> fun(1)()
TypeError: fun.<locals>.inner() missing 1 required positional argument: 'val'
>>> fun(1)(2)
1
2
```

**The question:** `fun` has already finished and returned. Its local `f` should be gone. And `inner` never ran while `fun` was running, so how could `inner` "know" it needs `f`?

**The wrong assumption:** "inner hasn't run yet, so inner doesn't know it needs f."

**The truth:** Python decides which variables `inner` needs **when the code is compiled**, before anything runs. Running `inner` is not required for Python to know that.

---

## 2. Two phases: compile time vs run time

Every piece of Python code goes through two phases.

| Phase | When | What happens |
|---|---|---|
| **Compile** | When you finish typing the `def` block / when the module is imported | Python reads the *text* of every function (including nested ones) and decides, for every name, whether it is local, global, or from an enclosing function. |
| **Run** | When the code is actually called | Python executes the bytecode using the decisions already made. |

During compilation of `fun`, Python looks inside `inner` and reasons:

> `inner` uses `f`. `f` is not a parameter of `inner` and is not assigned inside `inner`. But `f` is a local of the enclosing function `fun`. Therefore `inner` needs `f` from `fun`.

This is recorded permanently in the compiled code objects:

```python
>>> fun.__code__.co_cellvars      # fun's locals that some inner function needs
('f',)
>>> inner = fun(1)
>>> inner.__code__.co_freevars    # names inner takes from an enclosing scope
('f',)
```

- **cell variable** (`co_cellvars`) — a local of the *outer* function that an inner function uses.
- **free variable** (`co_freevars`) — a name the *inner* function uses that lives in an enclosing function.

Same variable, seen from two sides.

---

## 3. Step-by-step: what happens on `fun(1)(2)`

### Step 1 — `fun(1)` starts; `f` goes into a cell

Because the compiler already marked `f` as a cell variable, Python does **not** store `f` as a plain local. It stores it inside a small box called a **cell**:

```
fun's frame
   f  ──►  [ cell ] ──► 1
```

### Step 2 — the `def inner` line *executes*

`def` is an executable statement, not just a declaration. Each time `fun` runs, `def inner` builds a **new function object**. While building it, Python attaches the cell(s) for the free variables to the function, in `__closure__`:

```
inner (function object)
   ├── __code__     → compiled body: print(f); print(val)
   └── __closure__  → ( [ cell ] ──► 1 , )
```

`inner`'s body has **not** run. It doesn't need to. The cell is attached when the function object is *created*, not when it is *called*.

### Step 3 — `fun` returns; its frame dies, the cell survives

`fun`'s local frame is discarded. But the cell is still referenced by `inner.__closure__`, so Python's reference counting keeps it alive.

```python
>>> g = fun(1)
>>> g.__closure__
(<cell at 0x...: int object at 0x...>,)
>>> g.__closure__[0].cell_contents
1
```

### Step 4 — `g(2)` runs `inner`

- `val` → the argument you passed (`2`), a normal local.
- `f` → looked up through the attached cell (`1`).

Output: `1` then `2`.

### Why `fun(1)()` failed

`fun(1)` worked fine and returned `inner`. Then `()` called `inner` with **no** arguments, but `inner` requires `val`. The `f` part was never the problem.

---

## 4. Seeing it in bytecode

Use the `dis` module to see the instructions. Exact output differs between Python versions, but the important instruction names are stable enough to recognise:

```python
import dis
dis.dis(fun)
```

Things to look for:

| Instruction | Meaning |
|---|---|
| `MAKE_CELL f` | (3.11+) turn local `f` into a cell at function start |
| `LOAD_CLOSURE f` | push the cell itself (not its value) onto the stack |
| `BUILD_TUPLE` | bundle the cells into the closure tuple |
| `MAKE_FUNCTION` (+ `SET_FUNCTION_ATTRIBUTE` in 3.13+) | build the inner function and attach the closure |
| `LOAD_DEREF f` | inside `inner`: read the value *through* the cell |
| `STORE_DEREF f` | write a value *through* the cell (used with `nonlocal`) |
| `LOAD_FAST val` | normal local variable read |
| `LOAD_GLOBAL x` | module-level / builtin lookup (no closure involved) |

```python
dis.dis(fun(1))   # disassemble inner — you'll see LOAD_DEREF for f, LOAD_FAST for val
```

---

## 5. Every call makes a separate cell

```python
>>> a = fun(1)
>>> b = fun(99)
>>> a("x")
1
x
>>> b("y")
99
y
>>> a.__closure__[0] is b.__closure__[0]
False
```

Two calls → two frames → two cells → two different `inner` function objects. Each remembers its own `f`.

**Definition:** a **closure** = a function + the cells for the variables it uses from enclosing scopes.

---

## 6. Name lookup rules (LEGB)

When Python sees a name, it resolves it in this order:

1. **L**ocal — assigned in the current function (or a parameter)
2. **E**nclosing — locals of enclosing *functions* (this is where closures come from)
3. **G**lobal — module level
4. **B**uiltin — `len`, `print`, etc.

The decision of *which category* a name belongs to is made at **compile time**. Only the *value* is fetched at run time.

Module-level variables are **not** closures. A function reading a global uses `LOAD_GLOBAL` and looks it up in the module dict each time; nothing is captured.

---

## 7. Gotcha: closures capture the *variable*, not the *value* (late binding)

The cell holds a reference to the variable's current value. If the variable changes after `inner` is created, `inner` sees the new value.

```python
def outer():
    x = 1
    def inner():
        return x
    x = 2              # changes the cell's contents
    return inner

outer()()   # 2, not 1
```

### The classic loop trap

```python
funcs = [lambda: i for i in range(3)]
[f() for f in funcs]     # [2, 2, 2]  — all share the same i
```

All three lambdas close over the **same** `i`, which ends at `2`.

**Fix 1 — default argument (evaluated at definition time):**
```python
funcs = [lambda i=i: i for i in range(3)]
[f() for f in funcs]     # [0, 1, 2]
```

**Fix 2 — factory function (new cell per call):**
```python
def make(i):
    return lambda: i
funcs = [make(i) for i in range(3)]
```

---

## 8. Gotcha: assigning to an enclosing variable needs `nonlocal`

```python
def counter():
    count = 0
    def inc():
        count += 1      # UnboundLocalError!
        return count
    return inc
```

Why? At **compile time**, Python sees an assignment to `count` inside `inc`, so it decides `count` is **local to `inc`**. Then `count += 1` tries to read that local before it has a value.

This error is itself proof that scoping is decided at compile time.

**Fix:**
```python
def counter():
    count = 0
    def inc():
        nonlocal count   # "count belongs to the enclosing function's cell"
        count += 1
        return count
    return inc

c = counter()
c(), c(), c()    # (1, 2, 3)
```

`global x` does the same thing but points to module level instead.

---

## 9. Gotcha: class bodies do NOT create closures for methods

```python
class A:
    y = 10
    def method(self):
        return y        # NameError — class scope is skipped
```

Methods must use `self.y` or `A.y`. The class body is a temporary namespace, not an enclosing function scope, so LEGB skips it.

---

## 10. Decorators are just closures + syntax sugar

### The rule

```python
@deco
def f(): ...
```

is exactly the same as:

```python
def f(): ...
f = deco(f)
```

### A simple decorator

```python
import functools

def log_calls(func):
    @functools.wraps(func)          # copies __name__, __doc__, etc. to wrapper
    def wrapper(*args, **kwargs):
        print(f"calling {func.__name__}")
        return func(*args, **kwargs)
    return wrapper                   # wrapper closes over `func`

@log_calls
def add(a, b):
    return a + b
```

`wrapper` is the inner function; `func` is the captured variable (just like `f` earlier).

Without `functools.wraps`, `add.__name__` would become `"wrapper"`, which breaks debugging, logging, and tools that rely on names.

### A decorator *with arguments* = one more layer

```python
@repeat(times=3)
def hello(): print("hi")
```

is:

```python
deco = repeat(times=3)   # step 1: call the factory -> returns the real decorator
hello = deco(hello)      # step 2: apply it
```

So you need three levels:

```python
def repeat(*, times):                 # level 1: takes decorator arguments
    def decorator(func):              # level 2: takes the function   (closes over times)
        @functools.wraps(func)
        def wrapper(*args, **kwargs): # level 3: replaces the function (closes over times, func)
            for _ in range(times):
                result = func(*args, **kwargs)
            return result
        return wrapper
    return decorator
```

### Stacking order

```python
@a
@b
def f(): ...
```
equals `f = a(b(f))` — the decorator **closest to the function is applied first**.

### Class decorators

Same idea, but the thing passed in is a class:

```python
@deco
class C: ...
# C = deco(C)
```

A class decorator usually returns the same class (after registering or modifying it) instead of a wrapper.

---

## 11. Decorators run at IMPORT time

The decorator runs when the `def` / `class` statement executes, which is when the module is **imported** — not when the function is called.

Consequence for registries: if a module containing `@register_collector(...)` classes is never imported, those classes **never get registered**. A common pattern is to import all collector modules explicitly (e.g. in a package's `__init__.py`) so registration happens.

---

## 12. Applying it all: the registry decorator

### Mapping to the small example

| Small example | Registry decorator |
|---|---|
| `fun` | `register_collector` |
| `f` (captured) | `name` (captured) |
| `inner` | `register` |
| `val` (argument at call time) | `cls` (the decorated class) |

```python
@register_collector(name="jira_tests")
class MyCollector(TestCollector): ...
```

1. `register_collector(name="jira_tests")` runs → creates a cell for `name` → builds and returns `register` with that cell in its `__closure__`.
2. Python calls `register(MyCollector)` → `name` is read through the cell → class is validated and stored.
3. `register` returns the class, so `MyCollector` still refers to the original class.

### Fixed version

```python
_TEST_COLLECTOR_REGISTRY: dict[tuple["JiraFeatures", str], type["TestCollector"]] = {}

def register_collector(*, name: str):
    def register[T: BaseCollector](cls: type[T]) -> type[T]:
        if not issubclass(cls, BaseCollector):
            raise TypeError(f"{cls.__name__} does not satisfy a collector type")

        if not isinstance(cls.feature, JiraFeatures):
            raise ValueError("Wrong feature type selected. DO NOT OVERRIDE the feature variable.")

        if not issubclass(cls, TestCollector):
            raise TypeError(f"{cls.__name__} does not satisfy TestCollector")

        key = (cls.feature, name)
        if key in _TEST_COLLECTOR_REGISTRY:
            raise ValueError(f"collector '{name}' is already registered; choose a different name")

        _TEST_COLLECTOR_REGISTRY[key] = cls
        return cls

    return register
```

Bugs fixed compared to the original:

- The duplicate check was missing its `if key in ...:` line (the bare `raise` caused an `IndentationError`).
- `key` was built but the class was stored under `name`; now it's stored under `key`, so the same name can be reused across different features.
- `cls.feature not in [f for f in JiraFeatures]` builds a list every time; `isinstance(cls.feature, JiraFeatures)` is clearer. (On Python 3.12+, `cls.feature in JiraFeatures` also works directly; on older versions `in` with a non-member raises `TypeError`.)

### About `def register[T: BaseCollector](...)`

This is the **PEP 695** generic syntax (Python 3.12+). `T` is a type variable bounded by `BaseCollector`. It is **only for type checkers** (mypy, pyright): it tells them "whatever class goes in, the same class type comes out." It does **not** check anything at run time, which is why the explicit `issubclass` checks are still needed.

---

## 13. Debugging cheat sheet

```python
f.__code__.co_freevars          # names f captures from enclosing scopes
outer.__code__.co_cellvars      # outer's locals captured by inner functions
f.__closure__                   # tuple of cell objects (None if no closure)
f.__closure__[0].cell_contents  # value inside a cell
f.__code__.co_varnames          # f's own local variable names
f.__wrapped__                   # original function, if functools.wraps was used
import dis; dis.dis(f)          # see LOAD_DEREF / LOAD_FAST / LOAD_GLOBAL
import inspect
inspect.getclosurevars(f)       # nonlocals, globals, builtins f refers to — very readable
```

Example:

```python
>>> import inspect
>>> inspect.getclosurevars(fun(1))
ClosureVars(nonlocals={'f': 1}, globals={}, builtins={'print': <built-in function print>}, unbound=set())
```

---

## 14. One-paragraph summary

When Python compiles a function, it reads all nested functions and decides which names each one needs from an enclosing function. Those variables are stored in **cells** instead of plain locals. Each time the outer function runs, the `def inner` statement creates a new function object and attaches those cells to its `__closure__`. When the outer function returns, its frame is destroyed but the cells live on because the inner function still references them. Later, when the inner function is called, it reads those variables through the cells (`LOAD_DEREF`). A decorator is just a function that receives a function (or class) and returns something to replace it; a decorator *with arguments* is a function that returns such a decorator, which is why it has one extra layer and why the arguments (like `name`) are available inside via a closure.
