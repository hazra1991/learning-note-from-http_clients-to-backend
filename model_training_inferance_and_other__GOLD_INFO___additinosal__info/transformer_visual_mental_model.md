# The Transformer Mental Model — See It, Don't Read It

> **What this is:** A visual map of how everything connects. Open this when you need to get your brain back into context in 30 seconds. Heavy on flows, diagrams, and visual structure. Light on paragraphs.

---

## The Universe of Transformer Models

```
                          ┌─────────────────────────────────┐
                          │     THE TRANSFORMER BLOCK        │
                          │                                  │
                          │  LayerNorm → Attention → +       │
                          │  LayerNorm → FFN → +             │
                          │                                  │
                          │  (same building block everywhere)│
                          └──────────┬──────────────────────┘
                                     │
                    ┌────────────────┼────────────────────┐
                    │                │                     │
                    ▼                ▼                     ▼
          ┌─────────────┐  ┌─────────────────┐  ┌──────────────────┐
          │  ENCODER     │  │  DECODER         │  │ ENCODER-DECODER  │
          │  (BERT)      │  │  (GPT, LLaMA,   │  │ (T5, BART)       │
          │              │  │   Claude)        │  │                  │
          │  Sees ALL    │  │  Sees only PAST  │  │ Encoder: sees all│
          │  tokens      │  │  tokens          │  │ Decoder: sees    │
          │              │  │                  │  │ past + encoder   │
          │  Fills       │  │  Generates       │  │                  │
          │  blanks      │  │  next token      │  │ Input → Output   │
          │              │  │                  │  │ (translation,    │
          │  UNDERSTANDS │  │  CREATES         │  │  summarization)  │
          └─────────────┘  └─────────────────┘  └──────────────────┘
                │                   │                      │
                ▼                   ▼                      ▼
          Classification      Chat, Code,            Translation,
          Search, NER,        Stories,               Summarization,
          Similarity,         Completion,            Question Answering
          Q&A (extractive)    Reasoning              (generative)
```

---

## The One Diagram That Explains Everything

### What Happens When Text Enters a Model

```
 YOUR TEXT
 "The cat sat on the mat"
      │
      ▼
┌──────────────┐
│  TOKENIZER   │   Splits text into subword pieces
│              │   "The" "cat" "sat" "on" "the" "mat"
│  Text → IDs  │   [464, 3797, 3332, 319, 262, 2603]
└──────┬───────┘
       │
       │  Just integers now. No meaning yet.
       ▼
┌──────────────────────────────────────────────┐
│  EMBEDDING LOOKUP                             │
│                                               │
│  Token IDs → vectors via table lookup         │
│  [464]  → [0.012, -0.034, 0.056, ..., 0.021] │  768 numbers
│  [3797] → [0.044, -0.023, 0.091, ..., 0.017] │  768 numbers
│  [3332] → [-0.008, 0.067, 0.033, ..., -0.045]│  768 numbers
│  ...                                          │
│                                               │
│  + POSITIONAL EMBEDDING (added, same shape)   │
│  Position 0 → [0.1, 0.9, ...]                │
│  Position 1 → [0.8, 0.5, ...]                │
│  ...                                          │
│                                               │
│  Result: [6 tokens, 768 dims]                 │
│  Each token = a vector. Knows its position.   │
│  But knows NOTHING about its neighbors yet.   │
└──────────────────┬───────────────────────────┘
                   │
                   │  This is where the magic starts
                   ▼
┌──────────────────────────────────────────────────────────────────┐
│                                                                   │
│   TRANSFORMER LAYERS  (repeat N times — 12, 24, 32, 80, 96...)  │
│                                                                   │
│   Each layer does TWO things:                                     │
│                                                                   │
│   ┌─────────────────────────────────────────────────────────┐    │
│   │  1. ATTENTION — "Talk to other tokens"                   │    │
│   │                                                          │    │
│   │     Each token creates:                                  │    │
│   │       Q = "What am I looking for?"                       │    │
│   │       K = "What do I offer?"                             │    │
│   │       V = "Here's my content"                            │    │
│   │                                                          │    │
│   │     Q·K^T = compatibility scores (who cares about whom)  │    │
│   │     softmax = attention weights (how much to borrow)     │    │
│   │     weights · V = context-blended output                 │    │
│   │                                                          │    │
│   │     DECODER: each token only sees PAST tokens (masked)   │    │
│   │     ENCODER: each token sees ALL tokens (no mask)        │    │
│   │                                                          │    │
│   │     12 heads do this in parallel on different slices     │    │
│   │     → concatenate → one rich context-aware vector        │    │
│   └─────────────────────────────────────────────────────────┘    │
│                          │                                        │
│                          ▼                                        │
│   ┌─────────────────────────────────────────────────────────┐    │
│   │  2. FFN — "Think about what I gathered"                  │    │
│   │                                                          │    │
│   │     Each token independently:                            │    │
│   │     [768] → expand → [3072] → GELU → compress → [768]   │    │
│   │                                                          │    │
│   │     No cross-token mixing. Pure per-token processing.    │    │
│   │     This is where the model "reasons" about the context  │    │
│   │     that attention gathered.                             │    │
│   └─────────────────────────────────────────────────────────┘    │
│                          │                                        │
│                          ▼                                        │
│   Both steps have RESIDUAL CONNECTIONS (add input back)          │
│   and LAYER NORM (keep numbers stable)                           │
│                                                                   │
│   Output: SAME SHAPE [6 tokens, 768 dims]                       │
│   But now each vector is deeply context-aware                    │
│                                                                   │
└──────────────────────────────┬───────────────────────────────────┘
                               │
                               │  After all layers: rich representations
                               ▼
              ┌────────────────────────────────────┐
              │  OUTPUT HEAD  (depends on task)     │
              │                                     │
              │  DECODER (generation):              │
              │    [768] → [vocab_size] via LM head │
              │    → softmax → probability over     │
              │      every possible next token      │
              │    → pick one → append → repeat     │
              │                                     │
              │  ENCODER (classification):          │
              │    [CLS] vector [768]               │
              │    → Linear → [num_classes]         │
              │    → softmax → class probabilities  │
              │                                     │
              │  ENCODER (similarity):              │
              │    Mean of all token vectors [768]  │
              │    = one vector per sentence         │
              │    → cosine similarity between two  │
              └────────────────────────────────────┘
```

---

## Training vs Inference — The Two Modes

```
╔══════════════════════════════════════════════════════════════════════════════╗
║                              TRAINING                                       ║
║                                                                             ║
║  Goal: Make the model's weights BETTER                                      ║
║                                                                             ║
║  ┌──────────┐    ┌──────────┐    ┌──────────┐    ┌──────────┐             ║
║  │  Batch   │───→│ Forward  │───→│   Loss   │───→│ Backward │             ║
║  │  of text │    │  Pass    │    │ (how bad?)│    │  Pass    │             ║
║  └──────────┘    └──────────┘    └──────────┘    └────┬─────┘             ║
║                                                       │                     ║
║       ┌───────────────────────────────────────────────┘                     ║
║       │                                                                     ║
║       ▼                                                                     ║
║  ┌──────────┐                                                              ║
║  │ Optimizer│   Adam: uses momentum (trend) + velocity (adapt per weight)  ║
║  │ (Adam)   │   Updates ALL weights slightly to reduce loss                ║
║  └──────────┘                                                              ║
║       │                                                                     ║
║       └───→  Repeat millions of times until loss is low                    ║
║                                                                             ║
║  DECODER training:  predict next token at every position                   ║
║  ENCODER training:  predict masked tokens (15% randomly hidden)            ║
║                                                                             ║
╚══════════════════════════════════════════════════════════════════════════════╝


╔══════════════════════════════════════════════════════════════════════════════╗
║                              INFERENCE                                      ║
║                                                                             ║
║  Goal: USE the trained model to produce output                              ║
║  Weights are FROZEN. No learning happens.                                   ║
║                                                                             ║
║  ┌──────────┐    ┌──────────┐    ┌──────────┐    ┌──────────┐             ║
║  │  Your    │───→│ Forward  │───→│  Logits  │───→│  Sample  │             ║
║  │  prompt  │    │  Pass    │    │          │    │  token   │             ║
║  │          │    │  (only)  │    │ [50,257] │    │          │             ║
║  └──────────┘    └──────────┘    └──────────┘    └────┬─────┘             ║
║                                                       │                     ║
║                                 ┌─────────────────────┘                     ║
║                                 │                                           ║
║                                 ▼                                           ║
║                          Append token to prompt                             ║
║                          Run forward pass again                             ║
║                          Repeat until done                                  ║
║                                                                             ║
║  NO backward pass. NO gradient computation. NO weight updates.              ║
║  Just: text in → forward pass → probabilities out → pick token → repeat.   ║
║                                                                             ║
╚══════════════════════════════════════════════════════════════════════════════╝
```

---

## What You're Actually Choosing When You Pick a Model

```
  "I want to GENERATE text"
  (chat, code, stories, completion)
        │
        └──→  DECODER model (GPT, LLaMA, Claude, Mistral)
              Sees only past tokens. Generates one token at a time.
              More parameters = more knowledge + better reasoning


  "I want to UNDERSTAND text"
  (classify, search, find similar, extract info)
        │
        └──→  ENCODER model (BERT, RoBERTa, all-MiniLM, BGE)
              Sees all tokens both directions. Creates rich representations.
              Often smaller + faster. Perfect for embeddings.


  "I want to TRANSFORM text to text"
  (translate, summarize, convert format)
        │
        └──→  ENCODER-DECODER model (T5, BART, mBART)
              Encoder understands input fully (bidirectional).
              Decoder generates output (autoregressive).
              Best when input and output are structurally different.


  "I want to COMPARE or SEARCH text"
  (semantic search, duplicate detection, RAG retrieval)
        │
        └──→  ENCODER model + Sentence Transformers
              Produces one fixed-size vector per sentence.
              Compare vectors with cosine similarity.
              Fast. Can index millions of documents.
```

---

## Inference Deep Dive — What Happens When You Chat with an LLM

```
You type: "What is the capital of France?"

Step 1: TOKENIZE
  "What" "is" "the" "capital" "of" "France" "?"
  [2061, 318, 262, 3139, 286, 4881, 30]

Step 2: EMBED + POSITION
  7 vectors of size 4096 (for a LLaMA-sized model)
  Each vector = token meaning + position info

Step 3: FORWARD PASS through all layers (32 for LLaMA 7B)
  Each layer: attention (gather context) + FFN (process it)
  After 32 layers: deeply contextual representations

Step 4: LM HEAD on the LAST token's vector
  [4096] × [4096, 32000] = [32000] logits
  One score per vocabulary token

Step 5: SAMPLING
  ┌───────────────────────────────────────────────┐
  │                                               │
  │  logits: [..., "The"=2.1, "Paris"=8.7,       │
  │           "London"=3.2, "pizza"=-5.1, ...]    │
  │                                               │
  │  Optional: Grammar mask (set invalid to -inf) │
  │  Optional: Temperature scaling (logits / T)   │
  │                                               │
  │  softmax → [..., "Paris"=0.73, "The"=0.05,   │
  │             "London"=0.08, "pizza"=0.0, ...]  │
  │                                               │
  │  Pick "Paris" (highest prob or sampled)       │
  │                                               │
  └───────────────────────────────────────────────┘

Step 6: APPEND "Paris" to the sequence

Step 7: REPEAT from Step 2 with:
  "What is the capital of France? Paris"
  → next prediction might be "is" or "." or ","

Step 8: KEEP REPEATING until:
  - Model outputs <|endoftext|> or </s>
  - Max length reached
  - Stop sequence detected
```

### Sampling Strategies — What They Actually Do to the Probabilities

```
Raw logits:  [2.0, 8.7, 3.2, -5.1, 1.0, ...]

┌─────────────────────────────────────────────────────────────┐
│ TEMPERATURE (controls randomness)                            │
│                                                              │
│ T = 0.1 (very low):  logits/0.1 = [20, 87, 32, -51, 10]   │
│   → softmax → [0.00, 1.00, 0.00, 0.00, 0.00]              │
│   → ALWAYS picks "Paris". Deterministic. Boring.            │
│                                                              │
│ T = 1.0 (default):   logits unchanged                       │
│   → softmax → [0.02, 0.73, 0.08, 0.00, 0.01]              │
│   → Usually picks "Paris", sometimes others. Balanced.      │
│                                                              │
│ T = 2.0 (high):      logits/2 = [1.0, 4.35, 1.6, -2.55]   │
│   → softmax → [0.04, 0.48, 0.09, 0.00, 0.03]              │
│   → More spread out. More creative/random. Can hallucinate. │
└─────────────────────────────────────────────────────────────┘

┌─────────────────────────────────────────────────────────────┐
│ TOP-K (keep only k most likely tokens)                       │
│                                                              │
│ k = 3:  Keep "Paris"(0.73), "London"(0.08), "The"(0.05)    │
│         Zero out everything else. Re-normalize.              │
│         → [0.00, 0.85, 0.09, 0.00, 0.06]                   │
│         Model can only pick from top 3 candidates.          │
└─────────────────────────────────────────────────────────────┘

┌─────────────────────────────────────────────────────────────┐
│ TOP-P / NUCLEUS (keep tokens until cumulative prob ≥ p)      │
│                                                              │
│ p = 0.9: Sort by prob: "Paris"(0.73) → cumsum = 0.73       │
│          Add "London"(0.08) → cumsum = 0.81                 │
│          Add "The"(0.05) → cumsum = 0.86                    │
│          Add "Berlin"(0.04) → cumsum = 0.90  ← hit p!      │
│          Keep these 4, zero out rest, re-normalize.          │
│          Adapts to model's confidence automatically.         │
└─────────────────────────────────────────────────────────────┘

┌─────────────────────────────────────────────────────────────┐
│ GRAMMAR / GUIDED GENERATION                                  │
│                                                              │
│ Task: Output must be valid JSON                              │
│ Current output so far: '{"name": '                           │
│ Valid next tokens: only '"' (start a string value)           │
│                                                              │
│ Set ALL other logits to -inf                                │
│ After softmax: P('"') = 1.0, everything else = 0.0          │
│ Model is FORCED to output valid structure                    │
│ But its preferences among valid tokens are preserved         │
└─────────────────────────────────────────────────────────────┘
```

---

## The Shape Journey — Follow the Tensor

### Decoder (GPT-2 Small, 12 layers)

```
"The cat sat on the mat"
         │
    ┌────┴────┐
    │Tokenizer│
    └────┬────┘
         │
   [6] token IDs (integers)
         │
    ┌────┴──────────────────┐
    │Token Embed [50257,768]│──→ [6, 768]
    └───────────────────────┘       +
    ┌───────────────────────┐
    │Pos Embed [1024, 768]  │──→ [6, 768]
    └───────────────────────┘       =
                                [6, 768]  input to layers
                                    │
    ┌───────────────────────────────┤
    │ Layer 1                       │
    │   LN    → [6, 768]           │
    │   Attn  → split into 12 heads│
    │           each [6, 64]       │
    │           scores [6, 6]      │  ← who attends to whom
    │           output [6, 64] ×12 │
    │           concat → [6, 768]  │
    │           + residual         │
    │   LN    → [6, 768]           │
    │   FFN   → [6, 3072] → [6, 768]│
    │           + residual         │
    │   Out:    [6, 768]           │
    ├───────────────────────────────┤
    │ Layer 2:  [6, 768] → [6, 768]│
    ├───────────────────────────────┤
    │ ...                           │
    ├───────────────────────────────┤
    │ Layer 12: [6, 768] → [6, 768]│
    └───────────────────┬──────────┘
                        │
                    [6, 768]
                        │
                  ┌─────┴──────┐
                  │Final LN    │
                  └─────┬──────┘
                        │
                    [6, 768]
                        │
              ┌─────────┴──────────┐
              │LM Head [768, 50257]│
              └─────────┬──────────┘
                        │
                  [6, 50257]  logits
                        │
                  ┌─────┴──────┐
                  │  Softmax   │
                  └─────┬──────┘
                        │
                  [6, 50257]  probabilities
                        │
              Each position predicts next token
```

---

## The Attention Pattern — What the Model Actually "Sees"

### Decoder: The Triangle (Causal)

```
Generating: "The cat sat on"

             The  cat  sat  on
     The   [  ✓    ·    ·   · ]     "The" is alone. No context.
     cat   [  ✓    ✓    ·   · ]     "cat" sees "The" + itself
     sat   [  ✓    ✓    ✓   · ]     "sat" sees "The cat" + itself
     on    [  ✓    ✓    ✓   ✓ ]     "on" sees everything so far

     ✓ = can attend       · = masked (-inf)

     Triangle grows as sequence grows.
     The LAST position has the most context.
     That's why we use the LAST position to predict the next token.
```

### Encoder: The Full Grid (Bidirectional)

```
Understanding: "The cat sat on"

             The  cat  sat  on
     The   [  ✓    ✓    ✓   ✓ ]     Every token
     cat   [  ✓    ✓    ✓   ✓ ]     sees every
     sat   [  ✓    ✓    ✓   ✓ ]     other token
     on    [  ✓    ✓    ✓   ✓ ]     in both directions

     Every position has FULL context.
     That's why [CLS] (position 0) can summarize the entire sentence.
     But can't generate — it already sees the "future."
```

---

## The Training Data Pipeline

```
┌─────────────────────────────────────────────────────────────────┐
│ THE INTERNET (trillions of words)                                │
│                                                                  │
│  Web pages ─┐                                                    │
│  Books ─────┤                                                    │
│  Wikipedia ─┼──→ COLLECT ──→ CLEAN ──→ DEDUPLICATE               │
│  Code ──────┤         (remove HTML,    (same text on 100 sites   │
│  Papers ────┘          filter junk)     → keep one)              │
│                                                                  │
│  Result: ~1-5 trillion tokens of clean text                      │
└──────────────────────────────┬──────────────────────────────────┘
                               │
                               ▼
                ┌──────────────────────────────┐
                │  TOKENIZE (BPE, done once)    │
                │                               │
                │  "The cat sat..." →            │
                │  [464, 3797, 3332, ...]       │
                │                               │
                │  Save as binary files on disk  │
                └──────────────┬───────────────┘
                               │
                               ▼
                ┌──────────────────────────────┐
                │  CHUNK into sequences         │
                │                               │
                │  Long stream of token IDs     │
                │  → split into [1024] chunks   │
                │                               │
                │  Documents separated by        │
                │  <|endoftext|> token           │
                └──────────────┬───────────────┘
                               │
                               ▼
                ┌──────────────────────────────┐
                │  BATCH                        │
                │                               │
                │  32 sequences per batch       │
                │  Shape: [32, 1024]            │
                │                               │
                │  Input:  batch[:, :-1]  [32, 1023] │
                │  Target: batch[:, 1:]   [32, 1023] │
                │                               │
                │  32 × 1023 = 32,736           │
                │  training examples per step   │
                └──────────────────────────────┘
```

---

## The Loss Landscape — What Training Looks Like

```
Loss
  │
10.8 ┤ ★  ← Step 0: Random model. log(50257) ≈ 10.8
  │  │     Equal probability to ALL 50,257 tokens.
  │  │     Like guessing randomly.
  │   \
  │    \
 6.2 ┤  ╲  ← Step 1K: Learned common words
  │     ╲   "the", "a", "is" now get higher probability
  │      ╲
  │       ╲
 4.1 ┤     ╲  ← Step 10K: Learned grammar
  │        ╲   "The cat ___" → predicts verbs, not nouns
  │         ╲
 3.2 ┤       ╲────  ← Step 100K: Learned facts
  │                ───   "Paris is the capital of ___" → France
 2.8 ┤                 ──────────  ← Step 300K: Nuanced
  │                                 Fine-grained knowledge
  └──┬──────┬──────┬──────┬──────┬──→ Steps
     0     50K   100K   200K   300K
```

---

## Mental Model for Using a Model (Inference Decisions)

### When you change Temperature:

```
Low T (0.1-0.3):        "Be confident. Pick the obvious answer."
                          → Factual questions, code, structured output
                          → Less creative, can be repetitive

Default T (0.7-1.0):    "Be yourself. Balance confidence with variety."
                          → General conversation, writing
                          → Good balance of quality and diversity

High T (1.2-2.0):       "Be experimental. Surprise me."
                          → Brainstorming, creative writing
                          → More hallucination risk
```

### When you change Max Tokens:

```
This doesn't affect quality — it just sets when to STOP.
The model generates one token at a time.
Max tokens = maximum number of generation steps.
The model can still stop earlier (if it outputs a stop token).
```

### When you change Top-P:

```
Top-P = 0.1:   "Only consider the single most likely continuation"
Top-P = 0.5:   "Consider the top handful of options"
Top-P = 0.9:   "Consider most reasonable options" (common default)
Top-P = 1.0:   "Consider everything" (effectively disabled)
```

### What Context Window means:

```
Context window = max number of tokens the model can "see"

┌──────────────────────────────────────────────┐
│ System prompt + conversation history + your  │
│ latest message + the model's response so far │
│                                              │
│ ALL of this must fit in the context window.  │
│                                              │
│ GPT-2:     1,024 tokens   (~750 words)      │
│ GPT-3.5:   4,096 tokens   (~3,000 words)    │
│ GPT-4:     128K tokens    (~96,000 words)    │
│ Claude:    200K tokens    (~150,000 words)   │
│ LLaMA 3:  128K tokens    (~96,000 words)    │
│                                              │
│ Beyond this limit: the model literally       │
│ cannot see earlier tokens. They're gone.     │
└──────────────────────────────────────────────┘
```

---

## Quick Decision Matrix

```
┌─────────────────────────┬────────────────────────────┬──────────────────┐
│ I want to...            │ Use this type              │ Example models   │
├─────────────────────────┼────────────────────────────┼──────────────────┤
│ Generate text/code/chat │ Decoder                    │ GPT-4, Claude,   │
│                         │                            │ LLaMA, Mistral   │
├─────────────────────────┼────────────────────────────┼──────────────────┤
│ Classify text           │ Encoder                    │ BERT, RoBERTa,   │
│ (spam, sentiment, etc.) │ (fine-tune with classifier)│ DeBERTa          │
├─────────────────────────┼────────────────────────────┼──────────────────┤
│ Search / find similar   │ Encoder                    │ all-MiniLM,      │
│ text (semantic search)  │ (via Sentence Transformers)│ BGE, E5, GTE     │
├─────────────────────────┼────────────────────────────┼──────────────────┤
│ Extract entities (NER)  │ Encoder                    │ BERT, SpanBERT   │
│                         │ (token-level classifier)   │                  │
├─────────────────────────┼────────────────────────────┼──────────────────┤
│ Translate languages     │ Encoder-Decoder            │ T5, mBART,       │
│                         │ (or large Decoder)         │ NLLB             │
├─────────────────────────┼────────────────────────────┼──────────────────┤
│ Summarize documents     │ Encoder-Decoder            │ T5, BART, Pegasus│
│                         │ (or large Decoder)         │                  │
├─────────────────────────┼────────────────────────────┼──────────────────┤
│ Build a RAG system      │ Encoder (retrieval) +      │ BGE + Claude,    │
│                         │ Decoder (generation)       │ E5 + GPT-4       │
├─────────────────────────┼────────────────────────────┼──────────────────┤
│ Build embeddings for    │ Encoder                    │ all-MiniLM,      │
│ a vector database       │ (Sentence Transformers)    │ BGE-large        │
└─────────────────────────┴────────────────────────────┴──────────────────┘
```

---

## What Parameters Actually Mean (When Someone Says "7B Model")

```
"7B parameters" = 7 billion learnable numbers

These numbers are distributed across:
  ┌──────────────────────────────────┐
  │  Token Embedding Table           │  vocab × d_model
  │  Position Embedding Table        │  max_seq × d_model
  │                                  │
  │  Per Layer (×N layers):          │
  │    Attention: W_Q, W_K, W_V, W_O│  4 × d_model²
  │    FFN: W_up, W_down            │  2 × d_model × 4×d_model
  │    LayerNorms: γ, β (×2)        │  4 × d_model
  │                                  │
  │  LM Head (often tied to embed)  │  d_model × vocab
  └──────────────────────────────────┘

  More parameters = wider layers (bigger d_model)
                  + more layers (deeper network)
                  = more knowledge stored
                  + better reasoning ability
                  + slower inference
                  + more GPU memory needed

  Memory needed (inference):
    7B × 2 bytes (float16) = 14 GB GPU RAM
    70B × 2 bytes = 140 GB GPU RAM

  Memory needed (training):
    Model + Gradients + Adam states ≈ 6× model size
    7B → ~84 GB
    70B → ~840 GB
```

---

## The One-Sentence Summaries

```
Tokenizer:       Splits text into subword pieces and maps them to integer IDs.
Embedding:       Looks up a learned vector (768+ dims) for each token ID.
Position Embed:  Adds position information so the model knows word order.
Attention:       Each token asks "who is relevant to me?" and blends their info.
Causal Mask:     Decoder-only: prevents looking at future tokens.
Multi-Head:      Same attention, 12 different "perspectives", concatenated.
FFN:             Per-token deep processing. Expand → activate → compress.
Residual:        Add input back. Keeps gradients flowing. Incremental refinement.
LayerNorm:       Keeps numbers stable. Mean=0, std=1, then learned scale/shift.
Logits:          Raw score per vocab token. Not probabilities yet.
Softmax:         Converts logits to probabilities (positive, sums to 1).
Cross-Entropy:   -log(P(correct)). Low = good. High = bad. THE training signal.
Backprop:        Chain rule backwards. Computes gradient for every weight.
Adam:            Smart optimizer. Momentum (direction) + velocity (step size).
Self-Supervised: Labels come from the data. Shift by 1 (decoder) or mask (encoder).
```

---

> **Companion guides for the full discussion:**
> - `decoder_only_complete_guide.md` — Everything about GPT-style models with numerical examples
> - `encoder_only_complete_guide.md` — BERT, MLM, bidirectional attention, classification
