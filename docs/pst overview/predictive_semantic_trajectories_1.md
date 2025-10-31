## Section 1: Origins of Vector Semantics and Its Limits

The story of vector semantics begins with a deceptively simple idea: that meaning can be represented as position. Words, phrases, or entities are points in a vast, continuous space where distance encodes similarity. The closer two points are, the more alike their meanings. This approach emerged from the *distributional hypothesis* in linguistics: "You shall know a word by the company it keeps."

### From Co-occurrence to Geometry

Early systems like **Latent Semantic Analysis (LSA)** and **Word2Vec** (2013) turned that idea into computational geometry. They trained on enormous corpora, adjusting the coordinates of words so that contextually similar ones clustered together. This allowed machines to perform analogical reasoning: the famous `king - man + woman = queen` demonstration showed that linear arithmetic could reveal relationships encoded implicitly in the geometry.

That was a revelation. It meant meaning could be *quantified*, and relationships could be derived algebraically. But these models had an assumption baked deep within: **semantic relationships were symmetric and static.** The geometry itself held no sense of direction. “Dog” and “cat” were close, but the space didn’t know whether you were moving from canine to feline or back again.

### The Great Leap to Context

Transformers (Vaswani et al., 2017) changed the landscape by introducing **contextual embeddings**—vectors that changed depending on their surroundings. The word “bank” had one vector near “river” and another near “loan.” Context finally had direction, but only within the model’s ephemeral state. Each inference computed relationships anew; the results were *dynamic but disposable*. When the model finished a task, all that nuanced geometry evaporated.

### Why This Matters

LLMs, despite their brilliance, remain creatures of amnesia. They infer and forget billions of high-dimensional relationships in every conversation, never committing them to memory. Their vector spaces are stateless; they know proximity but not provenance. They can tell you that two ideas are semantically related but not that one *tends to lead* to the other.

This lack of directionality explains several persistent weaknesses: hallucination (when inference lacks grounding), redundant computation (relearning known relationships), and inefficiency in multi-step reasoning (since each step starts from a blank field).

### The Engineering Gap

The industry optimized for performance, not persistence. Embeddings became an indexing trick rather than a reasoning substrate. Massive gains in speed and scale hid a conceptual gap: **semantic motion**—the flow of meaning through time and context—remained unmodeled. That’s the doorway through which Predictive Semantic Trajectories (PST) now enters: a proposal to treat those flows not as temporary computations but as durable knowledge.