# The Deep World of Search & Retrieval — From First Principles to Production Pipelines

> A master reference for retrieval system design. The goal is not memorization — it's to install a **reasoning engine** so that for any retrieval problem you can derive the right chunk, the right embedding, the right query strategy, and the right pipeline, and always know *why*.
>
> **How this document is built (read this once):** Each section *leads* with a vivid explanation and a worked example — the **teaching layer**, for understanding. Tables, formulas, and cheat-sheets sit at the end of sections and in Section 16 — the **lookup layer**, for scanning mid-build. Read it top-to-bottom once to learn; jump to the tables later to decide.

---

## Table of Contents

1. [The Core Problem — Why Retrieval Is Hard](#1-the-core-problem--why-retrieval-is-hard)
2. [Classical / Lexical Retrieval — TF-IDF & BM25](#2-classical--lexical-retrieval--tf-idf--bm25)
3. [Inverted Indexes — How Lexical Search Runs in Milliseconds](#3-inverted-indexes--how-lexical-search-runs-in-milliseconds)
4. [Query Understanding — Planning, Decomposition, Rewriting](#4-query-understanding--planning-decomposition-rewriting)
5. [The Embedding Revolution — Semantic Search](#5-the-embedding-revolution--semantic-search)
6. [Bi-encoders vs Cross-encoders — The Critical Distinction](#6-bi-encoders-vs-cross-encoders--the-critical-distinction)
7. [Exact vs Approximate Search — IndexFlat, IVF, HNSW, PQ](#7-exact-vs-approximate-search--indexflat-ivf-hnsw-pq)
8. [Hybrid Retrieval & Fusion + The Full Pipeline](#8-hybrid-retrieval--fusion--the-full-pipeline)
9. [A Worked End-to-End Trace (the JWT query)](#9-a-worked-end-to-end-trace-the-jwt-query)
10. [Re-ranking with Cross-encoders — How to Actually Use Them](#10-re-ranking-with-cross-encoders--how-to-actually-use-them)
11. [Beyond Simple Embeddings — SPLADE & ColBERT](#11-beyond-simple-embeddings--splade--colbert)
12. [Chunking — The Foundation That Sets Your Ceiling](#12-chunking--the-foundation-that-sets-your-ceiling)
13. [What Makes a Good Embedding](#13-what-makes-a-good-embedding)
14. [The Design Framework + When to Use an LLM](#14-the-design-framework--when-to-use-an-llm)
15. [Evaluation — What Makes Every Decision Settle Itself](#15-evaluation--what-makes-every-decision-settle-itself)
16. [Quick-Reference Cheat Sheets](#16-quick-reference-cheat-sheets)

---

## 1. The Core Problem — Why Retrieval Is Hard

Before any technique, ask: *what are we actually trying to do?* You have a corpus (10 docs, or 100M code chunks). A query arrives. You need the **most relevant** chunks — fast, accurately, at scale. Sounds simple; here's why it isn't. Four hard problems sit underneath everything:

- **Vocabulary mismatch.** The user asks *"how do I exit a vim editor"*; the doc says *"to quit vim, press :q!"*. The strings "exit" and "quit" are completely different, yet they mean the same thing. A naive text-matcher misses this entirely; a human never would.
- **Scale.** With 50M documents you cannot compare the query against every one at query time — that's minutes. Users expect results in under 100ms.
- **Relevance / ranking.** Even once you've found "matches," which goes first? The spammy doc that repeats the keyword 50 times, or the canonical answer that mentions it twice?
- **Context / ambiguity.** "Python" in a query about snakes is a different thing from "Python" the language. Same token, different meaning.

> **Keep these four as your lens.** Every technique below is a *solution* to one or more of them. When a system misbehaves, first diagnose *which* problem is failing — then reach for the matching tool.

The three failure modes you'll diagnose against, over and over:

- **Recall** — is the right content retrieved *at all*?
- **Precision / ranking** — is it *ordered* correctly?
- **Speed** — is it *fast enough*?

---

## 2. Classical / Lexical Retrieval — TF-IDF & BM25

### The dumbest baseline: exact / Boolean match
Look for docs containing the exact words (`"python" AND "list" AND "sort"`). It works for trivial cases, but it dies on synonyms, and it has **no concept of which match is more relevant** — every matching doc looks equal. We need *scoring*.

### TF-IDF — teaching machines that words have different importance
The first genuinely smart idea in retrieval (1970s–80s, still inside search engines today). The insight: **not all word occurrences are equally meaningful.**

Picture a corpus of cooking recipes. The word *"the"* appears in every single one — if a query contains "the," that tells you nothing. But *"saffron"* appears in maybe 3% of recipes — if the query and a doc both say "saffron," that's a real signal. TF-IDF turns this intuition into two factors:

- **TF (Term Frequency)** — how often the term appears *in this doc*, normalized by length. A 100-word recipe mentioning "saffron" 5× is more "about" saffron than a 10,000-word one mentioning it 5×.
  `TF = count(term in doc) / total_words(doc)`
- **IDF (Inverse Document Frequency)** — how *rare* the term is across the whole corpus.
  `IDF = log(total_docs / docs_containing_term)`
  - **Worked example:** "the" appears in ~all docs → `log(1,000,000 / 999,999) ≈ 0` → contributes nothing. "saffron" appears in ~5,000 of 1,000,000 docs → `log(1,000,000 / 5,000) = log(200) ≈ 5.3` → high weight; when it matches, it matters a lot.
- **Score = TF × IDF**, summed over the query's terms. Rank by score.

**Wins:** rare matching words dominate; common words auto-vanish; length normalized.
**Loses:** still pure lexical (no synonyms); raw TF is gameable (stuff the keyword 100×); weak on long docs.

### BM25 — TF-IDF grown up (the modern lexical default)
What Elasticsearch / Lucene / Solr actually run. Two refinements fix TF-IDF's rough edges:

- **TF saturation (`k1`, ~1.2–2.0).** Going from 1→5 mentions is meaningful; 95→100 isn't — you're already clearly "about" it. BM25 makes the score approach a ceiling, so keyword-stuffing stops helping.
  `TF_sat = (TF × (k1 + 1)) / (TF + k1)`
- **Tunable length normalization (`b`, 0–1).** `b=0` = ignore length, `b=1` = full normalization, `b=0.75` = typical sweet spot. For **code**, you might lower `b`, because a longer function file mentioning a concept can be *more* relevant (it has more context), unlike a long news article.

**Why it matters for code:** BM25 nails **exact identifiers**. Ask about `authenticate_user` and BM25 finds every chunk that literally contains that string; an embedding model might instead return semantically-similar auth code that lacks the exact name. **Always keep BM25 in a code pipeline.** In several 2022-era benchmarks BM25 *beat* embedding models on exact-match tasks, especially code.

---

## 3. Inverted Indexes — How Lexical Search Runs in Milliseconds

You have 10M docs. How does BM25 not take minutes? The **inverted index** — one of the most elegant data structures in CS.

**Forward index (naive):** `Doc → [words]`. To answer "which docs contain 'sort'?" you scan every doc → O(N). Unacceptable.

```
Doc1 → [python, list, sort, algorithm, quick]
Doc2 → [python, dict, key, value, hash]
Doc3 → [javascript, list, array, sort, method]
```

**Inverted index:** flip it so the *word* is the key:

```
python    → [Doc1, Doc2]
list      → [Doc1, Doc3]
sort      → [Doc1, Doc3]
algorithm → [Doc1]
quick     → [Doc1]
dict      → [Doc2]
...
```

Now "which docs contain 'sort'?" is an **O(1) lookup** → `[Doc1, Doc3]`. For BM25 scoring, each posting also stores the term frequency, and IDF is precomputed at index time (it's a corpus-wide stat):

```
sort → [(Doc1, tf=2), (Doc3, tf=1)]
```

So a BM25 query = look up each query term (O(1) each) → fetch posting lists → score → merge → sort. Only a tiny fraction of docs is ever touched. (Posting lists for common words get huge, so real systems compress them with delta encoding — all under the hood in Lucene/Elasticsearch.)

---

## 4. Query Understanding — Planning, Decomposition, Rewriting

A common gap in people's mental model: retrieval is *not* `query → search → results`. The query gets **processed first**. Users write terrible search inputs — natural language is not a good retrieval input.

Take *"Why does my React component re-render every time even though I'm using useCallback?"* Sent raw to BM25, it scores every word, including the filler. But a human instantly zeroes in on **React + useCallback + re-render**. The understanding layer's job is to do the same.

### Pre-processing (classic, cheap, no LLM)
- **Stop-word removal** — strip "the/a/is/and". (Code has its own stop words — "function", "return" if they're everywhere.)
- **Stemming** (crude: "running"→"run"; sometimes wrong, "university"/"universe"→"univers") vs **Lemmatization** (linguistic, accurate, slower: "better"→"good").
- **Query expansion** — add synonyms: "exit vim" → `(exit OR quit) AND vim`, so you find docs that say "quit" without the user knowing to.

### LLM-powered query understanding
- **HyDE (Hypothetical Document Embeddings).** Instead of embedding the *question*, ask an LLM to *write a hypothetical answer*, then embed and search with **that**. Why it works (the geometric picture): a question — "What causes memory leaks in Python?" — and its answer — "Memory leaks in Python occur when objects are retained because…" — live in *different regions* of embedding space. An answer sits near *other answers*, not near questions. Generating a fake answer **moves your search probe from the question-region into the answer-region**, so your nearest neighbors become real relevant content instead of other questions.
- **Query decomposition** — split a complex query into independent sub-questions, retrieve each, merge.
- **Query rewriting** — "it keeps throwing null pointer" → "NullPointerException Java null reference debugging".

### Decomposition — the part people get wrong

> **You do NOT decompose by sentences or punctuation. You decompose by distinct *information needs*.**

A *sentence* is grammatical; an *information need* is "one thing to go look up." One sentence can hide three needs ("compare Django and FastAPI async handling and which scales better" = three lookups); three sentences can be one need ("My app is slow. It uses Postgres. Why might queries hang?" = one lookup). The unit of retrieval is the **information need**.

| Scenario | Right approach |
|---|---|
| **5 separate questions pasted** | 5 independent needs → 5 separate retrievals, each scoped to its own question. Do **not** blend into one search (you'd get mush relevant to all, excellent for none). |
| **"Write code that does X" (a task)** | Often needs *few or zero* retrievals. Retrieve only the parts grounded in *your* corpus. "Write a quicksort" → **no retrieval** (general knowledge). "Write a handler that uses our `AuthService` and our error pattern" → retrieve those **two** things. |
| **Multi-step task (step1/step2/step3 + tests)** | Retrieve per step **only if that step needs info you don't already have**. Step calls an external function → retrieve. Step is pure logic on already-retrieved context → don't. Tests against existing code → retrieve the code-under-test + test conventions (its own need). |

**Principle:** *Retrieve per information need, and only when the need can't be met from what you already have.* Over-decomposition floods context and dilutes signal; under-decomposition misses sub-topics.

### Who does the decomposition? (a spectrum)
- **Rules / classifiers** — cheap, deterministic, brittle. Good for routing simple-vs-complex.
- **LLM as planner** — handles arbitrary complexity (sees hidden needs), returns structured sub-queries (JSON); costs latency, money, determinism.
- **Pragmatic pattern:** a *cheap router* in front of the *expensive planner* — only complex queries pay for LLM planning.
- **Agentic / dynamic retrieval** (ideal for code): give the model a `search_codebase` tool and let it retrieve *as it reasons* — it searches only when it hits a knowledge gap. Interleaves planning + retrieval instead of front-loading; matches retrieval to need naturally; costs more round-trips.

---

## 5. The Embedding Revolution — Semantic Search

**Core breakthrough:** map text into a space where *meaning* determines proximity, not words. An embedding model turns text into a vector (384/768/1536 dims) such that **semantically similar text → nearby vectors**.

```
embed("How to exit vim")         → [ 0.23, -0.71,  0.44,  0.18, ...]
embed("Quitting the vim editor") → [ 0.21, -0.69,  0.47,  0.15, ...]   (very close → similar meaning)
embed("Python list sorting")     → [-0.45,  0.33, -0.12,  0.88, ...]   (far → unrelated)
```

- **Training:** contrastive learning (e.g., Sentence-BERT). Take pairs you *know* are related; train so related pairs land close and unrelated pairs land far — over millions of pairs the model develops a rich sense of meaning. (Push "exit vim" ↔ "quit vim editor" together; push both far from "bake a cake.")
- **Similarity:** **cosine similarity** — about the *direction* of the vector, not its magnitude, which handles variable-length text well.
  `cos(a,b) = (a·b) / (||a||·||b||)` — ranges −1 (opposite) to 1 (identical); most text pairs land 0–1.

**Solves:** vocabulary mismatch. **Loses:** exact-token matching (the `authenticate_user` problem) → needs **hybrid** + **ANN at scale**.

---

## 6. Bi-encoders vs Cross-encoders — The Critical Distinction

This governs the fundamental architecture of every serious retrieval system, so internalize it deeply.

### Bi-encoder (the retriever)
Query and doc are encoded **independently**:
```
q_vec = encode(query)
d_vec = encode(doc)          # ← because it's independent, this is PRE-COMPUTED offline
score = cosine(q_vec, d_vec)
```
The doc has no idea what query it'll face → you embed every doc once at index time → at query time you only encode the query. This is what makes semantic search fast. **Trade-off:** independent encoding can't use query info to shape the doc representation → limited accuracy.

### Cross-encoder (the reranker)
Query and doc go in **together** as one input, full attention across both:
```
score = cross_encode("[query] why does useCallback not stop re-renders [doc] useCallback returns a memoized callback; the component re-renders when ...")
# → one relevance number
```
It can notice "*this exact part* of the doc addresses *this exact part* of the query." Much more accurate. **Trade-off:** nothing precomputes — every (query, doc) pair is a fresh forward pass. At 10ms/pair × 10M docs that's ~28 hours per query. **Infeasible over a whole corpus.**

### The resolution: two-stage retrieval
```
Stage 1 (bi-encoder and/or BM25): retrieve top-100 candidates   → FAST, broad
Stage 2 (cross-encoder):          re-rank those 100             → ACCURATE, narrow
```
Speed *and* accuracy. This two-stage shape is the backbone of basically every production system.

---

## 7. Exact vs Approximate Search — IndexFlat, IVF, HNSW, PQ

> **You do NOT always need ANN.** ANN trades a little accuracy for speed — pay for it *only when you must*. On a small corpus you get none of the benefit (exact is already fast) and all the cost (recall loss, memory, build time, tuning).

### Exact / brute force — `IndexFlatIP` & `IndexFlatL2` (Faiss)
"Flat" = no index structure; it compares the query to **every** vector → **guaranteed-correct** top-k. The only difference between the two is the metric:
- `IndexFlatL2` — Euclidean distance (smaller = more similar).
- `IndexFlatIP` — inner product / dot product (larger = more similar).

**The cosine trick (memorize this idiom):** Faiss has no explicit cosine index, but **cosine = inner product on unit-normalized vectors.** So the standard recipe is: **normalize your vectors → use `IndexFlatIP`** → your inner product *is* cosine. Use raw L2/IP without normalizing only if the model card says the model was trained for it.

**When exact is the right call — and the key insight you asked about:** brute force is ~`N × D` ops/query. For 100k vectors × 768 dims that's ~77M ops → a few ms on CPU, sub-ms on GPU. **Exact search on 100k vectors is essentially free.** So for a **10k–100k corpus, use `IndexFlatIP` + normalized vectors and stop** — adding a graph index buys nothing and makes the system slightly worse. You only feel pain somewhere in the low millions.

> **Brute force *inside* ANN for accuracy:** the two aren't either/or. A very common production pattern is **ANN to narrow, then exact re-scoring to refine** — let HNSW/IVF (or PQ-compressed vectors) cheaply fetch a candidate set, then run *exact* full-precision similarity on just those candidates to fix the ranking. You get ANN's speed on the 10M and exact's accuracy on the final 100. For genuinely small sets, skip the ANN stage entirely and go straight to exact.

### The Faiss ladder (place everything)
| Index | What it is | Use when |
|---|---|---|
| `IndexFlatIP` / `IndexFlatL2` | Exact brute force, perfect recall | **< ~1M vectors** |
| `IndexIVFFlat` | k-means clustering buckets; `nprobe` = buckets searched | Brute force too slow, vectors fit in RAM |
| `IndexHNSWFlat` | Navigable small-world graph | Need fast + high recall in-memory; have the RAM |
| `IndexIVFPQ` | Clustering + product quantization (compressed) | Tens–hundreds of millions+; RAM-constrained |
| `IndexIVFScalarQuantizer` | float32→int8 (4× smaller, small accuracy hit) | Middle ground |

**Rule of thumb:** `< 1M → Flat` · `1M–10M & fits RAM → HNSW/IVFFlat` · `tens of millions+ or RAM-tight → IVFPQ`.

### How the ANN families work
- **IVF (clustering).** Run k-means → ~1000 cluster centroids; assign each vector to its nearest centroid. **Query:** compare to the 1000 centroids (cheap), then search only the nearest few clusters. `nprobe` = how many clusters to search (↑ = higher recall, slower). *Boundary error:* if your query sits between clusters, the true neighbor may be in one you didn't open.
- **HNSW (graph) — the subway analogy, narrated.** Build a multi-layer graph like a subway with express and local lines. **Bottom layer (Layer 0):** every vector is a node linked to its ~16–32 nearest neighbors — the "local stops," dense but slow over distance. **Higher layers:** progressively fewer nodes with longer-range links — the "express line," few stops but covers ground fast. **Query:** enter at the top express layer, greedily hop to whichever neighbor is closest to your query vector; when you can't get closer at this layer, **drop down a level** and continue; repeat until Layer 0 fine-tunes onto the true neighbors. Big jumps to the right *region* up top, precise homing down low → you reach the neighborhood in ~**O(log N)** hops instead of O(N). Params: `M` (links/node), `ef_construction` (build quality), `ef_search` (runtime recall↔speed dial). Fast, high recall, **memory-hungry**.
- **PQ (quantization).** Split a 768-d vector into, say, 96 sub-vectors of 8 dims; train a 256-entry codebook per group; store each sub-vector as the 1-byte index of its nearest code. **3072 B → 96 B = 32× compression** (with some accuracy loss). **Scalar quantization** = float32→int8 (4×, minimal loss). Often combined: HNSW graph + PQ-compressed vectors → navigate on compressed, then exact-re-score the top candidates on full vectors (the brute-force-refine pattern again).

---

## 8. Hybrid Retrieval & Fusion + The Full Pipeline

Lexical and semantic have **complementary blind spots**: BM25 nails exact terms but misses synonyms; embeddings catch meaning but miss exact tokens. So run both and merge.

### Reciprocal Rank Fusion (RRF) — the robust default
```
RRF_score(doc) = Σ over lists  1 / (k + rank_in_list)      # k ≈ 60
```
A doc ranked #1 in *both* lists scores high; #1 in only one scores lower; absent from a list contributes 0. **Robust because it uses ranks, not raw scores** — so it doesn't matter that BM25 scores and cosine scores live on totally different scales.

### Weighted linear combination — when you want a tunable dial
Normalize each system's scores to [0,1], then `final = α·BM25 + (1−α)·semantic`. For code (lots of exact identifiers) you might set `α = 0.6` to favor lexical.

### The full pipeline (the maximal menu — you rarely build all of it)

```
                          User Query
                              │
                  ┌───────────▼────────────┐
                  │ Query Understanding     │  rewrite · decompose · expand · HyDE
                  └───────────┬────────────┘   (LLM only when the query is messy)
                              │
              ┌───────────────┴────────────────┐
              ▼                                 ▼
   ┌──────────────────┐              ┌────────────────────────┐
   │ BM25 / Lexical    │              │ Semantic Retrieval      │
   │ (inverted index)  │              │ exact Flat for small    │
   │   top-100         │              │ sets, else ANN (HNSW/   │
   └─────────┬─────────┘              │ IVF/PQ) → top-100       │
             │                        └───────────┬─────────────┘
             └──────────────┬─────────────────────┘
                            ▼
                ┌───────────────────────────┐
                │ Fusion & Dedup (RRF)       │  merge ~200 candidates (some overlap)
                └─────────────┬──────────────┘
                              ▼
                ┌───────────────────────────┐
                │ Re-ranking (cross-encoder) │  score all ~200 jointly
                └─────────────┬──────────────┘   (optionally: exact full-precision
                              ▼                    re-score for final accuracy)
                       Top-K Results
                              │
                              ▼
                     LLM / Final Response
```

> **The pipeline is a menu, not a meal.** Start with the simplest thing that could work; add a stage only when your eval shows it helps. A clean 10k–100k code corpus may need only: embed → `IndexFlatIP` → BM25 → RRF. Reranking and an LLM planner are additions you *earn*, not defaults.

---

## 9. A Worked End-to-End Trace (the JWT query)

Let's run one real query through the whole pipeline so the abstract stages become concrete.

**Query:** *"Why is my JWT token validation failing with expired signature error?"*

**Stage 1 — Query Understanding.**
- Detect type: this is a *debugging* question → relevant chunks are validation logic, expiry checks, error handling (not "how to implement JWT from scratch").
- Extract entities: **JWT, token validation, expired, signature** → high-weight these.
- Rewrite for retrieval: *"JWT token signature expired validation error authentication middleware."*
- (Optionally decompose: "JWT signature validation code" / "token expiry checking" / "expired signature error handling.")

**Stage 2 — Multi-strategy retrieval (top-100 each).**
- *BM25 leg:* fires against the inverted index → instantly finds chunks literally containing `JWT`, `expired`, `signature`, `ValidationError`, `token`. Aces exact identifiers.
- *Semantic leg:* the rewritten query is embedded → vector search finds chunks *about* token-lifecycle/auth even if worded differently. A chunk that says "verify bearer token claims" has none of the query's exact words, so BM25 misses it — but the embedding knows it's relevant.

**Stage 3 — Fusion (RRF).** Two ranked lists → ~150–200 unique candidates. A chunk ranked highly by *both* legs floats to the top; chunks found by only one leg still survive. Scales don't need to match because RRF uses ranks.

**Stage 4 — Re-ranking (cross-encoder).** Each (query, candidate) pair is read *jointly*, so the model can tell:
- "this chunk contains the exact function from the query" → boost,
- "this discusses *session* expiry, not *token signature* expiry" → demote,
- "this is a test file, not the implementation" → demote.
Re-rank, take top 5–10.

**Stage 5 — Generation.** The tight, correctly-ordered top-K goes into the LLM's context to produce the final grounded answer.

Notice every earlier concept showing up in its natural slot: query understanding reshapes the input, BM25 covers exact terms, embeddings cover meaning, RRF merges, the cross-encoder fixes ordering, and only the final handful reaches the LLM.

---

## 10. Re-ranking with Cross-encoders — How to Actually Use Them

A cross-encoder is a **scoring function, not a search engine**: (query, doc) → one number. It runs in **stage two only**, over the candidate set, never the whole corpus.

```python
candidates = retriever.search(query, top_k=100)     # cheap stage (bi-encoder / BM25 / hybrid)
pairs      = [(query, c.text) for c in candidates]
scores     = cross_encoder.predict(pairs)           # BATCH on GPU
reranked   = sorted(zip(candidates, scores), key=lambda x: x[1], reverse=True)
final      = reranked[:5]                            # hand to the LLM
```

**Practical knobs:**
- **Candidate count is your main cost dial.** Reranking 100 ≈ 100× one inference. At 15ms/pair done serially that's 1.5s — too slow. Fix it by (a) **batching** (a GPU reranks 100 nearly as fast as 1) and/or (b) **shrinking the pool** (rerank 30, not 200).
- **Scores aren't calibrated probabilities.** 0.8 ≠ "80% relevant." Meaningful only *relative to each other within one query*. Use for ordering + an empirically-tuned cutoff.
- **When to skip it:** if the bi-encoder already orders well on your eval, the reranker is pure latency. Add it only when the right docs are **present but mis-ordered** — that's exactly the symptom it cures. If the right doc isn't even in the candidate set, that's a **recall** problem → fix retrieval upstream; reranking can't conjure missing docs.

Common reranker families: `ms-marco-MiniLM`, `bge-reranker`.

---

## 11. Beyond Simple Embeddings — SPLADE & ColBERT

### The bi-encoder ceiling
One vector per doc must compress *all* its meaning into a single point — a "center of gravity." A doc covering auth + DB + logging gets a fuzzy average vector close to nothing specific.

### ColBERT — late interaction
Encode **each token** to its own vector (a 128-token doc → 128 vectors). Score via **MaxSim** — for each query token, take its max similarity to any doc token, then sum:
```
score(Q,D) = Σ_q  max_d  cosine(q_vec, d_vec)
```
Each query aspect independently finds its best match: "expired" ↔ "expiry", "JWT" ↔ "JSON Web Token". **Trade-off:** N vectors per doc → storage explodes (a 200-token chunk at 128-d ≈ 100KB; 10M docs ≈ 1TB). PLAID/centroid compression makes it practical.

### SPLADE — learned sparse representations
Keeps BM25's sparse/inverted-index style but **learns** the vocabulary weights and **expands** terms semantically: a doc about expiration activates `expired/expiry/timeout/stale` dimensions even if those exact words aren't present. The output is still a sparse vector that fits an inverted index → **~BM25 latency with ~embedding-level semantics.** A genuinely strong middle ground.

---

## 12. Chunking — The Foundation That Sets Your Ceiling

> If the right answer is split across a chunk boundary, **no retriever can recover it.** Chunking sets the ceiling for everything downstream.

### The four forces pushing on every chunking decision
1. **Embedding blur (the deepest one).** A chunk's embedding is the *center of gravity* of all meaning in it. A chunk about one tight thing — "a function that parses a date" — lands precisely on "date parsing," and a date query lands right next to it. A chunk mixing date parsing + network retries + logging gets dragged to the *average* of all three → lands in fuzzy no-man's-land, close to *no* specific query. **More distinct ideas crammed in = blurrier embedding.** (This single intuition explains ~80% of good chunking.)
2. **Precision / granularity.** Retrieval returns *whole chunks*. A 2000-line chunk where only 10 lines matter buries the needle. **Chunk size = search resolution.**
3. **Context budget.** Retrieved text fills the LLM context — costs money *and* suffers "lost in the middle" degradation. You can't just return giant chunks "to be safe."
4. **Model token limit.** Embedding models silently truncate past their max input (often 512, sometimes 8k) — the tail of a long chunk may never be embedded at all.

**Counter-force — context preservation.** Cut too small and chunks lose meaning: *"It returns null if the user isn't found"* (what is "it"?), or `return self._cache[key]` (what is `self`? what's `_cache`? what's this function even called?). A razor-sharp embedding about *nothing identifiable* is useless.

> **Good chunking = finding the smallest unit that is still self-contained.** Small enough for sharp embeddings + precise retrieval; large enough to still mean something on its own.

### The five properties of a good chunk
1. **Self-containment** — understandable without neighbors (no dangling "this"/"above"/undefined `self`).
2. **Single-topicness** — about one thing → sharp embedding. Two unrelated ideas → split into two sharp embeddings.
3. **Right-sized for the query** — granularity matches *what people ask*. **The query distribution dictates chunk size, not the reverse.** (Most overlooked principle.)
4. **Low noise** — strip boilerplate, license headers, repeated imports, nav cruft (they drag the center of gravity + waste context).
5. **Indexable form vs retrievable form** — may *deliberately* differ (the centerpiece, below).

### The strategy ladder (crude → sophisticated)
| Strategy | What it does | Use / break |
|---|---|---|
| **Fixed-size (token/char)** | Cut every N tokens | Dumb, fast, ignores meaning; slices sentences/functions. Baseline only. |
| **Fixed-size + overlap** | Sliding window, ~10–20% shared | Cheap patch for the boundary problem. Near-universal default. |
| **Sentence / paragraph** | Split on language units | Sentences too small, paragraphs uneven. Building block. |
| **Recursive structural** | Split on the biggest natural boundary, fall to smaller (paragraph→line→sentence→word) | Sensible general default. Follows *syntax*, not *meaning*. |
| **Structure / layout-aware** | Use the doc's own structure (MD headers, HTML, code AST) | Best when structure is reliable — the author already marked the seams. Great for docs & code. |
| **Semantic chunking** | Embed sentences; cut where embedding distance spikes (topic shift) | Directly optimizes single-topicness. Costs embedding calls just to *decide* boundaries. |
| **LLM / agentic chunking** | LLM segments / rewrites chunks to be self-contained | Highest quality + cost. For high-value static corpora chunked once, retrieved millions of times. |
| **Late chunking** | Embed the *whole doc* with a long-context model first, then pool token embeddings per chunk | Each chunk's embedding is contextualized by the full doc → fixes "it returns null" without bloating chunks. Needs long-context model. |
| **Hierarchical / parent-child** | Small children (sharp embedding) nested in large parents (context); search children, **return** parents | "Small-to-big." Precision at retrieval + context at generation. Reliably useful. |

### ⭐ The centerpiece: decouple what you INDEX from what you RETURN
Most people unconsciously assume the chunk is one object — same text embedded, searched, *and* returned. **It isn't. These are three separate jobs:**
- **Indexed representation** exists to be *findable* — a sharp embedding / good BM25 terms landing near the queries people actually ask.
- **Returned representation** exists to be *useful* — exactly what the downstream consumer needs.

These goals differ, so optimizing one object for both is a compromise. **Splitting them is the unlock** (*multi-representation indexing*):
- **Index a summary, return the source.** Generate (once, at index time) a clean one-liner per function — *"Parses an ISO-8601 date string into a UTC datetime; raises ValueError on malformed input."* Embed *that* (clean, single-topic, question-shaped) → queries land right on it. Store/return the actual code. The summary is the lure; the code is the catch.
- **Index questions, return the chunk.** Generate the questions a chunk answers ("How do I parse a date?" / "What exception does date parsing throw?"), embed *those* → kills the query↔chunk shape mismatch (you match questions to questions).
- **Index signature + docstring, return the implementation.** ← *your function-name-vs-snippet question, answered:* it was a false choice. For **indexing**, embed the clean **signature + docstring** — the implementation body is low-signal noise (loop vars, error strings, boilerplate) that drags the embedding toward generic "code-ness" and away from purpose. For **returning**, give downstream exactly what it consumes — just the docstring if that's all it needs, or the full implementation if it must call/modify the function. Those two decisions are **independent.**

### Code-specific chunking (your battlefield)
- **Never fixed-size chunk code** — it slices mid-function, orphans braces, separates a function from its docstring. The cardinal sin of code RAG.
- **Chunk on syntactic boundaries with a parser** (e.g., **tree-sitter**): one chunk per function/method/class → every chunk is complete and valid and self-contained. The baseline-correct approach.
- **Granularity by query distribution.** Function-level is the usual sweet spot. For methods, **inject context**: prepend file path, imports, class signature, docstring, then the body → self-contained again. ("Here is method X, in class Y (fields A, B), in file Z.")
- **Signal vs noise.** Strip license/copyright/import boilerplate from the *indexed* form (keep it in stored source if downstream needs it). Comments & docstrings are **high signal** — the natural-language anchor that bridges to NL queries.
- **Lean on hybrid.** Index two representations of the *same* chunk: BM25 over raw tokens (so `authenticate_user` is literally findable) + an embedding over signature+docstring (so "log a user in" finds it). Fuse at query time.

---

## 13. What Makes a Good Embedding

Chunking decides *what* you embed; this makes the embedding itself good:
- **Clean, single-topic, right-length input.** Garbage in → blurry vector out. The embedding is only as sharp as the text is focused.
- **Respect query/passage asymmetry.** Many models expect different handling for queries vs docs (e.g. `"query: ..."` / `"passage: ..."` prefixes, or separate encoders). Treating both sides identically when the model expects prefixes silently loses accuracy — *read the model card.* (A frequent quiet bug.)
- **Match model to domain.** Code-trained models (CodeBERT, UniXcoder, newer code embedders) understand that `auth()` ≈ `verify_credentials()`; general-text models treat code as weird English.
- **Normalize + cosine** (the `IndexFlatIP` idiom) unless the model says otherwise.
- **Mind the query↔chunk shape gap.** A short question and a long code blob sit in the same space but look very different → similarity suffers. *This is the whole motivation* for the decouple-and-summarize tricks (Section 12): reshape the indexed thing to look like the query, and the gap closes.

---

## 14. The Design Framework + When to Use an LLM

### The framework — run it backwards from how people usually build
1. **Start at the query, not the corpus.** Write 20 real example queries. What granularity? "Find this function" (fine → small chunks) vs "explain this subsystem" (coarse → coarse representation too). **Chunk size is downstream of query distribution, always.** Both kinds → you need both granularities (hierarchical / multi-representation).
2. **Look at the downstream consumer.** What does whatever-receives-the-results actually need — a snippet? code to run? enough context to reason? This sets the **returned** representation, *independently* of the indexed one.
3. **Design the indexed representation to bridge query → content.** Make the embedded thing look like the query (summaries, synthetic questions, docstrings) and be single-topic (good boundaries). Add BM25 over raw tokens wherever exact terms matter (always, for code).
4. **Diagnose what machinery you actually need** (the three questions):
   - *Right content retrieved at all?* → **recall** problem → fix chunking / add hybrid / reshape indexed form. **No LLM.**
   - *Retrieved but mis-ordered?* → **precision** problem → add a cross-encoder reranker. **No LLM.**
   - *Query itself a bad search input?* (multi-part, vague, conversational) → *now* an LLM earns its place as planner/decomposer or dynamic agent — gated so only complex queries pay for it.

### When to use an LLM (and when you don't need one)
The LLM is needed **far less often** than people reach for it. Chunking, indexing, hybrid search, and reranking are all **non-LLM** machinery and solve the bulk of quality.
- **Index time (optional, one-time):** LLM generates summaries / synthetic questions / self-contained rewrites. Amortizes to ~nothing across millions of retrievals.
- **Query time (optional, messy queries only):** LLM plans / decomposes / rewrites — ideally behind a cheap router.
- **The hot path — the core retrieve→rerank loop on every query — usually should NOT contain an LLM** (too slow, too expensive). Cheap machinery already sees meaning and structure there.

> Reach for the LLM where cheap machinery *can't* see meaning or structure; keep it off the hot path where cheap machinery already works.

---

## 15. Evaluation — What Makes Every Decision Settle Itself

The most-skipped, most-regretted step. **Build the eval set first.**

- **20 real queries + their known-relevant chunks** (a labeled set).
- **Recall@k** — is the right chunk anywhere in top-k? → diagnoses **retrieval / chunking / indexing**.
- **MRR / nDCG** — is it *ordered* well? → diagnoses **reranking**.

With this, every "should I add stage X?" stops being a debate and becomes a measurement. You never doubt anything — not because you memorized answers, but because you can **test** which answer is right for *your* problem. That is the real end state of mastery: certainty from measurement, not from authority.

---

## 16. Quick-Reference Cheat Sheets

### "What does each technique solve?"
| Technique | Solves | Fails at | Notes |
|---|---|---|---|
| **BM25 / lexical** | Exact terms, identifiers, rare keywords | Synonyms, paraphrase | Fast via inverted index. Essential for code. |
| **Embeddings + vector search** | Vocabulary mismatch / meaning | Exact tokens | Needs ANN at scale. |
| **ANN (HNSW/IVF/PQ)** | Speed of vector search | (doesn't improve relevance) | Useless on small corpora. |
| **Hybrid + RRF** | Each method's blind spots | — | Combine lexical + semantic. |
| **Cross-encoder rerank** | Precision / ordering | Recall (can't add missing docs) | Stage two only. |
| **Query understanding** | Bad query as search input | — | Pre-retrieval; LLM only when needed. |
| **Chunking** | Sets the ceiling for all the above | — | Smallest self-contained unit. |

### Decision dials
- **Corpus size:** `<1M → IndexFlatIP (exact)` · `1M–10M & RAM → HNSW/IVFFlat` · `tens of M+ → IVFPQ`.
- **Cosine in Faiss:** normalize vectors → `IndexFlatIP`.
- **Accuracy on a candidate set:** ANN to narrow → **exact full-precision re-score** to refine (or just exact if the set is small).
- **Add hybrid?** Yes whenever exact identifiers matter (always for code).
- **Add a reranker?** Only when eval shows *present-but-mis-ordered* results.
- **Add an LLM?** Only off the hot path: index-time enrichment, or query-time planning for genuinely complex queries.
- **Chunk size?** Derived from the query distribution + downstream needs — never picked first.

### A solid v1 for a 10k–100k code RAG
```
chunk by function (tree-sitter; inject class/imports/path context)
  → embed signature+docstring with a CODE model (normalized)
  → IndexFlatIP (exact — no ANN needed at this scale)
  + BM25 over raw tokens
  → fuse with RRF
  → cross-encoder rerank ONLY IF eval shows mis-ordering
  → let the LLM drive retrieval via a search tool (don't rigidly pre-split queries)
build the eval set FIRST; add each stage only when it measurably helps.
```

### The three questions when retrieval misbehaves
1. Right content retrieved at all? → **recall** → chunking / hybrid / indexed representation.
2. Ordered correctly? → **precision** → reranker.
3. Query a bad input? → **query understanding** → rewrite / decompose / LLM planner.

---

*The pipeline is a menu, not a meal. Start with the simplest thing that could work, measure, and add stages only when the eval improves. Always know which of {recall, precision, speed} you're fixing, reach for the matching tool, and keep the LLM where cheap machinery can't see — that is informed retrieval design.*
