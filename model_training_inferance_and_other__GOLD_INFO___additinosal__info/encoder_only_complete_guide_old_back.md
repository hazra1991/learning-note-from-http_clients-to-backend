# Encoder-Only Transformer Models (BERT) — The Complete No-Black-Box Guide

> **What this is:** A deep walkthrough of how BERT-style encoder-only models work — what's the same as decoder models, what's different, and exactly why. If you've read the decoder guide first, this builds directly on that understanding.

> **Prerequisite:** Familiarity with decoder-only models (tokenization, embeddings, attention, transformer blocks, softmax, loss). See `decoder_only_complete_guide.md` for the full walkthrough.

---

## The Big Picture: Same Engine, Different Configuration

The encoder and decoder share the same core transformer machinery. Here's the exact split:

```
SAME (identical mechanics):
  ✓ Tokenization (BERT uses WordPiece — a BPE variant, same concept)
  ✓ Token embeddings (lookup table, random at first, learned during training)
  ✓ Positional embeddings (learned, same as GPT-2)
  ✓ Transformer blocks (LayerNorm → Attention → + → LayerNorm → FFN → +)
  ✓ Multi-head attention (Q, K, V, same math, same dot products)
  ✓ Backpropagation + Adam optimizer
  ✓ Self-supervised learning (labels come from the data itself)

DIFFERENT:
  ✗ The attention mask — no causal mask, fully bidirectional
  ✗ The training objective — Masked Language Modeling, not next-token prediction
  ✗ Special tokens — [CLS], [SEP], [MASK]
  ✗ Segment embeddings — a third embedding type
  ✗ What positions get a loss — only masked positions, not every position
  ✗ What the model is optimized FOR — understanding, not generation
```

Let's go through each difference in detail.

---

## Difference 1: The Attention Mask — Bidirectional

This is the biggest architectural difference between encoder and decoder.

### Decoder (GPT): Causal Mask — Can Only Look Backward

```
              "The"  "cat"  "sat"  "on"  "the"
"The" sees  → [ ✓      ✗      ✗     ✗      ✗  ]
"cat" sees  → [ ✓      ✓      ✗     ✗      ✗  ]
"sat" sees  → [ ✓      ✓      ✓     ✗      ✗  ]
"on"  sees  → [ ✓      ✓      ✓     ✓      ✗  ]
"the" sees  → [ ✓      ✓      ✓     ✓      ✓  ]
```

Each token can only attend to tokens before it (and itself). Future is masked with -inf.

### Encoder (BERT): No Mask — Sees Everything

```
              "The"  "cat"  "sat"  "on"  "the"
"The" sees  → [ ✓      ✓      ✓     ✓      ✓  ]
"cat" sees  → [ ✓      ✓      ✓     ✓      ✓  ]
"sat" sees  → [ ✓      ✓      ✓     ✓      ✓  ]
"on"  sees  → [ ✓      ✓      ✓     ✓      ✓  ]
"the" sees  → [ ✓      ✓      ✓     ✓      ✓  ]
```

Every token sees every other token in both directions. No masking at all.

### Why Bidirectional?

Because BERT isn't trying to generate text left-to-right. It's trying to **understand** the full sentence.

When you read:
```
"The cat sat on the mat because it was soft"
```

You use **both** directions to understand that "it" refers to "mat" — you look backward at "mat" AND forward at "soft." A decoder can only look backward, so it's weaker at understanding tasks.

### What This Means in the Attention Math

Remember from the decoder guide, the attention formula:

```
Attention(Q, K, V) = softmax(Q @ K^T / √d_k + mask) @ V
```

In GPT, `mask` is a triangle of -inf values that blocks future positions.
In BERT, `mask` is **all zeros** — nothing is blocked. Every position attends to every other position freely.

The Q, K, V computation, the dot products, the scaling, the softmax, the weighted sum of Values — all **exactly the same math**. The only difference is removing the causal mask.

### The Consequence: BERT Can't Generate Text

This bidirectional attention means BERT sees the **entire input at once**. If you ask BERT to predict the next word after "The cat sat", it says: "I need to see the WHOLE sentence. What comes after? I need that context too."

BERT has no mechanism for generating token after token because it was never trained that way. It's designed to **fill in blanks**, not **continue text**.

```
BERT is great at:                    BERT is bad at:
  - Understanding sentences           - Generating new text
  - Classifying text (spam/not spam)  - Continuing a prompt
  - Finding similar sentences          - Writing stories
  - Answering questions about text     - Chat / conversation
  - Named entity recognition           - Open-ended generation
```

---

## Difference 2: The Training Objective — Masked Language Modeling (MLM)

### Why GPT's Objective Doesn't Work for BERT

GPT's training task: "Given all previous tokens, predict the next one."

If BERT used this, it would be cheating — every token can see every other token (including the "future"), so the answer is already visible in the input. It would just learn to copy.

### BERT's Solution: Randomly Hide Tokens, Then Predict Them

```
Original:    "The cat sat on the mat"
Masked:      "The [MASK] sat on [MASK] mat"
Task:        Predict what's behind the masks
Answers:     position 1 → "cat", position 4 → "the"
```

This is called **Masked Language Modeling (MLM).**

The model can see the full context on BOTH sides of the mask — it uses "The ___ sat on ___ mat" to figure out the blanks. This is fundamentally different from GPT which only sees left context.

### The 80/10/10 Masking Strategy

BERT masks **15%** of tokens in each sequence. But not all become `[MASK]`. The selected tokens get one of three treatments:

```
Of the 15% selected tokens:
  80% → replaced with [MASK] token
  10% → replaced with a RANDOM token from vocabulary
  10% → kept UNCHANGED

Example with 20 tokens (15% ≈ 3 tokens selected):

Original:    "The cat sat on the soft mat because it was very comfortable"
Selected:    positions 1 ("cat"), 7 ("because"), 10 ("very")

Position 1 ("cat"):     80% chance → becomes [MASK]
Position 7 ("because"): 10% chance → becomes "hamburger" (random token)
Position 10 ("very"):   10% chance → stays "very" (unchanged)

Result:      "The [MASK] sat on the soft mat hamburger it was very comfortable"
Task:        Predict original tokens at positions 1, 7, and 10
```

### Why This 80/10/10 Split?

If you ALWAYS used `[MASK]`, the model learns a shortcut: "I only need to make predictions when I see the special `[MASK]` token." But during fine-tuning and real usage, there's no `[MASK]` token! The model would be confused.

By sometimes using random tokens or keeping the original:
- **80% [MASK]**: The core task — predict from context alone
- **10% random**: Forces the model to stay alert — "any token might be wrong, I should understand every position"
- **10% unchanged**: Forces the model to maintain good representations even for correct tokens — it can't just ignore non-`[MASK]` positions

The model must maintain a high-quality representation for **every** token, not just masked positions.

---

## Difference 3: Special Tokens and Extra Embeddings

### BERT's Special Tokens

BERT introduces three special tokens that GPT doesn't have:

```
[CLS]  — "Classification" token. Always added at position 0.
          Its output vector becomes a summary of the entire input.

[SEP]  — "Separator" token. Marks the boundary between two sentences.

[MASK] — "Mask" token. Replaces tokens during MLM training.
```

A typical BERT input looks like:

```
Single sentence:   [CLS] The cat sat on the mat [SEP]
Two sentences:     [CLS] The cat sat on the mat [SEP] It was fluffy [SEP]
```

### The [CLS] Token — Why It's Special

The [CLS] token is interesting. It starts as just another token with its own embedding. But because it attends to ALL other tokens (bidirectional attention) and ALL other tokens attend to IT, after 12 layers of attention it accumulates a "summary" of the entire sequence.

```
[CLS] at layer 0:  Just the [CLS] embedding + position 0 embedding. Meaningless.

[CLS] at layer 12: Has attended to every token. Every token has attended to it.
                    Contains a compressed representation of the entire input.
                    Shape: [768] — one vector that represents the whole sequence.
```

This [CLS] output is used as the input to classification heads:

```
[CLS] output [768] → Linear [768, 2] → softmax → [spam, not_spam]
[CLS] output [768] → Linear [768, 3] → softmax → [positive, neutral, negative]
```

### Segment Embeddings — The Third Embedding

Because BERT processes two sentences at once, it needs to know which tokens belong to which sentence. GPT doesn't have this problem (it only processes one stream left-to-right).

BERT adds a **third** embedding on top of token + position:

```
GPT input:
  final = token_embedding + position_embedding

BERT input:
  final = token_embedding + position_embedding + segment_embedding
```

```
Tokens:    [CLS] The cat sat [SEP] It was fluffy [SEP]
Segments:  [ 0    0   0   0    0    1   1    1     1  ]
            ↑ Sentence A (all 0)    ↑ Sentence B (all 1)
```

The segment embedding table is tiny — just 2 rows (segment 0 and segment 1), each of size 768. It's learned during training.

```python
segment_embed = nn.Embedding(2, 768)  # just 2 rows

segments = torch.tensor([0, 0, 0, 0, 0, 1, 1, 1, 1])
seg_vectors = segment_embed(segments)  # [9, 768]
```

---

## Difference 4: What Gets a Loss — Only Masked Positions

### GPT: Every Position Predicts

```
Input:   "The  cat  sat  on   the"
Predict:  cat  sat  on   the  mat    ← ALL 5 positions contribute to loss

loss = average of 5 cross-entropy losses
```

### BERT: Only Masked Positions Predict

```
Input:   "The  [MASK]  sat  on  [MASK]  mat"
Predict:        cat                the          ← ONLY 2 positions contribute

loss = average of 2 cross-entropy losses
```

In code, this looks like:

```python
# GPT: loss on every position
logits = gpt_model(input_tokens)                    # [seq_len, vocab_size]
loss = cross_entropy(logits, target_tokens)          # all positions

# BERT: loss only on masked positions
logits = bert_model(masked_input)                    # [seq_len, vocab_size]
masked_logits = logits[mask_positions]               # [num_masked, vocab_size]
masked_targets = original_tokens[mask_positions]     # [num_masked]
loss = cross_entropy(masked_logits, masked_targets)  # only masked positions
```

This means BERT is less "data efficient" per sequence — only 15% of tokens contribute to the loss (vs 100% for GPT). But the bidirectional context makes up for it with richer representations.

---

## Difference 5: BERT's Second Training Task — Next Sentence Prediction (NSP)

In addition to MLM, the original BERT was trained with a second objective: predict whether sentence B actually follows sentence A.

```
Positive example (50% of training data):
  Input: "[CLS] The cat sat on the mat [SEP] It was a fluffy Persian [SEP]"
  Label: IsNext (1)
  (These sentences actually appear consecutively in the training data)

Negative example (50% of training data):
  Input: "[CLS] The cat sat on the mat [SEP] Stock prices fell sharply [SEP]"
  Label: NotNext (0)
  (Sentence B is randomly sampled from elsewhere in the corpus)
```

### How NSP Works

The [CLS] token's output vector is passed through a simple binary classifier:

```
[CLS] output: [768]
      ↓
Linear layer: [768] → [2]   (two classes: IsNext, NotNext)
      ↓
Softmax: [0.9, 0.1]  → 90% chance it's IsNext
      ↓
Cross-entropy with true label
```

### Total BERT Training Loss

```
total_loss = MLM_loss + NSP_loss
```

Both losses are computed on the same forward pass and both contribute gradients during backpropagation.

### Important Note: NSP Was Later Found to Be Unnecessary

Later research (RoBERTa, 2019) showed that NSP doesn't actually help and sometimes hurts performance. RoBERTa removed NSP entirely and just trained with MLM alone — and got better results.

But it's important to understand NSP because:
1. The original BERT paper included it
2. It explains why the `[CLS]` token exists and is structured the way it is
3. Many BERT-based models still include the [CLS] architecture even without NSP

---

## The Full BERT Forward Pass — Step by Step

Let's trace through a complete example:

```
Original text: "The cat sat on the mat"
After tokenization: [1996, 4937, 2068, 2006, 1996, 13523]
(BERT uses WordPiece tokenizer, vocab size 30,522)
```

### Step 1: Add Special Tokens

```
[101, 1996, 4937, 2068, 2006, 1996, 13523, 102]
 ↑                                           ↑
[CLS]                                       [SEP]
```

### Step 2: Apply Masking (15% → select positions 2 and 5)

```
Before: [101, 1996, 4937, 2068, 2006, 1996, 13523, 102]
After:  [101, 1996,  103, 2068, 2006,  103, 13523, 102]
                      ↑                  ↑
                   [MASK]             [MASK]
(103 is BERT's [MASK] token ID)

Targets: position 2 → 4937 ("cat"), position 5 → 1996 ("the")
```

### Step 3: Three Embeddings Added Together

```
Token embeddings:    embed_table[101, 1996, 103, 2068, 2006, 103, 13523, 102]  → [8, 768]
Position embeddings: pos_table[0, 1, 2, 3, 4, 5, 6, 7]                         → [8, 768]
Segment embeddings:  seg_table[0, 0, 0, 0, 0, 0, 0, 0]                         → [8, 768]
                                                                                   (all same segment, single sentence)
Sum: [8, 768]
```

### Step 4: 12 Transformer Layers (NO Causal Mask)

```
Layer 1:  LN → 12-Head Attention (FULL, no mask) → + → LN → FFN → +
Layer 2:  same structure
...
Layer 12: same structure

Output: [8, 768]   ← every token now aware of EVERY other token, both directions
```

### Step 5: MLM Head — Predict Masked Tokens

```
Position 2 output vector: [768] → Linear [768, 30522] → logits [30522]
                                  → softmax → probabilities [30522]
                                  → compare with target 4937 ("cat")
                                  → loss1 = -log(P(4937))

Position 5 output vector: [768] → Linear [768, 30522] → logits [30522]
                                  → softmax → probabilities [30522]
                                  → compare with target 1996 ("the")
                                  → loss2 = -log(P(1996))
```

### Step 6: NSP Head (if using)

```
Position 0 ([CLS]) output: [768] → Linear [768, 2] → softmax → [P_isNext, P_notNext]
                                  → compare with true label
                                  → nsp_loss
```

### Step 7: Total Loss and Backprop

```
total_loss = (loss1 + loss2) / 2 + nsp_loss
total_loss.backward()    → gradients for all parameters
optimizer.step()         → Adam updates all weights
```

---

## BERT's Shape Journey (vs GPT)

Side by side:

```
                          GPT-2 Small              BERT-base
───────────────────────────────────────────────────────────────
Vocab size:               50,257                   30,522
Embedding dim:            768                      768
Layers:                   12                       12
Heads per layer:          12                       12
Max sequence length:      1024                     512
Parameters:               124M                     110M

Input:                    [seq, 768]               [seq, 768]
After layers:             [seq, 768]               [seq, 768]
Output projection:        [seq, 50257] (all pos)   [masked, 30522] (masked only)
                          + no CLS head            + [1, 2] (CLS→NSP)
```

---

## Why Encoder Models Exist — What They're Actually Good For

After pretraining, the BERT model produces a rich 768-dim vector for every token, with full bidirectional context. This makes it excellent for tasks where you need to **understand** text:

### Task 1: Text Classification

```
Input:  "[CLS] This movie was absolutely terrible [SEP]"
        ↓ BERT ↓
[CLS] vector: [768]  ← contains "understanding" of the whole sentence
        ↓
Linear [768, 2] → softmax → [P_positive, P_negative]
```

### Task 2: Named Entity Recognition (NER)

```
Input:  "[CLS] John works at Google in London [SEP]"
        ↓ BERT ↓
Every token gets a [768] vector with full context:
  "John"   → [768] → Linear [768, 5] → "PERSON"
  "works"  → [768] → Linear [768, 5] → "O" (not an entity)
  "at"     → [768] → Linear [768, 5] → "O"
  "Google" → [768] → Linear [768, 5] → "ORG"
  "in"     → [768] → Linear [768, 5] → "O"
  "London" → [768] → Linear [768, 5] → "LOC"
```

### Task 3: Semantic Similarity / Sentence Embeddings

This is where Sentence-BERT and the Sentence Transformers library come in. The [CLS] vector (or mean of all token vectors) becomes a fixed-size representation of the entire sentence:

```
Sentence A: "The cat sat on the mat"    → BERT → [CLS] vector A: [768]
Sentence B: "A feline rested on the rug" → BERT → [CLS] vector B: [768]

cosine_similarity(A, B) = 0.92   ← high! Semantically similar
```

> **This is a major topic on its own.** How Sentence Transformers works under the hood, how it fine-tunes BERT for similarity, and how the embedding space gets structured — that's a deep topic we can cover in a separate guide.

### Task 4: Question Answering (Extractive)

```
Input:  "[CLS] Where is Google headquartered? [SEP] Google's HQ is in Mountain View, California. [SEP]"
        ↓ BERT ↓
Each token in the passage gets a [768] vector.
Two classifiers predict START and END positions of the answer:
  Start: "Mountain" (position 9)
  End:   "California" (position 11)
  Answer: "Mountain View, California"
```

---

## Architecture Comparison Summary

```
                        GPT (Decoder)         BERT (Encoder)
─────────────────────────────────────────────────────────────
Attention mask:         Causal (triangular)   None (fully open)
Training task:          Next token prediction Masked token prediction
Masking rate:           N/A                   15% of tokens
Sees future tokens:     No                    Yes
Self-supervised:        Yes                   Yes
Special tokens:         <|endoftext|>         [CLS], [SEP], [MASK]
Extra embeddings:       None                  Segment embeddings
Positions with loss:    Every position        Only masked positions
Output used:            Last position (gen)   [CLS] + masked positions
Best for:               Generation            Understanding/Classification
Context direction:      Left-to-right only    Both directions
Can generate text:      Yes                   No
```

---

> **What's Next?**
> - **Encoder-Decoder models (T5):** Combines both — encoder understands input, decoder generates output. Used for translation, summarization, etc.
> - **Fine-tuning:** How to take a pretrained BERT/GPT and adapt it to specific tasks.
> - **Inference:** How generation actually works token-by-token.
> - **Sentence Transformers:** How BERT gets fine-tuned to produce meaningful sentence-level embeddings.
>
> See also: `decoder_only_complete_guide.md` for the full decoder walkthrough, `transformer_deep_reference.md` for a dense refresher.
