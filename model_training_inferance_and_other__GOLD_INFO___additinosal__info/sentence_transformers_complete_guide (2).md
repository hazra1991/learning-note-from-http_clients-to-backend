# Sentence Transformers — The Complete No-Black-Box Guide

> **What this is:** A deep walkthrough of how Sentence Transformers works under the hood — what the library does, what models it uses, how fine-tuning works, and how text becomes a single vector you can search and compare. No black boxes.

> **Prerequisite:** Understanding of encoder-only models (BERT), static vs dynamic embeddings, and the context window. See `encoder_only_complete_guide.md` and `shared_foundations.md`.

---

## What Sentence Transformers Actually Does — Step by Step

### What It IS and ISN'T

- Sentence Transformers is a **library**, not a model. Correct.
- It uses encoder models internally. Correct.
- The context window limits what can be processed at once. Correct.

**Common misconception:** "It just chunks long text and averages the chunk embeddings."

**No. That's not what happens.** Sentence Transformers does NOT chunk long text and average chunks. It sends the ENTIRE text (up to context window limit) through the encoder in one pass, then pools the token-level outputs into one vector. If the text is too long, it gets **truncated** (cut off), not chunked.

### The Actual Process

```
Input: "The cat sat on the mat"

Step 1: Tokenize (same as BERT)
  [101, 1996, 4937, 2068, 2006, 1037, 13523, 102]
   CLS  The   cat   sat   on    a     mat    SEP

Step 2: Pass through the encoder model (e.g., BERT, all-MiniLM)
  → 12 transformer layers, full bidirectional attention
  → Output: [8, 768]  (or [8, 384] for MiniLM)
  
  Each token has a contextualized vector:
    [CLS] → [0.12, -0.34, ...]
    "The" → [0.45, 0.23, ...]
    "cat" → [0.67, -0.12, ...]
    "sat" → [-0.23, 0.89, ...]
    "on"  → [0.34, -0.56, ...]
    "a"   → [0.11, 0.45, ...]
    "mat" → [0.78, -0.33, ...]
    [SEP] → [0.09, 0.67, ...]

Step 3: POOL these 8 vectors into ONE vector
  (this is the key step — multiple strategies exist)

  Mean pooling (most common):
    sentence_vector = average of all token vectors (excluding padding)
    = ([CLS] + "The" + "cat" + "sat" + "on" + "a" + "mat" + [SEP]) / 8
    = [0.416, 0.111, ...]    ← one vector, 768 dims (or 384 for MiniLM)

  This single vector IS the "sentence embedding."
```

That's it. No chunking. No re-running. One pass through the encoder, then average the outputs.

```
"The cat sat on the mat"  → encoder → [8, 768] → mean pool → [768]
                                                               ↑
                                              ONE vector representing
                                              the ENTIRE sentence
```

---

## But Wait — Base BERT Is BAD at This

Here's the crucial insight that explains why Sentence Transformers exists as a library.

If you take a pretrained BERT and just mean-pool its outputs, the sentence embeddings are **terrible** for similarity. Why?

```
BERT was trained on MLM (fill in the blanks).
It was NEVER trained to make similar sentences have similar average vectors.

BERT's training objective: "predict masked tokens"
What we want:             "similar sentences should have close vectors"

These are completely different goals!
```

Experiment (actual research finding):

```
Using raw BERT mean-pooled embeddings:

  "The cat sat on the mat"         → vector A
  "A feline rested on the rug"     → vector B
  "Stock prices fell sharply"      → vector C

  cosine_sim(A, B) = 0.75    ← should be high (similar meaning) ✓
  cosine_sim(A, C) = 0.72    ← should be LOW (different meaning) ✗ !!

  Almost the same similarity! BERT's raw embeddings don't capture
  sentence-level similarity well. They capture token-level features
  that happen to average out to similar-ish vectors for any English text.
```

---

## Sentence Transformers FIXES This Through Fine-Tuning

The Sentence Transformers library takes a pretrained encoder and **fine-tunes** it with a specific training objective that forces similar sentences to have similar vectors.

The architecture during fine-tuning:

```
┌─────────────────────────────────────────────────────┐
│  TRAINING A SENTENCE TRANSFORMER                     │
│                                                      │
│  Training data: pairs of sentences with labels       │
│    ("The cat sat", "A feline rested", similar)       │
│    ("The cat sat", "Stock prices fell", different)   │
│                                                      │
│  ONE encoder, TWO passes (same weights both times):  │
│                                                      │
│  Pass 1: Sentence A           Pass 2: Sentence B    │
│      ↓                             ↓                 │
│  ┌─────────────────────────────────────────┐        │
│  │         ONE encoder (e.g., BERT)         │        │
│  │         Same weights for both passes     │        │
│  └─────────────────────────────────────────┘        │
│      ↓                             ↓                 │
│  Mean Pool                    Mean Pool              │
│      ↓                             ↓                 │
│  Vector A [768]               Vector B [768]         │
│      ↓                             ↓                 │
│      └──────────┬──────────────────┘                 │
│                 ↓                                     │
│         Cosine Similarity                            │
│            sim(A, B)                                 │
│                 ↓                                     │
│              Loss:                                   │
│   If similar pair:  loss = 1 - sim(A,B)  (push close)│
│   If different:     loss = max(0, sim(A,B) - margin) │
│                     (push apart)                     │
│                 ↓                                     │
│         Backprop through the encoder                 │
│         (gradients from both passes accumulate       │
│          on the same weights)                        │
│                 ↓                                     │
│         Adam updates the encoder weights             │
│                                                      │
│  After fine-tuning:                                  │
│    The encoder has learned to produce vectors where  │
│    similar sentences ARE close and different ARE far. │
└─────────────────────────────────────────────────────┘
```
**Note:**  In practice, both sentences are often processed in the same batch for efficiency — but conceptually, it's the same model processing two different inputs. and the **`backpropagation sends the updates bact to bother the passes`**

**The key insight:** The encoder itself has no concept of "sentence similarity." It still does its normal job — process tokens, produce one contextualized vector per token. It doesn't know these vectors will be averaged or compared. But the fine-tuning loss flows backward *through* the mean pool *into* the encoder weights, shaping them so that as a side effect of normal token processing, the averaged vectors happen to capture sentence-level meaning. The encoder is still a token machine. The "magic" is just gradient descent working through the chain of operations.

```
BEFORE fine-tuning (raw BERT):
  "The cat sat"          → [0.45, 0.23, ...]  }
  "A feline rested"      → [0.52, 0.19, ...]  } similar-ish but unreliable
  "Stock prices fell"    → [0.48, 0.21, ...]  }

AFTER fine-tuning (Sentence Transformer):
  "The cat sat"          → [0.82, -0.44, ...]  }
  "A feline rested"      → [0.79, -0.41, ...]  } very close! ✓
  "Stock prices fell"    → [-0.31, 0.67, ...]  } very far! ✓
```

---

## So What Is all-MiniLM-L6-v2?

Let me break down the name:

```
all-MiniLM-L6-v2

all     → trained on a large diverse dataset (not domain-specific)
MiniLM  → the base encoder architecture (a distilled, smaller version of BERT)
L6      → 6 transformer layers (instead of BERT's 12)
v2      → version 2 of this model

Dimensions: 384 (instead of BERT's 768)
Parameters: ~22 million (instead of BERT's 110 million)
Max sequence: 256 tokens
```

**MiniLM is NOT BERT.** It's a different, smaller encoder model created through **knowledge distillation** — training a small model to mimic a large model's behavior. It's faster and lighter but captures most of BERT's capability.

The Sentence Transformers library fine-tuned this MiniLM encoder on sentence similarity data. The result is `all-MiniLM-L6-v2` — a small, fast model that produces good sentence embeddings.

---

## The Landscape of Sentence Transformer Models

```
┌──────────────────────────────────────────────────────────────────┐
│  Model Name              Base Encoder    Dims   Layers   Speed   │
├──────────────────────────────────────────────────────────────────┤
│  all-MiniLM-L6-v2       MiniLM          384    6        Fast    │
│  all-MiniLM-L12-v2      MiniLM          384    12       Medium  │
│  all-mpnet-base-v2      MPNet           768    12       Medium  │
│  BGE-large-en-v1.5      BERT-large      1024   24       Slow    │
│  E5-large-v2            BERT-large      1024   24       Slow    │
│  GTE-large              BERT-large      1024   24       Slow    │
│  nomic-embed-text-v1.5  BERT (modified) 768    12       Medium  │
└──────────────────────────────────────────────────────────────────┘

ALL of these follow the same pattern:
  1. Take a pretrained encoder (BERT, MiniLM, MPNet, etc.)
  2. Fine-tune it on sentence similarity data
  3. At inference: text → encoder → pool → one vector
  
The difference is the BASE ENCODER (bigger = richer but slower)
and the TRAINING DATA (more/better data = better embeddings).
```

---

## What Happens Under the Hood When You Call the Library

```python
from sentence_transformers import SentenceTransformer

model = SentenceTransformer('all-MiniLM-L6-v2')
embedding = model.encode("The cat sat on the mat")
print(embedding.shape)  # (384,)
```

What this single line actually does:

```
model.encode("The cat sat on the mat")

  Step 1: Tokenize
    → [101, 1996, 4937, 2068, 2006, 1037, 13523, 102]
    
  Step 2: Create attention mask
    → [1, 1, 1, 1, 1, 1, 1, 1]   (all 1s = all tokens are real, no padding)
    
  Step 3: Pass through MiniLM encoder (6 transformer layers)
    → token embeddings [8, 384]
    → + position embeddings [8, 384]
    → Layer 1: LN → Attention (full, no causal mask) → + → LN → FFN → +
    → Layer 2: same
    → ... 
    → Layer 6: same
    → Output: [8, 384]
    
  Step 4: Mean pooling
    → Average all 8 vectors: [8, 384] → [384]
    → BUT: exclude padding tokens (if any) from the average
    
  Step 5: Normalize (optional but common)
    → Divide vector by its L2 norm so it has length 1.0
    → This makes cosine similarity equal to dot product (faster)
    
  Return: numpy array of shape (384,)
```

---

## What About Long Text? Truncation, Not Chunking

```
Text: "Very long document with 500 tokens..."
Model max length: 256 tokens (all-MiniLM-L6-v2)

What happens:
  Tokens 0-255: processed normally
  Tokens 256-499: SILENTLY DROPPED. Gone. Never processed.
  
  The model does NOT chunk and average.
  It truncates. The extra tokens simply don't exist.

  embedding = model.encode("very long text...")
  # Only represents the FIRST 256 tokens!
```

If you WANT chunking behavior, you must implement it yourself:

```python
# Manual chunking (YOU write this, not the library)
def embed_long_text(text, model, chunk_size=256):
    # Split text into chunks
    tokens = tokenizer.encode(text)
    chunks = [tokens[i:i+chunk_size] for i in range(0, len(tokens), chunk_size)]
    
    # Embed each chunk separately
    chunk_embeddings = []
    for chunk in chunks:
        chunk_text = tokenizer.decode(chunk)
        emb = model.encode(chunk_text)
        chunk_embeddings.append(emb)
    
    # Average chunk embeddings
    return np.mean(chunk_embeddings, axis=0)
```

But this averaging of chunk embeddings is **lossy** — the chunks are processed independently, so cross-chunk context is lost. This is the context window limitation (see `shared_foundations.md`).

---

## The Three Pooling Strategies

Mean pooling is most common, but there are alternatives:

```
Token outputs from encoder: [8, 384]

  [CLS] → [0.12, -0.34, ...]
  "The" → [0.45, 0.23, ...]
  "cat" → [0.67, -0.12, ...]
  "sat" → [-0.23, 0.89, ...]
  "on"  → [0.34, -0.56, ...]
  "a"   → [0.11, 0.45, ...]
  "mat" → [0.78, -0.33, ...]
  [SEP] → [0.09, 0.67, ...]


Strategy 1: CLS Pooling
  Just take the [CLS] vector: [0.12, -0.34, ...]
  Pro: Simple, [CLS] was designed to summarize
  Con: One token carrying all the information is a bottleneck

Strategy 2: Mean Pooling (most common, best results usually)
  Average ALL token vectors (excluding padding):
  ([CLS] + "The" + "cat" + ... + [SEP]) / 8 = [0.416, 0.111, ...]
  Pro: Every token contributes, robust representation
  Con: All tokens weighted equally (even "a" and "the")

Strategy 3: Max Pooling
  Take the maximum value across tokens for each dimension:
  dim 0: max(0.12, 0.45, 0.67, -0.23, 0.34, 0.11, 0.78, 0.09) = 0.78
  dim 1: max(-0.34, 0.23, -0.12, 0.89, -0.56, 0.45, -0.33, 0.67) = 0.89
  Pro: Captures the strongest signal per dimension
  Con: Loses information about the "average" meaning
```

---

## How Cosine Similarity Works

Once you have sentence vectors, you compare them:

```
Vector A = [0.82, -0.44, 0.33, 0.21]    (sentence 1)
Vector B = [0.79, -0.41, 0.35, 0.18]    (sentence 2)

cosine_similarity = dot(A, B) / (|A| × |B|)

dot(A, B) = 0.82×0.79 + (-0.44)×(-0.41) + 0.33×0.35 + 0.21×0.18
          = 0.648 + 0.180 + 0.116 + 0.038
          = 0.982

|A| = √(0.82² + 0.44² + 0.33² + 0.21²) = √(0.672+0.194+0.109+0.044) = √1.019 = 1.009
|B| = √(0.79² + 0.41² + 0.35² + 0.18²) = √(0.624+0.168+0.123+0.032) = √0.947 = 0.973

cosine_sim = 0.982 / (1.009 × 0.973) = 0.982 / 0.982 = 1.00

These vectors are nearly identical → these sentences are very similar.
```

```
Scale:
  cosine_sim = 1.0   → identical meaning
  cosine_sim = 0.8+  → very similar
  cosine_sim = 0.5   → somewhat related
  cosine_sim = 0.0   → unrelated
  cosine_sim = -1.0  → opposite meaning
```

---

## The Complete Picture — From Text to Similarity Score

```
"The cat sat on the mat"              "A feline rested on the rug"
         │                                       │
    ┌────┴────┐                             ┌────┴────┐
    │Tokenize │                             │Tokenize │
    └────┬────┘                             └────┬────┘
         │                                       │
   [CLS,The,cat,sat,                       [CLS,A,feline,rested,
    on,a,mat,SEP]                           on,the,rug,SEP]
         │                                       │
    ┌────┴──────────┐                       ┌────┴──────────┐
    │  MiniLM       │                       │  MiniLM       │
    │  (6 layers,   │                       │  (same model, │
    │   full attn)  │                       │   same weights)│
    └────┬──────────┘                       └────┬──────────┘
         │                                       │
    [8, 384]                                [8, 384]
    token vectors                           token vectors
         │                                       │
    ┌────┴────┐                             ┌────┴────┐
    │  Mean   │                             │  Mean   │
    │  Pool   │                             │  Pool   │
    └────┬────┘                             └────┬────┘
         │                                       │
      [384]                                   [384]
    sentence                               sentence
    embedding A                            embedding B
         │                                       │
         └──────────────┬────────────────────────┘
                        │
                 cosine_similarity(A, B)
                        │
                      0.92
                        │
                  "Very similar!"
```

---

## The Exact Relationship Between Libraries, Architectures, and Models

```
LAYER 1: Base Encoder Architectures (the "engine")
──────────────────────────────────────────────────
These are the raw pretrained models. Trained on MLM (fill in blanks).
They know language, but are NOT yet good at sentence similarity.

  BERT         → Google, 2018. 12 layers, 768 dims, 110M params
  MiniLM       → Microsoft, 2020. Distilled from BERT. Smaller, faster.
  MPNet        → Microsoft, 2020. Combines BERT + XLNet ideas. Better than BERT.
  RoBERTa      → Meta, 2019. BERT but better training (more data, no NSP).
  DeBERTa      → Microsoft, 2021. Improved attention mechanism.
  XLM-RoBERTa  → Meta. Multilingual version of RoBERTa.

All of these are encoder-only transformers.
Same Q,K,V attention, same FFN, same LayerNorm.
Different training data, different sizes, small architectural tweaks.


LAYER 2: Fine-Tuning for Sentence Embeddings (the "specialization")
──────────────────────────────────────────────────────────────────
Take a base encoder from Layer 1, fine-tune it so that mean-pooled
output vectors capture sentence-level meaning.

This is where the different models and teams diverge:

  ┌──────────────────────────────────────────────────────────────┐
  │  TRAINED USING SentenceTransformers library:                  │
  │                                                               │
  │  all-MiniLM-L6-v2      base: MiniLM      trained by: UKPLab │
  │  all-MiniLM-L12-v2     base: MiniLM      trained by: UKPLab │
  │  all-mpnet-base-v2     base: MPNet       trained by: UKPLab │
  │  multi-qa-MiniLM-L6    base: MiniLM      trained by: UKPLab │
  │                                                               │
  │  These used the SentenceTransformers training framework       │
  │  with contrastive loss on sentence pairs.                     │
  └──────────────────────────────────────────────────────────────┘

  ┌──────────────────────────────────────────────────────────────┐
  │  TRAINED USING THEIR OWN PIPELINES:                           │
  │                                                               │
  │  E5-large-v2          base: BERT-large   trained by: Microsoft│
  │  BGE-large-en-v1.5    base: BERT-large   trained by: BAAI     │
  │  GTE-large            base: BERT-large   trained by: Alibaba  │
  │  nomic-embed-text     base: BERT (mod)   trained by: Nomic    │
  │  Jina-embeddings-v2   base: BERT (mod)   trained by: Jina AI  │
  │                                                               │
  │  These used their OWN training code, often with different    │
  │  loss functions, data mixing strategies, hard negative mining,│
  │  and multi-stage training. But the CONCEPT is the same:      │
  │  contrastive learning to make similar texts have close vectors│
  └──────────────────────────────────────────────────────────────┘


LAYER 3: The Libraries That Let You USE These Models
────────────────────────────────────────────────────
  SentenceTransformers library (by UKPLab):
    - Can load ANY of the above models (both its own and others)
    - Can fine-tune ANY of them further
    - Provides encode(), similarity(), etc.
    
  HuggingFace Transformers library:
    - Lower level. Loads the raw encoder model.
    - You write the pooling and similarity code yourself.
    - More control, more code.

  Both load the same model weights from the same HuggingFace Hub.
```

So the summary:

```
✅ Same idea (contrastive learning to produce good sentence embeddings)
❌ Not always the same tooling (different training pipelines)
✅ But all compatible with the SentenceTransformers library at inference time
```

---

## The Library vs Model vs Weights Relationship

This is where people get confused, so let me be very precise:

```
HuggingFace Hub (model storage):
  ├── sentence-transformers/all-MiniLM-L6-v2     ← model weights
  ├── sentence-transformers/all-mpnet-base-v2     ← model weights
  ├── BAAI/bge-large-en-v1.5                      ← model weights
  ├── intfloat/e5-large-v2                        ← model weights
  └── bert-base-uncased                           ← raw BERT weights

Each of these is a folder containing:
  - config.json       (architecture: layers, heads, dims)
  - model.safetensors (the actual weight numbers, millions of floats)
  - tokenizer files   (vocabulary, merge rules)
  - special_tokens_map.json
```

When you write code:

```python
from sentence_transformers import SentenceTransformer

# This downloads weights from HuggingFace Hub
# and wraps them in the SentenceTransformers pipeline
model = SentenceTransformer('sentence-transformers/all-MiniLM-L6-v2')
```

What happens internally:

```
1. Download config.json → reads: "6 layers, 12 heads, 384 dims, MiniLM architecture"

2. BUILD the architecture in code:
   embedding_table = nn.Embedding(30522, 384)
   position_table = nn.Embedding(512, 384)
   layer_1 = TransformerBlock(384, 12_heads)
   layer_2 = TransformerBlock(384, 12_heads)
   layer_3 = TransformerBlock(384, 12_heads)
   layer_4 = TransformerBlock(384, 12_heads)
   layer_5 = TransformerBlock(384, 12_heads)
   layer_6 = TransformerBlock(384, 12_heads)

3. LOAD the weights from model.safetensors into these layers:
   embedding_table.weight = [downloaded 30522×384 matrix]
   layer_1.attention.W_Q = [downloaded 384×384 matrix]
   layer_1.attention.W_K = [downloaded 384×384 matrix]
   ... (all weights loaded)
   
4. WRAP with pooling layer:
   pooling = MeanPooling()
   
5. Ready to use:
   model.encode("text") → tokenize → encoder → mean pool → [384] vector
```

**The SentenceTransformers library provides:**
- The code to build the encoder architecture
- The code for tokenization
- The code for pooling (mean, CLS, max)
- The code for fine-tuning (loss functions, training loops)
- Convenience methods (encode, similarity)

**The model weights on HuggingFace provide:**
- The actual numbers (millions of floats) that go into the architecture
- These numbers are what make the model "smart" — they were learned during pretraining + fine-tuning

**The library builds the house. The weights are the furniture that makes it useful.**

You can use the same library code with completely different weights:

```python
# Same library, different weights → different behavior

model_a = SentenceTransformer('all-MiniLM-L6-v2')       # small, fast, English
model_b = SentenceTransformer('all-mpnet-base-v2')       # medium, better quality
model_c = SentenceTransformer('BAAI/bge-large-en-v1.5')  # large, best quality
model_d = SentenceTransformer('bert-base-uncased')        # raw BERT, BAD at similarity!

# All four use the same library code
# All four call model.encode("text") the same way
# But they produce DIFFERENT embeddings because the weights are different
```

---

## How the Fine-Tuning Actually Works (Contrastive Learning)

### The Training Data

```
Pairs or triplets of sentences with relationships:

Pair format:
  ("A cat sits on a mat", "A feline rests on a rug", 0.95)   ← similar
  ("A cat sits on a mat", "Stock prices rose sharply", 0.05)  ← dissimilar

Triplet format:
  (anchor: "A cat sits on a mat",
   positive: "A feline rests on a rug",      ← should be CLOSE to anchor
   negative: "Stock prices rose sharply")     ← should be FAR from anchor

Sources of training data:
  - NLI datasets (Natural Language Inference): sentence pairs labeled as
    entailment/contradiction/neutral
  - Paraphrase datasets: pairs of sentences that mean the same thing
  - Question-answer pairs: question + relevant passage
  - Hundreds of millions of pairs total
```

### The Loss Functions

**Cosine Similarity Loss (for pairs with continuous scores):**

```
Sentence A → encoder → pool → vector A
Sentence B → encoder → pool → vector B

predicted_similarity = cosine_sim(A, B)      e.g., 0.72
actual_similarity = label                     e.g., 0.95

loss = (predicted_similarity - actual_similarity)²
     = (0.72 - 0.95)² = 0.053

Backprop pushes the encoder to produce vectors where
cosine_sim(A, B) is closer to 0.95 → vectors get closer.
```

**Triplet Loss:**

```
Anchor   → encoder → pool → vector_a
Positive → encoder → pool → vector_p    (should be CLOSE to anchor)
Negative → encoder → pool → vector_n    (should be FAR from anchor)

dist_positive = distance(vector_a, vector_p)   e.g., 0.3
dist_negative = distance(vector_a, vector_n)   e.g., 0.5
margin = 0.5

loss = max(0, dist_positive - dist_negative + margin)
     = max(0, 0.3 - 0.5 + 0.5)
     = max(0, 0.3)
     = 0.3

The loss says: "positive should be at least 'margin' closer than negative."
If it already is → loss = 0, no update needed.
If it isn't → loss > 0, push positive closer / negative farther.
```

**Multiple Negatives Ranking Loss (most popular now):**

```
Batch of N pairs: (query_1, passage_1), (query_2, passage_2), ..., (query_N, passage_N)

Each query_i should be similar to passage_i (its pair).
Each query_i should be DISSIMILAR to passage_j for j ≠ i.

So from a batch of N pairs, you get:
  N positive pairs (correct matches)
  N×(N-1) negative pairs (incorrect matches — for free!)

This is extremely data-efficient. A batch of 64 pairs gives you
64 positives and 64×63 = 4,032 negatives.

The loss pushes query_i closer to passage_i and farther from all other passages.
```

### What Changes During Fine-Tuning

```
BEFORE fine-tuning:
  All encoder weights are from pretraining (MLM task).
  The model understands language but doesn't optimize for similarity.

DURING fine-tuning:
  Sentence pairs go through the encoder.
  Loss compares similarity of output vectors to desired similarity.
  Backprop flows through: pooling → all 6/12 layers → embeddings.
  Adam updates all weights.
  
  EVERY weight in the encoder gets adjusted:
    - Token embeddings shift so similar words are closer
    - Attention weights change so the model focuses on meaning-bearing tokens
    - FFN weights change to produce more "similarity-friendly" representations
    
AFTER fine-tuning:
  Same architecture, different weights.
  Mean-pooled vectors now reliably capture sentence meaning.
  Similar sentences → close vectors. Different sentences → far vectors.
```

### Fine-Tuning in Code (Actual Sentence Transformers API)

```python
from sentence_transformers import SentenceTransformer, InputExample, losses
from torch.utils.data import DataLoader

# Start from a pretrained model (could be raw BERT or already fine-tuned)
model = SentenceTransformer('bert-base-uncased')

# Training data
train_examples = [
    InputExample(texts=["A cat sits on a mat", "A feline rests on a rug"], label=0.9),
    InputExample(texts=["A cat sits on a mat", "Stock prices fell"], label=0.1),
    # ... thousands more pairs
]

train_dataloader = DataLoader(train_examples, batch_size=32, shuffle=True)

# Loss function
train_loss = losses.CosineSimilarityLoss(model=model)

# Fine-tune!
model.fit(
    train_objectives=[(train_dataloader, train_loss)],
    epochs=3,
    warmup_steps=100,
)

# Save the fine-tuned model
model.save("my-custom-sentence-model")

# Now this produces good sentence embeddings
embedding = model.encode("A cat sits on a mat")
```

What `model.fit()` does internally:

```
for epoch in range(3):
    for batch in train_dataloader:
        
        # Encode both sentences in the pair
        embeddings_a = model.encode(batch.texts_a)   # [32, 768]
        embeddings_b = model.encode(batch.texts_b)   # [32, 768]
        
        # Compute predicted similarity
        pred_sim = cosine_similarity(embeddings_a, embeddings_b)  # [32]
        
        # Compute loss against labels
        loss = ((pred_sim - batch.labels) ** 2).mean()
        
        # Backprop through the entire encoder
        loss.backward()
        
        # Update weights
        optimizer.step()
        optimizer.zero_grad()
```

---

> **See also:**
> - `encoder_only_complete_guide.md` — How the encoder model (BERT) that Sentence Transformers uses internally actually works
> - `shared_foundations.md` — Static vs dynamic embeddings, context window — foundational concepts for understanding Sentence Transformers
> - `decoder_only_complete_guide.md` — How GPT-style models work (contrast with encoder approach)
> - `transformer_deep_reference.md` — Dense refresher for all concepts
> - `transformer_visual_mental_model.md` — Big-picture visual map
