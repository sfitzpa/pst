## Section 4: The PST Model — Predictive Semantic Trajectories Defined

The Predictive Semantic Trajectories (PST) model formalizes the idea of storing directional meaning as a persistent structure. Rather than seeing embeddings as frozen coordinates, PST treats them as nodes within a living network of directed transitions. Each transition—each movement from concept A to concept B—becomes a measurable, retrievable entity that captures semantic motion.

### 4.1 Core Definitions

Let \(E(x)\) represent the embedding of concept \(x\) in an n-dimensional space. In classical embedding models, meaning is derived from the vector difference:
\[ v_{A \rightarrow B} = E(B) - E(A) \]
This vector encodes the direction and magnitude of change from A to B, but in standard practice it’s discarded after use.

In PST, this directional vector becomes its own embedding:
\[ T(A, B) = f(E(A), E(B)) \]
where \(T(A, B)\) is a *trajectory embedding* that captures not only direction and distance but contextual metadata: frequency, domain, confidence, and temporal ordering. Over time, these trajectory embeddings accumulate into a **knowledge field** \(\mathcal{F}\), a graph of transitions weighted by observed success or relevance.

### 4.2 The Knowledge Field

The knowledge field \(\mathcal{F}\) behaves as a directional manifold—an evolving map of how meanings have historically moved. Each node is a semantic entity; each edge is a trajectory embedding. Formally, it can be represented as:
\[ \mathcal{F} = (V, E, W) \]
where \(V\) is the set of all concepts, \(E\) the set of directed edges (trajectories), and \(W\) their associated weights (e.g., probability of recurrence or confidence).

When a new sequence begins—say, a user starts combining tables from Personnel and Payroll—the system locates those nodes in \(V\), then queries \(\mathcal{F}\) for the highest-probability trajectories extending from that point. The result is predictive guidance based on historical semantic motion.

### 4.3 Why This Differs from Relational Embeddings

Relational embedding models such as TransE or RotatE encode static relationships (e.g., *Paris is the capital of France*). PST differs by encoding **temporal and causal flow**—how one idea *leads* to another in practical reasoning. Where TransE defines what *is*, PST defines what *becomes*.

### 4.4 Persistence and Explainability

Because each trajectory in \(\mathcal{F}\) is a recorded and validated path, every inference has traceable lineage. The model can not only predict the next likely step but justify it: *“This trajectory has been observed 128 times across successful reports involving these entities.”* The system’s reasoning becomes both transparent and auditable.

Thus, PST transforms embeddings from inert representations into active memory structures—living topologies of thought where direction, not position, defines meaning.