# Encoder-Only Transformer Models (BERT) — The Complete No-Black-Box Guide

> **What this is:** A deep walkthrough of how BERT-style encoder-only models work — what's the same as decoder models, what's different, and exactly why. Every confusing point is addressed head-on with concrete examples.

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
  ✗ The attention scores — no -inf triangle, fully bidirectional
  ✗ How the training challenge is created — [MASK] tokens in input, not blocked attention
  ✗ Special tokens — [CLS], [SEP], [MASK]
  ✗ Segment embeddings — a third embedding type
  ✗ What positions get a loss — only masked positions, not every position
  ✗ What the model is optimized FOR — understanding, not generation
```

---

## ⚠️ IMPORTANT: Two Different "Masks" — Don't Confuse Them

The word "mask" appears in two completely different contexts when discussing transformers. This is the #1 source of confusion. Let's kill it right now.

### Mask Type 1: The Causal Mask (in DECODER attention)

This is the **triangle of -inf values** added to attention scores in GPT-style models. It blocks tokens from attending to future positions.

```
Decoder attention scores BEFORE softmax:

              "The"   "cat"   "sat"
"The" looks→ [0.26,   -inf,   -inf]   ← -inf blocks "cat" and "sat"
"cat" looks→ [0.23,   0.19,   -inf]   ← -inf blocks "sat"
"sat" looks→ [0.22,   0.17,   0.13]   ← nothing blocked

This is added as a matrix:
scores = scores + causal_mask    (where causal_mask has -inf in upper triangle)
```

**BERT does NOT use this.** When we say "no mask" or "no causal mask" for BERT, we mean: **we don't add the -inf triangle to attention scores.** Every position's score stays as-is. Every token can freely attend to every other token.

```python
# DECODER — adds the -inf triangle
scores = Q @ K.T / sqrt(d_k)
mask = torch.triu(torch.ones(seq, seq) * float('-inf'), diagonal=1)
scores = scores + mask              # ← THIS LINE exists in decoder
weights = softmax(scores)

# ENCODER — no -inf triangle
scores = Q @ K.T / sqrt(d_k)
                                    # ← NO mask line. Nothing added.
weights = softmax(scores)           # every position keeps its score
```

### Mask Type 2: The [MASK] Token (in ENCODER input)

This is a **special vocabulary token** (token ID 103 in BERT) that **replaces** certain words in the input text before the model processes it.

```
Original:  "The cat sat on a mat"
Masked:    "The [MASK] sat on a [MASK]"

The token "cat" is literally removed and replaced with token 103.
The model never sees "cat" — it sees "there's a blank here."
```

### These two are COMPLETELY DIFFERENT mechanisms:

```
CAUSAL MASK (decoder):
  - WHERE: Inside the attention computation
  - WHAT: A matrix of -inf values added to attention scores
  - PURPOSE: Prevent tokens from seeing future positions
  - RESULT: Tokens can only attend backward (left-to-right)

[MASK] TOKEN (encoder):
  - WHERE: In the input, before the model runs at all
  - WHAT: A replacement token (ID 103) that replaces real words
  - PURPOSE: Hide specific words so the model must predict them
  - RESULT: The model receives a sentence with blanks to fill

DECODER hides information by blocking ATTENTION.
ENCODER hides information by blanking the INPUT.
Both create a challenge. Different mechanisms entirely.
```

From here on, when I say "no mask in attention" I mean: no -inf triangle, full bidirectional attention. When I say "[MASK] token" I mean: the blank placeholder in the input.

---

## How BERT Actually Trains — The Full Flow

Let me walk through every step with a concrete example, making every detail explicit.

### Step 1: Start with Raw Text

```
Training text: "The cat sat on a mat"
```

### Step 2: Tokenize

```
Token IDs: [1996, 4937, 2068, 2006, 1037, 13523]
            The   cat   sat   on    a     mat
```

(BERT uses WordPiece tokenizer, vocabulary size 30,522)

### Step 3: Add Special Tokens

```
[101, 1996, 4937, 2068, 2006, 1037, 13523, 102]
 CLS  The   cat   sat   on    a     mat    SEP
```

- `[CLS]` (token 101) — always at position 0. Its output vector becomes a "summary" of the entire input.
- `[SEP]` (token 102) — marks the end. Also separates two sentences when BERT processes a pair.

### Step 4: MASK — Before the Model Sees Anything

This is critical. The masking happens to the **input**, not inside the model. The model will never see the original tokens at masked positions.

```
Randomly select 15% of tokens (excluding [CLS] and [SEP]).
6 real tokens × 15% ≈ 1 token. Let's say we select 2 for this example.
Selected positions: 2 ("cat") and 6 ("mat")

For each selected position, apply the 80/10/10 rule:
  Position 2 ("cat"): 80% chance → [MASK] token (ID 103)
  Position 6 ("mat"): 80% chance → [MASK] token (ID 103)

Save the answers for later:
  Position 2 → correct answer is 4937 ("cat")
  Position 6 → correct answer is 13523 ("mat")

Masked input: [101, 1996, 103, 2068, 2006, 1037, 103, 102]
               CLS  The  MASK  sat   on    a    MASK  SEP
```

**The model will receive this masked version.** It has no way to know that position 2 was "cat" or position 6 was "mat". It must figure this out from context.

#### Why the 80/10/10 split?

Of the 15% selected tokens:
- **80% become [MASK]**: The core task — predict from context alone.
- **10% become a random token**: Forces the model to stay alert. "Any token might be wrong, I should understand every position."
- **10% stay unchanged**: Forces good representations even for correct tokens — the model can't just ignore non-[MASK] positions.

If you always used [MASK], the model would learn: "I only need to think hard when I see [MASK]." During fine-tuning and real usage, there's no [MASK] token. The 10/10 prevents this shortcut.

### Step 5: Embed + Position + Segment

```
Token embeddings:    embed_table[101, 1996, 103, 2068, 2006, 1037, 103, 102]  → [8, 768]
Position embeddings: pos_table[0, 1, 2, 3, 4, 5, 6, 7]                         → [8, 768]
Segment embeddings:  seg_table[0, 0, 0, 0, 0, 0, 0, 0]                         → [8, 768]
                                                                                  (single sentence = all 0s)

final_input = token_embed + position_embed + segment_embed    → [8, 768]
```

**Key point about [MASK]:** Token 103 (`[MASK]`) has its own row in the embedding table, just like every other token. Its embedding is a learned vector that essentially means "there's a blank here — figure out what goes in this position." This embedding starts random and gets refined through training.

### Step 6: Transformer Layers (Full Bidirectional Attention)

```
Layer 1:  LayerNorm → 12-Head Attention → + → LayerNorm → FFN → +
Layer 2:  same structure
...
Layer 12: same structure
```

**The attention here has NO -inf triangle.** Every token freely attends to every other token. The attention scores look like this:

```
              CLS   The   MASK₂  sat   on    a    MASK₆  SEP
CLS    →     [0.12, 0.14, 0.11, 0.13, 0.10, 0.09, 0.18, 0.13]  ← sees everything
The    →     [0.09, 0.15, 0.13, 0.16, 0.11, 0.12, 0.14, 0.10]  ← sees everything
MASK₂  →     [0.08, 0.19, 0.06, 0.22, 0.13, 0.10, 0.12, 0.10]  ← sees everything
sat    →     [0.07, 0.14, 0.16, 0.12, 0.18, 0.11, 0.13, 0.09]  ← sees everything
on     →     [0.06, 0.11, 0.10, 0.20, 0.09, 0.15, 0.19, 0.10]  ← sees everything
a      →     [0.08, 0.10, 0.09, 0.12, 0.17, 0.11, 0.23, 0.10]  ← sees everything
MASK₆  →     [0.07, 0.12, 0.11, 0.16, 0.21, 0.18, 0.05, 0.10]  ← sees everything
SEP    →     [0.13, 0.11, 0.12, 0.14, 0.10, 0.11, 0.15, 0.14]  ← sees everything

No -inf anywhere. Every cell has a real score. Every row sums to 1.0 after softmax.
```

**What's happening to [MASK] at position 2:**

This token started as the generic [MASK] embedding — "I'm a blank." But through 12 layers of attention, it gathers clues from ALL surrounding tokens:

```
Layer 1-3:  [MASK]₂ attends to "The" (left) and "sat" (right)
            → learns: "I'm between 'The' and 'sat'"
            → "The ___  sat" → probably a noun

Layer 4-8:  [MASK]₂ attends to "on", "a", [MASK]₆
            → learns: "something sat on a something"
            → pattern suggests an animal or person

Layer 9-12: [MASK]₂ has deep contextual representation
            → its [768] vector now encodes:
              "I should be a noun, probably an animal,
               that can sit on something"
```

**After all 12 layers:** The [MASK] at position 2 is no longer a generic blank. Its 768-dim vector has been transformed through 12 rounds of attention to encode **what word should be here**, based on the full bidirectional context.

Same thing happens for [MASK] at position 6, and for ALL other tokens too — every token's vector is now deeply context-aware. But we only care about predicting the masked ones.

Output shape: `[8, 768]` — 8 tokens, each with a deeply contextualized 768-dim vector.

### Step 7: MLM Head (After All Transformer Layers)

The MLM head sits **on top of** the transformer layers, not inside them. It's a separate component, just like the LM head in GPT.

It takes each masked position's contextualized vector and projects it to vocabulary size:

```
Position 2 vector: [768]   (rich with contextual info about "what should be here")
  → Linear layer [768, 30522]
  → [30522] logits  (one raw score per vocabulary token)
  → softmax
  → [30522] probabilities

  P("cat") = 0.12       ← the model's best guess
  P("dog") = 0.08       ← plausible alternative
  P("bird") = 0.05      ← less likely but possible
  P("pizza") = 0.0001   ← very unlikely
  ...all 30,522 tokens get some probability, summing to 1.0


Position 6 vector: [768]
  → same Linear layer → [30522] logits → softmax → [30522] probabilities

  P("mat") = 0.15
  P("rug") = 0.06
  P("floor") = 0.04
  ...
```

**Positions that are NOT masked (0, 1, 3, 4, 5, 7) are completely ignored here.** No projection, no logits, no loss. They contributed to the attention (they helped the [MASK] tokens gather context), but they don't need to predict anything.

**Important clarification:** The model doesn't compare vectors against embeddings directly. It projects the 768-dim vector to 30,522 logits (one per vocab word), applies softmax, and checks how much probability landed on the correct token ID. It's the same mechanism as the decoder — a multiple-choice test over the entire vocabulary.

```
It's like a multiple-choice test:

NOT this:  Model writes an essay answer and we compare to real essay.
THIS:      Model picks from 30,522 choices: "I think the answer is #4937"
           We check: "Was #4937 correct? Yes! How confident? 12%? Not enough."
           Loss reflects that low confidence → backprop adjusts weights.
```

### Step 8: Loss

Same cross-entropy as the decoder:

```
Position 2: correct answer = 4937 ("cat")
  loss₁ = -log(P(4937)) = -log(0.12) = 2.12

Position 6: correct answer = 13523 ("mat")
  loss₂ = -log(P(13523)) = -log(0.15) = 1.90

Total loss = (2.12 + 1.90) / 2 = 2.01
```

### Step 9: Backprop + Adam

Identical to decoder. Gradient flows backward through:

```
MLM Head → Layer 12 → Layer 11 → ... → Layer 1 → Embeddings
```

ALL weights get updated — attention weights, FFN weights, the embedding for [MASK] (token 103), every token's embedding, position embeddings, everything.

**The whole pipeline runs ONCE per training step.** No iteration, no re-running. One forward pass, one backward pass, one optimizer step. Load next batch. Repeat millions of times.

---

## BERT's Second Training Task: Next Sentence Prediction (NSP)

In addition to MLM, the original BERT was trained with a second objective: predict whether sentence B actually follows sentence A.

```
Positive example (50% of training data):
  Input: "[CLS] The cat sat on the mat [SEP] It was a fluffy Persian [SEP]"
  Label: IsNext (1)
  (These actually appeared consecutively in training data)

Negative example (50% of training data):
  Input: "[CLS] The cat sat on the mat [SEP] Stock prices fell sharply [SEP]"
  Label: NotNext (0)
  (Sentence B randomly sampled from elsewhere)
```

The [CLS] token's output vector is passed through a binary classifier:

```
[CLS] output: [768] → Linear [768, 2] → softmax → [P_isNext, P_notNext]
→ cross-entropy with true label → nsp_loss
```

Total training loss: `total_loss = MLM_loss + NSP_loss`

**Important:** Later research (RoBERTa, 2019) showed NSP doesn't help and sometimes hurts. RoBERTa removed it entirely and got better results. But it's good to know because it explains why the [CLS] token architecture exists.

### Segment Embeddings (for NSP)

Because BERT can take two sentences, it needs to know which tokens belong to which. This is a third embedding:

```
GPT:   final = token_embed + position_embed
BERT:  final = token_embed + position_embed + segment_embed

Tokens:    [CLS] The cat sat [SEP] It was fluffy [SEP]
Segments:  [ 0    0   0   0    0    1   1    1     1  ]
            └── sentence A ──┘    └── sentence B ──┘
```

The segment embedding table is tiny — just 2 rows (0 and 1), each 768-dim.

---

## Static vs Dynamic Embeddings, Context Window

These foundational concepts — how static token embeddings become dynamic contextualized embeddings through attention (including the "bank" disambiguation example), how models generalize to unseen words, and how the context window acts as a hard boundary — are universal to all transformer types and are covered in full detail in `shared_foundations.md`.

The key points for encoder models specifically:
- BERT's bidirectional attention creates **richer** contextualized embeddings than decoder models, because each token sees both left and right context.
- BERT's context window is 512 tokens — shorter than most decoder models.
- These concepts directly lead to understanding Sentence Transformers (see `sentence_transformers_complete_guide.md`).

---

## Why BERT Can't Generate Text

BERT sees the **entire input at once** — including tokens to the right. It was trained to fill blanks, not predict what comes next.

```
If you ask BERT: "The cat sat ___"
BERT says: "I need to see the WHOLE sentence to make predictions.
            What comes after the blank? I need that too."

BERT can fill in:  "The [MASK] sat on a mat" → "cat"  (sees both sides)
BERT cannot do:    "The cat sat" → predict next word   (no right context to use)
```

It has no mechanism for generating token after token because it was never trained to predict the next token.

```
BERT is great at:                    BERT is bad at:
  - Understanding sentences           - Generating new text
  - Classifying text (spam/not spam)  - Continuing a prompt
  - Finding similar sentences          - Writing stories
  - Answering questions about text     - Chat / conversation
  - Named entity recognition           - Open-ended generation
```

---

## What Encoder Models Are Actually Used For

After pretraining, every token has a rich 768-dim contextualized vector. Here's how that's used:

### Text Classification

```
Input:  "[CLS] This movie was absolutely terrible [SEP]"
        ↓ BERT (12 layers, full attention) ↓
[CLS] output vector: [768]  ← summarizes the whole sentence
        ↓
Linear [768, 2] → softmax → [P_positive=0.05, P_negative=0.95]
```

### Named Entity Recognition (NER)

```
Input:  "[CLS] John works at Google in London [SEP]"
        ↓ BERT ↓
Every token gets a contextualized [768] vector:
  "John"   → [768] → classify → "PERSON"
  "works"  → [768] → classify → "O" (not an entity)
  "Google" → [768] → classify → "ORG"
  "London" → [768] → classify → "LOC"
```

### Semantic Similarity / Sentence Embeddings

```
Sentence A: "The cat sat on the mat"    → BERT → mean of all vectors → [768]
Sentence B: "A feline rested on the rug" → BERT → mean of all vectors → [768]

cosine_similarity(A, B) = 0.92   ← semantically similar!
```

### Question Answering (Extractive)

```
Input:  "[CLS] Where is Google HQ? [SEP] Google's headquarters is in Mountain View. [SEP]"
        ↓ BERT ↓
Two classifiers predict START and END positions of the answer:
  Start: "Mountain" (position 9)
  End:   "View" (position 10)
  Answer: "Mountain View"
```

---

## Architecture Comparison Summary

```
                        GPT (Decoder)         BERT (Encoder)
─────────────────────────────────────────────────────────────
Attention:              Has causal mask       No mask (fully open)
                        (-inf triangle)       (all scores kept)
How challenge created:  Block attention        Replace input tokens
                        to future             with [MASK]
Training task:          Next token prediction Masked token prediction
Masking rate:           N/A                   15% of tokens
Sees future tokens:     No                    Yes (but masked ones are hidden)
Self-supervised:        Yes                   Yes
Special tokens:         <|endoftext|>         [CLS], [SEP], [MASK]
Extra embeddings:       None                  Segment embeddings
Positions with loss:    Every position        Only masked positions (15%)
Output used:            Last position (gen)   [CLS] + masked positions
Best for:               Generation            Understanding/Classification
Context direction:      Left-to-right only    Both directions
Can generate text:      Yes                   No
```

### The Complete Mental Model

```
DECODER (GPT):
  Full sentence in → causal mask blocks future → each position predicts next token
  "The cat sat" → model sees triangle → predicts "cat", "sat", next word
  Training creates challenge by: BLOCKING ATTENTION (adding -inf to scores)

ENCODER (BERT):
  Sentence with blanks in → no attention blocking → masked positions predict original
  "The [MASK] sat on a [MASK]" → model sees everything → predicts "cat", "mat"
  Training creates challenge by: BLANKING THE INPUT (replacing tokens with [MASK])

Same transformer blocks. Same Q, K, V math. Same softmax.
Same backprop. Same Adam optimizer.
Different challenge mechanism. Different resulting capabilities.
```

---

> **What's Next?**
> - **Encoder-Decoder models (T5):** Combines both — encoder understands input, decoder generates output.
> - **Fine-tuning:** How to take pretrained BERT/GPT and adapt to specific tasks.
> - **Sentence Transformers:** How BERT gets fine-tuned to produce meaningful sentence embeddings — builds directly on the static vs dynamic embeddings and context window concepts from this guide.
>
> See also: `decoder_only_complete_guide.md` for the full decoder walkthrough, `transformer_deep_reference.md` for dense refresher, `transformer_visual_mental_model.md` for the big-picture visual map.
