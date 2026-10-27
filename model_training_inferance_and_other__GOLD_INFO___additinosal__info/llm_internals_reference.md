# 📦 Packaging, Serving, and Prompting LLMs — What Actually Happens
### *From "what even is a model file" to self-hosting — built from real curiosity*

---

## 🗺️ What This Doc Is About

Ever wondered what actually happens when you send a message to an LLM API? You write a Python dict with `system`, `user`, `assistant` — and somehow the model responds intelligently. But the model doesn't understand Python dicts. It doesn't understand "system" or "user" as concepts. It only understands **numbers** — sequences of token IDs.

So something in the middle is doing translation work. That something is the **runner** (llama.cpp, vLLM, the DashScope API — they're all runners). And the runner knows how to translate because **the model ships with a blueprint** that tells it exactly what token sequences mean what.

**This doc is about understanding that full picture:**

- What a model actually *is* as a packaged artifact — what files it contains, what they mean
- How a runner reads those files and knows how to talk to that specific model
- What is *baked into the model* (immovable, trained in) vs what is *runner-controlled* (convenience layer on top)
- How features like `enable_thinking`, tool calls, system prompts — are just named shortcuts for injecting specific token patterns the model was already trained to understand
- And yes — you can inject those patterns directly yourself, bypassing the convenience layer entirely

By the end you'll be able to reason about any model, any runner, any feature — including your own custom fine-tuned model with your own token format.

---

## 🧩 The Two Layers You Need to Keep Separate

Before anything else — burn this distinction in. Everything in this doc hangs off it.

```
┌─────────────────────────────────────────────────────────┐
│                     THE MODEL                           │
│                                                         │
│  Just a mathematical function. Weights baked during     │
│  training. Immovable. Cannot be changed at runtime.     │
│                                                         │
│  Understands: token ID sequences → next token ID        │
│  Knows nothing about: Python, JSON, "system", "user"    │
│                                                         │
│  What's baked in: reasoning ability, coding skill,      │
│  language understanding, tool call patterns,            │
│  <think> behavior — ALL from training data              │
└─────────────────────────┬───────────────────────────────┘
                          │
                feeds token IDs ↕ gets token IDs back
                          │
┌─────────────────────────▼───────────────────────────────┐
│                    THE RUNNER                           │
│         (llama.cpp, vLLM, DashScope API, etc.)          │
│                                                         │
│  The translation bridge. Reads what the model           │
│  understands (from the model's own config files),       │
│  then converts your high-level API call into            │
│  exactly those token sequences.                         │
│                                                         │
│  Runner-controlled: message formatting, enable_thinking  │
│  flag, tool call parsing, streaming, API schema         │
└─────────────────────────────────────────────────────────┘
```

**Key insight:** The model has capabilities. The runner *exposes* them conveniently. But you can always bypass the runner's convenience layer and inject the exact token patterns yourself — the model will behave identically because it only cares about what token sequences it receives, not how they got there.

---

## 🔑 The Core Concept: Everything Becomes Token Sequences

Here's what actually happens from your Python code to the GPU:

```python
# What YOU write:
messages = [
    {"role": "system", "content": "You are an expert Python developer."},
    {"role": "user",   "content": "Write a function to reverse a linked list."}
]
```

After the runner processes this through the model's chat template:

```
<|im_start|>system
You are an expert Python developer.<|im_end|>
<|im_start|>user
Write a function to reverse a linked list.<|im_end|>
<|im_start|>assistant
```

After the tokenizer converts that string to integers:

```
[151644, 8948, 198, 2610, 525, 458, 6173, 13, 151645, 198, 151644, 872, 198, ...]
```

**That integer array is literally all the model sees.** No Python. No JSON. No "role". Just numbers. The GPU runs matrix math on those numbers and produces more numbers. The runner decodes those back to text and streams it to you.

The `<|im_start|>`, `<|im_end|>` tokens — those aren't just formatting decoration. The model was **trained on millions of conversations that used exactly these tokens** to signal role boundaries. So when it sees `<|im_start|>assistant`, it knows: *"my turn to generate."* That behavior is baked into the weights during training. The runner didn't invent it — it just triggers it by injecting the right sequence.

### The Complete Journey — One Example, All the Way Through

Same example, no steps skipped, nothing hand-waved:

```
STEP 1 — You write this in Python:
─────────────────────────────────────────────────────────────
messages = [
    {"role": "system", "content": "You are an expert Python developer."},
    {"role": "user",   "content": "Write a function to reverse a linked list."}
]

STEP 2 — OpenAI SDK serializes it to an HTTP POST (nothing more):
─────────────────────────────────────────────────────────────
POST /v1/chat/completions
{"model": "qwen3.6", "messages": [{"role": "system", "content": "..."}, ...]}

STEP 3 — Runner reads chat_template, renders it into a raw string:
─────────────────────────────────────────────────────────────
<|im_start|>system
You are an expert Python developer.<|im_end|>
<|im_start|>user
Write a function to reverse a linked list.<|im_end|>
<|im_start|>assistant

STEP 4 — Tokenizer converts that string to integers:
─────────────────────────────────────────────────────────────
[151644, 8948, 198, 2610, 525, 458, 6173, 13, 151645, 198, ...]
  ↑       ↑     ↑
  │       │     └─ 198 = newline character
  │       └─────── 8948 = "system"
  └─────────────── 151644 = <|im_start|>

STEP 5 — GPU receives ONLY those integers. No text. Produces output integers:
─────────────────────────────────────────────────────────────
[1527, 10293, 1703, 5384, 1188, 8, 198, 1054, 3314, 284, ...]

STEP 6 — Runner decodes output integers back to text:
─────────────────────────────────────────────────────────────
"def reverse_list(head):
    prev = None
    while head: ..."

STEP 7 — Runner wraps in OpenAI-compatible JSON and streams to you:
─────────────────────────────────────────────────────────────
{"choices": [{"delta": {"content": "def reverse_list"}, ...}]}
```

At no point does the model know what Python is. It doesn't understand "system" as a concept. It saw integer 151644 followed by integer 8948 and knew — because it was trained on millions of examples with that exact pattern — what to do next. That's the whole trick. No magic. Just pattern matching on integers at massive scale.

---

## 🎭 Runner Convenience vs Model Capability — The Critical Distinction

This is where most people get confused. Let's be precise.

### What's BAKED INTO THE MODEL (runner can't add or remove this):

- Reasoning ability — solving math, writing code, following instructions
- Understanding of its own special tokens — `<|im_start|>`, `<think>`, tool call formats
- **`<think>` reasoning behavior** — Qwen3.6 was fine-tuned on data that had `<think>...</think>` blocks before answers. The model *learned* this pattern. It knows that when it sees or generates `<think>`, it should do extended reasoning before responding.
- **Tool call structure** — same thing. Trained on data with structured function call patterns. The model knows the format.
- All of this lives in the **weights**. Immovable. Same whether you run on DashScope or RunPod or your own machine.

### What's RUNNER-CONTROLLED (convenience layer):

- **`enable_thinking=True`** — the runner's chat template has a conditional: if this flag is set, prepend a `<think>` token to the assistant's generation, forcing it into thinking mode. That's literally all it does. The capability existed in the model already.
- **`--tool-call-parser qwen3`** (vLLM flag) — the model outputs tool calls as structured text in a specific format. The runner parses that text and converts it to a clean JSON object for your API response. Without this flag, you'd still see the tool call — just as raw text you'd have to parse yourself.
- **System prompt handling** — the runner wraps your system content in `<|im_start|>system...<|im_end|>`. The model just sees tokens. "System" as a concept is a construct the runner manufactures through the template.
- **Streaming** — runner-level. The model generates tokens one by one. The runner decides whether to buffer or stream.
- **OpenAI-compatible API schema** — entirely runner. The model knows nothing about REST APIs.

### The Proof: You Can Bypass All Convenience Features

Since features are just token patterns, you can inject them directly:

```python
# enable_thinking=True is just the runner doing this for you automatically.
# You can do it yourself by pre-filling the assistant turn:
messages = [
    {"role": "system",    "content": "You are helpful."},
    {"role": "user",      "content": "What is 2+2?"},
    {"role": "assistant", "content": "<think>\n"},  # partial assistant turn
]
# Model sees <|im_start|>assistant\n<think>\n and continues the thinking block.
# No flag needed. You triggered it directly with the token pattern.
```

```python
# Tool calling without --tool-call-parser:
# The model still outputs the tool call as structured text.
# You just parse it yourself instead of the runner doing it:
raw_output = '{"name": "get_weather", "arguments": {"city": "Chennai"}}'
# The model generated this because it was trained to. The parser flag just
# saves you from writing the JSON extraction code.
```

This is the mental model: **features are token patterns the model learned during training. Runners expose them as named flags. You can always go direct.**

---

## 📦 A Model Is a Package — What's Inside

When you download a model from HuggingFace, you get a directory of files. Each has a job:

```
Qwen3-8B/
├── config.json                  ← model architecture (layers, heads, dimensions)
├── tokenizer_config.json        ← HOW TO TALK TO THIS MODEL ← this is the key file
├── tokenizer.json               ← the full vocabulary (all tokens and their IDs)
├── special_tokens_map.json      ← which tokens are "special" (BOS, EOS, PAD, etc.)
└── model.safetensors            ← the actual weights (the big file, many GBs)
```

> 📌 **Two packaging formats, same model:** HuggingFace format = a directory of separate files like above, used by vLLM and transformers. GGUF = a single self-contained binary file, used by llama.cpp, quantized for efficiency. Same weights, same chat template embedded inside, different container. That's the only reason vLLM and llama.cpp have slightly different flags — they're reading the same information from different packaging.

The runner loads all of these at startup. Weights go to GPU. The config files tell the runner everything it needs to know about how to interact with this specific model.

**`tokenizer_config.json` is the most important config for understanding how to prompt a model.** It contains:

```json
{
  "model_max_length": 32768,
  "tokenizer_class": "Qwen2Tokenizer",
  "chat_template": "...the Jinja2 blueprint...",
  "added_tokens_decoder": {
    "151643": {"content": "<|endoftext|>", "special": true},
    "151644": {"content": "<|im_start|>",  "special": true},
    "151645": {"content": "<|im_end|>",    "special": true}
  },
  "bos_token": "<|endoftext|>",
  "eos_token": "<|im_end|>"
}
```

| Field | What it does | Who uses it |
|---|---|---|
| `chat_template` | Jinja2 blueprint: messages dict → raw token string | Runner (at every API call) |
| `added_tokens_decoder` | Maps token IDs ↔ their string representations | Tokenizer (at model load) |
| `model_max_length` | Max context window the model supports | Runner (for validation) |
| `tokenizer_class` | Which tokenizer implementation to instantiate | Runner (at model load) |
| `bos_token` / `eos_token` | Beginning/end of sequence markers | Tokenizer + runner |

These do **independent jobs**. The template says *how to format* conversations. The `added_tokens_decoder` says *what integer to use* for each special string. Both needed. Work together.

---

## 📋 The Chat Template — Just a Jinja2 String

> *"The chat template — it's basically strings formatted. That's it right?"*

Exactly. Nothing magic. It's a Jinja2 template string. The escaped blob in the JSON looks intimidating:

```json
"chat_template": "{%- for message in messages %}\n{{- '<|im_start|>' + message['role'] + '\\n' }}\n{{- message['content'] + '<|im_end|>\\n' }}\n{%- endfor %}"
```

Unescape it and it's just:

```jinja2
{%- for message in messages %}
{{- '<|im_start|>' + message['role'] + '\n' }}
{{- message['content'] + '<|im_end|>\n' }}
{%- endfor %}
<|im_start|>assistant
```

You give it your messages → it loops through → outputs a formatted string → runner tokenizes it → GPU gets integers. That's the whole chain.

### Is This Standardized?

Yes. HuggingFace `transformers` standardized the convention:

- Any chat/instruct fine-tuned model → put your Jinja2 template in `tokenizer_config.json` under the key `chat_template`
- Every runner (vLLM, llama.cpp, transformers pipeline) reads that exact key

So if you fine-tune a model tomorrow in any style with any tokens — write your Jinja2, drop it in that field, and every runner handles it correctly. The standardization is in the **key name and file location**, not in what the template contains. The content is entirely yours.

### Different Models, Different Special Tokens

Each model was trained on its own specific token sequences. You can't mix them.

| Model | Special tokens used |
|---|---|
| Qwen3.6 | `<\|im_start\|>`, `<\|im_end\|>`, `<think>`, `</think>` |
| Llama 3.1 Instruct | `<\|start_header_id\|>`, `<\|end_header_id\|>`, `<\|eot_id\|>` |
| Mistral Instruct | `[INST]`, `[/INST]` |
| Your custom model | Whatever you trained it on — `<abc_user>` if you want |

When you load Qwen → runner reads Qwen's template → uses Qwen's tokens. Load Llama → reads Llama's template → Llama's tokens. **The runner figures this out at load time by reading the file. It doesn't hardcode any of this.**

---

## 🗂️ `added_tokens_decoder` — The Vocabulary Map

> *"There is an `added_tokens_decoder` alongside `chat_template` in Mistral — model specific things right?"*

Yes — completely separate job. Here's Mistral's:

```json
"added_tokens_decoder": {
  "1":     {"content": "<s>",     "special": true},
  "2":     {"content": "</s>",    "special": true},
  "32000": {"content": "[INST]",  "special": true},
  "32001": {"content": "[/INST]", "special": true}
}
```

This is a **vocabulary map**. It tells the tokenizer: "token ID 32000 = the string `[INST]`." Without this, when the chat template produces `[INST]` in the rendered string, the tokenizer wouldn't know what integer ID to assign to it.

```
chat_template produces: "[INST]You are helpful.[/INST]"
                              ↓
added_tokens_decoder: [INST] = ID 32000, [/INST] = ID 32001
                              ↓
tokenizer outputs: [32000, 1734, 526, 8444, 29889, 32001]
                              ↓
GPU receives integers
```

- `chat_template` = the recipe (how to build the prompt string)
- `added_tokens_decoder` = the ingredient dictionary (string → integer ID)

Both needed. Work together. Independent jobs.

---

## 🔍 Where to Find Any Model's Template (No Download Needed)

You don't need to download 35GB of weights. Just hit this URL in your browser:

```
https://huggingface.co/<org>/<model>/raw/main/tokenizer_config.json
```

### Go Check These Side by Side Right Now

| Model | `tokenizer_config.json` |
|---|---|
| Qwen3-8B | `huggingface.co/Qwen/Qwen3-8B/raw/main/tokenizer_config.json` |
| Llama 3.1 8B Instruct | `huggingface.co/meta-llama/Llama-3.1-8B-Instruct/raw/main/tokenizer_config.json` |
| Mistral 7B Instruct | `huggingface.co/mistralai/Mistral-7B-Instruct-v0.3/raw/main/tokenizer_config.json` |
| BGE large (embedding) | `huggingface.co/BAAI/bge-large-en-v1.5/raw/main/tokenizer_config.json` |

Open BGE and Qwen side by side. BGE has **no `chat_template` key**. Qwen has a long Jinja2 string. That single difference tells you what each model is for.

> 💡 **Instant rule:** `chat_template` present → chat/instruct model. Absent → embedding model or untuned base model.

### For GGUF Files (llama.cpp format)

The same template is embedded as metadata inside the `.gguf` binary itself:

```bash
pip install gguf

python -c "
import gguf
reader = gguf.GGUFReader('your-model.gguf')
for field in reader.fields.values():
    if 'chat_template' in field.name:
        print(bytes(field.parts[-1]).decode('utf-8'))
"
```

Same Jinja2 string, different container. The `--jinja` flag in llama.cpp tells it: "read the template from the GGUF metadata, don't guess based on model name."

---

## 🤿 Why Embedding Models Have No Template

> *"Do models like BGE or all-MiniLM have such template files?"*

No — and they don't need them. Chat templates exist for generative models that produce text replies. Embedding models do something entirely different:

```
Generative model (Qwen, Llama):
  Input:  "Write a function to reverse a linked list."
  Output: "def reverse_list(head): ..."  ← text

Embedding model (BGE, all-MiniLM):
  Input:  "Write a function to reverse a linked list."
  Output: [0.021, -0.134, 0.887, 0.003, ...]  ← 384 or 768 numbers (a vector)
```

No roles. No turns. No assistant reply. Just text → fixed-size vector. Nothing to template.

### What About T5 / FLAN-T5?

Encoder-decoder models — generative but not chat. Trained on task prefixes:

```
"summarize: The quick brown fox..."
"translate English to French: Hello world"
```

No formal `chat_template`. You prepend the task string manually. Different era, different convention.

### The Full Breakdown

| Model Type | `chat_template`? | Why |
|---|---|---|
| Chat/Instruct LLMs (Qwen, Llama, Mistral) | ✅ Yes | Conversation structure, turn-taking |
| Base LLMs (raw pretrained, not fine-tuned) | ❌ Usually no | Not trained on dialogue format |
| Embedding models (BGE, MiniLM) | ❌ No | Outputs vectors, not text |
| Encoder-decoder (T5, FLAN) | ❌ No | Task prefix convention instead |
| Vision-language models (LLaVA, Qwen-VL) | ✅ Yes | Still chat-based, adds image tokens |

---

## ⚙️ The Full Pipeline — Every Layer Explained

> *"The messages dict is auto-converted to `<|im_start|>system...` — by what? The llama.cpp server or the OpenAI Python SDK?"*

**The runner. Not the SDK.**

The OpenAI Python SDK is just a thin HTTP wrapper. All it does:

```python
# SDK pseudocode — this is literally all it does:
def chat_completions_create(messages, model, **kwargs):
    return requests.post(
        base_url + "/v1/chat/completions",
        json={"model": model, "messages": messages, **kwargs}
    )
```

It serializes your Python dict to a JSON HTTP POST and sends it to whatever URL you gave as `base_url`. Zero knowledge of `<|im_start|>` or model-specific tokens.

The runner receives the JSON and does all the real work:

```
POST /v1/chat/completions
{"messages": [...], "temperature": 0.7, "stream": true}
        ↓
Runner receives JSON
        ↓
Reads chat_template from tokenizer_config.json  ← loaded ONCE at model startup
        ↓
Jinja2 renders messages → raw string with special tokens
  "<|im_start|>system\nYou are helpful<|im_end|>\n<|im_start|>user\n..."
        ↓
Tokenizer converts string → integer token IDs
  [151644, 8948, 198, 2610, 525, ...]
        ↓
GPU runs math on integers → produces output integer IDs
        ↓
Runner decodes output → wraps in OpenAI-compatible JSON → streams back
```

### How API Fields Map Through the Pipeline

Not all fields go to the same place:

```python
{
  "messages":    [...],    # → Jinja2 template (rendered into token string)
  "temperature": 0.7,      # → GPU generation engine (never touches template)
  "max_tokens":  1000,     # → GPU generation engine
  "stream":      True,     # → response handling layer
}
```

`messages` is the only field that flows through the chat template. Everything else bypasses it.

---

## 🔌 The OpenAI SDK With Non-OpenAI Models

> *"This uses the OpenAI SDK — which is for GPT. How can Qwen use the same API?"*

Because DashScope, vLLM, llama.cpp — they all **implement the same REST API schema that OpenAI defined.** The SDK doesn't care what's behind the URL. It only cares about:

1. HTTP endpoint structure (`/v1/chat/completions`)
2. JSON request/response format (`{"choices": [...]}`)
3. Auth header (`Authorization: Bearer <key>`)

To switch between GPT and Qwen you change two lines:

```python
# OpenAI GPT:
client = OpenAI(base_url="https://api.openai.com/v1", api_key="sk-...")
model = "gpt-4o"

# Qwen via DashScope:
client = OpenAI(base_url="https://dashscope-intl.aliyuncs.com/compatible-mode/v1", api_key="your-key")
model = "qwen3.6-flash"

# Qwen self-hosted via llama.cpp:
client = OpenAI(base_url="http://YOUR_RUNPOD_IP:8080/v1", api_key="not-needed")
model = "qwen3.6"  # name doesn't matter for llama.cpp

# All three use identical Python code for the actual call.
```

`extra_body` params like `enable_thinking` are Qwen-specific — they pass through fine and get ignored by endpoints that don't understand them.

---

## 🖥️ Self-Hosting on RunPod — llama.cpp & vLLM

> *"If I take it and run on RunPod with a runner — will it behave like the coding agent?"*

**100% identical behavior.** Same model weights, same template, same token sequences → same behavior. The cloud API and your self-hosted instance are indistinguishable to the model.

### Option A: llama.cpp (Good for single-user, quantized models)

```bash
# Build with CUDA:
git clone https://github.com/ggml-org/llama.cpp && cd llama.cpp
cmake -B build -DLLAMA_CUBLAS=ON
cmake --build build --config Release -j$(nproc)

# Download GGUF (quantized, much smaller than full weights):
huggingface-cli download Qwen/Qwen3.6-35B-A3B-GGUF \
  qwen3.6-35b-a3b-q4_k_m.gguf --local-dir ./models

# Start OpenAI-compatible server:
./build/bin/llama-server \
  -m ./models/qwen3.6-35b-a3b-q4_k_m.gguf \
  --port 8080 --host 0.0.0.0 \
  --jinja \              # ← CRITICAL: read template from GGUF metadata
  --ctx-size 32768 \
  --n-gpu-layers 99 \    # offload all layers to GPU
  --temp 0.6 --top-p 0.95
```

```python
from openai import OpenAI
client = OpenAI(api_key="not-needed", base_url="http://YOUR_RUNPOD_IP:8080/v1")

response = client.chat.completions.create(
    model="qwen3.6",
    messages=[
        {"role": "system", "content": "You are a senior Python engineer. Think step-by-step."},
        {"role": "user",   "content": "Implement a thread-safe singleton in Python."}
    ],
    stream=True
)
for chunk in response:
    if chunk.choices[0].delta.content:
        print(chunk.choices[0].delta.content, end="", flush=True)
```

### Option B: vLLM (Higher throughput, multiple users)

```bash
pip install vllm

python -m vllm.entrypoints.openai.api_server \
  --model Qwen/Qwen3.6-35B-A3B \
  --tensor-parallel-size 4 \      # split across 4 GPUs
  --max-model-len 262144 \
  --port 8000 \
  --enable-auto-tool-choice \
  --tool-call-parser qwen3         # runner parses tool call text into clean JSON
```

```python
# enable_thinking with vLLM (runner injects <think> via template kwarg):
completion = client.chat.completions.create(
    model="Qwen/Qwen3.6-35B-A3B",
    messages=[...],
    extra_body={"chat_template_kwargs": {"enable_thinking": True}}
)
```

> ⚠️ **`enable_thinking` is runner-controlled, not model-baked** — remember Layer 1 vs Layer 2 from the top of this doc. The reasoning capability lives in the weights, always. This flag is just the runner's convenience switch for triggering it. The template has an `if enable_thinking` branch that prepends `<think>` to the assistant generation. vLLM supports passing template kwargs via `extra_body`. llama.cpp doesn't expose this yet — use system prompt `"Think step by step before answering."` instead, which triggers the same trained behavior via natural language. Same model behavior either way.

### Prompt Format (system → user → assistant order)

```python
messages = [
    # System MUST be first if present
    {"role": "system",    "content": "You are Qwen, a helpful assistant."},
    {"role": "user",      "content": "Explain transformers."},
    {"role": "assistant", "content": "Transformers use self-attention to..."},
    {"role": "user",      "content": "Show me code."}
]
```

### Common Mistakes

| Mistake | Why It Breaks | Fix |
|---|---|---|
| System after user | Template expects system first | Always index 0 |
| Forgetting `--jinja` in llama.cpp | Uses legacy guessed format → garbage output | Always add `--jinja` |
| `enable_thinking` with llama.cpp | Template kwargs not supported yet | Add to system prompt instead |
| Injecting `<think>` in user turn | Wrong position — model trained to generate it in assistant turn | Pre-fill assistant turn instead |

> 🌟 **Verify your setup:** Send `{"role": "user", "content": "Who are you?"}` first. Clean response = template working.

---

## 🎛️ Injecting Token Patterns Directly — The Full Spectrum

> *"If I put `<think>` directly in my message, the model will start thinking, isn't it?"*

Technically yes — but position matters. Here's the full spectrum from safest to most direct:

```python
# Option A — Runner convenience flag (cleanest, vLLM only):
extra_body={"chat_template_kwargs": {"enable_thinking": True}}
# Runner inserts <think> at start of assistant generation via template conditional.

# Option B — System prompt (works on any runner):
{"role": "system", "content": "Think step by step before answering."}
# Natural language instruction. Model understands it because it was trained
# on this kind of instruction. Triggers the same reasoning behavior.

# Option C — Pre-fill assistant turn (advanced, direct token injection):
messages = [
    {"role": "system",    "content": "You are helpful."},
    {"role": "user",      "content": "What is 2+2?"},
    {"role": "assistant", "content": "<think>\n"},  # partial assistant turn
]
# Rendered prompt ends with: <|im_start|>assistant\n<think>\n
# Model continues from that exact point — inside the thinking block.
# No flag needed. You injected the token pattern directly.

# ❌ Option D — Wrong way (in user turn):
{"role": "user", "content": "<think>\nLet me reason\n</think>\nWhat is 2+2?"}
# Renders as <|im_start|>user\n<think>... — wrong position.
# Model was not trained on <think> in user turns. Unpredictable results.
```

Option C is genuinely powerful — pre-filling the assistant turn forces the model to continue from any token sequence you choose. You can:
- Force a `<think>` block
- Force a specific output format like `{"result":`
- Continue a partial response

**This works because the model only sees token sequences.** It doesn't know `<think>` came from a pre-fill vs a flag vs a template conditional. It just sees the integer and continues from there.

---

## 🏗️ Your Own Custom Model With `<abc>` Tags — Will It Work?

> *"If I fine-tune a model with my own `<abc>` tags — will the runner still work?"*

**Yes. Completely.** The runner doesn't care what your tokens are. It reads whatever Jinja2 you wrote and renders it.

Your custom `tokenizer_config.json`:

```json
{
  "chat_template": "{%- for message in messages %}<abc_{{ message['role'] }}>\n{{ message['content'] }}\n</abc_{{ message['role'] }}>\n{%- endfor %}<abc_assistant>\n",
  "added_tokens_decoder": {
    "32000": {"content": "<abc_system>",    "special": true},
    "32001": {"content": "</abc_system>",   "special": true},
    "32002": {"content": "<abc_user>",      "special": true},
    "32003": {"content": "</abc_user>",     "special": true},
    "32004": {"content": "<abc_assistant>", "special": true}
  }
}
```

Runner renders → produces:

```
<abc_system>
You are a helpful assistant.
</abc_system>
<abc_user>
What is 2+2?
</abc_user>
<abc_assistant>
```

Tokenizes using your `added_tokens_decoder` → feeds to GPU → works perfectly.

**The one catch:** You must add your custom tokens to `added_tokens_decoder` with unique IDs. Here's exactly what breaks without it:

```
✅ WITH added_tokens_decoder correctly set:
   "<abc_system>" → tokenizer sees it as one unit → ID 32000
   GPU receives: [..., 32000, ...]
   Model recognizes it as the boundary token it was trained on. Works perfectly.

❌ WITHOUT added_tokens_decoder:
   "<abc_system>" → tokenizer splits it into characters
   GPU receives: [..., 27, 16363, 62, 9537, 29, ...]
                       ↑   ↑      ↑    ↑     ↑
                       <   abc    _  system  >   (separate tokens)
   Model sees random character tokens. No boundary recognized.
   Output is garbage — or the model ignores the tag entirely.
```

The model was trained on `<abc_system>` as a **single atomic token** with ID 32000. If it arrives as 5 separate character tokens, it's a completely different input. The model has no idea what it means.

The runner is just a renderer. It has no opinion on your token choices. Train on whatever sequences you want — write the matching template — done.

---

## 🔁 Qwen3.6 — Open Source vs Model Studio (Applied Example)

> *"If Qwen3.6 is open source, why is it different in Model Studio?"*

It's not different — same weights, different delivery layer.

| Aspect | Open-Source Weights | Model Studio (DashScope) |
|---|---|---|
| Access | Download from HuggingFace | REST API via Alibaba Cloud |
| Model Name | `Qwen/Qwen3.6-35B-A3B` | `qwen3.6-flash` (product alias) |
| Deployment | You run the runner | They run the runner |
| License | Apache 2.0 | Commercial API terms |
| Features | All model capabilities + manual prompting | Same + convenience flags |

The name difference: open-source uses the technical name (35B total params, 3B active, MoE architecture). API uses a simplified product alias. Same bytes in the weights.

### "But the API has `enable_thinking` and self-hosted doesn't?"

`enable_thinking` is **runner-controlled** — remember Layer 1 vs Layer 2. The model capability (reasoning via `<think>` blocks) is baked in either way. The flag is a convenience the DashScope runner exposes. On your self-hosted llama.cpp, you trigger the same behavior via system prompt or pre-fill. Different runner interface, identical model behavior.

```python
# DashScope runner convenience:
extra_body={"enable_thinking": True}

# Self-hosted llama.cpp equivalent:
{"role": "system", "content": "Think step by step before answering."}

# Or direct injection (any runner):
{"role": "assistant", "content": "<think>\n"}  # pre-fill

# All three → same model behavior. The behavior lives in the weights.
```

---

## ✅ Final Checklist — Self-Hosting

| | Check |
|---|---|
| ✅ | Model: Use official GGUF from `Qwen/Qwen3.6-35B-A3B-GGUF` |
| ✅ | llama.cpp: Always launch with `--jinja` flag |
| ✅ | vLLM: Use `--tool-call-parser qwen3` for tool calls |
| ✅ | Prompt order: `system → user → assistant`, system always first |
| ✅ | Thinking on vLLM: `extra_body={"chat_template_kwargs": {"enable_thinking": true}}` |
| ✅ | Thinking on llama.cpp: System prompt or pre-fill `{"role": "assistant", "content": "<think>\n"}` |
| ✅ | Custom model: Jinja2 in `chat_template` + token IDs in `added_tokens_decoder` |
| ✅ | Verify first: Send `"Who are you?"` — clean response = template working |

---

## 🧠 The Mental Model — One Final Summary

```
MODEL    = token sequences → token sequences (math, baked during training, immovable)
RUNNER   = your API call → correct token sequences (reads model's own config files)
TEMPLATE = the blueprint that tells the runner how to do that translation
FEATURES = named shortcuts for injecting specific token patterns the model already knows
YOU      = can always bypass the shortcuts and inject the patterns directly
```

Everything in this doc is an elaboration of those five lines.

### 🧪 Test Yourself — Is the Magic Gone?

If you truly got this, you should be able to answer these without looking:

**1.** You load Llama 3.1 instead of Qwen on llama.cpp. Why does the prompt format automatically change — did you configure anything?
> *Because llama.cpp reads the chat_template embedded in the model file at load time. Different model = different template = different format. You configured nothing. The model shipped with its own instructions.*

**2.** `enable_thinking` works on DashScope but not on your llama.cpp server. Does that mean your self-hosted model can't reason?
> *No. The reasoning capability is baked into the weights — identical on both. The flag is a runner convenience. On llama.cpp, trigger it via system prompt or pre-fill the assistant turn with `<think>
`. Same behavior, different interface.*

**3.** You fine-tune a model on your own `<abc>` tags but forget to add them to `added_tokens_decoder`. What happens when you serve it?
> *The tokenizer splits `<abc_system>` into individual characters. The model receives completely different token IDs than what it was trained on. It won't recognize its own special tokens. Output will be broken or nonsensical.*

**4.** Someone says "the OpenAI SDK converted my message to the right prompt format." What's wrong with that statement?
> *The SDK did nothing except serialize Python to JSON and POST it to a URL. The runner converted the message — by reading the chat_template from the model's config file and rendering it through Jinja2.*

If those feel obvious — the doc did its job.

---

*Built from real curiosity. Every question was real. Every answer leads to the next.*
