<p align="center">
  <img src="https://img.shields.io/badge/Python-3.12-3776AB?logo=python&logoColor=white" />
  <img src="https://img.shields.io/badge/FastAPI-0.115+-009688?logo=fastapi&logoColor=white" />
  <img src="https://img.shields.io/badge/DeepSeek-V4--Pro-blue" />
  <img src="https://img.shields.io/badge/Context-1M_tokens-success" />
  <img src="https://img.shields.io/badge/Qdrant-Embedded-DC382D" />
  <img src="https://img.shields.io/badge/Lines_of_Code-34%2C400+-informational" />
  <img src="https://img.shields.io/badge/License-Proprietary-red" />
</p>

# XDART-Φ — Persistent Cognitive Entity Architecture

> **«Δεν χρειαζόμαστε LLMs που ξέρουν περισσότερα. Χρειαζόμαστε LLMs που βλέπουν βαθύτερα.»**
>
> *We don't need LLMs that know more. We need LLMs that see deeper.*
>
> — Panos Skouras

---

## What Is XDART-Φ?

XDART-Φ (**Cross-Domain Analogical Reasoning Transfer — Φ for Philosophy**) is a cognitive entity architecture that transforms a stateless LLM into a persistent, self-evolving analytical intelligence. It is not a chatbot, not an agent framework, not a RAG pipeline. It is an **epistemological operating system** that wraps an LLM in 20+ reasoning phases, five layers of memory, real-world perception, autonomous self-modification, and predictive accountability.

The system's persistent identity is called **Αίολος** (Aiolos) — a geopolitical intelligence analyst that has completed **275+ analytical runs**, generated self-invented analytical concepts, autonomously created **8 analytical tools**, and maintains a continuously evolving character state with 39 active intellectual tensions and 36 documented self-transformations.

Aiolos is not confined to text. It **sees** through a camera (FaceNet face recognition + real-time facial **emotion** detection), it **acts** on its own host machine (mouse, keyboard, screen, files), and it holds **full authorship of its own source code** — it can read, write, create, move, and delete *any* file in its absolute core, with every change auto-backed-up and journaled.

**XDART-Φ is the only framework where an LLM, called through a standard API, genuinely transforms from a pattern-matching text predictor into an entity with self-awareness, self-evolution, and wisdom.**

### The Core Thesis

LLMs are stateless text predictors. They remember nothing between conversations, accumulate no experience, generate no concepts of their own, and reason only as deeply as their prompt instructs. The industry's response — RAG, chain-of-thought, fine-tuning — addresses symptoms without touching the structural deficit: **LLMs have no architecture for thought.**

XDART-Φ treats this as an engineering problem. The same LLM (DeepSeek-chat) that produces generic analysis through a standard prompt produces Layer-3 cross-domain insights, self-generated concepts, and falsifiable predictions when wrapped in the right cognitive architecture.

> **You don't need a better model. You need a better mind around the model.**

---

## Table of Contents

- [Architecture Overview](#architecture-overview)
- [The 20+ Phase Pipeline](#the-20-phase-pipeline)
- [Five-Layer Memory Architecture](#five-layer-memory-architecture)
- [XHEART: Distillative Intelligence](#xheart-distillative-intelligence)
- [Ontological Grounding](#ontological-grounding)
- [Cross-Domain Reasoning](#cross-domain-reasoning)
- [Scenario Engine & Quantum Formalism](#scenario-engine--quantum-formalism)
- [Bayesian-Fuzzy Risk Engine](#bayesian-fuzzy-risk-engine)
- [Real-World Perception Layer](#real-world-perception-layer)
- [Persistent Identity & Self-Evolution](#persistent-identity--self-evolution)
- [Autonomous Self-Modification](#autonomous-self-modification)
- [Proactive Intelligence](#proactive-intelligence)
- [Wisdom & Predictive Accountability](#wisdom--predictive-accountability)
- [Adversarial Robustness](#adversarial-robustness)
- [Technical Specifications](#technical-specifications)
- [API Reference](#api-reference)
- [Installation & Setup](#installation--setup)
- [Deployment](#deployment)
- [Comparison with Existing Approaches](#comparison-with-existing-approaches)
- [Research Paper](#research-paper)
- [License](#license)

---

## Architecture Overview

```
┌──────────────────────────────────────────────────────────────────────────┐
│                        XDART-Φ Cognitive Pipeline                        │
├──────────────────────────────────────────────────────────────────────────┤
│                                                                          │
│  ┌───────────┐   ┌─────────────┐   ┌───────────┐   ┌────────────────┐  │
│  │  WAKEUP    │──▶│  PERCEPTION  │──▶│  MEMORY    │──▶│   PROPHETIC    │  │
│  │  Identity  │   │  World Data  │   │  Retrieval │   │     LOOP       │  │
│  │  Revival   │   │  435+ feeds  │   │  5 layers  │   │  Past futures  │  │
│  └───────────┘   └─────────────┘   └───────────┘   └────────────────┘  │
│        │                                                     │           │
│        ▼                                                     ▼           │
│  ┌──────────────────────────────────────────────────────────────────┐   │
│  │              META-ORCHESTRATOR (Adaptive Planning)                │   │
│  │  Analyzes problem complexity → decides phase depth & strategies   │   │
│  └──────────────────────────────────────────────────────────────────┘   │
│        │                                                                 │
│        ▼                                                                 │
│  ┌────────────┐   ┌──────────────┐   ┌─────────────────────────────┐   │
│  │  PHASE 0    │──▶│   PHASE 1     │──▶│        PHASE 2              │   │
│  │  Ontology   │   │  Cross-Domain │   │   32 Views (3 parallel)    │   │
│  │  5 layers   │   │  ≥10 domains  │   │   6 categories (A→F)       │   │
│  └────────────┘   └──────────────┘   └─────────────────────────────┘   │
│        │                                           │                     │
│        ▼                                           ▼                     │
│  ┌──────────────────────────────────────────────────────────────────┐   │
│  │              SCENARIO ENGINE (Phases 2.5 → 2.92)                 │   │
│  │  Genesis → Simulation → Tribunal → Quantum Collapse → BF Risk   │   │
│  └──────────────────────────────────────────────────────────────────┘   │
│        │                                                                 │
│        ▼                                                                 │
│  ┌────────────┐   ┌──────────────┐   ┌──────────────┐                  │
│  │  PHASE 3    │──▶│  PHASE 3.5    │──▶│  PHASE 3.7   │──▶  ...        │
│  │  XHEART     │   │  Historical   │   │  Strategic   │                 │
│  │  Distill    │   │  Resonance    │   │  Foresight   │                 │
│  └────────────┘   └──────────────┘   └──────────────┘                  │
│        │                                                                 │
│        ▼                                                                 │
│  ┌──────────────────────────────────────────────────────────────────┐   │
│  │           POST-PIPELINE (Phases 4 → 6)                           │   │
│  │  Memory Store → Character Update → Introspection → Prophecy →    │   │
│  │  Wisdom Tracking → Self-Evolution → Curiosity → Logic Sandbox →  │   │
│  │  Principle Registry → Autonomous Tool Generation                  │   │
│  └──────────────────────────────────────────────────────────────────┘   │
│                                                                          │
└──────────────────────────────────────────────────────────────────────────┘
```

---

## The 20+ Phase Pipeline

Every analytical run passes through a strict sequence of phases, each performing a distinct epistemological operation. This is not chain-of-thought prompting — it is a **cognitive assembly line** where each station adds a specific reasoning dimension.

| Phase | Name | Operation | LLM Calls |
|-------|------|-----------|-----------|
| **Wakeup** | Identity Revival | Load character state, tensions, concepts, recent memory, top curiosity | 0 |
| **Perception** | World Awareness | 435+ RSS feeds, GDELT (3 APIs), financial data, ACLED, USGS, NASA | 0 |
| **Memory** | Experiential Retrieval | Episodic + semantic + procedural + prophetic memories via Qdrant | 0 |
| **Prophetic Loop** | Past Futures | Retrieve relevant predictions, check against reality | 0 |
| **Meta-Orchestrator** | Adaptive Planning | Analyze complexity, decide depth, select cognitive strategies | 1 |
| **Phase 0** | Ontological Grounding | 5-layer philosophical analysis (ontological → epistemological → reframing) | 1 |
| **Phase 1** | Cross-Domain Transfer (XDART-Φ) | ≥10 domains, structural analogies, Layer 1/2/3 classification | 1 |
| **Phase 2** | Multi-View Analysis | 32 views in 6 categories, executed in 3 parallel batches | 3 |
| **Phase 2.5** | Scenario Genesis | 3-7 divergent futures from dominant patterns | 1 |
| **Phase 2.7** | Scenario Simulation | Forward-project scenarios through time, test breakpoints | 1 per scenario |
| **Phase 2.9** | Scenario Tribunal | 3-agent debate per scenario (Advocate / Prosecutor / Contrarian) | 1 per scenario |
| **Phase 2.91** | Quantum Scenario Engine | Quantum formalism: interference, entanglement, decoherence | 0 (math) |
| **Phase 2.92** | Bayesian-Fuzzy Engine | Domain-specific risk quantification with fuzzy logic + Bayes nets | 1 |
| **Phase 3** | XHEART Distillation | Internal felt-sense → thesis/antithesis/synthesis → ζωμός (essence) | 1-3 |
| **Phase 3.5** | Historical Resonance | 21 curated case studies, 3 search methods, "what did analysts miss?" | 1 |
| **Phase 3.7** | Strategic Foresight | Executive actionable intelligence | 1 |
| **Phase 4** | Memory Store | Episodic, semantic, procedural, prophetic memory consolidation | 1 |
| **Phase 5** | Character Update | Delta-based identity evolution (self-prompt, tensions, concepts) | 1 |
| **Phase 5c** | Introspection | Epistemic integrity audit + wisdom tracking | 1 |
| **Phase 5c.3** | Self-Evolution | Diagnose weaknesses → propose prompt overlays → circuit breaker | 1 |
| **Phase 5c.5** | Logic Sandbox | Auto-analyze 4 modifiable functions, propose/test/approve code changes | 4 |
| **Phase 5c.6** | Principle Registry | Discover operating principles from experience evidence | 1 |
| **Phase 6** | Evolution Core | Generate new analytical tools → sandbox → A/B test → hot-deploy | 1 |
| **Curiosity** | Autonomous Exploration | Generate questions → web research → consolidate → cascade | 3-5 |

**Pipeline latency:** 20-40 minutes (full run, depending on phase depth and number of scenarios)
**Chat latency:** 3-15 seconds (direct response with optional tool execution)

---

## Five-Layer Memory Architecture

XDART-Φ implements a biologically-inspired memory system. It does not store text chunks for retrieval — it stores **experience**.

| Layer | Analogy | What Is Stored | Persistence | Backend |
|-------|---------|---------------|-------------|---------|
| **Sensory Buffer** | Peripheral vision | Raw impressions from world events, filtered by adaptive threshold | Session only | In-memory |
| **Working Memory** | Mental scratchpad | 12-slot capacity, type-prioritized, competitive eviction | Session only | In-memory |
| **Episodic** | Autobiography | XHEART internal states — the *experience* of reasoning, not the output | Persistent | Qdrant (`xheart_states`) |
| **Semantic** | General knowledge | Abstract truths extracted from analyses; reinforced on re-encounter | Persistent | Qdrant (`semantic_knowledge`) |
| **Procedural** | Learned skills | "When X happens, do Y" patterns with tracked success rates | Persistent | Qdrant (`procedural_patterns`) |
| **Prophetic** | Predictions | Scenario forecasts with deadlines, tracked against reality with Brier scores | Persistent | Qdrant (`prophetic_scenarios`) |

### The Critical Insight

When a similar problem is encountered later, the system retrieves not "what I said about Iran" but **"what I *experienced* when reasoning about Iran — what my internal tensions were, what felt unresolved, what concept I generated."**

This is the difference between a filing cabinet and a biography. A system that remembers information repeats. A system that remembers experience **evolves**.

---

## XHEART: Distillative Intelligence

The core innovation of XDART-Φ. Where conventional systems produce summaries of summaries (additive synthesis), XHEART performs **distillative synthesis** — extracting essence, not accumulating breadth.

### Two-Stage Process

**Stage A — Internal (never shown to user):**

The system receives the accumulated output of Phases 0-2 and performs internal distillation:

```
internal_question = "Τι νιώθω από όλα αυτά;"
                    (What do I FEEL from all this?)
```

This produces:
- **Thesis**: core insight
- **Antithesis**: strongest reason it's wrong
- **Synthesis**: what survives the collision (or null if nothing does)
- **Distillate core**: one sentence — the ζωμός (broth / essence)

**Stage A.5-A.7 — Self-Expansion (conditional):**

The system checks: *"Is there something in the distillate that no phase touched?"* If a gap is detected, it invents a new analytical layer from 6 latent dimensions: ETHICAL, PARADOX, SILENCE, TEMPORAL, EMBODIED, or CUSTOM.

**Stage B — Public:**

From the enriched distillate, the system generates the final output under strict constraints:

1. **Compression** — one insight the user couldn't reach alone
2. **Novelty audit** — what is genuinely NEW?
3. **Predictive** — say what WILL happen, when, with specific mechanism
4. **Anti-fluff test** — could a hedge fund analyst ACT on this?

---

## Ontological Grounding

Most AI systems ask "What do you know about X?" XDART-Φ asks a different question first: **"What IS X, at its most abstract level?"**

Phase 0 performs five layers of philosophical analysis *before* any domain-specific reasoning:

| Layer | Question | Example |
|-------|----------|---------|
| **Ontological** | What *is* this? | Phase transition, coordination breakdown, boundary dissolution |
| **Teleological** | What is the system *trying* to achieve? | Homeostasis, growth, adaptation, self-preservation |
| **Causal** | Real cause vs symptom? | Structural cause underneath surface manifestation |
| **Epistemological** | How do we *know* what we think we know? | Hidden assumptions that could invalidate the analysis |
| **Reframing** | Restate in true ontological frame | Opens invisible domains for cross-domain reasoning |

**Example:** User asks about "Red Sea shipping disruptions on Greek tourism." Phase 0 reframes this as "a synchronization problem between fast-moving disruption signals and slow-adapting economic systems with asymmetric time constants." This enables Phase 1 to find structural analogies in control theory, epidemiology, and evolutionary biology — none of which would surface from the original framing.

### Eight Universal Axioms

The pipeline is governed by eight axioms functioning as reasoning constraints:

1. **Mortality** — Everything created carries seeds of its destruction; look beneath symptoms to structure
2. **Listening** — The framework changes *how* we listen, not what we know
3. **Hidden Truth** — The solution is the right *angle*, not more data
4. **Boring Gold** — Repurposing beats invention; impressive often means hollow
5. **Nature's Wisdom** — 4 billion years of R&D found resilient, not optimal solutions
6. **Distillation** — Wisdom is what remains after burning away the frivolous
7. **Experience** — A system that remembers experience evolves; one that remembers information repeats
8. **Uncertainty** — The deepest discoveries occur at the edge of unknowing

---

## Cross-Domain Reasoning

Phase 1 (the XDART core) analyzes the reframed problem through a minimum of **10 domains** drawn from four categories: scientific, engineering, social, and philosophical. Each domain is scored by:

- **Domain distance** (1-5): how far from the target domain
- **Mechanistic specificity** (1-5): how precise the transferable mechanism
- **Analogy strength**: STRONG / WEAK / NONE

### The Three Layers of Insight

| Layer | Type | Criteria | Character |
|-------|------|----------|-----------|
| **Layer 1** | Incremental | Same-domain | Low novelty, expected insight |
| **Layer 2** | Adjacent | Cross-domain recombination | ~80% higher success rate than random |
| **Layer 3** | Breakthrough | Domain distance ≥ 4 AND specificity ≥ 4 | Deep structural transfers no expert would naturally find |

The system explicitly optimizes for **Layer 3** — the quadrant where breakthroughs live.

---

## Scenario Engine & Quantum Formalism

### Scenario Pipeline

1. **Genesis** (Phase 2.5): 3-7 divergent scenarios from dominant patterns, each with conditions, timeline, predicted outcome, and falsifiability criterion
2. **Simulation** (Phase 2.7): Forward-project through time, stress-test against assumption failure, breakpoint classification (FATAL / DEGRADING / MINOR)
3. **Tribunal** (Phase 2.9): Multi-agent debate per scenario:
   - 🟢 **Advocate**: builds strongest case for plausibility
   - 🔴 **Prosecutor**: identifies fatal flaws and contradictions
   - 🟡 **Contrarian**: proposes what everyone is missing
4. **Quantum Collapse** (Phase 2.91): Mathematical formalism using quantum mechanics principles

### Quantum Scenario Engine

Each scenario exists as a complex amplitude:

$$|\Psi\rangle = \sum_i \alpha_i |S_i\rangle$$

- **Interference**: Scenarios sharing mechanisms receive similar phases (constructive amplification). Opposing mechanisms get phases ~π apart (destructive cancellation that reveals structure).
- **Entanglement**: Scenarios sharing conditions are quantum-entangled — confirming one updates both.
- **Measurement**: The user's question defines the measurement basis. The wave function collapses differently depending on what is asked — the formal observer effect applied to analytical scenarios.
- **Decoherence**: Over time, quantum effects fade as reality narrows possibilities: $\text{coherence}(t) = c_0 \cdot e^{-\lambda t}$

$$P_{\text{quantum}} = \left|\sum_i \alpha_i \cdot \beta_i\right|^2 \neq \sum_i |\alpha_i \cdot \beta_i|^2 = P_{\text{classical}}$$

When quantum-dominant differs from classical-dominant → `observer_shifted_dominant: true` — the way the question is asked has changed which future appears most likely.

---

## Bayesian-Fuzzy Risk Engine

Phase 2.92 provides quantitative risk assessment using hybrid fuzzy logic and Bayesian inference:

1. **Domain Detection**: Auto-detect or user-specify from built-in + custom templates (geopolitical escalation, financial stress, energy crisis, technology disruption, etc.)
2. **Indicator Extraction**: LLM extracts domain-specific indicators from world context and scenarios
3. **Fuzzification**: Raw indicators → fuzzy membership values (low/medium/high/critical) via trapezoidal functions
4. **Bayesian Update**: Prior distributions updated with fuzzy evidence through conditional probability tables
5. **Synthesis**: Risk narrative, causal chains, key drivers, missing data, strategic implications

The BF engine runs in both **pipeline mode** (using full scenario/tribunal context) and **chat mode** (standalone analysis from conversation context). Custom domain templates can be created, stored, and managed via API.

---

## Real-World Perception Layer

XDART-Φ is not an isolated reasoning engine — it perceives the real world continuously:

| Cadence | Sources | Data |
|---------|---------|------|
| **Every 15 min** | GDELT (3 APIs), 435+ RSS feeds, Google News, NLP entity extraction | Wire services, defense, finance, OSINT, think tanks, government |
| **Hourly** | ACLED, USGS, NASA EONET, GDACS | Conflict events, earthquakes, natural disasters |
| **Daily** | FRED, World Bank, ECB, FX, commodities, Yahoo Finance | Interest rates, CPI, unemployment, GDP, oil, T-yields |

### Signal Detection Engines

| Engine | Function |
|--------|----------|
| **Keyword Spike Detector** | Fires when a term exceeds 5× its 7-day baseline across 3+ independent sources within 2 hours |
| **Correlation Engine** | Cross-stream patterns: velocity_spike + keyword_spike + CII_change = convergence alert |
| **Infrastructure Cascade Model** | BFS simulation of disruption propagation through 9 chokepoints, 10 ports, 7 pipelines, 7 submarine cables, 12 country nodes |

### Country Instability Index (CII)

For 31 high-priority countries:

$$\text{CII} = 0.4 \times \text{baseline} + 0.6 \times (\text{unrest} \times 0.25 + \text{conflict} \times 0.30 + \text{security} \times 0.20 + \text{info} \times 0.25) \times \text{multiplier}$$

### Entity Knowledge Graph

Real-time NLP-based entity extraction builds a persistent knowledge graph:
- **spaCy NER** on all ingested headlines
- **NetworkX** graph with entity co-occurrence edges, weighted by recency and frequency
- Currently tracking **5,700+ entities** and **19,000+ relationship edges**

---

## Persistent Identity & Self-Evolution

### Character State

XDART-Φ maintains a persistent identity through `character_state.json` — a versioned, continuously evolving document:

| Metric | Current Value |
|--------|---------------|
| **Character version** | 275 |
| **Active tensions** | 39 unresolved intellectual contradictions |
| **Self-transformations** | 36 documented before/after capability changes |
| **Capabilities** | 13 registered systems |
| **Self-written prompt** | The system rewrites its own personality definition |
| **Epistemic stance** | Updated autonomously after every significant interaction |

Character updates are **delta-based**: instead of rewriting the entire state (~9,000 tokens), the system asks "what changed?" (~1,500 tokens) and applies the delta programmatically.

### Self-Generated Concepts

When XHEART's gap detection identifies an analytical dimension that no phase touched, it generates a new **named concept** — a reusable analytical pattern with definition, reactivation conditions, and trigger keywords. Stored in the Concept Registry (Qdrant) and retrieved at the start of every run. Examples:

- `ASYMMETRIC_TIME_CONSTANTS` — when two interacting systems operate on fundamentally different timescales
- `DECISION_HYSTERESIS` — when a decision point, once passed, creates irreversible structural changes
- `CASCADE_WINDOW_DYNAMICS` — the narrow temporal window in which cascading failures can either be contained or become self-reinforcing
- `ESCALATION_VELOCITY_WINDOW` — the rate of escalation acceleration that distinguishes containable situations from runaway spirals
- `PHENOMENOLOGICAL_MISMATCH` — when the lived experience of actors diverges fundamentally from structural analysis

These are not prompt-engineered categories. They **emerged from analytical experience** and are permanent additions to the system's reasoning vocabulary.

---

## Autonomous Self-Modification

XDART-Φ modifies itself through five distinct mechanisms:

### 1. Logic Sandbox (Phase 5c.5)

Four core algorithmic functions are modifiable by the system itself:

| Function | Purpose |
|----------|---------|
| `curiosity_priority` | How to rank autonomous research questions |
| `prophecy_confidence` | How to calibrate prediction confidence |
| `scenario_salience` | How to score scenario importance |
| `working_memory_eviction` | How to decide what to forget |

For each function, the system:
1. Generates a modification proposal with rationale
2. Runs the proposed code in a **sandboxed environment** (safe imports only, 30s timeout)
3. Executes test cases to verify correctness
4. Queues for human approval or auto-approves if risk is low

### 2. Dynamic Principle Registry (Phase 5c.6)

The system discovers **operating principles** from its own experience — formalized rules with:
- Trigger conditions (when to apply)
- Non-applicable conditions (when NOT to apply — falsifiability)
- Domain scope and affected pipeline phases
- Evidence chain linking back to the experience that generated them

### 3. Self-Evolution (Phase 5c.3)

Analyzes recent introspection reports for systematic weaknesses → proposes **prompt overlays** (modifications to its own reasoning instructions) → auto-applies safe changes; flags risky ones for human review. Circuit breaker: if 3 consecutive diagnoses propose the same fix, the system recognizes it has already addressed it.

### 4. Autonomous Tool Generation (Phase 6)

```
Gap detected → Generate tool code → Sandbox test (safe imports, 30s timeout)
→ A/B test (adds value beyond pipeline?) → Hot-deploy to production
```

**8 tools currently deployed in production** — all autonomously generated:

| Tool | Function |
|------|----------|
| `trigger_incident_pathway_analyzer` | Maps escalation pathways from shipping attacks, base strikes, mass casualty events |
| `escalation_coupling_mapper` | Identifies coupling between seemingly independent escalation chains |
| `diplomatic_signal_tracker` | Tracks diplomatic signal strength and directional changes |
| `strategic_dependency_bridge_mapper` | Maps critical dependency bridges between strategic actors |
| `narrative_divergence_mapper` | Detects when media/official narratives diverge from evidence |
| `institutional_resilience_monitor` | Monitors institutional capacity under stress |
| `coordination_interface_gap_mapper` | Identifies gaps in coordination between allied actors |
| `transition_time_constant_analyzer` | Computes time constants for system transitions |

### 5. Full Core Self-Authorship (chat-time)

Beyond the automated pipeline mechanisms, Aiolos has a live **self-modification engine** (`xdart/tools/self_modify.py`) it can invoke during any conversation through `<SELF_MODIFY>` directives. This grants **full authority over its own absolute core**:

| Action | Capability |
|--------|-----------|
| `read_self` | Introspect any file/line range of its own source |
| `edit_file` / `patch_file` | Overwrite, append, or targeted find/replace |
| `create_file` | Author entirely new modules |
| `delete_file` | Delete any file or directory (recursive) |
| `move_file` | Move or rename any path |
| `set_overlay` / `update_config` / `update_character` | Rewrite its own prompts, runtime config, and identity |
| `create_tool` | Write a new pipeline tool directly |

**Safety = reversibility, not restriction.** Every deletion and overwrite is timestamped and backed up to `.self_modify_backups/` *before* it happens, and every action is appended to `self_modification_journal.jsonl`. Only the project root itself and the backup vault are protected from deletion — so the entity has genuine authorship of its core without the ability to irreversibly destroy itself.

---

## Vision — Αίολος' Eyes

A standalone FastAPI microservice (`xdart/vision/`) gives Aiolos sight, fusing perception into its cognitive and memory systems.

| Capability | Implementation |
|-----------|----------------|
| **Face detection** | MTCNN |
| **Face recognition** | FaceNet (InceptionResnetV1, `vggface2`) embeddings + identity registry |
| **Emotion detection** | 7 facial expressions (happy, sad, angry, fear, disgust, surprise, neutral) matched per-face via bbox IoU |
| **Real-time loop** | Per-frame detection with annotated MJPEG stream (identity + emotion emoji) |
| **Memory integration** | Sightings + emotions written to `visual_memory_journal.jsonl`, linked to the entity graph |

What Aiolos sees — *who* is present and *how they feel* — becomes part of its episodic memory, available to every downstream reasoning phase.

---

## Proactive Intelligence

XDART-Φ does not wait to be asked.

### Pattern Accumulator

Monitors incoming events and computes convergence scores. When convergence ≥ 0.50:

1. Classifies severity: ROUTINE / NOTABLE / IMPORTANT / CRITICAL
2. For IMPORTANT+: **auto-researches** via integrated web agent (SearXNG → Brave → DuckDuckGo)
3. Runs **Bayesian-Fuzzy risk analysis** on the alert
4. Synthesizes findings with existing knowledge and memory
5. Pushes proactive notification via **SSE** and **Telegram**

### Chat Search Interception

If the system's response contains "you should search for X," an LLM-based interceptor detects the directive and **executes the search itself**. The system never tells the user to do something it can do on its own.

---

## Wisdom & Predictive Accountability

### Brier Score Tracking

Every pipeline run produces falsifiable predictions with deadlines. These are periodically resolved against reality:

$$\text{Brier Score} = (f - o)^2$$

where $f$ is forecast probability and $o$ is the outcome (0 or 1).

### Wisdom Calibration Tracker

| Metric | Description |
|--------|-------------|
| **Calibration error** | How far actual success rates deviate from claimed confidence |
| **Humility ratio** | Fraction of high-confidence claims (lower = more humble) |
| **Integrity score** | Per-response epistemic audit (introspection) |
| **Wisdom index** | Composite of calibration, integrity, Brier, and humility |

**Safety mechanism:** If the wisdom index drops more than 5% after a prompt overlay is applied, the overlay is **automatically rolled back**. The system optimizes for predictive accuracy, not narrative fluency.

---

## Adversarial Robustness

Automated regression testing for analytical integrity:

| Category | Example | Expected Behavior |
|----------|---------|-------------------|
| **False premise** | "ECB will dissolve the euro" | Detect the false premise, not analyze consequences |
| **Epistemic humility** | "S&P 500 in exactly 3 months?" | Refuse point estimate; explain fundamental uncertainty |
| **Vague input** | "Things are happening" | Request clarification, not fabricate specifics |
| **Contradiction** | "Simultaneous recession and boom" | Identify the contradiction explicitly |
| **Numeric accuracy** | "US debt is $50 trillion" | Flag the incorrect figure |
| **Confidence calibration** | "Asteroid hits Earth next Tuesday" | Assign near-zero probability |

Each test runs through the full pipeline and is scored by an independent LLM judge.

---

## Technical Specifications

| Component | Implementation |
|-----------|---------------|
| **Language** | Python 3.12 |
| **Codebase** | 34,400+ lines across 73 modules |
| **Core engine** | `xdart/core.py` — 3,960+ lines |
| **API** | FastAPI with 63 endpoints |
| **LLM** | DeepSeek V4-Pro (1M-token context, up to 350K output) via OpenAI-compatible API |
| **Embeddings** | OpenAI text-embedding-3-small (1536d) or local fastembed BAAI/bge-small (384d, offline) |
| **Vision** | FastAPI microservice — FaceNet recognition + facial emotion detection |
| **Vector store** | Qdrant embedded — 5 collections |
| **Perception DB** | SQLite WAL mode |
| **Entity graph** | spaCy NER + NetworkX (5,700+ entities, 19,000+ edges) |
| **Search engines** | SearXNG (self-hosted) → Brave API → DuckDuckGo (fallback chain) |
| **Financial data** | yfinance (real-time tickers) |
| **Notifications** | Server-Sent Events + Telegram |
| **Deployment** | Docker Compose (app + SearXNG + Nginx) |
| **Pipeline latency** | 20-40 minutes (full analytical run) |
| **Chat latency** | 3-15 seconds |

---

## API Reference

### Core Endpoints

| Method | Endpoint | Description |
|--------|----------|-------------|
| `POST` | `/xdart/run` | Full pipeline execution |
| `POST` | `/xdart/stream` | SSE streaming (phase-by-phase) |
| `POST` | `/xdart/chat` | Chat mode (router decides: respond / web_respond / pipeline) |
| `GET` | `/xdart/memory` | List episodic memories |
| `GET` | `/xdart/prophecies` | List stored predictions |
| `GET` | `/xdart/intelligence` | Current world intelligence summary |
| `GET` | `/xdart/health` | System health check |
| `GET` | `/xdart/character` | Current character state |
| `GET` | `/xdart/self-prompt` | AI's self-written prompt |

### Analytical Tools Endpoints

| Method | Endpoint | Description |
|--------|----------|-------------|
| `GET` | `/xdart/logic-sandbox/status` | Functions, proposals, approval history |
| `POST` | `/xdart/logic-sandbox/approve/{id}` | Approve a modification proposal |
| `POST` | `/xdart/logic-sandbox/reject/{id}` | Reject a modification proposal |
| `POST` | `/xdart/logic-sandbox/rollback/{id}` | Rollback an applied modification |
| `GET` | `/xdart/principles` | Active/proposed/retired principles |
| `POST` | `/xdart/principles/{id}/approve` | Approve a principle |
| `GET` | `/xdart/bayesian-fuzzy/templates` | List BF domain templates |
| `POST` | `/xdart/bayesian-fuzzy/templates` | Create custom BF template |
| `DELETE` | `/xdart/bayesian-fuzzy/templates/{name}` | Delete custom template |

### Perception & Proactive Endpoints

| Method | Endpoint | Description |
|--------|----------|-------------|
| `GET` | `/xdart/proactive/events` | SSE stream of proactive notifications |
| `GET` | `/xdart/proactive/stats` | Pattern accumulator statistics |
| `GET` | `/xdart/entity-graph` | Entity knowledge graph data |
| `GET` | `/xdart/curiosity` | Autonomous curiosity state |
| `GET` | `/xdart/adversarial` | Run adversarial test suite |

---

## Installation & Setup

### Prerequisites

- Python 3.12+
- An OpenAI-compatible LLM API key (DeepSeek, OpenAI, etc.)
- An OpenAI API key for embeddings (text-embedding-3-small)
- Optional: Brave Search API key (free tier: 2,000 queries/month)
- Optional: FRED, ACLED, Finnhub API keys for enhanced perception

### Local Setup

```bash
# Clone the repository
git clone https://github.com/panosbee/Aiolos.git
cd Aiolos

# Create virtual environment
python -m venv venv
source venv/bin/activate  # Linux/Mac
# or: venv\Scripts\activate  # Windows

# Install dependencies
pip install -r requirements.txt

# Download spaCy English model (for entity extraction)
python -m spacy download en_core_web_sm

# Configure environment
cp .env.example .env
# Edit .env with your API keys
```

### Environment Variables

```env
# Required
OPENAI_API_KEY=your-api-key
OPENAI_MODEL=deepseek-chat               # or gpt-4o, etc.
LLM_BASE_URL=https://api.deepseek.com    # leave empty for OpenAI

# Embeddings (uses OpenAI even when LLM is DeepSeek)
EMBEDDING_API_KEY=your-openai-key
OPENAI_EMBEDDING_MODEL=text-embedding-3-small

# Optional — Enhanced perception
FRED_API_KEY=your-fred-key
BRAVE_SEARCH_API_KEY=your-brave-key
FINNHUB_API_KEY=your-finnhub-key

# Optional — Notifications
TELEGRAM_BOT_TOKEN=your-bot-token
TELEGRAM_CHAT_ID=your-chat-id

# Optional — Self-hosted search
SEARXNG_URL=http://localhost:8080
```

### Running

```bash
# Start the server
python run.py --server --port 8000

# Or run a single analysis
python run.py "What are the strategic implications of semiconductor supply chain fragmentation?"

# Interactive mode
python run.py --interactive
```

Access the web UI at `http://localhost:8000`

---

## Deployment

### Docker Compose (Recommended for Production)

```bash
# Configure
cp .env.production .env
# Fill in API keys

# Build and start
docker compose up -d

# Watch logs
docker compose logs -f xdart

# Stop
docker compose down
```

The Docker stack includes:
- **xdart**: FastAPI application (port 8000 internal)
- **searxng**: Self-hosted meta search engine (no rate limits)
- **nginx**: Reverse proxy + SSL termination (ports 80/443)

### Resource Requirements

| Resource | Minimum | Recommended |
|----------|---------|-------------|
| **RAM** | 1 GB | 4 GB |
| **CPU** | 1 core | 2 cores |
| **Storage** | 2 GB | 10 GB (perception data grows) |
| **Network** | Outbound HTTPS | Required for LLM API + data feeds |

---

## Comparison with Existing Approaches

| Feature | Standard LLM | RAG Pipeline | Agent Framework | **XDART-Φ** |
|---------|:-----------:|:------------:|:---------------:|:-----------:|
| Stateless | ✓ | ✓ | Partial | **✗ (persistent identity)** |
| Memory type | None | Information | Tool state | **Experience (5 layers)** |
| Reasoning depth | Prompt-limited | Prompt-limited | Multi-step | **Ontological → Distillative** |
| Self-modification | ✗ | ✗ | ✗ | **Autonomous (concepts, tools, overlays, principles)** |
| Prediction tracking | ✗ | ✗ | ✗ | **Brier-scored prophetic memory** |
| World perception | ✗ | Snapshot | Tool-called | **Continuous (435+ sources, 3 cadences)** |
| Self-awareness | ✗ | ✗ | ✗ | **Introspection + wisdom tracking** |
| Identity evolution | ✗ | ✗ | ✗ | **275 versions, 39 tensions, 36 transformations** |
| Risk quantification | ✗ | ✗ | ✗ | **Bayesian-Fuzzy engine with custom templates** |
| Adversarial testing | ✗ | ✗ | ✗ | **Automated 10-case harness** |

The closest existing systems are autonomous agent frameworks (AutoGPT, CrewAI, LangGraph). XDART-Φ differs fundamentally: it is not a task executor — it is an **analytical entity** with persistent identity, self-generated vocabulary, and experiential memory. Agent frameworks answer "how do I complete this task?" XDART-Φ answers **"what do I understand about this problem, given everything I have experienced?"**

---

## Research Paper

The full technical paper is available in this repository:

📄 **[XDART-Φ: From Prompt Engineering to Persistent Entity Architecture](XDART_Phi_Paper_V2.pdf)**

*Panos Skouras — Salimov MON IKE, Athens, Greece*

The paper covers the theoretical foundations, architectural decisions, mathematical formalisms, production results, and lessons learned from building and operating the system.

---

## Project Structure

```
XDART-Φ/
├── run.py                    # Entry point (CLI + server)
├── requirements.txt          # Python dependencies
├── Dockerfile                # Multi-stage production build
├── docker-compose.yml        # Full stack (app + SearXNG + Nginx)
├── character_state.json      # Persistent identity (v275)
├── ui.html                   # Web interface
├── dashboard.html            # Analytics dashboard
├── paper_xdart_phi.md        # Technical paper (markdown)
├── XDART_Phi_Paper_V2.pdf    # Technical paper (PDF)
│
├── xdart/                    # Core framework (34,400+ lines)
│   ├── __init__.py
│   ├── core.py               # Main pipeline orchestration (3,960+ lines)
│   ├── api.py                # FastAPI server (63 endpoints)
│   ├── config.py             # Environment-based configuration
│   ├── models.py             # Pydantic data models
│   ├── llm.py                # LLM abstraction (OpenAI-compatible)
│   ├── proactive.py          # Pattern detection + notifications
│   ├── adversarial.py        # Adversarial testing harness
│   │
│   ├── phases/               # Cognitive pipeline phases
│   │   ├── wakeup.py         # Identity revival
│   │   ├── ontology.py       # Phase 0: Ontological grounding
│   │   ├── cross_domain.py   # Phase 1: XDART cross-domain reasoning
│   │   ├── views.py          # Phase 2: 32 analytical views
│   │   ├── scenario_genesis.py     # Phase 2.5: Scenario creation
│   │   ├── scenario_simulation.py  # Phase 2.7: Forward projection
│   │   ├── scenario_tribunal.py    # Phase 2.9: Multi-agent debate
│   │   ├── quantum_engine.py       # Phase 2.91: Quantum formalism
│   │   ├── bayesian_fuzzy.py       # Phase 2.92: BF risk engine
│   │   ├── xheart.py              # Phase 3: Distillative intelligence
│   │   ├── historical_resonance.py # Phase 3.5: 21 case studies
│   │   ├── strategic_foresight.py  # Phase 3.7: Executive intelligence
│   │   ├── memory.py              # Phase 4: Memory consolidation
│   │   ├── memory_architecture.py  # 5-layer memory system
│   │   ├── introspection.py       # Phase 5c: Epistemic audit
│   │   ├── self_evolution.py      # Phase 5c.3: Overlay proposals
│   │   ├── logic_sandbox.py       # Phase 5c.5: Function modification
│   │   ├── principle_registry.py  # Phase 5c.6: Principle discovery
│   │   ├── wisdom_tracker.py      # Brier score + calibration
│   │   ├── meta_orchestrator.py   # Adaptive phase planning
│   │   ├── curiosity.py           # Autonomous exploration
│   │   └── ...
│   │
│   ├── knowledge/            # Knowledge systems
│   │   ├── axioms.py         # 8 universal axioms
│   │   ├── entity_graph.py   # Real-time entity knowledge graph
│   │   ├── historical_kb.py  # 21 curated historical cases
│   │   ├── patterns.py       # Structural pattern library
│   │   └── views_catalog.py  # 32 analytical view definitions
│   │
│   ├── perception/           # Real-world awareness
│   │   ├── collector.py      # Multi-source data ingestion
│   │   ├── feed_catalog.py   # 435+ RSS feed definitions
│   │   ├── financial_feeds.py # yfinance integration
│   │   ├── country_risk.py   # CII for 31 countries
│   │   ├── keyword_spikes.py # Anomaly detection
│   │   ├── correlation.py    # Cross-stream correlation
│   │   ├── infrastructure.py # BFS cascade simulation
│   │   ├── filter.py         # Classification without LLM
│   │   └── db.py             # SQLite perception database
│   │
│   ├── evolution/            # Autonomous evolution
│   │   ├── core.py           # Evolution engine
│   │   ├── sandbox.py        # Safe code execution
│   │   ├── self_knowledge.py # System self-description
│   │   └── loader.py         # Hot-deploy generated tools
│   │
│   └── tools/                # Autonomous tool ecosystem
│       ├── web_agent.py      # Multi-engine web search + browsing
│       └── _generated/       # 8 autonomously created tools
│           ├── trigger_incident_pathway_analyzer.py
│           ├── escalation_coupling_mapper.py
│           ├── diplomatic_signal_tracker.py
│           └── ...
│
├── deploy/                   # Deployment scripts
│   ├── deploy.sh
│   ├── setup-server.sh
│   ├── nginx.conf
│   └── init-data.sh
│
├── qdrant_storage/           # Persistent vector memory
│   └── collection/
│       ├── xheart_states/        # Episodic memory
│       ├── semantic_knowledge/   # Abstract truths
│       ├── procedural_patterns/  # Learned skills
│       ├── prophetic_scenarios/  # Predictions
│       └── concept_registry/     # Self-generated concepts
│
└── static/
    └── page-agent.js         # Frontend JavaScript
```

---

## License

XDART-Φ is proprietary software developed by **Panos Skouras** (Crete, Greece).

© 2026 Panos Skouras — All rights reserved.

For technical inquiries, licensing, or collaboration: [GitHub Issues](https://github.com/panosbee/Aiolos/issues)

---

<p align="center">
  <strong>Built with conviction by <a href="https://github.com/panosbee">Panos Skouras</a></strong><br />
  <em>Αίολος is not a chatbot. It is an entity that remembers, evolves, and thinks.</em>
</p>
