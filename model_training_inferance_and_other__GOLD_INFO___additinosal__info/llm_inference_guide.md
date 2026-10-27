# LLM Inference Mechanics: Temperature, Seed, Sampling & Training

A technical deep-dive into how Large Language Models generate text, how inference-time
parameters control output, and how training shapes the weights that produce it all.

---

## 1. The Two Phases of an LLM's Life

An LLM goes through two completely separate phases, and understanding the boundary
between them is critical to understanding what temperature and seed actually do.

### Phase 1: Training (offline, happens once)

Training determines the **weight values** of the neural network. During training,
the model sees billions of tokens and adjusts its parameters (weights) to minimize
a loss function — specifically, the cross-entropy loss between its predictions and
the actual next tokens in the training data.

```
Training data: "The capital of France is Paris"

At the token "is", the model predicts what comes next.
If it predicts "Paris" with high probability → low loss → small weight update
If it predicts "Pizza" with high probability → high loss → large weight update
```

The training process uses **backpropagation** and an optimizer (like Adam) to
iteratively adjust every weight in the network. After training:

- The weights are **frozen** — they never change again during inference
- The model has "learned" statistical patterns: what tokens tend to follow what contexts
- The model does NOT store facts like a database — it stores **probability patterns**
  encoded in billions of floating-point weight values

Key training hyperparameters that affect the final model:

| Parameter       | What it controls                                           |
|-----------------|------------------------------------------------------------|
| Learning rate   | How big each weight update step is                         |
| Batch size      | How many examples the model sees before each update        |
| Epochs          | How many times the model sees the full training data       |
| Weight decay    | Regularization to prevent overfitting                      |
| Warmup steps    | Gradually increase learning rate at the start              |
| Dataset mix     | Ratio of code vs text vs math vs conversation etc.         |

**None of these exist at inference time.** Once training is done, they're gone.

### Phase 2: Inference (online, happens every time you call the API)

Inference is when you send a prompt and get a response. The model's weights are
frozen. The only thing that changes between requests is the **input** and the
**sampling parameters**.

```
┌─────────────────────────────────────────────────────────┐
│                   YOUR API REQUEST                       │
│                                                          │
│  prompt: "What is the capital of France?"                │
│  temperature: 0.7                                        │
│  seed: 42                                                │
│  top_p: 0.9                                              │
│  max_tokens: 100                                         │
└──────────────────────┬──────────────────────────────────┘
                       │
                       ▼
┌─────────────────────────────────────────────────────────┐
│          TRANSFORMER NEURAL NETWORK                      │
│          (weights frozen from training)                   │
│                                                          │
│  Embedding → [Attention + FFN] × N layers → Linear head  │
│                                                          │
│  Input: token IDs from your prompt                       │
│  Output: logit vector (one score per vocab token)        │
│                                                          │
│  ⚠️  temperature, seed, top_p DO NOT EXIST HERE          │
│  Same input tokens → same logits, always, deterministic  │
└──────────────────────┬──────────────────────────────────┘
                       │
                       │ raw logits: [-2.1, 5.8, 3.2, -0.4, ...]
                       │             (one per vocab token, e.g. 50,000 values)
                       ▼
┌─────────────────────────────────────────────────────────┐
│              SAMPLING LAYER                              │
│              (this is just code, not neural network)     │
│                                                          │
│  1. Apply temperature scaling:  logits = logits / T      │
│  2. Apply top-p (nucleus) filtering                      │
│  3. Apply top-k filtering                                │
│  4. Softmax → probability distribution                   │
│  5. Sample from distribution using PRNG(seed)            │
│                                                          │
│  ✅ THIS is where temperature and seed operate           │
└──────────────────────┬──────────────────────────────────┘
                       │
                       ▼
                  selected token: "Paris"
                  (append to sequence, feed back in, repeat)
```

**The key insight:** Temperature and seed are NOT model parameters. They're
post-processing controls applied to the model's raw output. The model itself
is completely unaware of them.

---

## 2. Logits: What the Model Actually Outputs

Before understanding temperature, you need to understand **logits**.

At each generation step, the transformer produces a vector of raw scores — one
per token in the vocabulary. These are called **logits** (short for log-odds).

```python
# Conceptual example — what the model outputs internally
# Vocabulary: ["the", "a", "Paris", "London", "42", "cat", ...]
# Logits:     [ 1.2,  0.8,  6.3,    5.1,    -3.2,  -1.8, ...]

# Higher logit = the model thinks this token is more likely to come next
# These are NOT probabilities — they're unbounded real numbers
# They can be negative, and they don't sum to 1
```

Logits are the **direct output of the final linear layer** in the transformer:

```
logits = hidden_state @ W_vocab + b_vocab
```

Where `W_vocab` is the vocabulary projection matrix (shape: [hidden_dim, vocab_size])
and `hidden_state` is the output of the last transformer layer for the current position.

---

## 3. Temperature: The Full Technical Story

### The Math

Temperature modifies the **sharpness** of the probability distribution by scaling
the logits before softmax:

```
Standard softmax:     P(token_i) = exp(logit_i) / Σ_j exp(logit_j)

With temperature:     P(token_i) = exp(logit_i / T) / Σ_j exp(logit_j / T)
```

That single division by `T` has dramatic effects.

### Worked Example: 4 Candidate Tokens

Suppose the model outputs these logits for the next token after
"The best programming language for data science is":

```
"Python"     → logit = 7.0
"R"          → logit = 5.5
"Julia"      → logit = 3.0
"COBOL"      → logit = 0.5
```

#### Temperature = 1.0 (default — use logits as-is)

```
Scaled logits: [7.0, 5.5, 3.0, 0.5]

P("Python") = exp(7.0) / (exp(7.0) + exp(5.5) + exp(3.0) + exp(0.5))
            = 1096.6 / (1096.6 + 244.7 + 20.1 + 1.6)
            = 1096.6 / 1363.0
            = 0.8046  →  80.5%

P("R")      = 244.7 / 1363.0  = 0.1795  →  18.0%
P("Julia")  = 20.1 / 1363.0   = 0.0147  →  1.5%
P("COBOL")  = 1.6 / 1363.0    = 0.0012  →  0.1%
```

Python dominates but R has a real chance.

#### Temperature = 0.3 (low — sharper, more deterministic)

```
Scaled logits: [7.0/0.3, 5.5/0.3, 3.0/0.3, 0.5/0.3]
             = [23.33,   18.33,   10.0,    1.67]

P("Python") = exp(23.33) / (exp(23.33) + exp(18.33) + exp(10.0) + exp(1.67))
            ≈ 0.9934  →  99.3%

P("R")      ≈ 0.0066  →  0.7%
P("Julia")  ≈ 0.0000  →  ~0%
P("COBOL")  ≈ 0.0000  →  ~0%
```

Python wins almost every single time. The distribution is extremely "peaked."

#### Temperature = 2.0 (high — flatter, more random)

```
Scaled logits: [7.0/2.0, 5.5/2.0, 3.0/2.0, 0.5/2.0]
             = [3.5,     2.75,    1.5,     0.25]

P("Python") = exp(3.5) / (exp(3.5) + exp(2.75) + exp(1.5) + exp(0.25))
            = 33.1 / (33.1 + 15.6 + 4.5 + 1.3)
            = 33.1 / 54.5
            = 0.607  →  60.7%

P("R")      = 15.6 / 54.5  = 0.286  →  28.6%
P("Julia")  = 4.5 / 54.5   = 0.083  →  8.3%
P("COBOL")  = 1.3 / 54.5   = 0.024  →  2.4%
```

Now even COBOL has a 2.4% chance. Over many tokens, this randomness compounds
and you get highly varied (often incoherent) outputs.

#### Temperature = 0 (greedy decoding — special case)

Temperature 0 is implemented as **argmax**, not as actual division by zero:

```python
# Pseudocode for what the API does
if temperature == 0:
    selected_token = argmax(logits)   # always pick highest score
else:
    scaled = logits / temperature
    probs = softmax(scaled)
    selected_token = sample(probs, rng=PRNG(seed))
```

With T=0: "Python" is selected. Every time. No randomness. No sampling.

### Visual Summary of Temperature Effects

```
Temperature 0.0 (greedy):     [████████████████████████████████] Python
                               [                                ] R
                               [                                ] Julia
                               [                                ] COBOL

Temperature 0.3 (focused):    [██████████████████████████████  ] Python  99.3%
                               [                                ] R       0.7%
                               [                                ] Julia   ~0%
                               [                                ] COBOL   ~0%

Temperature 1.0 (default):    [████████████████████████        ] Python  80.5%
                               [█████                           ] R      18.0%
                               [                                ] Julia   1.5%
                               [                                ] COBOL   0.1%

Temperature 2.0 (creative):   [██████████████████              ] Python  60.7%
                               [████████                        ] R      28.6%
                               [██                              ] Julia   8.3%
                               [                                ] COBOL   2.4%

Temperature → ∞ (uniform):    [████████                        ] Python  25%
                               [████████                        ] R      25%
                               [████████                        ] Julia  25%
                               [████████                        ] COBOL  25%
```

As T → ∞, every token becomes equally likely regardless of what the model learned.
As T → 0, only the top token matters.

---

## 4. Seed: Deterministic Randomness

### What Problem Does Seed Solve?

When temperature > 0, the model **samples** from a probability distribution. Sampling
requires randomness. But sometimes you want **reproducible** randomness — run the same
prompt twice, get the same output.

### How Pseudorandom Number Generators (PRNGs) Work

Computers don't have true randomness. They use algorithms that produce sequences of
numbers that *look* random but are fully determined by a starting value — the **seed**.

```python
import random

# Same seed → same sequence, always
random.seed(42)
print(random.random())  # 0.6394267984578837
print(random.random())  # 0.02501082482265604
print(random.random())  # 0.27502931836911926

# Reset seed → exact same sequence
random.seed(42)
print(random.random())  # 0.6394267984578837  ← identical
print(random.random())  # 0.02501082465265604  ← identical
print(random.random())  # 0.27502931836911926  ← identical

# Different seed → completely different sequence
random.seed(99)
print(random.random())  # 0.5765085996155698
```

### How Seed Is Used in Token Sampling

```python
# Simplified pseudocode for what happens inside the inference engine

def sample_next_token(logits, temperature, seed, step_number):
    """Called once per generated token."""

    # 1. Scale by temperature
    scaled_logits = logits / temperature

    # 2. Convert to probabilities
    probs = softmax(scaled_logits)

    # 3. Initialize or advance the PRNG
    #    The seed + step_number together determine the random draw
    rng = PRNG(seed + step_number)  # (actual implementation varies)

    # 4. Draw from the distribution
    cumulative = 0.0
    random_value = rng.random()  # deterministic given the seed
    for i, p in enumerate(probs):
        cumulative += p
        if random_value <= cumulative:
            return vocab[i]
```

### Seed Guarantees and Limitations

| Guarantee                                    | Caveat                                              |
|----------------------------------------------|-----------------------------------------------------|
| Same seed + same input + same params = same output | Only on the **same hardware/software** |
| Different seeds = different outputs          | The outputs still follow the same probability distribution |
| Seed is irrelevant at temperature=0          | Greedy decoding has no randomness to seed |

**Why the hardware caveat?** Floating-point arithmetic on GPUs can have tiny
rounding differences across GPU architectures (A100 vs H100 vs TPU). These
tiny differences in logit values can occasionally tip a close sampling decision
differently. OpenAI's docs acknowledge this — seed provides "mostly deterministic"
output, not an absolute guarantee.

---

## 5. Top-p (Nucleus Sampling) and Top-k

Temperature isn't the only sampling control. Two other parameters filter the
distribution before sampling.

### Top-k: Keep Only the Top K Tokens

```
Logits: "Python"=7.0, "R"=5.5, "Julia"=3.0, "COBOL"=0.5, "Rust"=-1.2, ...

With top_k=3:
  Keep: "Python", "R", "Julia"
  Discard everything else (set their probability to 0)
  Renormalize the remaining 3 probabilities to sum to 1

Result: The model can only choose from {Python, R, Julia}
```

Top-k is simple but crude — it always keeps exactly K candidates regardless of
how the probability mass is distributed.

### Top-p (Nucleus Sampling): Keep Tokens Until Cumulative Probability Reaches p

```
After softmax at temperature=1.0:
  P("Python") = 0.805    cumulative: 0.805
  P("R")      = 0.180    cumulative: 0.985  ← exceeds p=0.95 here
  P("Julia")  = 0.015    cumulative: 1.000
  P("COBOL")  = 0.001

With top_p=0.95:
  Keep: "Python", "R"  (their cumulative mass is 0.985 ≥ 0.95)
  Discard: "Julia", "COBOL"
  Renormalize: P("Python")=0.817, P("R")=0.183
```

Top-p is **adaptive** — when the model is confident, it might keep only 1-2 tokens.
When uncertain, it might keep 50+. This is why it's generally preferred over top-k.

### How They Interact With Temperature

The order of operations matters:

```
Raw logits
    │
    ├──→ Divide by temperature
    │
    ├──→ Softmax → probabilities
    │
    ├──→ Apply top-k filter (if set)
    │
    ├──→ Apply top-p filter (if set)
    │
    ├──→ Renormalize remaining probabilities
    │
    └──→ Sample using PRNG(seed)
```

Temperature changes the *shape* of the distribution. Top-p and top-k *truncate* it.
You can combine them.

### Common Configurations and When to Use Them

```
┌─────────────────────────────────────────────────────────────────────┐
│ Use Case             │ temperature │ top_p │ top_k │ seed          │
├──────────────────────┼─────────────┼───────┼───────┼───────────────┤
│ Code generation      │ 0           │ -     │ -     │ any (ignored) │
│ Structured data/JSON │ 0           │ -     │ -     │ fixed         │
│ Factual Q&A          │ 0 - 0.3     │ 0.9   │ -     │ optional      │
│ General chat          │ 0.7         │ 0.9   │ -     │ -             │
│ Creative writing     │ 0.8 - 1.0   │ 0.95  │ -     │ -             │
│ Brainstorming        │ 1.0 - 1.2   │ 0.95  │ -     │ -             │
│ Maximum randomness   │ 1.5 - 2.0   │ 1.0   │ -     │ -             │
└─────────────────────────────────────────────────────────────────────┘

"-" means "not set" or "doesn't matter"
```

---

## 6. Repetition Penalty and Frequency/Presence Penalty

Some APIs expose additional parameters that modify logits before sampling.

### Frequency Penalty

Reduces the logit of tokens proportionally to how often they've already appeared:

```
adjusted_logit[i] = logit[i] - (frequency_penalty × count_of_token_i_so_far)
```

Example: If "the" has appeared 5 times and frequency_penalty = 0.5:

```
logit("the") was 4.0 → adjusted to 4.0 - (0.5 × 5) = 1.5
```

This discourages the model from repeating the same words over and over.

### Presence Penalty

Similar, but binary — penalizes any token that has appeared at all, regardless
of how many times:

```
adjusted_logit[i] = logit[i] - (presence_penalty × has_token_appeared_before)
```

Where `has_token_appeared_before` is 1 if the token has appeared, 0 otherwise.

This encourages the model to introduce new topics and vocabulary.

---

## 7. The Autoregressive Loop: How Full Responses Are Generated

LLMs generate text **one token at a time**, feeding each output back as input.
Every sampling decision compounds.

```
Prompt: "The best city to visit in Japan is"

Step 1: Model sees full prompt → logits → sample → "Tokyo"
Step 2: Model sees prompt + "Tokyo" → logits → sample → "."
Step 3: Model sees prompt + "Tokyo." → logits → sample → " It"
Step 4: Model sees prompt + "Tokyo. It" → logits → sample → " has"
...continues until max_tokens or stop token...
```

**Why this matters for temperature:**

At each step, temperature affects the sampling. Over 100 tokens:

- Temperature 0: every single token is the greedy choice. Completely deterministic.
- Temperature 0.7: each token has a *small* chance of being non-greedy. Over 100
  tokens, you'll see some variation, but the output is mostly coherent.
- Temperature 1.5: each token has a *significant* chance of being a surprise choice.
  Over 100 tokens, the randomness compounds and the output can go wildly off-track.

This **compounding effect** is why even small temperature changes feel significant
in long outputs. A 5% per-token divergence rate means roughly:

```
Probability of identical 100-token sequences:
  T=0.0: 100% (deterministic)
  T=0.3: ~60-80% (mostly the same)
  T=0.7: ~5-15%  (usually similar theme, different wording)
  T=1.0: ~0.1%   (very unlikely to match)
  T=1.5: ~0%     (virtually impossible to match)
```

---

## 8. Training Internals: What Actually Creates the Weights

Since temperature and seed only make sense once you understand that the model's
weights are frozen at inference time, here's a deeper look at what training does.

### The Objective: Next-Token Prediction (Causal Language Modeling)

```python
# Simplified training loop pseudocode
for batch in training_data:
    # batch = sequences of token IDs, e.g. [[101, 2003, 1996, ...], ...]

    # Forward pass: model predicts next token at every position
    logits = model(batch[:, :-1])        # input: all tokens except last
    targets = batch[:, 1:]                # target: all tokens except first

    # Loss: cross-entropy between predicted distribution and actual next token
    loss = cross_entropy(logits, targets)

    # Backward pass: compute gradients
    loss.backward()

    # Update weights
    optimizer.step()   # e.g., Adam optimizer
    optimizer.zero_grad()
```

Cross-entropy loss for a single position:

```
L = -log(P(correct_token))

If model gives P("Paris") = 0.9 for the correct answer "Paris":
  L = -log(0.9) = 0.105  (low loss, model is doing well)

If model gives P("Paris") = 0.01:
  L = -log(0.01) = 4.605  (high loss, model needs to adjust)
```

### Pre-training vs Fine-tuning vs RLHF

Modern LLMs go through multiple training stages:

```
Stage 1: Pre-training
├── Data: trillions of tokens from the internet, books, code
├── Objective: next-token prediction
├── Result: a "base model" that can complete text but isn't conversational
└── Cost: millions of dollars, weeks on thousands of GPUs

Stage 2: Supervised Fine-Tuning (SFT)
├── Data: thousands of (instruction, response) pairs written by humans
├── Objective: still next-token prediction, but on conversation format
├── Result: a model that follows instructions
└── Cost: much cheaper, hours to days

Stage 3: RLHF / DPO / Constitutional AI
├── Data: pairs of responses ranked by humans (or AI) as better/worse
├── Objective: make the model prefer the "better" response
├── Result: a model that's helpful, harmless, and honest
└── Cost: moderate
```

After all stages, the weights are frozen. Temperature and seed are applied
at inference time and have nothing to do with any of these training stages.

### What the Weights Encode

A transformer's weights encode **conditional probability distributions** over
the vocabulary given any context. Concretely:

```
Weight matrix W in attention layer:
  Encodes patterns like "after 'capital of France', attend strongly to
  geographic entities and country-capital relationships"

Weight matrix W in feedforward layer:
  Encodes patterns like "when the attended context involves France + capital,
  boost the logit for token 'Paris'"

These aren't stored as explicit rules — they're distributed across millions
of parameters in a way that's not human-readable. The patterns emerge from
the statistics of the training data.
```

---

## 9. Practical Decision Guide: Choosing Parameters

### Decision Flowchart

```
Is the output format rigid (JSON, code, structured data)?
├── YES → temperature=0, seed=fixed, top_p=irrelevant
│         Reasoning: you want the single most likely output every time.
│         Any randomness risks malformed output.
│
└── NO → Is correctness critical (factual Q&A, math, logic)?
    ├── YES → temperature=0.1-0.3, top_p=0.9
    │         Reasoning: slight randomness avoids degenerate repetition
    │         loops that greedy decoding sometimes falls into, while
    │         keeping the output highly focused.
    │
    └── NO → Is creativity/variety desired?
        ├── SOMEWHAT → temperature=0.7-0.9, top_p=0.95
        │              Reasoning: good balance of coherence and novelty.
        │              This is the sweet spot for most chat applications.
        │
        └── VERY MUCH → temperature=1.0-1.3, top_p=0.95
                        Reasoning: high variety but top_p prevents total
                        nonsense by cutting off the long tail.
                        Above 1.3 you risk incoherence.
```

### Anti-Patterns: What NOT to Do

```
❌ temperature=0 + top_p=0.1
   Why: top_p is irrelevant at T=0 (argmax ignores probabilities).
   Not harmful, just wasteful.

❌ temperature=2.0 + no top_p/top_k
   Why: extremely flat distribution + no filtering = the model picks
   random rare tokens. Output becomes gibberish.

❌ temperature=0 + seed=None for deterministic use cases
   Why: some APIs have minor nondeterminism even at T=0 due to
   floating-point GPU behavior. Setting a seed adds a safety net.

❌ temperature=1.5 for JSON/code generation
   Why: even a single wrong token breaks the entire output.
   A misplaced comma or wrong bracket makes the JSON unparseable.

❌ Changing temperature mid-conversation via API
   Why: not supported by any major API. Temperature applies to the
   entire completion, not individual tokens.
```

### The Parameters From Your Code, Explained

```python
TEMPERATURE  = 0      # Greedy decoding. Always pick most probable token.
MAX_TOKENS   = 4096   # Maximum output length in tokens (~3000 words).
"seed": 42            # Redundant with T=0 but harmless safety net.

# Why these choices make sense for test generation:
# - You want the SAME pytest script every time for the same input
# - JSON output must be structurally valid — no room for "creativity"
# - The task is pattern matching (action text → code), not creative writing
# - Reproducibility matters for CI/CD pipelines
```

---

## 10. What the Model CANNOT See

A common misconception is that these parameters somehow change the model's
"thinking." They don't. Here's what the model is unaware of:

```
The model has NO knowledge of:
  ✗ What temperature is set to
  ✗ What seed value was used
  ✗ Whether top_p or top_k filtering is active
  ✗ What max_tokens is set to (it doesn't know when it'll be cut off)
  ✗ Whether its output is being parsed as JSON or displayed to a human

The model's weights produce the SAME logits regardless of all these settings.
The logits flow into the sampling layer, which is ordinary code (not a neural
network) that applies these parameters.

Analogy: The model is a chef who always cooks the same dish the same way.
Temperature is how the waiter decides which portions to serve to the customer.
The chef doesn't know and doesn't care about the waiter's decisions.
```

---

## 11. Summary Table

| Parameter        | Where it acts     | When it's set          | Affects weights? | What it controls                              |
|------------------|-------------------|------------------------|------------------|-----------------------------------------------|
| Learning rate    | Training          | Before/during training | Yes              | Speed of weight updates                       |
| Batch size       | Training          | Before training        | Yes (indirectly) | Gradient estimation quality                   |
| Dataset          | Training          | Before training        | Yes              | What patterns the model learns                |
| **Temperature**  | **Sampling layer**| **Each API call**      | **No**           | **Sharpness of token probability distribution** |
| **Seed**         | **Sampling layer**| **Each API call**      | **No**           | **Reproducibility of random sampling**        |
| **Top-p**        | **Sampling layer**| **Each API call**      | **No**           | **Cumulative probability cutoff for candidates**|
| **Top-k**        | **Sampling layer**| **Each API call**      | **No**           | **Max number of candidate tokens**            |
| **Max tokens**   | **Stopping rule** | **Each API call**      | **No**           | **When to stop generating**                   |
| Freq. penalty    | Sampling layer    | Each API call          | No               | Discourages repeating the same tokens         |
| Presence penalty | Sampling layer    | Each API call          | No               | Encourages introducing new tokens             |

The bolded rows are the ones you'll interact with most often. Everything in
the sampling layer is just code that processes the frozen model's output — the
model itself is unchanged by any of these settings.
