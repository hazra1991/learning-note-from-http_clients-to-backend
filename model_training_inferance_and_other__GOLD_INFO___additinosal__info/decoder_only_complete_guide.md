# Decoder-Only Transformer Models — The Complete No-Black-Box Guide

> **What this is:** A deep, conversational walkthrough of how GPT-style decoder-only models work — from raw text to trained model. Every concept is demystified with real numerical examples. No hand-waving, no "it just works." You'll see exactly what goes in, what comes out, and why.

> **Who this is for:** Someone who knows the basic idea of transformers and neural networks but wants to truly understand the full pipeline with proper flow and clarity.

---

## Step 1: Tokenization & Vocabulary

### The Core Idea

Before a model can process text, it needs to convert it to numbers. But the question is: what's a "unit" of text?

**Tokens are NOT words.** They're sub-word pieces. This is critical to understand.

### Why Not Just Use Words?

If we used whole words as tokens, consider the problem:

```
"unhappiness"  → needs its own token
"unhappy"      → needs its own token
"happy"        → needs its own token
"happiness"    → needs its own token
```

That's 4 tokens for related concepts. And what about a word the model has never seen? Say `"unfathomableness"` — it would be an unknown token. Useless.

### What Actually Happens: BPE (Byte-Pair Encoding)

Most modern models (GPT, LLaMA, etc.) use BPE or a variant called SentencePiece. Here's how the vocabulary is built:

**Start with individual characters as your initial vocabulary:**

```
Initial vocab: {a, b, c, d, e, f, ..., z, A, B, ..., Z, 0-9, !, ?, space, ...}
```

**Scan the entire training corpus. Find the most frequent pair of adjacent tokens. Merge them into a new token. Repeat:**

```
Training text: "low low low low lowest lowest newer newer"

Iteration 1: Most frequent pair = ('l', 'o') → merge into 'lo'
Iteration 2: Most frequent pair = ('lo', 'w') → merge into 'low'
Iteration 3: Most frequent pair = ('e', 'r') → merge into 'er'
Iteration 4: Most frequent pair = ('n', 'e') → merge into 'ne'
Iteration 5: Most frequent pair = ('ne', 'w') → merge into 'new'
Iteration 6: Most frequent pair = ('new', 'er') → merge into 'newer'
...and so on until you reach your desired vocab size
```

**The vocab size is a design choice.** GPT-2 uses ~50,257 tokens. LLaMA uses ~32,000. GPT-4 uses ~100,000.

### Real Example — What Tokenization Actually Looks Like

```python
# Using tiktoken (OpenAI's tokenizer for GPT models)
import tiktoken

enc = tiktoken.encoding_for_model("gpt-4")

text = "unhappiness is unfathomable"
tokens = enc.encode(text)
print(tokens)        # [359, 21139, 1918, 374, 3432, 69, 589, 316, 481]

# Let's see what each token actually is:
for t in tokens:
    print(f"  Token ID {t} → '{enc.decode([t])}'")

# Output:
#   Token ID 359    → 'un'
#   Token ID 21139  → 'happiness'
#   Token ID 1918   → ' is'
#   Token ID 374    → ' un'
#   Token ID 3432   → 'f'
#   Token ID 69     → 'ath'
#   Token ID 589    → 'om'
#   Token ID 316    → 'able'
#   Token ID 481    → ' '
```

See what happened? `"unhappiness"` became `["un", "happiness"]`. The model can now understand `"un"` as a prefix that means negation — it reuses this knowledge across `"unhappy"`, `"unfair"`, `"undo"`, etc.

### What You Get After Tokenization

```
Input text:  "The cat sat"
Token IDs:   [464, 3797, 3332]
```

That's it. A sequence of integers. This is what enters the model. Every piece of text — books, code, PDFs — all becomes a sequence of integer IDs.

### Key Facts to Lock In

1. **Vocabulary is built ONCE, before training**, by scanning the corpus and running BPE merges.
2. **During training and inference**, the tokenizer just looks up the merge rules to convert text → token IDs. No new tokens are created.
3. **Vocab size is fixed** — it's a hyperparameter chosen by the model designer.
4. **Each token ID will get its own embedding vector** (that's our next step).

---

## Step 2: Embeddings

### The Core Idea

A token ID like `3797` (for "cat") is just a number. The model can't do math with a single integer in any meaningful way. So we convert each token ID into a **vector** — a list of numbers that represents that token in a high-dimensional space.

### How? The Embedding Matrix

The model has a big table called the **embedding matrix**. Think of it as a lookup table.

```
Vocab size:      50,257 tokens
Embedding dim:   768    (GPT-2 small)

Embedding matrix shape: [50,257 × 768]
```

That's 50,257 rows, one row per token in the vocabulary. Each row is a vector of 768 numbers.

```
Token ID 0     → [0.023, -0.041, 0.119, ..., 0.008]   (768 numbers)
Token ID 1     → [0.091, 0.005, -0.067, ..., 0.034]   (768 numbers)
Token ID 2     → [-0.012, 0.078, 0.045, ..., -0.056]  (768 numbers)
...
Token ID 3797  → [0.044, -0.023, 0.091, ..., 0.017]   (768 numbers)  ← "cat"
...
Token ID 50256 → [0.031, 0.062, -0.088, ..., 0.041]   (768 numbers)
```

**At initialization (before any training), these 768 numbers are random.** The word "cat" has no meaningful representation yet. It's just random noise.

### The Lookup Is Dead Simple

```python
import torch
import torch.nn as nn

# Create an embedding table: 50257 tokens, each gets a 768-dim vector
embedding_table = nn.Embedding(num_embeddings=50257, embedding_dim=768)

# Our token IDs from "The cat sat"
token_ids = torch.tensor([464, 3797, 3332])

# Look up embeddings — this is literally just indexing into the table
vectors = embedding_table(token_ids)

print(vectors.shape)  # torch.Size([3, 768])
```

That's it. No multiplication, no neural network magic. `embedding_table(token_ids)` is equivalent to:

```python
vectors = embedding_table.weight[token_ids]  # just row selection
```

Three token IDs go in, three vectors of size 768 come out.

### Why 768 Dimensions?

This is a **design choice** by the model architects:

| Model | Embedding Dimension |
|---|---|
| GPT-2 Small | 768 |
| GPT-2 Large | 1280 |
| GPT-3 (175B) | 12,288 |
| LLaMA 7B | 4,096 |
| LLaMA 70B | 8,192 |

More dimensions = the model can encode more nuanced meaning per token, but it costs more memory and compute.

### How Do These Random Vectors Become Meaningful?

**The embedding matrix is a learnable parameter.** It gets updated during backpropagation just like every other weight in the model.

Before training:
```
"cat" → [0.044, -0.023, 0.091, ...]   (random)
"dog" → [0.078, 0.012, -0.034, ...]   (random)
"sat" → [-0.008, 0.067, 0.033, ...]   (random)
```

After training on billions of sentences where "cat" and "dog" appear in similar contexts ("The cat sat", "The dog sat", "The cat ate", "The dog ate"):
```
"cat" → [0.821, -0.445, 0.332, ...]
"dog" → [0.798, -0.412, 0.351, ...]   ← very close to "cat"!
"sat" → [-0.234, 0.891, -0.123, ...]  ← far from both (different concept)
```

The training process pushes tokens that appear in similar contexts to have similar vectors. This is how meaning emerges from random numbers.

### What We Have So Far

```
"The cat sat"
      ↓ tokenizer
[464, 3797, 3332]
      ↓ embedding lookup
[[0.012, -0.034, ...],    ← shape: [3, 768]
 [0.044, -0.023, ...],
 [-0.008, 0.067, ...]]
```

### But There's a Problem

Look at those three vectors. There's nothing in them that tells the model the **order** of the tokens. The model sees three 768-dim vectors, but it doesn't know that "The" came first and "sat" came last.

`"The cat sat"` and `"sat cat The"` would produce the exact same set of vectors (just in different order in the matrix), but the model processes them through matrix operations that could easily lose that ordering.

This is why we need **positional encodings**.

---

## Step 3: Positional Encodings

### The Problem

Attention (which we'll cover next) works by comparing every token to every other token. It's a set operation — it doesn't inherently know that token 0 came before token 1. But word order matters enormously:

```
"The dog bit the man"   ← very different meaning from
"The man bit the dog"
```

Same tokens, same embeddings, but completely different meaning. The model needs to know **where** each token sits in the sequence.

### The Solution: Add Position Information to Each Embedding

Create another vector that encodes the **position** (0, 1, 2, ...) and **add it** to the token embedding:

```
final_embedding[i] = token_embedding[i] + position_embedding[i]
```

That's literally it. Element-wise addition.

```
"The" at position 0:   [0.012, -0.034, 0.056, ...] + [0.000, 1.000, 0.000, ...] = [0.012, 0.966, 0.056, ...]
"cat" at position 1:   [0.044, -0.023, 0.091, ...] + [0.841, 0.540, 0.841, ...] = [0.885, 0.517, 0.932, ...]
"sat" at position 2:   [-0.008, 0.067, 0.033, ...] + [0.909, -0.416, 0.909,...] = [0.901, -0.349, 0.942, ...]
```

Now the same token "cat" at position 1 vs position 5 will have **different** vectors entering the attention layers. Order is preserved.

### Two Approaches

**Approach 1: Learned Positional Embeddings (GPT-2, GPT-3, LLaMA)**

Exactly like the token embedding table, but indexed by position instead of token ID:

```python
# Token embedding table:    [50257 × 768]  — one row per vocab token
# Position embedding table: [1024 × 768]   — one row per possible position

token_embed = nn.Embedding(50257, 768)     # lookup by token ID
pos_embed   = nn.Embedding(1024, 768)      # lookup by position index

token_ids = torch.tensor([464, 3797, 3332])           # "The cat sat"
positions = torch.tensor([0, 1, 2])                    # their positions

tok_vectors = token_embed(token_ids)   # [3, 768]
pos_vectors = pos_embed(positions)     # [3, 768]

final_input = tok_vectors + pos_vectors  # [3, 768] — element-wise add
```

These position embeddings start random and are **learned during training**, just like token embeddings. The model discovers what properties each position should have.

**The 1024 here means GPT-2 can only handle sequences up to 1024 tokens.** There's no row for position 1025. This is one source of the "context length" limit.

**Approach 2: Sinusoidal (Original Transformer paper)**

Instead of learning positions, the original paper used fixed sine and cosine waves at different frequencies:

```
PE(pos, 2i)     = sin(pos / 10000^(2i/d_model))
PE(pos, 2i+1)   = cos(pos / 10000^(2i/d_model))
```

Think of it like a clock — second hand changes fast (fine position), minute hand changes slower (medium range), hour hand changes slowest (broad position). Each dimension of the positional vector oscillates at a different frequency.

In practice, **most modern models use learned positions** or **RoPE (Rotary Position Embeddings)** which encodes relative position through rotation of vectors.

### Updated Pipeline

```
"The cat sat"
      ↓ tokenizer
[464, 3797, 3332]
      ↓ token embedding lookup
[[0.012, -0.034, ...],       shape: [3, 768]
 [0.044, -0.023, ...],
 [-0.008, 0.067, ...]]
      ↓ + positional embedding
[[0.012, 0.966, ...],        shape: [3, 768]  ← now position-aware
 [0.885, 0.517, ...],
 [0.901, -0.349, ...]]
```

This is the **input to the transformer layers**.

### Quick Parameter Count

For GPT-2 Small:
```
Token embeddings:    50,257 × 768 = 38,597,376 parameters
Position embeddings: 1,024 × 768  =    786,432 parameters
                                    ───────────
Just embeddings alone:              ~39.4 million parameters
```

About a third of GPT-2 Small's 124 million parameters is just these two lookup tables.

---

## Step 4: The Attention Mechanism

This is where most explanations go wrong — they throw math at you without building the intuition first. We'll do it differently.

### The Core Problem Attention Solves

Consider this sentence:

```
"The cat sat on the mat because it was tired"
```

What does "it" refer to? The cat? The mat? **You** know it's the cat because cats get tired, mats don't.

Now consider:

```
"The cat sat on the mat because it was soft"
```

Now "it" refers to the mat! Same sentence structure, but the meaning of "it" changed based on a **different word** ("tired" vs "soft").

The model needs a way for every token to **look at every other token** and decide: "which other tokens are relevant to understanding **me** in this context?"

That's attention. Each token asks: **"Who should I pay attention to?"**

### The Intuition: Query, Key, Value

Think of it like a library search:

- **You walk into a library with a question (Query).**
- Every book on the shelf has a label on its spine (Key).
- You compare your question to each label. The better the match, the more relevant that book is.
- Then you pull relevant books and read their contents (Value).

Mapping to attention:

```
Query (Q): "What am I looking for?"     — what this token needs
Key (K):   "What do I contain?"         — what each token offers
Value (V): "Here's my actual content"   — what gets passed forward if selected
```

### How Q, K, V Are Created

Each token's embedding gets multiplied by three different weight matrices:

```python
# For each token embedding vector x (shape: [768])

Q = x @ W_Q    # [768] × [768, 768] → [768]   "what I'm looking for"
K = x @ W_K    # [768] × [768, 768] → [768]   "what I offer"
V = x @ W_V    # [768] × [768, 768] → [768]   "my actual content"
```

`W_Q`, `W_K`, `W_V` are **learned weight matrices**. They start random and get trained.

### Full Numerical Walkthrough

Let's use **4 dimensions** and a **3-token sentence** to see everything clearly.

```
Sentence: "The cat sat"
After embeddings + positions:

x_The = [1.0, 0.5, 0.3, 0.8]
x_cat = [0.6, 0.9, 0.7, 0.2]
x_sat = [0.3, 0.4, 0.8, 0.6]
```

Stacked into matrix X of shape `[3, 4]`:
```
X = [[1.0, 0.5, 0.3, 0.8],    ← "The"
     [0.6, 0.9, 0.7, 0.2],    ← "cat"
     [0.3, 0.4, 0.8, 0.6]]    ← "sat"
```

**Compute Q, K, V for all tokens at once:**

```
Q = X @ W_Q    →  [3, 4] × [4, 4] = [3, 4]
K = X @ W_K    →  [3, 4] × [4, 4] = [3, 4]
V = X @ W_V    →  [3, 4] × [4, 4] = [3, 4]
```

Manual computation of Q for "The" (row 0 of X):

```
Q_The[0] = 1.0×0.1 + 0.5×0.3 + 0.3×0.0 + 0.8×0.2 = 0.41
Q_The[1] = 1.0×0.2 + 0.5×0.1 + 0.3×0.3 + 0.8×0.0 = 0.34
Q_The[2] = 1.0×0.0 + 0.5×0.2 + 0.3×0.1 + 0.8×0.3 = 0.37
Q_The[3] = 1.0×0.1 + 0.5×0.0 + 0.3×0.2 + 0.8×0.1 = 0.24

Q_The = [0.41, 0.34, 0.37, 0.24]
```

After computing all:

```
Q = [[0.41, 0.34, 0.37, 0.24],    ← Q for "The"
     [0.33, 0.44, 0.23, 0.22],    ← Q for "cat"
     [0.27, 0.32, 0.36, 0.25]]    ← Q for "sat"

K = [[0.29, 0.42, 0.21, 0.57],    ← K for "The"
     [0.38, 0.33, 0.20, 0.29],    ← K for "cat"
     [0.30, 0.15, 0.25, 0.21]]    ← K for "sat"

V = [[0.44, 0.31, 0.38, 0.30],    ← V for "The"
     [0.29, 0.34, 0.41, 0.33],    ← V for "cat"
     [0.36, 0.27, 0.26, 0.33]]    ← V for "sat"
```

### Computing Attention Scores (Q × K^T)

Each token's Query asks: "How relevant is each other token's Key to me?"

This is a dot product. The 4 dimensions get consumed, producing one score per pair:

```
Scores = Q @ K^T    →  [3, 4] × [4, 3] = [3, 3]
```

**How [3,4] × [4,3] = [3,3]:** Each row of Q (a 4-dim vector) takes a dot product with each column of K^T (also 4-dim). The dot product collapses 4 dimensions into 1 number. You have 3 rows × 3 columns = 9 scores.

Manual example — "cat"'s Query dotted with "The"'s Key:

```
Q_cat   = [0.33, 0.44, 0.23, 0.22]
K_The   = [0.29, 0.42, 0.21, 0.57]

dot product = 0.33×0.29 + 0.44×0.42 + 0.23×0.21 + 0.22×0.57
            = 0.096 + 0.185 + 0.048 + 0.125
            = 0.454

This single number answers: "How relevant is 'The' to 'cat'?"
```

The full score matrix:

```
              "The"  "cat"  "sat"
"The" looks→ [0.52,  0.38,  0.27]   "The" finds itself most relevant
"cat" looks→ [0.46,  0.37,  0.24]   "cat" finds "The" most relevant
"sat" looks→ [0.44,  0.34,  0.26]   "sat" finds "The" most relevant
```

### Scaling

Divide by √d_k (square root of key dimension) to prevent softmax from becoming too peaked:

```
d_k = 4, √d_k = 2

Scaled = scores / 2
```

### The Causal Mask (Critical for Decoder Models)

In a decoder-only model, a token can **only attend to tokens that came before it** (and itself). It cannot look into the future — that would be cheating during training.

Set future positions to negative infinity:

```
              "The"   "cat"   "sat"
"The" looks→ [0.26,   -inf,   -inf]   ← can only see itself
"cat" looks→ [0.23,   0.19,   -inf]   ← can see "The" and itself
"sat" looks→ [0.22,   0.17,   0.13]   ← can see everything before it
```

This is what makes a model **autoregressive**.

### Softmax — Converting Scores to Weights

Softmax converts each row into a probability distribution (sums to 1.0). `e^(-inf) = 0`, so masked positions get zero weight.

```
softmax([0.26, -inf, -inf]) = [1.00, 0.00, 0.00]   ← "The" only attends to itself
softmax([0.23, 0.19, -inf]) = [0.51, 0.49, 0.00]   ← "cat" splits attention
softmax([0.22, 0.17, 0.13]) = [0.36, 0.34, 0.30]   ← "sat" attends to all three
```

**These are NOT prediction probabilities.** These are **attention weights** — they answer: "When computing the new representation for this token, how much should I borrow from each other token?"

### Weighted Sum of Values

Multiply weights by Value vectors to get context-blended output:

```
For "cat" (attention weights: [0.51, 0.49, 0.00]):

output_cat = 0.51 × V_The + 0.49 × V_cat + 0.00 × V_sat
           = 0.51 × [0.44, 0.31, 0.38, 0.30]
           + 0.49 × [0.29, 0.34, 0.41, 0.33]
           = [0.366, 0.325, 0.395, 0.315]
```

**Before attention:** "cat" only knew about itself.
**After attention:** "cat" contains information from "The" blended in. It's now context-aware.

### The Full Attention Formula

```
Attention(Q, K, V) = softmax(Q @ K^T / √d_k + mask) @ V
```

That's the entire attention mechanism in one line.

### Multi-Head Attention

One attention computation captures one "type" of relationship. But language has many simultaneous relationships. So the model runs **multiple attention heads in parallel**, each with their own W_Q, W_K, W_V.

**Key insight: multi-head is the SAME Q,K,V process repeated N times on different slices of the embedding.** Nothing fundamentally new.

```
GPT-2 Small:  768 dimensions, 12 heads
Each head gets: 768 / 12 = 64 dimensions

Head 1:  works on dimensions 0-63     → learns one type of relationship
Head 2:  works on dimensions 64-127   → learns another type
Head 3:  works on dimensions 128-191  → learns another type
...
Head 12: works on dimensions 704-767  → learns another type
```

Each head does the exact same attention process on its 64-dim slice. All run in parallel. Then concatenate back:

```
Head 1 output:  [seq_len, 64]  ─┐
Head 2 output:  [seq_len, 64]   │
Head 3 output:  [seq_len, 64]   ├─→ concatenate → [seq_len, 768]
...                              │
Head 12 output: [seq_len, 64]  ─┘
```

**Think of it this way:** Single-head attention is like reading a sentence and asking one question. Multi-head is asking 12 different questions simultaneously. Each reveals different relationships, and the answers are stitched together into a richer understanding.

Different heads learn different things:
- Some attend to the previous word
- Some track subject-verb agreement
- Some resolve coreference ("it" → "cat")
- Some attend to the first word of the sentence

---

## Step 5: The Full Transformer Block

Attention is the star, but each layer has more:

```
Input [seq_len, 768]
    │
    ├──────────────────────┐
    │                      │  (residual connection)
    ▼                      │
 Layer Norm                │
    │                      │
    ▼                      │
 Multi-Head Attention      │
    │                      │
    ▼                      │
  + ADD ◄──────────────────┘
    │
    ├──────────────────────┐
    │                      │  (residual connection)
    ▼                      │
 Layer Norm                │
    │                      │
    ▼                      │
 Feed-Forward Network      │
    │                      │
    ▼                      │
  + ADD ◄──────────────────┘
    │
    ▼
Output [seq_len, 768]
```

### Layer Normalization

Keeps numbers stable as they flow through layers. Normalizes each vector to mean 0, standard deviation 1, then applies learned scale and shift:

```
x = [4.0, 2.0, 0.0, 6.0]
mean = 3.0, std = 2.236
normalized = [0.447, -0.447, -1.342, 1.342]
output = gamma * normalized + beta    (gamma, beta are learned)
```

### Feed-Forward Network (FFN)

After attention blends info **across tokens** (horizontal mixing), FFN processes each token **independently** (vertical processing):

```
Attention:  "Let me gather context from other tokens"
FFN:        "Now let me think deeply about what I've gathered"
```

Two linear layers with activation:

```python
def feed_forward(x):
    hidden = gelu(x @ W1 + b1)     # [768] → [3072]  EXPAND (4× wider)
    output = hidden @ W2 + b2       # [3072] → [768]  COMPRESS back
    return output
```

The expansion to 4× creates more "thinking space" for the model — more room to detect complex patterns before compressing back.

**GELU** is the non-linearity. Without it, two stacked linear layers collapse into one (useless). GELU selectively suppresses some neurons and passes others, letting the network develop specialized features.

### Residual Connections (the + ADD)

```python
x = x + attention(layer_norm(x))    # don't replace x, ADD to it
x = x + ffn(layer_norm(x))          # each layer makes incremental adjustments
```

Two critical reasons:
1. **Gradient flow:** Gradients can flow directly through the additions during backprop, preventing vanishing gradients in deep networks.
2. **Incremental refinement:** Each layer adds a delta, never destroying the original information.

### Stacking Layers — The Deep Network

**Same shape in, same shape out** — so you can stack any number of blocks:

```
Input: [seq_len, 768]
  ↓
Block 1:  LN → Attention → + → LN → FFN → +  → [seq_len, 768]
  ↓
Block 2:  LN → Attention → + → LN → FFN → +  → [seq_len, 768]
  ↓
...
  ↓
Block 12: LN → Attention → + → LN → FFN → +  → [seq_len, 768]
  ↓
Final LayerNorm → [seq_len, 768]
```

**Every layer has its OWN separate weights.** Layer 1's W_Q is different from Layer 2's W_Q.

**Heads ≠ Layers.** Heads are 12 parallel attention patterns WITHIN one layer (horizontal). Layers are 12 sequential transformer blocks (vertical, making it "deep"). GPT-2 Small: 12 layers × 12 heads per layer = 144 total attention heads.

What each depth captures (experimentally verified):
```
Layers 1-3 (early):    Surface patterns — POS tags, local word patterns
Layers 4-8 (middle):   Syntax/semantics — subject-verb agreement, coreference
Layers 9-12 (late):    High-level reasoning — next-word prediction, facts
```

### Parameter Count for One Block

```
Attention (Q,K,V,O):  4 × (768 × 768) = 2,359,296
FFN (W1, b1, W2, b2): 768×3072 + 3072 + 3072×768 + 768 = 4,722,432
LayerNorms:           2 × (768 + 768) = 3,072
Block total:          ≈ 7,084,800

× 12 blocks = ≈ 85 million
+ embeddings = ≈ 39 million
────────────
GPT-2 Small ≈ 124 million parameters
```

---

## Step 6: Logits → Softmax → Prediction

### From Hidden State to Vocabulary Scores

After all transformer blocks, each token is a 768-dim context-aware vector. The model must answer: "Which of the 50,257 vocabulary tokens comes next?"

768 is the model's **internal thinking space**. 50,257 is the **answer space**. We need a projection:

```python
logits = output @ W_lm_head    # [seq_len, 768] × [768, 50257] = [seq_len, 50257]
```

**Weight tying:** In many models, W_lm_head is the **transpose of the token embedding matrix**. The same matrix that converts tokens → vectors at input is reused (transposed) to convert vectors → token scores at output.

Each of the 50,257 scores is a dot product between the hidden state and one column of the LM head. High dot product = the hidden state is "close" to that token's representation = high confidence.

### Softmax — Probabilities from Raw Scores

```
logits = [2.0, 1.0, 0.1, -1.0, 3.0]

e^2.0 = 7.389     →  7.389 / 31.666 = 0.233   (23.3%)
e^1.0 = 2.718     →  2.718 / 31.666 = 0.086   (8.6%)
e^0.1 = 1.105     →  1.105 / 31.666 = 0.035   (3.5%)
e^-1.0 = 0.368    →  0.368 / 31.666 = 0.012   (1.2%)
e^3.0 = 20.086    → 20.086 / 31.666 = 0.634   (63.4%)
                                        ─────
                                        1.000 ✓
```

Properties: largest logit → highest probability, everything positive, sums to 1.0.

### The Loss Function: Cross-Entropy

During training, we know the right answer:

```
loss = -log(probability of the correct token)

P(correct) = 1.0  → loss = 0.0      (perfect)
P(correct) = 0.5  → loss = 0.693    (okay)
P(correct) = 0.08 → loss = 2.526    (bad)
P(correct) = 0.001 → loss = 6.908   (terrible)
```

Higher confidence in the right answer → lower loss.

For the full sequence, average across all positions:

```
loss_pos0 = -log(P("cat"  | "The"))         = 2.8
loss_pos1 = -log(P("sat"  | "The cat"))     = 2.5
loss_pos2 = -log(P("on"   | "The cat sat")) = 3.1

total_loss = (2.8 + 2.5 + 3.1) / 3 = 2.8
```

### Grammar/Guided Generation (Inference Time)

During inference, grammar constraints sit between logits and softmax:

```
logits [50257] → Grammar mask (set invalid tokens to -inf) → softmax → sample
```

For valid JSON output, the grammar says: "Only `{`, `"`, or a digit are valid here. Set all others to -inf." The model's preferences among valid tokens are preserved.

---

## Step 7: Backpropagation and Optimizers

### What Backpropagation Is

The forward pass gave us a loss number (e.g., 2.8). Backprop answers: **for each of the 124 million parameters, which direction should I nudge it to make the loss smaller?**

### The Chain Rule

```
embedding → attention → FFN → ... → logits → loss

For each weight, the gradient tells you:
  gradient > 0  → weight is too high, decrease it
  gradient < 0  → weight is too low, increase it
  |gradient| large → this weight matters a lot
  |gradient| small → this weight barely matters
```

The gradient flows backward through ALL layers — from the loss, through the LM head, through layer 12, 11, 10, all the way to the embedding table. Every learnable parameter gets a gradient.

### Why Not Simple Gradient Descent

The simple update `w = w - lr × gradient` has problems:

1. **Noisy gradients** — computed on small batches, not the full dataset. Weights oscillate.
2. **One learning rate for all** — some weights need big updates, others tiny.
3. **Flat regions and sharp valleys** — learning stalls or explodes.

### Adam Optimizer

Adam maintains two extra numbers per weight:

```
m = momentum — running average of recent gradients (direction)
v = velocity — running average of squared gradients (magnitude)
```

What each does:

```
Momentum (m):
  "Don't just look at this one gradient. Look at the TREND."
  Smooths out noise. If last 10 gradients say "go left",
  keep going left even if this one says "slightly right."

Velocity (v):
  "How much has this weight been bouncing around?"
  Large gradients → v is large → take SMALLER steps (prevent explosion)
  Small gradients → v is small → take LARGER steps (escape plateaus)
  Each weight gets its OWN effective learning rate.
```

### Memory Cost of Adam

```
GPT-2 Small: 124M parameters
  Model weights:  496 MB
  Adam m values:  496 MB
  Adam v values:  496 MB
  Total:          ~1.5 GB

GPT-3 175B:
  Model weights:  350 GB
  Adam states:    1,400 GB
  Total:          ~1.75 TB
```

### One Complete Training Step

```
1. Forward:   batch [32, 1024] → embeddings → 12 layers → logits → loss = 3.42
2. Backward:  compute 124M gradients
3. Adam:      update 124M weights using momentum + velocity
4. Repeat with next batch
```

---

## Step 8: Self-Supervised Learning — How Training Data Is Prepared

### Labels Come From the Data Itself

The genius: you don't need human labelers. You just shift the text by one position:

```
Training text:  "The cat sat on the mat"

Input:          "The  cat  sat  on  the"
Target:         "cat  sat  on   the mat"
```

Every sentence ever written is simultaneously the input AND the answer. You never run out of labeled data — you run out of compute first.

### In Code — Shockingly Simple

```python
tokens = torch.tensor([464, 3797, 3332, 319, 262, 2603])

input_tokens  = tokens[:-1]    # [464, 3797, 3332, 319, 262]
target_tokens = tokens[1:]     # [3797, 3332, 319, 262, 2603]

logits = model(input_tokens)   # [5, 50257]
loss = F.cross_entropy(logits.view(-1, 50257), target_tokens.view(-1))
```

The causal mask ensures each position only sees prior tokens:

```
Position 0: sees "The"                    → must predict "cat"
Position 1: sees "The cat"                → must predict "sat"
Position 2: sees "The cat sat"            → must predict "on"
Position 3: sees "The cat sat on"         → must predict "the"
Position 4: sees "The cat sat on the"     → must predict "mat"
```

From one sequence of 6 tokens, we get 5 training examples. All computed in a single forward pass.

### How Raw Data Becomes Training Batches

```
Step 1: Collect — web pages, books, code, Wikipedia, papers, forums
Step 2: Clean — remove HTML, deduplicate, filter quality
Step 3: Tokenize — convert all text to token IDs using BPE (done once)
Step 4: Chunk — split into fixed-length sequences (e.g., 1024 tokens)
        Documents separated by <|endoftext|> token
Step 5: Batch — group sequences into batches (e.g., 32 sequences per batch)
```

### What the Loss Looks Like Over Training

```
Step 0:       loss = 10.8    (random model — equal prob to all 50,257 tokens)
Step 1000:    loss = 6.2     (learning common words: "the", "a", "is")
Step 10000:   loss = 4.1     (learning grammar: "The cat ___" → verb)
Step 100000:  loss = 3.2     (learning facts: "Paris is the capital of ___")
Step 300000:  loss = 2.8     (nuanced predictions)
```

Initial loss ≈ log(50,257) ≈ 10.8 makes perfect mathematical sense.

### The Complete Training Pipeline

```
ONCE (before training):
  Raw text → Clean → BPE (builds vocab) → Token IDs → Chunked sequences

TRAINING LOOP (millions of steps):
  for step in range(300_000):
      batch = load_next_batch()             # [32, 1024]
      inputs  = batch[:, :-1]               # [32, 1023]
      targets = batch[:, 1:]                # [32, 1023]

      embeddings = tok_embed(inputs) + pos_embed(positions)
      hidden = embeddings
      for layer in transformer_layers:
          hidden = layer(hidden)
      hidden = final_layer_norm(hidden)
      logits = lm_head(hidden)              # [32, 1023, 50257]

      loss = cross_entropy(logits, targets)
      loss.backward()                       # backprop
      optimizer.step()                      # Adam update
      optimizer.zero_grad()

RESULT: A model that can predict the next token given any context.
```

---

> **End of Decoder-Only Guide.**
> For the Encoder-Only (BERT) architecture, see the companion guide: `encoder_only_complete_guide.md`
> For a dense deep-reference, see: `transformer_deep_reference.md`
