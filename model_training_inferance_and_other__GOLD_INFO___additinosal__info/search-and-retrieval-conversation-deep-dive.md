# The Deep World of Search & Retrieval — From First Principles to Production Pipelines

Let me take you on this journey properly. No skipping, no "you probably know this." We're going to build the mental model from the ground up so that when you're designing a retrieval system, every decision feels like *of course* rather than *I think this might work*.

---

## Part 1: The Core Problem — Why is Retrieval Even Hard?

Before any technique, ask: **what are we actually trying to do?**

You have a corpus. Maybe 10 documents. Maybe 100 million code chunks. A user asks a question. You need to find the *most relevant* chunks — fast, accurately, at scale.

Sounds simple. Here's why it isn't.

**Problem 1: The vocabulary mismatch problem.**
The user says *"how do I exit a vim editor"*. Your document says *"to quit vim, press :q!"*. The words "exit" and "quit" are completely different strings. A naive text-matching system would miss this entirely. Humans understand they mean the same thing. Computers historically didn't.

**Problem 2: The scale problem.**
If you have 50 million documents, you cannot compare the query against every single one at query time. That would take minutes. Users expect results in under 100ms.

**Problem 3: The relevance problem.**
Even when you find "matching" documents, which one do you put first? The one that mentions the query word 50 times in a spammy way? Or the authoritative one that mentions it twice but is clearly the canonical answer?

**Problem 4: The context problem.**
"Python" in a query about snakes is fundamentally different from "Python" in a programming context. The same word, entirely different meaning. How does a retrieval system know which you mean?

Every technique we're about to cover is essentially a *solution* to one or more of these problems. Keep these problems in your head — they'll be the lens through which everything makes sense.

---

## Part 2: The Classical Era — Lexical Retrieval

### First, the dumbest possible approach: Exact Match / Keyword Search

You have documents. A query comes in. You look for documents that contain the exact words. Boolean search — AND, OR, NOT.

`"python" AND "list" AND "sort"` → give me documents with all three words.

This actually works okay for simple cases. But it breaks immediately on synonyms, and it treats all matching documents as equal — it has no concept of *which document is more relevant*.

We need a way to **score** documents.

---

### TF-IDF — Teaching Machines to Understand Word Importance

This is the first genuinely smart idea in retrieval. Invented in the 1970s-80s. Still runs inside search engines today.

The insight is beautiful and simple: **not all word occurrences are equally meaningful.**

Think about a corpus of cooking recipes. The word "the" appears in every single recipe. If a query contains "the", finding documents with "the" tells you absolutely nothing. But the word "saffron" — that appears in maybe 3% of recipes. If a query mentions "saffron" and a document also mentions "saffron", that's a *meaningful signal*.

TF-IDF formalizes this intuition into two components:

**TF — Term Frequency**
How often does the query word appear in *this specific document*?

If the document mentions "saffron" 5 times versus a document that mentions it once, the first document is probably more about saffron. So: more occurrences in a document → higher score.

Formula: `TF(term, doc) = count of term in doc / total words in doc`

The division by total words normalizes for document length — a 10,000-word document mentioning "saffron" 5 times is less "about saffron" than a 100-word document mentioning it 5 times.

**IDF — Inverse Document Frequency**
How rare is this word across the *entire corpus*?

`IDF(term) = log(total documents / documents containing this term)`

The word "the" appears in basically every document. `log(1,000,000 / 999,999)` ≈ nearly 0. Its IDF weight is almost zero — it contributes almost nothing to the score. That's correct behavior.

The word "saffron" appears in maybe 5,000 documents out of 1,000,000. `log(1,000,000 / 5,000)` = `log(200)` ≈ 5.3. High IDF weight. When it matches, it matters a lot.

**TF-IDF score = TF × IDF**

For each word in the query, compute this score for each document, sum them up. That's the document's relevance score. Rank by score. Return top results.

**What TF-IDF gets right:**
- Rare words in the query that appear in a document are very meaningful matches
- Common words are automatically downweighted
- Document length normalization is built in

**What TF-IDF gets wrong:**
- Still pure lexical — "exit" and "quit" are completely unrelated to it
- The raw TF part can be gamed (stuff your document with the keyword 100 times)
- Doesn't handle the "long document problem" particularly well

---

### BM25 — TF-IDF, Grown Up

BM25 (Best Match 25 — it was the 25th iteration of a series of experiments) is what modern search engines actually use. Elasticsearch, Lucene, Solr — BM25 is the default. It came out of the Okapi project at City University London in the 1990s.

BM25 takes TF-IDF's core intuition and fixes its rough edges with two key refinements.

**Refinement 1: TF Saturation**

In raw TF-IDF, if a document mentions "saffron" 100 times, it scores 100× higher than a document that mentions it once. That's not really how relevance works. Going from 1 mention to 5 mentions is meaningful. Going from 95 to 100 mentions barely changes anything — you're already clearly a saffron document.

BM25 introduces a parameter called **k1** (typically between 1.2 and 2.0) that controls TF saturation:

```
TF_saturated = (TF × (k1 + 1)) / (TF + k1)
```

As TF grows very large, this formula approaches `k1 + 1` — it hits a ceiling. The score stops growing after a point. Spamming the keyword no longer helps infinitely.

**Refinement 2: Length Normalization (the b parameter)**

TF-IDF divides by document length, but BM25 gives you a tunable knob called **b** (0 to 1):
- b = 0: No length normalization at all
- b = 1: Full normalization (a 1000-word document mentioning "saffron" twice is treated the same as a 100-word document mentioning it twice)
- b = 0.75: The typical sweet spot

Why does this matter? In code retrieval (your RAG use case), a long function file mentioning a concept twice might actually be *more* relevant than a short comment file mentioning it twice — it has more context. So you might tune b lower than for, say, news articles.

**What BM25 gives you in practice:**

It's shockingly good. In a 2022 benchmark, BM25 outperformed many embedding-based approaches on exact-match retrieval tasks — especially for code, where exact identifiers like function names, variable names, error codes matter enormously.

For your RAG application: if someone asks *"how do I use the `authenticate_user` function"*, BM25 will nail it because it'll find every chunk that literally says `authenticate_user`. An embedding model might find semantically similar authentication code that doesn't even have that function.

---

## Part 3: Understanding Queries — Query Planning and Optimization

Here's where a lot of people's mental model of retrieval is incomplete. They think of retrieval as: *query comes in → search → results*. But in a sophisticated retrieval system, the query goes through significant *processing* before it ever hits the search index.

### The Raw Query Problem

Users are terrible at writing search queries. (This isn't an insult — it's just that natural language and retrieval system inputs are different things.)

A user might ask: *"Why does my React component re-render every time even though I'm using useCallback?"*

If you send this raw query to BM25, what does BM25 do? It scores every word. "Why", "does", "my", "React", "component", "re-render", "every", "time", "even", "though", "I'm", "using", "useCallback" — all get TF-IDF scores. The stop words ("why", "does", "my", "even", "though", "I'm") are usually stripped. But "every", "time" are still there, diluting the signal.

The really important signal is: **React + useCallback + re-render problem**. A human reading that query immediately focuses on those three things. The retrieval system needs to do the same.

### Query Pre-processing: The Foundation

**Stop word removal:** Words that carry no semantic content. "the", "a", "is", "are", "was", "were", "and", "but" — classic BM25 systems strip these before indexing and at query time. For code retrieval, your stop word list is different — "function", "return", "var" might be stop words if they appear everywhere.

**Stemming and Lemmatization:**
- Stemming is crude: "running" → "run", "runs" → "run", "runner" → "run". Porter Stemmer is the classic algorithm. It's fast and wrong a lot of the time ("university" and "universe" both stem to "univers") but on net helps.
- Lemmatization is smarter: uses actual linguistic rules. "better" → "good", "was" → "be". Slower, more accurate.

For code retrieval: be careful. `authenticate` and `authentication` should probably match. But `get` and `got` in code contexts are different things.

**Query Expansion:**
The user said "exit vim". Your system knows (through synonym dictionaries, WordNet, or an LLM) that "exit" and "quit" are synonymous in this context. Expand the query: search for `(exit OR quit) AND vim`. Suddenly you find the documents that use "quit" without the user needing to know that.

---

### Query Understanding — The LLM-Powered Layer

This is where modern systems get really interesting. Before you even think about retrieval, an LLM (or a smaller model) can transform the user's query in powerful ways.

**Hypothetical Document Embedding (HyDE):**
This is a fascinating technique. Instead of embedding the *question* and searching for documents that are similar to a question, you ask an LLM: *"Write a paragraph that would answer this question."* Then you embed that *hypothetical answer* and search for documents similar to it.

Why does this work? Think about it geometrically. A question ("What causes memory leaks in Python?") and its answer ("Memory leaks in Python occur when objects are retained in memory because...") live in different parts of the embedding space. An answer is much closer in embedding space to *other answers* than a question is. By generating a hypothetical answer, you move from the "question region" to the "answer region" of the vector space, and your nearest neighbors are actual relevant content rather than other questions.

**Query Decomposition:**
Complex queries often contain multiple sub-questions. *"Compare how Django and FastAPI handle async requests and which one scales better"* is actually two questions:
1. How does Django handle async?
2. How does FastAPI handle async?
3. What are the scaling characteristics of each?

A query decomposition step breaks this into sub-queries, retrieves for each, then merges results. You get much better coverage than trying to retrieve for the whole complex query at once.

**Query Rewriting:**
The user asks: *"it keeps throwing null pointer"*. A rewriting model expands this into: *"NullPointerException Java null reference error debugging"* — adding context, adding technical terms, making it searchable.

---

## Part 4: Inverted Indexes — How BM25 Actually Runs in Milliseconds

You have 10 million documents. How does BM25 not take minutes per query?

The answer is the **inverted index** — one of the most elegant data structures in computer science.

**The forward index** (naive approach): 
```
Document 1 → [python, list, sort, algorithm, quick]
Document 2 → [python, dict, key, value, hash]
Document 3 → [javascript, list, array, sort, method]
```

To answer "which documents contain 'sort'?", you scan every document. That's O(N) — unacceptable at scale.

**The inverted index** flips it:
```
python → [Doc1, Doc2]
list → [Doc1, Doc3]
sort → [Doc1, Doc3]
algorithm → [Doc1]
quick → [Doc1]
dict → [Doc2]
...
```

Now to answer "which documents contain 'sort'?" — it's an O(1) lookup. You go directly to the "sort" entry and get [Doc1, Doc3]. Done.

For BM25 scoring, each entry doesn't just store the document ID — it stores the *term frequency* too:
```
sort → [(Doc1, tf=2), (Doc3, tf=1)]
```

And IDF is precomputed at index time because it only depends on corpus-wide statistics.

So a BM25 query is: look up each query term in the inverted index (O(1) each), get the posting lists, compute scores, merge, sort. For most queries, only a tiny fraction of documents are even touched.

**Compression:** Posting lists can get huge ("the" in a 100M document corpus has a 100M entry posting list). Real systems use sophisticated delta encoding and compression (the Elias Gamma code, Golomb codes, etc.). Elasticsearch and Lucene are doing all of this under the hood.

---

## Part 5: The Embedding Revolution — Semantic Search

Now we get to the neural era. The core problem BM25 solves brilliantly — fast lexical matching — it has a hard ceiling: it only matches what's literally there.

The fundamental breakthrough: **what if we could map text into a mathematical space where *meaning* determines proximity, not words?**

### Embeddings: Meaning as a Point in Space

An embedding model takes text and outputs a vector — a list of numbers (typically 384, 768, or 1536 dimensions). The magic: the model is trained so that **semantically similar text produces vectors that are close together**.

```
embed("How to exit vim") → [0.23, -0.71, 0.44, 0.18, ...]
embed("Quitting the vim editor") → [0.21, -0.69, 0.47, 0.15, ...]
embed("Python list sorting") → [-0.45, 0.33, -0.12, 0.88, ...]
```

The first two vectors are very close (small distance). The third is far away. Closeness = semantic similarity.

**How are these models trained?**

The dominant paradigm is **contrastive learning** with architectures like Sentence-BERT:

You take pairs of sentences you *know* are semantically related (from Natural Language Inference datasets, question-answer pairs, etc.). You train the model so that related pairs produce close vectors and unrelated pairs produce distant vectors.

The objective is something like: push `embed("exit vim")` close to `embed("quit vim editor")`, while pushing both far from `embed("bake a cake")`.

After training on millions of such pairs, the model develops a rich internal representation of meaning.

**Cosine similarity** is usually used to measure closeness (rather than Euclidean distance), because it's about the *direction* of the vector, not its magnitude — which handles variable-length text better.

```
cosine_similarity(a, b) = (a · b) / (||a|| × ||b||)
```

Ranges from -1 (opposite meaning) to 1 (identical meaning). In practice, most text pairs are 0 to 1.

---

### Bi-encoders vs Cross-encoders — A Critical Distinction

This is one of the most important concepts to deeply understand, because it governs the fundamental architecture of retrieval systems.

**Bi-encoder (the retrieval model):**
The query and each document are encoded *independently*. 

```
query_vector = encode(query)
doc_vector = encode(doc)
similarity = cosine(query_vector, doc_vector)
```

The key word: **independently**. The document has no idea what query it's being compared to. This means you can **pre-compute and store all document vectors offline**. At query time, you only encode the query (one inference pass), then compute similarities.

This is what makes semantic search fast. The expensive part (encoding documents) happens once at indexing time.

**Trade-off:** Because the document is encoded independently of the query, it can't use information *about the query* to inform its encoding. This limits its accuracy.

**Cross-encoder (the reranking model):**
The query and document are fed together as a single input:

```
score = cross_encode("[query] Why does useCallback not prevent re-renders [doc] useCallback returns a memoized callback. The component re-renders when...")
```

The model reads *both together* and outputs a single relevance score.

This is much more powerful because the model can do *full attention* across both texts — it can say "Oh, this specific part of the document directly addresses the 'prevent re-renders' part of the query." It captures subtle, query-specific relevance signals that the bi-encoder misses.

**Trade-off:** You cannot pre-compute anything. Every query-document pair requires a fresh inference pass. At 10ms per inference and 10 million documents, you'd need 100,000 seconds per query. **Completely infeasible for full corpus retrieval.**

This creates the classic two-stage architecture:

```
Stage 1: Bi-encoder retrieves top-100 candidates fast
Stage 2: Cross-encoder re-ranks those 100 with high accuracy
```

You get both speed and accuracy. This is how basically every serious retrieval system works.

---

## Part 6: ANN Indexes — Fast Nearest Neighbor Search at Scale

You have 10 million document vectors, each 768 dimensions. A query vector comes in. You need the top-10 most similar vectors.

**Exact nearest neighbor search:** Compare the query against every single vector. 10M × 768 multiply-accumulate operations per query. Takes seconds. Not okay.

**Approximate Nearest Neighbor (ANN):** Trade a tiny bit of accuracy for enormous speed gains. Instead of *guaranteed* top-10, find *probably* top-10 with 95-99% recall. In practice, the approximation error rarely matters for retrieval quality.

There are three major families of ANN indexes:

---

### Family 1: Clustering-Based Indexes (IVF — Inverted File Index)

The intuition: instead of searching all 10M vectors, can we narrow down to a promising *region* of the space first?

**Building the index:**
1. Run k-means clustering on all your document vectors. Maybe k=1000 clusters.
2. Assign each document vector to its nearest cluster centroid.
3. Store each cluster as a "bucket" of vectors.

**At query time:**
1. Find the nearest cluster centroids to your query vector (fast — only comparing to 1000 centroids, not 10M vectors).
2. Only search within those clusters (say, top-10 nearest clusters).
3. You've reduced the search space from 10M to roughly 10M/1000 × 10 = 100,000 vectors.

**The nprobe parameter:** How many clusters do you search? More clusters = higher recall (less likely to miss the true nearest neighbor), slower search. This is a tunable runtime parameter — you can trade accuracy for speed on the fly.

**Limitation:** If your query falls near the boundary between two clusters, the true nearest neighbor might be in the cluster you didn't search. This is the approximation error.

---

### Family 2: Graph-Based Indexes (HNSW — Hierarchical Navigable Small World)

This is the current state-of-the-art for most retrieval applications. It's what Pinecone, Weaviate, Qdrant, and Chroma all default to. Understanding *why* it works is genuinely fascinating.

It's inspired by the **small world phenomenon** (the "six degrees of separation" idea). In social networks, you can reach anyone through surprisingly few hops even though the network is massive. HNSW builds an artificial graph with this property.

**Building the graph:**
Think of it as a multi-layer graph, like a subway system with express and local lines.

- **Bottom layer (Layer 0):** Every vector is a node. Each node connects to its K nearest neighbors (typically K=16 or 32). This is the "local stops" layer — dense but slow to traverse long distances.

- **Higher layers:** Progressively fewer nodes, but each connection spans longer distances. Think of the express train — fewer stops, but you cover ground faster.

Each vector is assigned a maximum layer level (randomly, with exponential decay — most vectors are only in layer 0, fewer in layer 1, very few reach layer 3).

**At query time:**
1. Enter the graph at the top layer (the "express" layer with few nodes and long-range connections).
2. Greedily navigate: from your current node, move to whichever neighbor is closest to the query vector.
3. When you can't move closer at this layer (local optimum), drop down to the next layer.
4. Repeat until you reach layer 0 and can't move closer anymore.
5. The nodes you're at (and nearby) are your approximate nearest neighbors.

**Why this works so well:**
- At high layers, you make large jumps toward the right region of the space quickly.
- At low layers, you fine-tune to find the precise nearest neighbors.
- The small-world structure means you reach approximately the right neighborhood in O(log N) hops instead of O(N).

**HNSW parameters:**
- `M` (connections per node): Higher → better recall, more memory, slower build time. Typical values: 16-64.
- `ef_construction` (search breadth during build): Higher → better quality index, slower to build.
- `ef_search` (search breadth at query time): Runtime tunable. Higher → better recall, slower.

**Memory trade-off:** HNSW is fast and high-recall but memory-hungry. Storing 10M vectors of 768 dims in float32 = 10M × 768 × 4 bytes = ~30GB. Plus the graph structure. This is why quantization matters.

---

### Family 3: Quantization — Compressing Vectors

**Product Quantization (PQ):** Instead of storing 768 float32 values per vector (3072 bytes), you compress them dramatically.

The idea: split the 768-dimensional vector into, say, 96 sub-vectors of 8 dimensions each. For each group of 8 dimensions, train a codebook of 256 possible "codes." Then represent each sub-vector as which of the 256 codes it's closest to — that's just 1 byte.

So a 768-dim float32 vector (3072 bytes) becomes 96 bytes. **32× compression.** With some accuracy loss, but often acceptable.

**Scalar Quantization (SQ):** Simply reduce precision. Convert float32 (4 bytes) to int8 (1 byte) by mapping the range of each dimension. 4× compression, minimal accuracy loss.

Modern systems often combine: HNSW for the graph structure, PQ for the stored vectors. You navigate the graph using compressed vectors (fast), then re-score the top candidates with the full vectors (accurate).

---

## Part 7: The Full Retrieval Pipeline — Putting It All Together

Now let's build the complete picture. This is how production retrieval systems are actually designed.

```
User Query
    ↓
[Query Understanding Layer]
    ↓ query rewriting, decomposition, expansion, HyDE
[Multi-Strategy Retrieval]
    ↓
    ├── BM25 / Lexical Retrieval (top-100)
    └── ANN / Semantic Retrieval (top-100)
    ↓
[Fusion & Deduplication]
    ↓ merge ~200 candidates (some overlap)
[Re-ranking]
    ↓ cross-encoder scores all ~200
[Top-K Results]
    ↓
[LLM / Final Response]
```

Let's walk through each stage with your code RAG use case as the running example.

---

### Stage 1: Query Understanding

Query comes in: *"Why is my JWT token validation failing with expired signature error?"*

The understanding layer might:
- **Detect the query type:** This is a debugging question, not a "how to implement" question. Relevant chunks are likely error handling code, token validation logic, expiry checking code.
- **Extract entities:** JWT, token validation, expired signature — these are the key terms. High-weight them.
- **Rewrite for retrieval:** Generate a retrieval-optimized version: *"JWT token signature expired validation error authentication middleware"*
- **Maybe decompose:** 
  - Sub-query 1: "JWT signature validation code"
  - Sub-query 2: "token expiry checking"
  - Sub-query 3: "expired signature error handling"

---

### Stage 2: Multi-Strategy Retrieval (Hybrid Search)

**BM25 leg:**
Fires against your inverted index. It will natively find chunks containing: `JWT`, `expired`, `signature`, `ValidationError`, `token`. It'll ace finding chunks with those exact identifiers.

**ANN/Semantic leg:**
Your query gets embedded → vector search finds chunks that are semantically about authentication token lifecycle management — even if they use different words. Maybe there's a chunk that says "verify bearer token claims" — BM25 won't match because "expired signature" isn't in it, but the embedding model knows it's relevant.

Each leg returns top-100. Now you have up to 200 candidates (some will be in both).

---

### Stage 3: Fusion — Merging Two Result Lists

You have two ranked lists. How do you combine them into one?

**Reciprocal Rank Fusion (RRF):** Elegant and surprisingly effective. For each document, look at its rank in each list. Score it as:

```
RRF_score(doc) = Σ 1 / (k + rank_in_list)
```

Where k is typically 60. A document ranked #1 in both BM25 and semantic gets `1/(60+1) + 1/(60+1)` = high score. A document ranked #1 in only one list gets `1/(60+1)` = lower. Documents not in a list get 0 contribution from that list.

RRF is robust because it doesn't require the scores from different systems to be on the same scale (BM25 scores and cosine similarities are totally different number ranges).

**Weighted Linear Combination:** Normalize scores from each system to [0,1], then `final = α × BM25_score + (1-α) × semantic_score`. The α hyperparameter lets you tune how much each system contributes. For code retrieval with lots of exact identifiers, you might set α = 0.6 (favor BM25).

---

### Stage 4: Re-ranking with a Cross-Encoder

Now you have ~150-200 unique candidates. Feed each (query, candidate) pair to a cross-encoder.

The cross-encoder reads both and produces a precise relevance score. It can do things the bi-encoder can't:
- "This chunk has the exact function name mentioned in the query"
- "This chunk discusses expiry in the context of authentication specifically, not session expiry"
- "This chunk is a test file, probably less useful than the implementation file"

Re-rank the 150 candidates by cross-encoder score. Take top 5-10.

**Cost:** If your cross-encoder takes 20ms per inference and you have 150 candidates, that's 3 seconds of re-ranking. Too slow. Solutions:
- Batch inference (GPUs are great at this — run all 150 in parallel)
- Use a smaller/faster cross-encoder model
- Reduce candidate pool before re-ranking (be more aggressive in retrieval, take top-50 not top-150)

---

### Stage 5: Optional — Metadata Filtering and Contextual Re-ranking

Before or after the main retrieval, you can apply filters:
- "Only look at Python files" → metadata filter on file extension
- "Only look at files modified in the last 30 days" → recency filter
- "The user is asking about authentication, so boost chunks from the `auth/` directory"

This is sometimes called **contextual compression** — after retrieving, a small model or LLM reads each retrieved chunk and says "is this actually answering the question, or is it tangentially related?" and trims or scores accordingly.

---

## Part 8: SPLADE, ColBERT, and Late Interaction — Beyond the Simple Bi-encoder

This is the frontier — where the field has been pushing recently.

### The Fundamental Bi-encoder Limitation

When a bi-encoder encodes a document into one vector, it has to **compress all the information in the document into one point in space**. It can't simultaneously be close to every possible relevant query — it has to pick a "center of gravity."

A long code file about authentication, database connections, and error handling — what's its one vector? It's a sort of average, and that average might not be particularly close to *any* specific query.

### ColBERT: Late Interaction

ColBERT (Contextualized Late Interaction over BERT) is a fascinating architecture that changes the unit of comparison.

Instead of encoding a document into *one* vector, ColBERT encodes each **token** (word/subword) into its own vector.

A document with 128 tokens produces 128 vectors. A query with 15 tokens produces 15 vectors.

**Relevance score:** For each query token, find its maximum similarity to any document token. Sum these up.

```
score(Q, D) = Σ (for each query token q) max(cosine(q_vec, d_vec) for each doc token d)
```

This is called **MaxSim** — maximum similarity.

Why is this powerful? The query token "expired" finds the document token "expiry" (close vectors). The query token "JWT" finds the document token "JSON Web Token" (close vectors). Each query aspect independently finds its best match in the document.

**The trade-off:** You now store N vectors per document instead of 1. For a chunk of 200 tokens with 128-dim vectors, that's 200 × 128 × 4 bytes = ~100KB. For 10M documents, that's 1TB of vectors. Storage becomes a serious concern.

**PLAID (the practical ColBERT):** Recent work on making ColBERT practical with centroid-based compression.

### SPLADE: Sparse Learned Representations

SPLADE takes a different angle. It keeps the sparse/inverted-index style of BM25 but *learns* the vocabulary weights.

Instead of "the word 'expired' has IDF weight X", SPLADE learns: "when this document has the concept of expiration, activate the 'expired', 'expiry', 'timeout', 'stale' dimensions — even if those words don't literally appear in the document."

It's a trained sparse expansion model. The output is still a sparse vector (mostly zeros) that fits in an inverted index, but it's vocabulary-expanded based on learned semantics.

SPLADE often achieves BM25-level latency with embedding-model-level semantic understanding. It's a genuinely exciting middle ground.

---

## Part 9: What This Means for Your Code RAG System

Now let's bring everything back to you. You're building a code RAG system. Here's how to think about every design decision:

**Chunking strategy:** Before any retrieval, how you chunk matters enormously.
- Function-level chunks: preserves semantic units, ideal for code
- File-level: too large, dilutes signal
- Line-level: too small, loses context
- Overlapping chunks: include some context before/after the main chunk to avoid cutting mid-thought

**Lexical retrieval matters a lot for code:** Function names, variable names, class names, error codes — these are exact strings. BM25 will outperform embeddings for queries that include specific identifiers. Always include BM25 in your pipeline for code.

**Embedding model choice:** General-purpose models (OpenAI Ada, sentence-transformers) are okay. Code-specific models (CodeBERT, UniXcoder, CodeT5) are trained on code and understand code semantics better — they know that `authenticate()` and `verify_credentials()` are semantically related in a way a general model might not.

**Re-ranking investment:** For code RAG, a cross-encoder re-ranker that can distinguish "this is the implementation" vs "this is a test that uses it" vs "this is a comment about it" is very valuable. The quality jump from re-ranking is significant.

**Query transformation for code:** If the user asks a natural language question, consider extracting the technical entities and using those for BM25 retrieval, while using the full query for semantic retrieval. They serve different purposes.

---

## Part 10: The Mental Model to Keep

Here's the one-page version of everything we just covered:

**The fundamental tension in retrieval:**
- Exact matching (BM25): fast, accurate for known terms, blind to synonyms
- Semantic matching (embeddings): understands meaning, can miss exact terms, needs ANN for speed
- These are complementary, not competing — use both

**The fundamental tension in accuracy vs. speed:**
- Bi-encoders are fast but limited (independent encoding)
- Cross-encoders are accurate but slow (joint encoding)
- Two-stage retrieval solves this: fast broad retrieval → slow accurate re-ranking

**The indexing-time vs. query-time trade-off:**
- Everything you can precompute (document vectors, IDF scores, graph structure) should be precomputed
- Query-time should only do the irreducible minimum

**The query is not sacred:**
- The raw user query is usually suboptimal
- Rewriting, expanding, decomposing, and transforming queries before retrieval is often where the biggest quality gains come from

---

---

# Follow-up Deep Dives

---

## Part 11: Exact Search vs ANN — When Does ANN Make Sense?

### Is the "full pipeline" always what's used?

No — and this is the most important mental correction to make. The full pipeline drawn above is the *maximal* version. Nobody builds the whole thing unless their scenario demands it. You assemble the pipeline to fit the problem, like picking tools out of a box.

The right way to think about it: **start with the simplest thing that could possibly work, then add stages only when you can measure that they help.** A 10k-document corpus of clean code chunks might need nothing more than a single embedding search with exact (brute-force) similarity. Adding HNSW, BM25 fusion, and a cross-encoder to that would be wasted complexity that buys you nothing and costs you latency and bugs.

### Exact search vs ANN — and what IndexFlatIP / IndexFlatL2 actually are

You named Faiss index types, so let's ground this concretely in Faiss since that's the most common library, but the concepts are universal.

**`IndexFlatL2` and `IndexFlatIP` are not ANN at all. They are brute force — exact search.** The word "Flat" means "no index structure, just a flat list of all vectors." When a query comes in, it computes the distance from the query to *every single vector* and returns the true top-k. There is zero approximation. The result is guaranteed correct.

The difference between the two is only the **distance metric**:

- `IndexFlatL2` uses **Euclidean (L2) distance** — the straight-line distance between two points. Smaller = more similar.
- `IndexFlatIP` uses **inner product (dot product)** — larger = more similar.

Now here's the part that confuses everyone, so let me make it crisp. You probably want **cosine similarity** (the standard for semantic search, since it's about the *direction* of the vector, not its length). Faiss doesn't have an explicit "cosine" index. But there's a trick: **cosine similarity equals inner product when both vectors are normalized to unit length.** So the standard recipe is: normalize all your vectors (divide each by its magnitude), then use `IndexFlatIP`. Now your inner product *is* cosine similarity. This is why you see `IndexFlatIP` + normalization everywhere — it's the cosine search idiom.

When would you use raw L2 or raw IP without normalizing? Rarely in modern embedding retrieval. Some embedding models are specifically trained for dot-product (where magnitude carries meaning, like importance weighting), and their model card will tell you. When in doubt, normalize and use IP — that's cosine, which is what almost every sentence/code embedding model is trained for.

**So for your 10k–100k corpus: yes, IndexFlat (exact) makes perfect sense and is often the *correct* choice.** Let me give you the actual numbers so you have an intuition, not a rule you're memorizing.

Brute-force search is roughly `N × D` multiply-add operations per query, where N = number of vectors, D = dimensions. For 100k vectors at 768 dims, that's ~77 million operations per query. A modern CPU does this in a few milliseconds; a GPU does it in well under a millisecond. **Exact search on 100k vectors is essentially free.** You'd only feel pain somewhere in the low millions of vectors. The commonly cited crossover where ANN starts genuinely earning its keep is around 1 million vectors and up, though it depends on your latency budget and hardware.

The thing people forget: **ANN is a tradeoff you only want to pay for when you have to.** ANN gives you speed but costs you (a) recall — you might miss some true neighbors, (b) memory — HNSW graphs are big, (c) build time, (d) tuning complexity (M, ef_search, nprobe...). On a small corpus you get *none of the benefit* (exact search is already fast) and *all of the cost*. So at 10k–100k, use `IndexFlatIP` with normalized vectors and move on. Don't add a graph index to look sophisticated — adding it would make your system slightly worse.

Here's the full Faiss ladder so you can place everything:

- **`IndexFlatIP` / `IndexFlatL2`** — exact, brute force. Use under ~1M vectors. Perfect recall.
- **`IndexIVFFlat`** — the clustering approach (k-means buckets, `nprobe` controls how many buckets to search). Use when brute force gets slow but you still have RAM for full vectors. Tune `nprobe` to trade recall for speed.
- **`IndexHNSWFlat`** — the graph approach. Best recall-vs-speed for in-memory search, but memory-hungry. The go-to for "I need fast and accurate and I have the RAM."
- **`IndexIVFPQ`** — clustering plus product quantization (compressed vectors). Use when vectors won't fit in RAM. Trades accuracy for massive memory savings — the option for hundreds of millions to billions of vectors.
- **`IndexIVFScalarQuantizer`** — milder compression (float32 → int8), 4× smaller, small accuracy hit. A nice middle ground.

A clean decision heuristic: under ~1M → Flat (exact). 1M–10M and fits in RAM → HNSW or IVFFlat. Tens of millions+ or RAM-constrained → IVFPQ. That's genuinely most of the decision space.

---

## Part 12: Quick review — the "what does each thing actually solve" map

The table you want burned into memory:

- **BM25 / lexical** solves the *exact-term* problem — function names, error codes, identifiers, rare keywords. Fails on synonyms and paraphrase. Fast via inverted index.
- **Embeddings + vector search** solves the *vocabulary mismatch* problem — "exit" matching "quit". Fails when exact tokens matter (your `authenticate_user` query). Needs ANN at scale.
- **ANN indexes (HNSW/IVF/PQ)** solve the *scale/speed* problem for vector search. They don't improve relevance — they make vector search fast. On a small corpus they solve a problem you don't have.
- **Hybrid + fusion (RRF)** solves the *"each method has blind spots"* problem by combining lexical and semantic so one covers the other's gaps.
- **Cross-encoder reranking** solves the *precision* problem — the bi-encoder's independent encoding misses query-specific relevance nuance; the cross-encoder reads query and doc together and fixes the ordering.
- **Query understanding (rewrite/expand/decompose/HyDE)** solves the *"the raw query is a bad search input"* problem — before retrieval even happens.

Notice that several of these solve *speed*, several solve *recall* (finding the right stuff at all), and several solve *precision* (ordering it correctly). When you debug a retrieval system, first diagnose which of those three is broken, then reach for the matching tool. That diagnosis-first habit is what separates informed design from cargo-culting.

---

## Part 13: How to actually use a cross-encoder

A cross-encoder is a model (commonly a `ms-marco-MiniLM` or BGE/`bge-reranker` style model) that takes a **(query, document) pair as a single joint input** and outputs **one number** — a relevance score. That's it. It's a scoring function, not a search engine.

The flow is always: retrieve a candidate set with something cheap (bi-encoder and/or BM25), *then* rerank that set with the cross-encoder. You never run a cross-encoder over your whole corpus — it has no precomputed index; it must do a fresh forward pass for every pair. That's the whole reason it lives in stage two.

Mechanically, in pseudocode:

```python
candidates = retriever.search(query, top_k=100)   # cheap stage
pairs = [(query, c.text) for c in candidates]
scores = cross_encoder.predict(pairs)             # batched on GPU
reranked = sort(zip(candidates, scores), desc=True)
final = reranked[:5]                              # what you hand to the LLM
```

The practical knobs that matter:

The **candidate count** you rerank is your main cost dial. Reranking 100 candidates is roughly 100× the cost of one inference. If your reranker is 15ms/pair and you do them serially, that's 1.5 seconds — too slow. So you (a) batch them — GPUs rerank a batch of 100 nearly as fast as one — and/or (b) shrink the candidate pool (rerank 30, not 200). Tuning that pool size is the central latency-vs-quality tradeoff of the rerank stage.

The **scores are not calibrated probabilities** — don't treat 0.8 as "80% relevant." They're only meaningful *relative to each other within one query*. Use them for ordering, and optionally for a cutoff threshold you tune empirically.

And know **when to skip reranking entirely**: if your bi-encoder already nails ordering on your eval set, the cross-encoder adds latency for no gain. Add it only when you can measure that the top results are *present but mis-ordered* — that's the exact symptom reranking cures. If the right doc isn't even in the candidate set, reranking can't help you; that's a *recall* problem and you fix it upstream (better retrieval, hybrid, more candidates).

---

## Part 14: Query planning and decomposition — the heart of it

### The core correction

**You do not decompose by sentences or punctuation. You decompose by distinct *information needs*.** A "sentence" is a grammatical unit; an "information need" is "one thing I need to go look up." These are not the same. One sentence can contain three information needs ("compare Django and FastAPI async handling and which scales better" = three lookups). Three sentences can contain one information need ("My app is slow. It uses Postgres. Why might queries hang?" = one lookup about Postgres query hangs). So the unit of retrieval is the *information need*, and the planner's job is to find those, regardless of how the text is punctuated.

With that fixed, here's how to think about each scenario.

**Scenario A — the user pastes 5 genuinely separate questions.** These are 5 independent information needs. You decompose into 5 sub-queries and run 5 separate retrievals, each scoped to its own question. You do *not* concatenate them into one search — a blended query would return mush relevant to all and excellent for none (remember the "averaged vector" problem). Each sub-query gets its own clean retrieval, and you assemble the context per-question for the LLM. So: yes, separate searches, but because they're separate *needs*, not because there are 5 sentences.

**Scenario B — "write me code that does X" (a task, not a question).** This is where people over-retrieve. A task often needs *zero or few* retrievals if it's general knowledge the LLM already has. You retrieve only for the parts where *your specific codebase or docs matter*: the existing functions it should call, your project's conventions, the API signatures it must match. So the decomposition isn't "split the task into steps and search each step" — it's "identify which pieces of this task require *grounding in my private corpus* and retrieve only those." If the task is "write a quicksort," retrieval is pointless. If it's "write a handler that uses our existing `AuthService` and follows our error-handling pattern," you retrieve `AuthService`'s code and one example of the error pattern — two targeted lookups, not one-per-step.

**Scenario C — the multi-step task with step1/step2/step3 and test cases.** Here decomposition by step *can* be right, but conditionally. The question to ask for each step is: *does executing this step require information I don't already have in context?* If step 2 needs to call a function defined elsewhere in the repo, retrieve for step 2. If step 3 is pure logic the model can write from what's already retrieved, don't retrieve again. Test cases are their own interesting case: if the user wants tests written against existing code, you retrieve the code-under-test and any existing test conventions/fixtures — that's a distinct information need worth its own retrieval. So you end up retrieving for *some* steps and not others, driven by "does this step touch the corpus," not by the mere existence of steps.

The principle threading through all three: **retrieve per information need, and only when the need can't be satisfied from what you already have.** Over-decomposition (a search per sentence/step) floods the LLM with redundant context, costs latency, and often *hurts* answer quality because relevant signal gets diluted by marginally-relevant chunks. Under-decomposition (one blended search for a multi-part query) misses whole sub-topics. The art is matching retrieval granularity to need granularity.

**Now: who actually does the decomposition — LLM or code?** There's a spectrum, and mature systems use a mix:

At the cheap, deterministic end: **rules and classifiers**. A small intent classifier or even regex/heuristics can route ("does this contain a question mark and multiple clauses?", "is this a 'how to' vs a 'debug' query?"). Fast, cheap, predictable, but brittle — it can't truly understand a tangled multi-part request.

At the powerful, flexible end: **an LLM as the planner.** You give an LLM the user's message and a prompt like "Break this into the minimal set of independent search queries needed to answer it; if no search is needed, say so." The LLM returns structured sub-queries (often as JSON). This handles arbitrary complexity — it understands that three sentences are one need, or that one sentence hides three. The cost is latency and money (an extra LLM call before you even retrieve) and non-determinism.

The pragmatic production pattern is **a cheap router in front of an expensive planner**: a fast classifier decides "is this simple (single need → just retrieve once) or complex (→ invoke the LLM planner to decompose)?" Simple queries skip the expensive planning entirely; only genuinely complex ones pay for LLM decomposition. This is the same "don't pay for the maximal pipeline unless you need it" principle applied to the planning stage itself.

For an agentic code system specifically, there's a fourth, increasingly dominant option worth naming: **the LLM decides retrieval dynamically through tool calls.** Instead of decomposing everything upfront, you give the model a `search_codebase` tool and let it retrieve *as it reasons* — it writes step 1, realizes it needs `AuthService`, calls search, continues. This interleaves planning and retrieval instead of front-loading all decomposition, and it tends to match retrieval to need very naturally because the model only searches when it actually hits a knowledge gap. The tradeoff is more LLM round-trips. For your code RAG/agent use case this pattern is very much worth considering over rigid upfront decomposition.

---

## Part 15: The other pieces a complete retrieval system needs

To round out your mental map, here are the components not dwelt on that you'll run into and should know exist:

**Chunking** is upstream of everything and quietly determines your ceiling — if the right answer is split across a chunk boundary, no retriever can recover it. For code, chunk by semantic unit (function/class) rather than fixed token windows, and consider small overlaps.

**Metadata and filtering** — attach structured fields to chunks (language, file path, last-modified, function vs test) so you can pre-filter the search space ("only Python files") or post-boost ("prefer `src/` over `tests/`"). This is cheap and high-leverage.

**Evaluation** is the thing most people skip and most regret skipping. You need a labeled set of queries with known-relevant chunks, and you measure **recall@k** (is the right chunk anywhere in your top-k — diagnoses retrieval) and a ranking metric like **MRR or nDCG** (is it ordered well — diagnoses reranking). Without this you're tuning blind; with it, every "should I add X stage?" question becomes an experiment with an answer.

**Embedding and reranker model choice**, especially code-specific models (CodeBERT, UniXcoder, and newer code embedding models) over general-purpose ones for code corpora.

**Caching** — query results, and especially embeddings, since recomputing them is the bulk of your cost.

So to directly answer the opening question one more time: the full pipeline is the menu, not the meal. For your stated 10k–100k code corpus, a strong, realistic v1 is: chunk by function → embed with a code model → normalized `IndexFlatIP` (exact, no ANN needed) → add BM25 + RRF fusion because code has exact identifiers that embeddings miss → add a cross-encoder reranker *only if* your eval shows mis-ordering → let the LLM drive decomposition via a search tool rather than rigidly splitting queries upfront. Build it in that order, measure at each step, and stop adding stages the moment the eval stops improving.

---

---

# Deep Dive: Chunking — The Foundation That Sets Your Ceiling

---

## Part 16: Why Do We Chunk at All?

Before the methods, feel the four forces pushing you to chunk. Every chunking decision is a negotiation between them.

**Force one — the embedding blur problem.** This is the deepest one. When you embed a piece of text, the model squeezes everything in it down to one point in vector space. Think of that point as the *center of gravity* of all the meaning in the text. If your chunk is about one tight thing — a single function that parses a date — that center of gravity lands precisely on "date parsing," and a query about date parsing lands right next to it. But if your chunk is a whole file containing date parsing *and* network retries *and* logging config, the center of gravity gets dragged to the average of all three — it lands in a fuzzy no-man's-land that's not really close to *any* specific query. **A chunk's embedding gets blurrier the more distinct ideas you cram into it.** This single intuition explains 80% of good chunking. Big mixed chunks = blurry embeddings = weak retrieval.

**Force two — the precision/granularity problem.** Retrieval returns *whole chunks*. If your chunk is an entire 2,000-line file and only 10 lines are relevant, you've handed the LLM 1,990 lines of noise to find the needle in. The chunk is the unit of retrieval, so its size *is* the resolution of your search. Coarse chunks → coarse answers.

**Force three — the context budget problem.** Whatever you retrieve gets stuffed into the LLM's context. Context is finite and (a) costs money, (b) has a real "lost in the middle" degradation where models attend worse to stuff buried in long contexts. So you can't just return giant chunks "to be safe" — you pay for it twice.

**Force four — the model token limit.** Embedding models have a maximum input length (often 512 tokens, sometimes 8k). Text past the limit is silently truncated — the tail of a long chunk may simply not be embedded at all. This is a hard ceiling, not a preference.

Now here's the tension that makes chunking an *art*: forces one, two, and three push you toward **smaller** chunks (sharp embeddings, precise retrieval, lean context). But there's an opposing force pulling the other way —

**The context-preservation counter-force.** A chunk ripped out of its surroundings can become *meaningless or misleading*. Imagine a chunk that says "It returns null if the user isn't found, which the caller must handle." What is "it"? Which caller? The chunk lost its anchor. Or a code snippet `return self._cache[key]` — without the class definition, you don't know what `self` is, what `_cache` holds, or what this function is even called. Cut too small and your sharp embedding is sharply about *nothing identifiable*.

So **good chunking is the act of finding the smallest unit that is still self-contained.** Small enough that the embedding is sharp and the retrieval is precise; large enough that the chunk still means something on its own. Every strategy below is a different tactic for finding that sweet spot.

---

## Part 17: What Makes a *Good Chunk* — The Five Properties

Before the methods, internalize the properties you're optimizing for. When you evaluate any chunk, run it against these five:

**Self-containment.** Can this chunk be understood without its neighbors? A good chunk doesn't have dangling references ("as mentioned above," "this function," an undefined `self`). If understanding it requires the previous chunk, you cut in the wrong place.

**Single-topicness (low semantic variance).** The chunk should be *about one thing*, so its embedding lands as a sharp point. The moment a chunk covers two unrelated ideas, split it — you'll get two sharp embeddings instead of one blurry one.

**Right-sized for the query.** The chunk's granularity should match the granularity of what people will *ask*. If users ask "what does function X do," function-level chunks are right. If they ask "how does the auth module work overall," you may need a coarser representation too. The query distribution dictates chunk size — not the other way around. This is the single most overlooked principle.

**Low noise.** Boilerplate, license headers, repeated import blocks, navigation menus, HTML cruft — this stuff pollutes the embedding (drags the center of gravity) and wastes context. Strip it before embedding.

**Retrievable form matches indexable form... or deliberately doesn't.** This is the advanced one and the heart of the question — devoted a whole section to it below.

---

## Part 18: The Full Taxonomy of Chunking Strategies

Walking the ladder from crude to sophisticated, telling you what problem each rung solves and where it breaks. This is the menu you'll mix and match from.

**Fixed-size chunking (by token or character count).** Just cut every N tokens. Dumb, fast, deterministic. It completely ignores meaning — it'll slice a sentence in half, cut a function down the middle, split a table from its header. Its only virtue is simplicity and predictable sizes. It's the baseline you start from and almost always improve on. The one place it's tolerable is truly unstructured uniform text where you have no boundaries to exploit.

**Fixed-size with overlap (sliding window).** Same as above but each chunk shares its last ~10–20% with the next chunk's start. This is a *patch* for the boundary problem: if an important idea straddles a cut, the overlap means at least one chunk captures it whole. Cheap insurance. Costs you some duplication (the same text indexed twice, slight context bloat). Almost always worth a small overlap; this is why it's a near-universal default.

**Sentence / paragraph chunking.** Split on natural language boundaries. Respects that a sentence is a complete thought. Better than fixed-size for prose, but sentences are often too small (lose context) and paragraphs vary wildly in size. Usually a building block rather than a final answer.

**Recursive structural splitting** (what LangChain's `RecursiveCharacterTextSplitter` does, and why it's the common default). The idea: try to split on the *biggest* natural boundary first, and only fall to smaller ones if a piece is still too large. So it tries to split on double-newlines (paragraphs); if a paragraph still exceeds your size limit, it splits that on single newlines; if still too big, on sentences; then words; then characters as a last resort. This respects document structure as much as possible while guaranteeing a max size. It's the sensible general-purpose default for mixed text. Its weakness: it follows *syntactic* structure (newlines, punctuation), not *semantic* structure — it doesn't know that two adjacent paragraphs are actually one idea, or that one paragraph secretly switches topics halfway.

**Structure / layout-aware chunking.** Use the document's *own* structure as the boundaries. Markdown headers, HTML sections, PDF layout, slide boundaries. Split a Markdown doc at its `##` headings; each section becomes a chunk and you can even prepend the heading path ("Setup > Authentication > Token Refresh") into the chunk so it carries its location. This is strictly better than recursive splitting *when the document has reliable structure*, because the author already told you where the conceptual seams are. This is the right instinct for technical docs, wikis, and — crucially — code.

**Semantic chunking.** Instead of structural cues, use *meaning shifts* to find boundaries. The technique: embed each sentence, walk through the document, and measure the embedding distance between consecutive sentences. When the distance spikes — meaning the topic just changed — cut there. So chunks naturally form around topic-coherent runs of text. This directly optimizes for the single-topicness property. The cost: you're running an embedding model just to *decide boundaries*, which is slower and more expensive than counting tokens. Worth it when topic coherence really matters and your text doesn't have clean structural markers.

**LLM-based / agentic chunking.** Hand the document to an LLM and ask it to segment into coherent self-contained units, or even to rewrite each chunk to be self-contained (resolving "it"/"this" references, adding missing context). This is the highest-quality and highest-cost end. You'd use it for high-value, relatively static corpora where chunk quality dominates and you chunk once but retrieve millions of times — there the one-time LLM cost amortizes to nothing. You would *not* use it for a corpus that re-indexes constantly or is enormous and low-value-per-doc.

**Late chunking** (a newer, clever idea worth knowing). Normally you chunk first, then embed each chunk in isolation — so each chunk's embedding has no idea about the rest of the document. Late chunking flips the order: feed the *whole* document through a long-context embedding model first, get token-level embeddings that have "seen" the full document via attention, *then* pool those token embeddings into chunk embeddings by averaging over each chunk's token span. The payoff: each chunk's embedding is contextualized by the whole document, so a chunk that says "it returns null" still carries the document's knowledge of what "it" is. It directly attacks the context-preservation problem without bloating chunks. Requires a long-context embedding model and a bit more machinery, but it's a genuinely elegant solution.

**Hierarchical / parent-child chunking** (this bridges into the centerpiece idea). You chunk at *two* granularities at once: small child chunks (for sharp embeddings and precise matching) nested inside larger parent chunks (for context). You *search* over the small children but *return* the parent. So you get the precision of small chunks at retrieval time and the context of large chunks at generation time. This is sometimes called "small-to-big" or parent-document retrieval, and it's one of the most reliably useful patterns in production. Notice what just happened: **the thing you embedded is not the thing you returned.** That's the door we're about to walk through.

---

## Part 19: The Centerpiece — Decouple What You *Index* From What You *Return*

Here is the idea that answers the function-name-vs-docstring question, and it's the thing that, once it clicks, changes how you design everything.

Most people unconsciously assume the chunk is one object: the same text gets embedded, gets searched, and gets returned. **It doesn't have to be. These are three separate jobs, and you can use a different representation for each.**

- The **indexed representation** exists to be *findable* — to produce a sharp embedding (and/or good BM25 terms) that lands close to the queries people will actually ask.
- The **returned representation** exists to be *useful* — to give the downstream consumer (the LLM, or your code) exactly what it needs to do its job.

These goals are *different*, so optimizing one object for both is a compromise. Splitting them is the unlock. This pattern is called **multi-representation indexing**, and it has several flavors:

**Index a summary, return the source.** For each function, you generate (often with an LLM, once, at index time) a clean one-line description: "Parses an ISO-8601 date string into a UTC datetime, raising ValueError on malformed input." You *embed that summary* — it's clean, single-topic, and shaped like how people ask questions, so it produces a beautiful sharp embedding that queries land right next to. But you *store and return* the actual function code. The summary is the lure; the code is the catch.

**Index questions, return the chunk.** For each chunk, generate the questions it answers ("How do I parse a date?", "What exception does date parsing throw?") and embed *those*. Now you've eliminated the query-chunk asymmetry entirely — you're matching questions against questions. The user's question lands right on top of your synthetic questions. You still return the underlying code. (This is HyDE's cousin, done at index time instead of query time.)

**Index the signature + docstring, return the full implementation.** And here's the exact example, finally answered head-on. The question was: if downstream I only need the function name and docstring, should the chunk hold code snippets or a clean function-plus-docs sentence?

The reframed, correct answer: **decide separately for each job.**

For the *indexed* representation, you almost always want the clean, distilled version — the function name, signature, and docstring (and maybe a generated one-liner of what it does), *not* the raw implementation body. Why? Because the implementation body is full of low-signal noise for retrieval purposes: loop variables, temporary names, error-string literals, framework boilerplate. All of that drags the embedding's center of gravity toward generic "code-ness" and away from the function's *purpose*. The docstring and signature, by contrast, are a dense, purpose-focused, query-shaped description — they embed sharply onto the queries people ask ("how do I parse a date"). So: **embed the clean signature+docstring, not the raw snippet, because the clean version is what queries actually resemble.**

For the *returned* representation, you give downstream exactly what it consumes. If downstream genuinely only needs the name and docstring — return just that, tight and cheap. If downstream needs to *call or modify* the function, return the full implementation even though you didn't embed it. The implementation was dead weight for *finding* the function but essential for *using* it. So you store it, return it, and simply never embedded it.

That's the resolution to the puzzle: it was a false choice. The clean docstring representation wins *for indexing*, and whether you return the snippet depends entirely on what the downstream task needs — and those two decisions are independent. The moment you stop assuming "the chunk" is one fixed object, the apparent dilemma dissolves.

---

## Part 20: Code-Specific Chunking — Your Actual Battlefield

Code has a property prose lacks: it has a *formal, parseable structure* (an Abstract Syntax Tree). That's a gift — exploit it.

**Never fixed-size chunk code.** Cutting every 500 tokens will slice through the middle of a function, orphan a closing brace, separate a function from its docstring, split a class from its methods. The resulting chunks are syntactically broken and semantically meaningless. This is the cardinal sin of code RAG.

**Chunk on syntactic boundaries using a parser.** Tools like **tree-sitter** parse code into an AST and let you split on real boundaries: one chunk per function, per method, per class. Now every chunk is a complete, valid, self-contained unit — exactly the self-containment property we want. This is the baseline correct approach for code, and it's what serious code-search systems do.

**Choose your granularity by the query distribution (again).** Function-level is the usual sweet spot: it matches how people ask ("what does `parse_date` do," "find the function that validates tokens"). But classes complicate it: a method ripped from its class loses `self`'s meaning, the class's fields, sibling methods it calls. So the common refinement is **inject context into the chunk**: prepend the file path, the imports it depends on, the class signature, and the docstring, then include the method body. The chunk becomes "here is method X, which lives in class Y (whose relevant fields are A, B), in file Z" — self-contained again. You're manufacturing the context that naive splitting destroys.

**Decide what's signal vs noise for *your* downstream.** License headers, copyright blocks, and giant import lists are usually noise for retrieval — strip them from the indexed representation (you can still keep them in the stored source if downstream needs them). Comments and docstrings are *high* signal — they describe intent in natural language, which is exactly what bridges the gap to natural-language queries. Many code-search systems weight or even separately index docstrings precisely because they're the natural-language anchor in a sea of syntax.

**Lean hard on hybrid here.** Recall from before: code is full of exact identifiers, and BM25 nails exact identifiers while embeddings nail intent. For code chunking this means you often want the chunk's *indexed form* to feed both: BM25 over the raw tokens (so `authenticate_user` is findable literally) and an embedding over the signature+docstring (so "log a user in" finds it semantically). Same chunk, two indexed representations, fused at query time.

---

## Part 21: What Makes a *Good Embedding*

Chunking decides *what* you embed; here's how to make the embedding itself good:

**Feed it clean, single-topic, right-length input.** Everything above. Garbage in, blurry vector out. The embedding can only be as sharp as the text is focused.

**Respect query/passage asymmetry.** Many modern embedding models are trained *asymmetrically* — they expect you to mark queries and documents differently (e.g., prefixing `"query: ..."` vs `"passage: ..."`, or using separate query/document encoders). If you embed both sides the same way when the model expects prefixes, you silently lose accuracy. Read the model card; this is a frequent quiet bug.

**Match the model to the domain.** A general-text embedding model treats code as weird English. A code-trained model (CodeBERT, UniXcoder, and newer code-embedding models) actually understands that `auth()` and `verify_credentials()` are related. For a code corpus, a code model is a free accuracy gain.

**Normalize, and use cosine** (the IndexFlatIP idiom from before) unless the model says otherwise.

**Mind the asymmetry between what a query looks like and what a chunk looks like.** A query is a short question; a code chunk is a long syntactic blob. They live in the same space but have very different shapes, and similarity suffers across that gap. *This is the entire motivation* for the decouple-and-summarize tricks above: by indexing a docstring or a synthetic question, you reshape the indexed thing to look like the query, closing the gap. So "what makes a good embedding" and "decouple index from return" are the same insight viewed from two angles.

---

## Part 22: The Design Framework — How to Actually Reason About a New Problem

Here's the thinking procedure to run whenever you sit down to design a retrieval system. Notice it runs *backwards* from how people usually build:

**Start at the query, not the corpus.** Ask: *what will people actually ask, and at what granularity?* Write down 20 real example queries. Are they "find this specific function" (fine-grained → small chunks)? Or "explain how this subsystem works" (coarse → you need a coarse representation too)? Your chunk size is downstream of your query distribution, always. If you have both kinds of queries, you need both granularities (hierarchical/multi-representation).

**Then look at the downstream consumer.** What does whatever-receives-the-results actually need? Just an answer snippet? Code to execute? Enough context to reason? This decides your *returned* representation — independently of your indexed one.

**Now design the indexed representation to bridge query→content.** Make the embedded thing look as much like the query as possible (summaries, synthetic questions, docstrings) and as single-topic as possible (good chunk boundaries). Add BM25 over raw tokens wherever exact terms matter (always, for code).

**Then ask the three diagnostic questions to decide which machinery you actually need** — and this is where you decide *where to use an LLM and where you don't even need one*:

- *Is the right content even getting retrieved (recall)?* If not, fix chunking, add hybrid, or reshape the indexed representation. **No LLM needed** — this is an indexing problem.
- *Is it retrieved but mis-ordered (precision)?* Add a cross-encoder reranker. **No LLM needed** — a reranker, not a generator.
- *Is the query itself a bad search input — multi-part, vague, conversational?* *Now* an LLM earns its place, as a query planner/decomposer or as the agent that searches dynamically. And even here, recall the cheap-router idea: use the LLM only for the genuinely complex queries, not the simple ones.

That last point is the heart of "where do I even need an LLM." The honest answer for most retrieval pipelines: **the LLM is needed far less often than people reach for it.** Chunking, indexing, hybrid search, and reranking are all *non-LLM* machinery and they solve the bulk of retrieval quality. The LLM shows up at the *edges*: optionally at index time to generate summaries/synthetic-questions (a one-time cost), and optionally at query time to plan/decompose/rewrite messy queries. The core retrieval loop in the middle — the part that runs on every single query at scale — usually shouldn't have an LLM in it at all, because it'd be slow and expensive on the hot path. Knowing *that* is exactly the kind of informed judgment you said you wanted: you reach for the LLM where cheap machinery can't see meaning or structure, and you keep it off the hot path where cheap machinery already works.

And the one thing that turns all of this from theory into engineering: **build the eval set first.** Twenty real queries with their known-correct chunks. Then every decision above — chunk size, summary-vs-raw indexing, add-a-reranker, add-an-LLM-planner — stops being a debate and becomes a measurement. Recall@k tells you if chunking/indexing is working; ranking metrics tell you if you need the reranker. You will *never have to doubt anything* not because you memorized the right answers, but because you can *measure* which answer is right for your specific problem. That's the actual end state of "knowing the stuff" — not certainty from authority, but certainty from being able to test.

---

*When you sit down to design a retrieval system, these tensions are your framework. Every technique you pick is navigating these trade-offs given your specific constraints — corpus size, query type, latency budget, accuracy requirements, and infrastructure.*

*The pipeline is a menu, not a meal. Start with the simplest thing that could work, measure, and add stages only when the eval improves. Know which of {recall, precision, speed} you're fixing, reach for the matching tool, and keep the LLM where cheap machinery can't see — that is informed retrieval design.*
