# Long-Term Memory Architectures for LLM Agents — Research Survey

Date: 2026-03-17
Scope: Memory systems for LLM game agents, with focus on applicability to roguelike/permadeath settings

---

## 1. Low-Noise Memory Systems

### 1.1 CLIN — Structured Causal Abstractions
**Paper**: Majumder et al., "CLIN: A Continually Learning Language Agent for Rapid Task Adaptation and Generalization" (Oct 2023, ICML 2024)
**Env**: ScienceWorld (text-based science tasks)

**Key mechanism**: Memory items are constrained to four causal templates:
- `"X SHOULD BE NECESSARY to Y"` — high confidence positive
- `"X MAY BE NECESSARY to Y"` — uncertain positive
- `"X DOES NOT CONTRIBUTE to Y"` — high confidence negative
- `"X MAY NOT CONTRIBUTE to Y"` — uncertain negative

Example: *"opening the fridge is necessary to access apple juice"*

**Why this prevents noise**:
- Template constraints prevent free-form hallucination — the LLM cannot store arbitrary rambling
- Uncertainty markers ("may" vs "should") express confidence calibration
- Reward-based filtering: low-performing trials contribute less to memory (saliency-based pruning)
- Memory size remains significantly smaller than executed action count

**Update mechanism**: After each trial, the memory generator receives (1) current trial sequence, (2) final reward as natural language, (3) memories from 3 most recent prior trials. This rolling window enables accumulation while preventing unbounded growth.

**Meta-memory for generalization**: For cross-task/environment transfer, CLIN creates abstracted memories by selecting the highest-reward trial from each prior episode (fixed archive of 10) and using specialized prompts.

**Results**: +23 points over Reflexion on ScienceWorld. Transfer: +4 (new env), +13 (new task) zero-shot.

**Ablation finding**: Replacing structured templates with free-form advice caused -6 point drop in 10% of test cases. Structured > unstructured empirically validated.

**Source**: [arxiv.org/abs/2310.10134](https://arxiv.org/abs/2310.10134), [allenai.github.io/clin](https://allenai.github.io/clin/), [GitHub](https://github.com/allenai/clin)

### 1.2 AriGraph — Episodic + Semantic Memory Graph
**Paper**: Anokhin & Semenov, "AriGraph: Learning Knowledge Graph World Models with Episodic Memory for LLM Agents" (Jul 2024, IJCAI 2025)
**Env**: Interactive text games (TextWorld, etc.)

**Architecture**:
- **Episodic memory**: At each timestep, a new vertex containing the full textual observation is added
- **Semantic memory**: LLM parses observations to extract relationship triplets `(object, relation, object)`, updating a knowledge graph
- **Episodic-semantic bridge**: Episodic edges link each episodic vertex to all triplets extracted from that observation

**Why this prevents noise**: The graph structure enforces relational consistency — contradictory triplets can be detected and resolved. Separating episodic (raw experience) from semantic (abstracted knowledge) means noise in individual observations doesn't directly corrupt the abstract model.

**Results**: Markedly outperforms other memory methods and strong RL baselines in complex partially-observable environments.

**Source**: [arxiv.org/abs/2407.04363](https://arxiv.org/abs/2407.04363), [GitHub](https://github.com/AIRI-Institute/AriGraph)

### 1.3 Voyager — Code as Memory (Skill Library)
**Paper**: Wang et al., "Voyager: An Open-Ended Embodied Agent with Large Language Models" (May 2023, NeurIPS 2023)
**Env**: Minecraft

**Architecture**: Three components:
1. **Automatic curriculum** — maximizes exploration
2. **Skill library** — executable JavaScript programs (Mineflayer APIs) stored with description embeddings
3. **Iterative prompting** — environment feedback + self-verification for program improvement

**Why code is low-noise**: Code is either executable or not — a binary validation mechanism. Faulty skills fail at runtime and are not added to the library. Skills are indexed by GPT-3.5-generated descriptions and retrieved via semantic similarity.

**Key insight**: Code naturally represents temporally extended, compositional actions. Skills compound — new skills reuse existing ones, mitigating catastrophic forgetting.

**Source**: [voyager.minedojo.org](https://voyager.minedojo.org/), [arxiv.org/abs/2305.16291](https://arxiv.org/abs/2305.16291), [GitHub](https://github.com/MineDojo/Voyager)

### 1.4 Claude Plays Pokemon — Knowledge Base Dictionary
**Project**: Anthropic's Claude Plays Pokemon (Feb 2025)
**Env**: Pokemon Red (Game Boy)

**Architecture**: A dictionary with sections:
- `current_status`
- `game_progress`
- `current_objectives`
- `inventory`

Each section editable via `update_knowledge_base --edit section`. Claude fully controls the knowledge base — can add and edit sections. Stored in-prompt as persistent context across summarization events.

**Prompt assembly**: `tool definitions + system instructions + knowledge_base contents + summarization info + conversation history`

**Summarization system**: When conversation exceeds turn limits:
1. Claude writes a detailed summary
2. Full conversation history is cleared
3. Summary becomes first assistant message in new conversation
4. A secondary LLM reviews the knowledge base for inconsistencies

**Problems observed**: Despite sophisticated memory, Claude struggled with:
- Prematurely declaring goals complete
- Forgetting recorded critical information
- Attempting to interact with already-defeated trainers

**Stats**: 200k context window, ~35,000 actions for 3 badges, ~140 hours of compute.

**Source**: [michaelyliu6.github.io/posts/claude-plays-pokemon](https://michaelyliu6.github.io/posts/claude-plays-pokemon/), [zenml.io](https://www.zenml.io/llmops-database/building-and-deploying-a-pokemon-playing-llm-agent-at-anthropic)

---

## 2. Memory Compaction and Summarization

### 2.1 Sliding Window / Observation Masking
**Paper**: JetBrains Research, "Cutting Through the Noise: Smarter Context Management for LLM-Powered Agents" (Dec 2025)

Compared three approaches:
1. **Raw agent** — unbounded context growth (baseline)
2. **Observation masking** — strips older environment observations while preserving reasoning/action history
3. **LLM summarization** — compresses all parts of turns via a separate summarizer LLM

**Key finding**: Observation masking with Qwen3-Coder 480B boosted solve rates by 2.6% while being 52% cheaper. LLM summarization caused agents to run ~15% longer with minimal benefit, and summary generation consumed >7% of total cost.

**Verdict**: "Simplicity often takes the prize for total efficiency and reliability."

**Source**: [blog.jetbrains.com/research/2025/12/efficient-context-management](https://blog.jetbrains.com/research/2025/12/efficient-context-management/)

### 2.2 Hierarchical Summarization — HiAgent
**Paper**: "HiAgent: Hierarchical Working Memory Management for Solving Long-Horizon Agent Tasks" (Aug 2024, ACL 2025)

**Mechanism**: LLM formulates subgoals before generating actions. When a subgoal is completed (or replaced), previous action-observation pairs are summarized, retaining only the current subgoal's pairs in full detail.

**Results**: 2x success rate, 3.8 fewer average steps across five long-horizon tasks.

**Key insight**: Subgoals are natural "chunking boundaries" for memory — they correspond to cognitively meaningful units, not arbitrary token counts.

**Source**: [arxiv.org/abs/2408.09559](https://arxiv.org/abs/2408.09559)

### 2.3 MemGPT — OS-Inspired Tiered Paging
**Paper**: Packer et al., "MemGPT: Towards LLMs as Operating Systems" (Oct 2023, evolved into Letta platform)

**Architecture** (OS memory hierarchy analogy):
- **Main context** (Tier 1, "RAM"): Core memories always in context
- **Recall storage** (Tier 2, "disk"): Searchable database for reconstruction via semantic search
- **Archival storage** (Tier 2, "cold"): Long-term vector-indexed storage

The LLM itself manages paging between tiers through function calls, deciding when to move information between context and storage.

**Source**: [arxiv.org/abs/2310.08560](https://arxiv.org/abs/2310.08560), [research.memgpt.ai](https://research.memgpt.ai/)

### 2.4 Importance-Based Retention with Decay Functions

**Generative Agents** (Park et al., 2023) — foundational retrieval scoring:
```
score = α_recency · recency + α_importance · importance + α_relevance · relevance
```
- Recency: exponential decay, factor 0.995 per hour
- Importance: LLM-rated (mundane vs core)
- Relevance: cosine similarity between memory embedding and query
- All normalized to [0,1] via min-max scaling

**FadeMem** (2025) — dual decay rates:
- Long-term memories: half-life ~11.25 days
- Short-term memories: half-life ~5.02 days
- Important information persists longer by design

**MemoryBank** (Zhong et al., 2024) — Ebbinghaus forgetting curve:
Linear scoring combining recency, relevance, importance. Memories decay without reinforcement, matching psychological models.

**Sources**: [dl.acm.org/doi/10.1145/3586183.3606763](https://dl.acm.org/doi/fullHtml/10.1145/3586183.3606763), [co-r-e.com/method/agent-memory-forgetting](https://www.co-r-e.com/method/agent-memory-forgetting)

### 2.5 Warning: Summarization Drift

The March 2026 survey (Memory for Autonomous LLM Agents) warns:
> After three summary cycles over a week of interactions, low-frequency, high-importance details like safety constraints may disappear entirely.

This "context rot" is **not a hypothetical failure mode** — it is documented in production systems. Aggressive compression must be balanced against detail loss.

**Source**: [arxiv.org/abs/2603.07670](https://arxiv.org/html/2603.07670)

---

## 3. Cross-Session Persistence

### 3.1 Anthropic's Multi-Session Agent Pattern
**Source**: Anthropic Engineering Blog (2025-2026)

**Two-agent architecture**:
1. **Initializer agent** — sets up environment, creates `init.sh`, generates `claude-progress.txt`, makes initial git commit
2. **Coding agent** — reads progress file + git history, makes incremental single-feature progress per session, leaves codebase in clean/mergeable state

**Key pattern**: `claude-progress.txt` serves as the bridge between sessions. Each session reads this + git log to reconstruct context without replaying full history. A feature list (JSON) tracks 200+ items as passing/failing.

**Analogy**: "A software project staffed by engineers working in shifts, where each new engineer arrives with no memory of what happened on the previous shift."

**Source**: [anthropic.com/engineering/effective-harnesses-for-long-running-agents](https://www.anthropic.com/engineering/effective-harnesses-for-long-running-agents)

### 3.2 WebCoach — Self-Evolving Cross-Session Memory
**System**: WebCoach (2025) — for web browsing agents

Components:
- **WebCondenser**: Standardizes navigation logs
- **External Memory Store**: Organizes episodic experiences
- **Coach**: Provides task-specific advice from memory

Improves long-term planning and continual learning without retraining.

### 3.3 What Transfers Well vs What Doesn't (Game Agents)

From the 2026 NetHack LLM agent study (kenforthewin.github.io):

**Transfers well**:
- API-driven movement/pathfinding abstractions
- Basic combat loops with conditionals
- Item identification patterns

**Does NOT transfer**:
- Spatial reasoning for hidden passages
- Long-term strategic planning (agents rush downward unprepared)
- Distinguishing dungeon branches (missed Gnomish Mines dangers)
- Food management (only prioritized reactively when already Hungry)

**Critical observation**: "Opus seemed to have much better map awareness during one-off conversations than during actual gameplay" — single-turn reasoning != sustained agent behavior.

**No cross-run learning implemented**: 37-140 runs measured aggregate statistics rather than improvement trajectories. No systematic mechanism for learning from permadeath.

**Source**: [kenforthewin.github.io/blog/posts/nethack-agent](https://kenforthewin.github.io/blog/posts/nethack-agent/)

### 3.4 Build-Specific vs Universal Knowledge Separation

No single paper addresses this directly, but the pattern emerges from multiple sources:

**Universal knowledge** (transfers across runs):
- Game mechanics (damage formulas, status effects, item properties)
- Enemy behaviors and weaknesses
- Map topology / area relationships
- Crafting recipes and skill trees
- Strategic principles ("always carry healing items", "don't fight X without Y")

**Build-specific knowledge** (does NOT transfer):
- Current inventory state
- Current character stats/build choices
- Current quest progress
- Specific NPC interactions in this run
- Explored/unexplored areas in this run

**Recommended separation**: CLIN's approach of extracting causal abstractions (universal) from trial-specific observations (build-specific) is the closest match. The meta-memory mechanism explicitly abstracts universal patterns from episode-specific details.

---

## 4. Memory Validation / Self-Correction

### 4.1 GLOVE — Environment-Grounded Memory Validation
**Paper**: "GLOVE: Global Verifier for LLM Memory-Environment Realignment" (Jan 2026)

**Three-phase mechanism**:
1. **Cognitive Dissonance Detection**: New observations contradict historical experiences for the same state-action pair
2. **Relative Truth Construction**: Re-executes the same action multiple times to sample current environment response distribution (no external oracle needed)
3. **Memory Realignment**: Removes obsolete experiences, inserts updated transition summaries

**Results**:
- WebShop (semantic drift): 0-20% → ~90% success
- FrozenLake (topological drift): +65% average over non-augmented agents
- MountainCar (dynamics drift): near-perfect maintenance
- Consistent across Llama, Qwen, GPT-4o, Grok-3, DeepSeek

**Theoretical guarantees**: Formal bounds on *when* to verify and *how much* interaction needed for reliable realignment.

**Source**: [arxiv.org/abs/2601.19249](https://arxiv.org/html/2601.19249)

### 4.2 A-MAC — Admission Control (Prevention over Correction)
**Paper**: "Adaptive Memory Admission Control for LLM Agents" (Mar 2026)

Five-factor scoring for whether to admit a memory:
1. **Utility (U)**: LLM-assessed future actionability
2. **Confidence (C)**: ROUGE-L matching against conversational evidence (combats hallucination)
3. **Novelty (N)**: Semantic distinctness from existing memories via embeddings
4. **Recency (R)**: Exponential decay, half-life ~69 hours
5. **Type Prior (T)**: Rule-based persistence by content type (preferences > transient states)

`Score = w1·U + w2·C + w3·N + w4·R + w5·T`, admit if Score >= threshold.

Conflict resolution: similarity > 0.85 with differing content → retain higher-scoring version.

**Results**: F1 0.583 on LoCoMo (+7.8% over A-MEM), 31% lower latency.

**Ablation**: Type Prior was the dominant factor (removing it → -0.107 F1).

**Source**: [arxiv.org/abs/2603.04549](https://arxiv.org/abs/2603.04549)

### 4.3 The Self-Reinforcing Error Problem

The March 2026 survey warns about reflective memory's central danger:
> False beliefs become entrenched through non-use of contradictory paths.

**Mitigations**:
- Reflection grounding: require citations to episodic evidence
- Contradiction detection: flag conflicts for resolution
- Confidence tracking: apply decay without confirming evidence
- GLOVE-style environmental verification

**Key warning**: This failure mode "scales with agent lifetime" — most dangerous in long-running deployments.

**Source**: [arxiv.org/abs/2603.07670](https://arxiv.org/html/2603.07670)

---

## 5. Structured vs Unstructured Memory

### 5.1 Empirical Evidence: Structured Wins

| System | Structure | Evidence |
|--------|-----------|----------|
| CLIN | Causal templates | -6pt drop when replaced with free-form |
| AriGraph | Knowledge graph (triplets) | Outperforms all unstructured baselines |
| A-MEM | Zettelkasten (7-field notes) | 2x on multi-hop reasoning vs unstructured |
| Voyager | Executable code | Binary pass/fail validation |

### 5.2 A-MEM's Zettelkasten Structure (NeurIPS 2025)

Each memory note has 7 fields:
1. **Content (c_i)**: Original interaction data
2. **Timestamp (t_i)**: When interaction occurred
3. **Keywords (K_i)**: LLM-generated key concepts
4. **Tags (G_i)**: Categorical labels
5. **Contextual Description (X_i)**: LLM-generated rich semantic context
6. **Embedding (e_i)**: Dense vector via text encoder
7. **Links (L_i)**: Connections to related memories

Link generation: two-stage (cosine similarity candidates → LLM analysis for semantic relationships). New memories can trigger updates to existing memories' keywords/tags/context.

**Source**: [arxiv.org/abs/2502.12110](https://arxiv.org/abs/2502.12110), [GitHub](https://github.com/WujiangXu/A-mem)

### 5.3 Optimal Structure for Game Agents

Based on converging evidence, the optimal structure for game agents combines:

1. **Causal abstractions** (CLIN-style) for game mechanics: `"action X IS NECESSARY to achieve Y"`, `"enemy Z IS WEAK to W"`
2. **Knowledge graph** (AriGraph-style) for world model: entity-relation-entity triplets tracking locations, items, NPCs
3. **Skill library** (Voyager-style) for reusable action sequences: executable plans with pre/post conditions
4. **Structured notes** (Claude Pokemon-style) for current session state: dictionary of objectives, inventory, progress

The separation between semantic (graph), episodic (experience logs), and procedural (skills/plans) memory maps well to game agent needs.

### 5.4 Sculptor — Active Context Management (ICLR 2026)

**Paper**: Li et al., "Sculptor: Empowering LLMs with Cognitive Agency via Active Context Management" (Aug 2025, ICLR 2026)

Rather than external memory, gives LLMs tools to actively manage their own context:
1. **Context fragmentation** — break context into manageable pieces
2. **Summary, hide, and restore** — compress/hide irrelevant parts, restore when needed
3. **Precise search** — find specific information within context

Trained via dynamic context-aware reinforcement learning. The LLM learns to sculpt its own working memory.

**Source**: [arxiv.org/abs/2508.04664](https://arxiv.org/abs/2508.04664)

---

## 6. Context Window Management for Long-Running Agents

### 6.1 Anthropic's Context Engineering Principles

**Core definition**: "The set of strategies for curating and maintaining the optimal set of tokens during LLM inference."

**Three primary techniques**:
1. **Compaction** — summarize conversation history at context limits, restart with compressed summary
2. **Structured note-taking** — persistent memory outside context (CLAUDE.md, progress files)
3. **Sub-agent architectures** — specialized agents with clean context windows return condensed summaries

**Just-in-time context**: Maintain lightweight references (file paths, URLs), dynamically load data at runtime. Never load everything upfront.

**Key quote**: "Find the smallest set of high-signal tokens that maximize the likelihood of your desired outcome."

**Source**: [anthropic.com/engineering/effective-context-engineering-for-ai-agents](https://www.anthropic.com/engineering/effective-context-engineering-for-ai-agents)

### 6.2 The 1M Token Wall

From morphllm.com analysis: Models hit a clear performance ceiling around 1M tokens regardless of window size. Claude Code uses 5.5x fewer tokens than alternatives for equivalent tasks. Just-in-time loading can eliminate 95% of unnecessary context. Practical cost difference: ~$4.80 vs ~$0.35 (14x) for the same task.

**Source**: [morphllm.com/context-engineering](https://www.morphllm.com/context-engineering)

### 6.3 LangChain's Context Engineering Framework

Four strategies (Write/Select/Compress/Isolate):
- **Write**: Save to scratchpads, files, state objects
- **Select**: Retrieve via embeddings, knowledge graphs, or file lookup
- **Compress**: Summarize trajectories, trim messages, prune irrelevant content
- **Isolate**: Split context across multi-agent systems or sandboxed environments

**Warning for long-running agents**: Context poisoning (hallucinations entering context), distraction (irrelevant information), confusion (superfluous details), and clash (conflicting context).

**Source**: [blog.langchain.com/context-engineering-for-agents](https://blog.langchain.com/context-engineering-for-agents/)

### 6.4 Practical Pattern: NetHack Agent's Approach

From kenforthewin.github.io (2026):
- Previous turn maps completely stripped
- Tool call arguments compressed to `<compacted>` after 10 turns
- Sliding window: messages dropped after 100 turns
- All parameters configurable

This aggressive masking prioritized token efficiency while minimizing context noise.

**Source**: [kenforthewin.github.io/blog/posts/nethack-agent](https://kenforthewin.github.io/blog/posts/nethack-agent/)

---

## 7. Anthropic's "Context Engineering" Insights

### 7.1 From Claude Plays Pokemon

The Pokemon agent demonstrated structured note-taking in action:
- Maintained "precise tallies across thousands of game steps"
- Tracked objectives and developed strategic notes about effective combat
- Did this without explicit memory prompting — emergent behavior
- Opus 4 created a "Navigation Guide" autonomously while playing

**Lesson**: Given file access, Claude naturally creates and maintains memory files for long-term task awareness.

### 7.2 Claude Code Memory Architecture

Two complementary systems:
1. **CLAUDE.md** — human-written persistent instructions (build commands, coding standards, architectural decisions)
2. **MEMORY.md** — auto-generated notes Claude writes itself (debugging patterns, project context, workflow preferences)

Both loaded at start of every conversation. Simple Markdown files in hierarchical structure. No vector databases or semantic search — deliberate simplicity.

### 7.3 Memory Tool API (Sep 2025)

Client-side tool for Claude API agents:
- Agent makes tool calls for memory CRUD operations
- Application executes locally (developer controls storage)
- Designed for cross-conversation persistence

### 7.4 Multi-Session SDK (2026)

Anthropic's Agent SDK for long-running tasks:
- `CLAUDE_CODE_TASK_LIST_ID` environment variable for multi-instance coordination
- Two-agent harness (initializer + worker)
- Progress files + git history as session bridges

**Sources**: [anthropic.com/engineering/effective-context-engineering-for-ai-agents](https://www.anthropic.com/engineering/effective-context-engineering-for-ai-agents), [anthropic.com/engineering/effective-harnesses-for-long-running-agents](https://www.anthropic.com/engineering/effective-harnesses-for-long-running-agents), [code.claude.com/docs/en/memory](https://code.claude.com/docs/en/memory)

---

## 8. Additional Systems Worth Noting

### 8.1 MemOS — Memory Operating System (2025)
Three-layer architecture (Interface / Operation / Infrastructure) treating memory as a first-class operational resource. Introduces MemCube abstraction unifying plaintext, activation, and parameter memories. Asynchronous ingestion with millisecond latency.

**Source**: [arxiv.org/abs/2507.03724](https://arxiv.org/abs/2507.03724), [GitHub](https://github.com/MemTensor/MemOS)

### 8.2 Comprehensive Surveys
- **"Memory for Autonomous LLM Agents: Mechanisms, Evaluation, and Emerging Frontiers"** (Mar 2026) — the most comprehensive and recent survey. [arxiv.org/abs/2603.07670](https://arxiv.org/abs/2603.07670)
- **"A Survey on the Memory Mechanism of Large Language Model-based Agents"** (ACM TOIS, 2025). [dl.acm.org/doi/10.1145/3748302](https://dl.acm.org/doi/10.1145/3748302)
- **Paper list**: [github.com/Shichun-Liu/Agent-Memory-Paper-List](https://github.com/Shichun-Liu/Agent-Memory-Paper-List)

---

## 9. Synthesis: Recommendations for a Roguelike Game Agent

Based on this research, a memory architecture for a roguelike/permadeath game agent should:

### Memory Structure (Hybrid)
1. **Causal abstractions** (CLIN-style) for game mechanics — structured templates prevent noise
2. **Knowledge graph** for world model — entity-relation triplets for items, enemies, locations
3. **Skill/plan library** for reusable strategies — with pre/post conditions and success tracking
4. **Session state dictionary** (Claude Pokemon-style) for current run tracking

### Cross-Run Persistence
- Separate **universal memory** (game mechanics, enemy data, strategies) from **run-specific memory** (current inventory, map state, quest progress)
- Universal memory persists across runs; run-specific is discarded at death
- Use CLIN's meta-memory approach: extract causal abstractions from run-specific observations
- Track confidence: memories that hold across multiple runs gain confidence; contradicted memories decay

### Memory Validation
- GLOVE-style environmental verification for critical beliefs (test assumptions when possible)
- A-MAC-style admission control (filter before storing, not just after)
- Confidence decay for unverified memories
- Contradiction detection between new observations and stored beliefs

### Context Management
- Observation masking (strip old maps/observations, keep reasoning history)
- Subgoal-based summarization (HiAgent-style chunking at meaningful boundaries)
- Just-in-time retrieval of universal memory (don't load everything)
- Sub-agents for specialized tasks (combat, exploration, inventory management)

### What to Avoid
- Free-form unstructured memory (noise accumulation is empirically proven)
- Unbounded context growth (performance degrades, costs increase 14x)
- LLM summarization as primary compaction (15% longer runs, 7%+ cost overhead vs masking)
- Trusting reflective memory without environmental grounding (self-reinforcing errors scale with lifetime)
