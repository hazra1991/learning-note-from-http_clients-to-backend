# Transformer Deep Reference — The Quick-but-Deep Refresher

> **What this is:** A dense reference for someone who already understands transformers and needs to refresh deeply in minutes. Not a summary. Not an overview. Every line carries weight. If a section feels too brief, the full discussion is in the companion guides.

> **How to use:** Jump to any section. Each is self-contained but cross-references where needed.

---

## 1. Tokenization

**Method:** BPE (Byte-Pair Encoding) or variants (WordPiece for BERT, SentencePiece for LLaMA).

**Mechanism:** Start with character-level vocabulary. Iteratively merge the most frequent adjacent pair into a new token. Repeat until desired vocab size is reached. This is done ONCE before training.

**Result:** Subword tokens, not words. `"unhappiness"` → `["un", "happiness"]`. Handles unseen words by decomposition. Common words stay whole; rare words get split.

**Vocab sizes:** GPT-2: 50,257 | LLaMA: 32,000 | GPT-4: ~100,000 | BERT: 30,522

**During training/inference:** Tokenizer applies pre-learned merge rules. No new tokens created. Text → sequence of integer IDs.

```python
# tiktoken example
enc = tiktoken.encoding_for_model("gpt-4")
tokens = enc.encode("The cat sat")  # [464, 3797, 3332]
```

---

## 2. Embeddings

**Token Embedding Matrix:** `[vocab_size, d_model]` — one row per token. Pure lookup (indexing, not multiplication).

```python
embedding_table = nn.Embedding(50257, 768)
vectors = embedding_table(token_ids)  # equivalent to: embedding_table.weight[token_ids]
```

**Initialization:** Random. Becomes meaningful through training — tokens appearing in similar contexts converge to similar vectors.

**Positional Embeddings:** Separate table `[max_seq_len, d_model]`. Added element-wise to token embeddings.

```
final_input = token_embed(ids) + pos_embed(positions)
```

Types: Learned (GPT-2, BERT), Sinusoidal (original transformer), RoPE (LLaMA, Mistral — encodes relative position via rotation).

**Max sequence length** is determined by the position embedding table size (1024 for GPT-2, 512 for BERT).

**BERT adds a third:** Segment embeddings `[2, d_model]` — marks sentence A (0) vs sentence B (1).

```
BERT: final = token_embed + pos_embed + segment_embed
GPT:  final = token_embed + pos_embed
```

**Parameter count (GPT-2 Small):**
```
Token:    50,257 × 768 = 38.6M
Position: 1,024 × 768  = 0.8M
Total embeddings:       ≈ 39.4M (31% of 124M total)
```

---

## 3. Attention Mechanism

### Core Formula

```
Attention(Q, K, V) = softmax(Q·K^T / √d_k + mask) · V
```

### Step-by-Step

1. **Project:** `Q = X·W_Q`, `K = X·W_K`, `V = X·W_V` — three separate learned projections
2. **Score:** `S = Q·K^T` — shape `[seq, seq]`. Entry `S[i][j]` = how much token i should attend to token j
3. **Scale:** `S = S / √d_k` — prevents softmax saturation
4. **Mask (decoder only):** Set `S[i][j] = -inf` where `j > i` — prevents looking at future
5. **Normalize:** `W = softmax(S)` — each row sums to 1.0. These are attention weights, NOT prediction probabilities
6. **Blend:** `Output = W · V` — weighted combination of Value vectors

### Shape Journey (single head)

```
X: [seq, d_model] → Q,K,V: [seq, d_k] → Scores: [seq, seq] → Output: [seq, d_k]
```

### Multi-Head

Split d_model into h heads, each with d_k = d_model/h dimensions. Run attention independently per head. Concatenate. Project.

```
GPT-2 Small: d_model=768, h=12, d_k=64
Each head: Q,K,V are [seq, 64]. Scores are [seq, seq]. Output is [seq, 64].
Concatenate 12 heads: [seq, 768]. Final projection W_O: [768, 768] → [seq, 768].
```

**Heads ≠ Layers.** Heads are parallel within one layer (horizontal). Layers are sequential (vertical).

Different heads learn different patterns: previous-word attention, subject-verb tracking, coreference resolution, positional patterns.

### Causal Mask (Decoder) vs No Mask (Encoder)

```
Decoder:  Lower-triangular mask. Token i attends to positions 0..i only.
Encoder:  No mask. Every token attends to every other token. Full bidirectional.
```

This is the single biggest architectural difference between encoder and decoder.

---

## 4. Transformer Block

```
x = x + MultiHeadAttention(LayerNorm(x))    # attention + residual
x = x + FeedForward(LayerNorm(x))            # FFN + residual
```

### Components

**LayerNorm:** Normalizes each vector to mean=0, std=1, then applies learned γ (scale) and β (shift). Purpose: numerical stability across deep layers.

**Feed-Forward Network:** Two linear layers with GELU activation.
```
FFN(x) = GELU(x·W1 + b1)·W2 + b2
Shapes: [d_model] → [4·d_model] → [d_model]
GPT-2:  [768] → [3072] → [768]
```
The 4× expansion creates more "feature detection" capacity. GELU provides non-linearity (without it, two linear layers collapse to one). FFN processes each token independently — no cross-token mixing (that's attention's job).

**Residual Connections:** `x = x + sublayer(x)`. Two purposes:
1. Gradient highway — prevents vanishing gradients in deep networks
2. Incremental refinement — each layer adds a delta, never destroys original information

### Stacking

Same shape in, same shape out → stack N blocks. Each layer has its OWN weights.

```
GPT-2 Small:  12 layers, 12 heads/layer → 144 total attention heads
GPT-3:        96 layers, 96 heads/layer → 9,216 total attention heads
LLaMA 70B:    80 layers, 64 heads/layer → 5,120 total attention heads
```

**Depth captures hierarchy:**
```
Early layers (1-3):    Surface features — POS, token identity, local patterns
Middle layers (4-8):   Syntactic/semantic — agreement, phrases, coreference
Late layers (9-12):    Task-specific reasoning — prediction, factual recall
```

### Parameter Count Per Block (GPT-2 Small)

```
Attention:  4 × (768 × 768) = 2.36M   (Q, K, V, O projections)
FFN:        768×3072 + 3072×768 = 4.72M  (up and down projections + biases)
LayerNorm:  2 × 768×2 = 3K
Block total: ~7.08M
× 12 blocks = ~85M + ~39M embeddings = ~124M total
```

---

## 5. Output: Logits → Softmax → Loss

### LM Head (Decoder)

```
logits = hidden @ W_lm_head    # [seq, d_model] × [d_model, vocab_size] = [seq, vocab_size]
```

Often uses **weight tying**: `W_lm_head = token_embedding.weight.T`. Same matrix, transposed.

Each logit = dot product of hidden state with a vocabulary token's representation. High dot product = model thinks this token is likely.

### Softmax

```
P(token_i) = e^(logit_i) / Σ_j e^(logit_j)
```

Converts raw scores to valid probability distribution (positive, sums to 1.0). Amplifies differences between logits.

### Cross-Entropy Loss

```
loss = -log(P(correct_token))

P = 1.0 → loss = 0.0     (perfect)
P = 0.5 → loss = 0.693
P = 0.01 → loss = 4.605  (bad)
```

**Decoder:** Loss computed at every position (each predicts next token).
**Encoder (BERT):** Loss computed only at masked positions (15% of sequence).

### Grammar/Guided Generation (Inference Only)

Sits between logits and softmax. Sets disallowed token logits to -inf. After softmax, these become P=0. Model's preferences among valid tokens are preserved.

---

## 6. Training

### Self-Supervised Objective

**Decoder (GPT):** Next-token prediction. Shift text by 1:
```
Input:  tokens[:-1]   "The  cat  sat  on   the"
Target: tokens[1:]    "cat  sat  on   the  mat"
```
Every position predicts the next token. Causal mask ensures no cheating.

**Encoder (BERT):** Masked Language Modeling. Mask 15% of tokens (80% [MASK], 10% random, 10% unchanged). Predict originals.
```
Input:  "The [MASK] sat on [MASK] mat"
Target: positions 1→"cat", 4→"the"
```
Plus optional NSP (Next Sentence Prediction) — later found unnecessary.

### Data Pipeline

```
1. Collect: web (Common Crawl), books, Wikipedia, code, papers
2. Clean: dedup, filter quality, remove boilerplate
3. Tokenize: BPE → integer sequences (done once, saved to disk)
4. Chunk: pack into fixed-length sequences (1024 for GPT-2, 512 for BERT)
5. Batch: group sequences (batch size 32-3M tokens per step)
```

### Training Loop

```python
for step in range(num_steps):
    batch = next_batch()              # [batch_size, seq_len]
    inputs, targets = batch[:, :-1], batch[:, 1:]
    logits = model(inputs)            # forward pass
    loss = cross_entropy(logits, targets)
    loss.backward()                   # backpropagation
    optimizer.step()                  # weight update (Adam)
    optimizer.zero_grad()
```

### Backpropagation

Chain rule applied backwards through every operation. For each of N parameters, computes:
```
gradient = ∂loss/∂weight
```
Gradient > 0 → weight too high → decrease. Gradient < 0 → weight too low → increase. |gradient| = magnitude of needed change.

Flows through ALL layers: loss → LM head → layer N → ... → layer 1 → embeddings. Residual connections prevent gradient vanishing.

### Adam Optimizer

Maintains per-weight state:
```
m = β1·m + (1-β1)·gradient         (momentum: smoothed direction)
v = β2·v + (1-β2)·gradient²        (velocity: smoothed magnitude)
weight -= lr · m_corrected / (√v_corrected + ε)
```

**Momentum:** Smooths noisy gradients. Follows the trend, not individual noisy steps.
**Velocity:** Adaptive learning rate per weight. Large gradients → smaller steps. Small gradients → larger steps.

**Typical hyperparameters:** lr=1e-4, β1=0.9, β2=0.999, ε=1e-8

**Memory cost:** 2× model size (m and v per parameter). GPT-2: 1.5 GB total. GPT-3: ~1.75 TB total.

**AdamW** (what most models actually use): Adam + weight decay (`w *= (1-decay)` each step). Prevents weights from growing unboundedly.

### Loss Trajectory

```
Step 0:      ~log(vocab_size) ≈ 10.8  (random, uniform prediction)
Step 1K:     ~6.2  (common words)
Step 10K:    ~4.1  (grammar)
Step 100K:   ~3.2  (facts, patterns)
Step 300K:   ~2.8  (nuanced prediction)
```

---

## 7. Decoder vs Encoder vs Encoder-Decoder

### Decoder-Only (GPT, LLaMA, Claude)

```
Mask: Causal | Task: Next-token | Direction: Left-to-right | Best for: Generation
```

### Encoder-Only (BERT, RoBERTa)

```
Mask: None | Task: MLM (fill blanks) | Direction: Bidirectional | Best for: Understanding
```

### Encoder-Decoder (T5, BART)

```
Encoder: bidirectional attention on input
Decoder: causal attention on output + cross-attention to encoder
Task: Sequence-to-sequence (translation, summarization)
```

Cross-attention: Decoder's Q attends to encoder's K and V. Decoder asks "what parts of the input are relevant to generating this output token?"

---

## 8. Inference (Decoder — Generation)

**Forward pass only.** No backpropagation, no gradient computation, no optimizer.

### Autoregressive Generation

```
Input:  "The cat"
Step 1: model("The cat") → logits → softmax → sample "sat"
Step 2: model("The cat sat") → logits → softmax → sample "on"
Step 3: model("The cat sat on") → logits → softmax → sample "the"
...repeat until stop condition
```

Each step appends one token and re-runs the forward pass. (KV-caching optimizes this — cache K,V from previous positions so only the new token needs full computation.)

### Sampling Strategies

**Greedy:** Always pick highest probability token. Deterministic but can be repetitive.

**Temperature:** Scale logits before softmax: `logits / T`
```
T < 1: sharper distribution → more confident, less creative
T = 1: unchanged
T > 1: flatter distribution → more random, more creative
```

**Top-k:** Keep only top k tokens, zero out the rest, re-normalize.

**Top-p (nucleus):** Keep smallest set of tokens whose cumulative probability ≥ p, zero out rest, re-normalize.

**Grammar/guided:** Mask invalid tokens to -inf before softmax. Ensures output conforms to structure (JSON, code, etc.).

---

## 9. Key Dimensions Quick Reference

| Model | d_model | Layers | Heads | d_k | FFN | Vocab | Max Seq | Params |
|---|---|---|---|---|---|---|---|---|
| GPT-2 Small | 768 | 12 | 12 | 64 | 3,072 | 50,257 | 1,024 | 124M |
| GPT-2 Large | 1,280 | 36 | 20 | 64 | 5,120 | 50,257 | 1,024 | 774M |
| BERT-base | 768 | 12 | 12 | 64 | 3,072 | 30,522 | 512 | 110M |
| BERT-large | 1,024 | 24 | 16 | 64 | 4,096 | 30,522 | 512 | 340M |
| GPT-3 | 12,288 | 96 | 96 | 128 | 49,152 | 50,257 | 2,048 | 175B |
| LLaMA 7B | 4,096 | 32 | 32 | 128 | 11,008 | 32,000 | 2,048 | 7B |
| LLaMA 70B | 8,192 | 80 | 64 | 128 | 28,672 | 32,000 | 2,048 | 70B |

**Pattern:** d_k = d_model / num_heads. FFN = 4 × d_model (approximately). More params = more layers AND wider dimensions.

---

## 10. Parameter Count Formula

```
Per transformer block:
  Attention: 4 × d_model²           (W_Q, W_K, W_V, W_O)
  FFN:       2 × d_model × d_ff     (up + down projections)
  LayerNorm: 4 × d_model            (2 norms × scale + shift)
  ≈ 4·d² + 8·d²  = 12·d²           (when d_ff = 4·d)

Total ≈ N_layers × 12·d² + vocab × d + seq_len × d

GPT-2 Small:  12 × 12 × 768² ≈ 85M + 39M embeddings ≈ 124M ✓
```

---

## 11. The Relationship Between Everything

```
                    ┌─────── PRETRAINING ───────┐
                    │                            │
   Raw Text ──→ Tokenize ──→ Embed+Position ──→ │ N × Transformer Block │ ──→ LM Head ──→ Softmax ──→ Loss
                    │         (lookup)           │   (Attn + FFN + Res)  │    (project)   (probs)    (cross-ent)
                    │                            │                        │
                    │                            └────────────────────────┘
                    │                                       ↑
                    │                              Backprop + Adam
                    │                            (update ALL weights)
                    │
                    │         ┌─────── INFERENCE ───────┐
                    │         │                          │
   Prompt ──→ Tokenize ──→ Embed+Position ──→ │ Same blocks │ ──→ LM Head ──→ [Grammar] ──→ Softmax ──→ Sample
                              (lookup)         │ (frozen)    │    (project)    (optional)    (probs)    (pick one)
                                               └─────────────┘
                                               No backprop. Forward only.
```

---

> **Companion guides:**
> - `decoder_only_complete_guide.md` — Full teaching walkthrough with numerical examples
> - `encoder_only_complete_guide.md` — BERT specifics with comparisons to decoder
