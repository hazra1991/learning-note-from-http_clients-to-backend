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

## Static vs Dynamic Embeddings — The Core Power of Encoders

This is a foundational concept that connects everything and directly leads to understanding sentence transformers.

### Two Layers of Embedding

**Layer 1: Token Embeddings (STATIC)**

The embedding lookup table is fixed after training. The word "cat" ALWAYS starts with the same vector, regardless of context:

```
"The cat sat on a mat"     → "cat" initial embedding = [0.82, -0.44, 0.33, ...]
"The cat ate the fish"     → "cat" initial embedding = [0.82, -0.44, 0.33, ...]  ← SAME
"I love my cat"            → "cat" initial embedding = [0.82, -0.44, 0.33, ...]  ← SAME

This is just a table lookup. Token ID 4937 always maps to the same row.
No matter what sentence, no matter what context. Same 768 numbers.
```

**Layer 2: Contextualized Embeddings (DYNAMIC)**

After passing through the 12 transformer layers, the vector for "cat" is **completely different depending on the sentence**. This is the entire point of the transformer:

```
BEFORE transformer layers (from lookup table — STATIC):
  "The cat sat on a mat"  → "cat" = [0.82, -0.44, 0.33, ...]
  "The cat ate the fish"  → "cat" = [0.82, -0.44, 0.33, ...]   ← same

AFTER 12 transformer layers (context-blended — DYNAMIC):
  "The cat sat on a mat"  → "cat" = [0.15, 0.67, -0.89, ...]   ← unique
  "The cat ate the fish"  → "cat" = [0.42, -0.23, 0.56, ...]   ← different!
  "I love my cat"         → "cat" = [-0.31, 0.78, 0.12, ...]   ← different!
```

The attention mechanism creates this difference. In "The cat sat", "cat" attends to "sat" and "mat". In "The cat ate", it attends to "ate" and "fish" instead. Different context → different attention weights → different output vector.

```
Static embedding:          "Who am I?"        → "I am the word cat"
Contextualized embedding:  "Who am I HERE?"   → "I am 'cat' in the context of sitting on a mat"
```

### The "bank" Example — Why This Matters

Consider two sentences:

```
Sentence 1: "He is going to the bank for getting money"
Sentence 2: "He is fishing at the bank"
```

**Old approach (Word2Vec, static embeddings):**

```
"bank" → [0.45, -0.23, 0.67, ...]    ← ONE vector, always the same.
The model CANNOT distinguish financial bank from river bank.
This was a fundamental limitation of pre-transformer NLP.
```

**BERT (contextualized embeddings):**

```
BEFORE transformer layers:
  "bank" in sentence 1 = [0.45, -0.23, 0.67, ...]   ← same static embedding
  "bank" in sentence 2 = [0.45, -0.23, 0.67, ...]   ← same static embedding
  (Same word → same row in lookup table → same starting vector)

AFTER 12 transformer layers:
  "bank" in "going to the bank for getting money":
    → "bank" attended heavily to "money" and "getting"
    → These words pulled its vector toward the FINANCIAL meaning
    → Output: [0.82, 0.15, -0.44, 0.91, ...]    ← financial bank

  "bank" in "fishing at the bank":
    → "bank" attended heavily to "fishing"
    → These words pulled its vector toward the RIVER meaning
    → Output: [-0.31, 0.67, 0.23, -0.18, ...]    ← river bank

  These two vectors are VERY DIFFERENT.
  Same input token, completely different output vectors.
```

Here's exactly how attention creates this difference:

```
"He is going to the bank for getting money"

When "bank" computes attention weights (who should I pay attention to?):

         He   is  going  to   the  bank  for  getting  money
bank → [0.03, 0.02, 0.08, 0.04, 0.05, 0.10, 0.12,  0.21,  0.35]
                                                              ↑
                                                    "money" gets 35% weight!

"bank" borrows heavily from "money"'s Value vector.
→ its representation shifts toward financial meaning.


"He is fishing at the bank"

         He   is  fishing  at   the  bank
bank → [0.03, 0.02, 0.42,  0.06, 0.07, 0.40]
                     ↑
           "fishing" gets 42% weight!

"bank" borrows heavily from "fishing"'s Value vector.
→ its representation shifts toward river/nature meaning.
```

This happens at every layer, getting more refined. By layer 12, the two "bank" vectors are in completely different regions of 768-dimensional space. **This disambiguation of meaning from context is the core power of transformer-based models over everything that came before.**

### Generalization — Handling Words in New Contexts

If the model was trained on "the cat sat on a mat" and "the dog sat on the mat", what happens with a new sentence: "an animal sat on the rug"?

The token "rug" has its own static embedding, learned from billions of training sentences where "rug" appeared in contexts similar to "mat", "carpet", "floor covering":

```
After training on billions of sentences:
  "mat"    embedding: [0.71, -0.33, 0.45, ...]
  "rug"    embedding: [0.68, -0.30, 0.42, ...]  ← very close to "mat"!
  "carpet" embedding: [0.65, -0.28, 0.40, ...]  ← also close!
  "pizza"  embedding: [-0.22, 0.81, -0.15, ...]  ← far from all of them

The model generalizes because similar words developed similar embeddings
during pretraining on massive text corpora.
```

And after the transformer layers, "animal" in context of "sat on the rug" produces a vector similar to "cat" in context of "sat on a mat" — because the surrounding structure is similar. The model has never seen this exact sentence, but it understands it through generalization.

---

## The Context Window — The Hard Boundary

This is crucial for understanding what any transformer model can and cannot do, and it directly affects how sentence transformers and RAG systems work.

### The Rule

Every transformer model has a **maximum sequence length** — the position embedding table has a fixed number of rows. This is the **context window**.

```
BERT:       512 tokens    (~380 words)
GPT-2:      1,024 tokens  (~750 words)
GPT-4:      128K tokens   (~96,000 words)
Claude:     200K tokens   (~150,000 words)
```

**Inside the context window:** Full attention. Every token sees every other token (encoder) or all previous tokens (decoder). Rich, deep understanding.

**Outside the context window:** Doesn't exist. Invisible. Zero influence. Not "partial understanding" — literally nonexistent to the model. It's a binary boundary.

### What Happens with Long Text

```
Your text: 1000 tokens
BERT's context window: 512 tokens

Option A: Truncate
  Feed tokens 0-511. Tokens 512-999 are THROWN AWAY.
  The model literally never sees them.

  [token 0, token 1, ..., token 511]       ← processed
  [token 512, token 513, ..., token 999]   ← GONE. Doesn't exist.


Option B: Chunk into separate inputs
  Input 1: [token 0, token 1, ..., token 499]     ← processed independently
  Input 2: [token 500, token 501, ..., token 999]  ← processed independently

  ⚠️ These two chunks have NO connection.
  Each is its own independent universe.
  Attention only works WITHIN a chunk.
  Information CANNOT flow between chunks.
```

### Concrete Example of Why This Matters

```
Original document (1000 tokens):
"In 1997 the company hired John Smith as CEO. [... 400 tokens ...]
He transformed the business completely. [... more tokens ...]
Smith's greatest achievement was the acquisition of ..."
                                                  ↑ token 600

If context window is 512:
  Chunk 1 (tokens 0-511):   Contains "hired John Smith as CEO"
  Chunk 2 (tokens 500-999): Contains "Smith's greatest achievement"

  In Chunk 2, when the model sees "Smith's", it has NO IDEA
  this is the same John Smith from Chunk 1.
  That information is in a different chunk = different universe.
```

### This Directly Connects to Sentence Transformers and RAG

When you use an encoder model to create embeddings for search or similarity:

```
Each sentence/chunk gets embedded independently.
The embedding captures meaning WITHIN that chunk only.
It cannot reference anything outside the chunk.

This is why chunking strategy matters enormously for RAG systems:
  - Chunk too large → exceeds context window, gets truncated
  - Chunk too small → loses context, embeddings are less meaningful
  - Chunk at natural boundaries (paragraphs, sections) → best balance
```

> This is the foundation for understanding Sentence Transformers — they take the encoder's ability to create rich contextualized embeddings and fine-tune it to produce one meaningful vector per sentence/passage, which can then be compared and searched. More on this in the Sentence Transformers guide.

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
