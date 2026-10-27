# Shared Foundations — Concepts That Apply to ALL Transformer Models

> **What this is:** Foundational concepts that are universal across decoder, encoder, and encoder-decoder models. Pulled out of the individual guides because they apply everywhere.

---

## Static vs Dynamic Embeddings — The Core Power of Transformers

This concept applies to every transformer model — encoder, decoder, encoder-decoder. It's what makes transformers fundamentally different from everything that came before.

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

After passing through the transformer layers, the vector for "cat" is **completely different depending on the sentence**. This is the entire point of the transformer:

```
BEFORE transformer layers (from lookup table — STATIC):
  "The cat sat on a mat"  → "cat" = [0.82, -0.44, 0.33, ...]
  "The cat ate the fish"  → "cat" = [0.82, -0.44, 0.33, ...]   ← same

AFTER transformer layers (context-blended — DYNAMIC):
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

**Transformer-based model (contextualized embeddings):**

```
BEFORE transformer layers:
  "bank" in sentence 1 = [0.45, -0.23, 0.67, ...]   ← same static embedding
  "bank" in sentence 2 = [0.45, -0.23, 0.67, ...]   ← same static embedding
  (Same word → same row in lookup table → same starting vector)

AFTER transformer layers:
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

This applies equally to encoder models (BERT), decoder models (GPT), and encoder-decoder models (T5).

---

## The Context Window — The Hard Boundary

This applies to every transformer model. It's the single most important practical limitation to understand.

### The Rule

Every transformer model has a **maximum sequence length** — the position embedding table has a fixed number of rows. This is the **context window**.

```
BERT:       512 tokens    (~380 words)
GPT-2:      1,024 tokens  (~750 words)
GPT-4:      128K tokens   (~96,000 words)
Claude:     200K tokens   (~150,000 words)
LLaMA 3:   128K tokens   (~96,000 words)
all-MiniLM: 256 tokens    (~190 words)
```

**Inside the context window:** Full attention. Every token sees every other token (encoder) or all previous tokens (decoder). Rich, deep understanding.

**Outside the context window:** Doesn't exist. Invisible. Zero influence. Not "partial understanding" — literally nonexistent to the model. It's a binary boundary.

### What Happens with Long Text

```
Your text: 1000 tokens
Model's context window: 512 tokens

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

### How This Affects Different Use Cases

```
FOR GENERATION (decoder models):
  Context window = how much conversation/prompt the model can "remember"
  In a chat: system prompt + all previous messages + your latest message
  must ALL fit in the context window.
  If the conversation grows too long → earliest messages get dropped.

FOR EMBEDDINGS (encoder models / Sentence Transformers):
  Context window = max text that can be embedded in one vector.
  Sentence Transformers with all-MiniLM-L6-v2 (256 tokens):
    - Sentences and short paragraphs: fine
    - Full documents: gets truncated, only first 256 tokens embedded
    - Must chunk manually for long documents

FOR RAG (Retrieval Augmented Generation):
  Chunking strategy matters enormously:
    - Chunk too large → exceeds context window, gets truncated
    - Chunk too small → loses context, embeddings are less meaningful
    - Chunk at natural boundaries (paragraphs, sections) → best balance
  
  Each chunk is embedded independently.
  When retrieved, the chunk is inserted into the decoder's context window.
  The decoder can then reason about it alongside the user's question.
```

---

> **Referenced by:**
> - `encoder_only_complete_guide.md`
> - `decoder_only_complete_guide.md`
> - `sentence_transformers_complete_guide.md`
> - `transformer_visual_mental_model.md`
