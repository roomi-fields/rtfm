# SOTA 8 — Competitive Landscape: Who Is Already Doing What?

## Executive summary

**Pre-indexing a codebase and exposing search via MCP is no longer novel in 2026.** Augment does it (paid), and several open-source tools do as well (Code-Index-MCP, mcp-codebase-index). The contribution therefore CANNOT be "we propose an MCP retrieval tool."

What remains differentiating: **multi-domain**, **extensible parsers**, and the **metadata-first pattern**. But above all, the paper's angle must not be the tool — it must be the **empirical thesis**: giving an agent the ability to search improves its performance on large repos.

---

## 1. Direct Competitors (MCP + indexing)

### 1.1 Augment Context Engine MCP — The most serious
- **What:** Proprietary semantic context engine exposed via MCP (Feb 2026)
- **Indexes:** Code + documentation + tickets + internal wikis + commit history
- **MCP:** Yes, `codebase-retrieval` tool. Local (Auggie CLI) and remote modes
- **Open source:** No. Only the MCP wrapper is open source
- **Claude Code:** Yes
- **Pricing:** $20-200/mo. 40-70 credits/request. 1000 free requests in Feb 2026
- **Claimed benchmark:** +80% perf with Claude Code + Opus 4.5, +71% with Cursor
- **vs. RTFM:** Multi-domain but proprietary, cloud-first, paid, not community-extensible
- **URLs:**
  - https://www.augmentcode.com/blog/context-engine-mcp-now-live
  - https://docs.augmentcode.com/context-services/mcp/overview
  - https://www.augmentcode.com/pricing

### 1.2 Sourcegraph Cody MCP
- **What:** Sourcegraph code search engine exposed via MCP (GA with OAuth)
- **Indexes:** Code only (multi-repo, cross-organization)
- **MCP tools:** `keyword_search`, `nls_search` (semantic), `go_to_definition`, `find_references`, `commit_search`, `diff_search`, `deepsearch`, `read_file`, `list_repos`
- **Open source:** Open-core. MCP = Enterprise-only
- **Claude Code:** Yes
- **Pricing:** Enterprise ($49+/user/month)
- **vs. RTFM:** Infinitely more powerful on code at scale. But code-only, enterprise-only.
- **URLs:**
  - https://sourcegraph.com/docs/api/mcp
  - https://sourcegraph.com/blog/cody-supports-anthropic-model-context-protocol

### 1.3 Greptile
- **What:** Cloud codebase analysis API + MCP server
- **Indexes:** Code (dependency graph, git history, PRs, code reviews). Also Jira/Docs/Notion via MCP
- **Open source:** No. SaaS (YC, $180M valuation)
- **Claude Code:** Yes via MCP
- **Pricing:** $30/dev/month. API: $0.15/unit
- **vs. RTFM:** Code-review focused, cloud-only, paid
- **URLs:**
  - https://www.greptile.com/docs/mcp/overview
  - https://www.greptile.com/pricing

---

## 2. IDEs with Built-in Indexing (no MCP)

### 2.1 Cursor
- **Indexes:** Code (syntactic chunking, Turbopuffer embeddings, Merkle tree for cache)
- **MCP:** No — IDE-integrated only
- **Open source:** No
- **Claude Code:** Not compatible (competing IDE)
- **Pricing:** $20/mo
- **vs. RTFM:** Similar approach but closed within the IDE. Not accessible to external agents.
- **URLs:**
  - https://cursor.com/docs/context/codebase-indexing

### 2.2 Windsurf (Codeium)
- **Indexes:** Code (background indexing)
- **MCP:** No — integrated into Cascade only
- **Open source:** No
- **vs. RTFM:** Closed within the IDE. Code only.

---

## 3. Open Source MCP Tools for Code Indexing

### 3.1 Code-Index-MCP (johnhuang316) — 793 stars
- **Indexes:** Code (50+ types, 7 languages with tree-sitter AST, regex fallback)
- **MCP:** Yes (`search_code_advanced`, `get_file_summary`)
- **Open source:** Yes
- **Claude Code:** Yes
- **vs. RTFM:** More popular but purely code. No docs, legal, research. No hash-based incremental sync.
- **URL:** https://github.com/johnhuang316/code-index-mcp

### 3.2 Code-Index-MCP (ViperJuice) — 38 stars
- **Indexes:** Code (48 tree-sitter languages) + Markdown/JSON/YAML/XML
- **Search:** FTS5 (SQLite) + optional semantic (Voyage AI) + hybrid
- **Open source:** Yes
- **Claude Code:** Yes
- **vs. RTFM:** **The closest architecturally** — same SQLite+FTS5 stack. But code-first, docs secondary. No extensible parsers. No multi-corpus. No metadata-then-expand.
- **URL:** https://github.com/ViperJuice/Code-Index-MCP

### 3.3 mcp-codebase-index (PyPI) — v0.5.0
- **Indexes:** Code (Python AST, regex for TS/JS/Go/Rust). Zero dependencies
- **MCP:** Yes (18 tools: functions, classes, imports, dependency graph)
- **Technique:** Incremental via `git diff`, pickle cache, instant startup if HEAD unchanged
- **vs. RTFM:** Very efficient for code. Zero deps. But code only, not extensible.
- **URL:** https://pypi.org/project/mcp-codebase-index/

### 3.4 CodeCompass (Navigation Paradox paper)
- **Indexes:** Python code only (AST graph → Neo4j)
- **MCP:** Yes (`get_architectural_context`, `semantic_search`)
- **Open source:** Yes
- **vs. RTFM:** Structural navigation (dependency graph), not text search. Complementary, not a competitor.
- **URL:** https://github.com/TheAlchemist6/codecompass-mcp

---

## 4. Complementary Tools (not competitors)

### 4.1 Aider Repo Map
- **What:** Repo map via tree-sitter + PageRank, passively injected into the prompt
- **MCP:** Not native (third-party MCP wrapper exists)
- **vs. RTFM:** Static injection, no interactive search. The agent cannot query.
- **URL:** https://aider.chat/docs/repomap.html

### 4.2 Continue.dev
- **What:** Open-source IDE extension, MCP **client** (consumes MCP servers)
- **vs. RTFM:** Complementary — Continue could use RTFM as a context provider.
- **URL:** https://docs.continue.dev/customize/deep-dives/mcp

### 4.3 Context7
- **What:** MCP server serving docs for 500+ external libraries (React, Next.js, etc.)
- **vs. RTFM:** Complementary — Context7 serves third-party library docs, RTFM serves project content.
- **URL:** https://github.com/upstash/context7

### 4.4 Bloop
- **What:** Rust-based code search engine, desktop app
- **MCP:** No
- **vs. RTFM:** No exposure to agents. Appears to have pivoted.
- **URL:** https://github.com/BloopAI/bloop

---

## 5. Comparison Matrix

| Tool | Indexes | MCP | OSS | Claude Code | Multi-domain | Extensible parsers | Pricing |
|---|---|---|---|---|---|---|---|
| **RTFM** | Code+docs+legal+research | Yes | Yes | Yes | **Yes** | **Yes** | Free |
| Augment CE | Code+docs+tickets+wikis | Yes | No | Yes | Partially | No | $20-200/mo |
| Sourcegraph | Code (multi-repo) | Yes | Enterprise | Yes | No | No | $$$/mo |
| Greptile | Code+PRs+reviews | Yes | No | Yes | No | No | $30/dev/mo |
| Cursor | Code | No (IDE) | No | No | No | No | $20/mo |
| Windsurf | Code | No (IDE) | No | No | No | No | $15-60/mo |
| Code-Index (JH) | Code (50+ types) | Yes | Yes | Yes | No | No | Free |
| Code-Index (VJ) | Code+MD/YAML | Yes | Yes | Yes | Limited | No | Free |
| mcp-codebase-index | Code (Py/TS/Go) | Yes | Yes | Yes | No | No | Free |
| CodeCompass | Python code (graph) | Yes | Yes | Yes | No | No | Free |
| Aider Map | Code (symbols) | Not native | Yes | Not native | No | No | Free |
| Context7 | Third-party lib docs | Yes | Yes | Yes | No | No | Free |

---

## 6. Conclusion: Implications for the Paper

### What is NOT novel (do not claim):
- Pre-indexing a codebase and exposing it via MCP
- FTS5 + SQLite for indexing
- Semantic search via embeddings
- Incremental sync

### What remains differentiating for RTFM (but not the subject of the paper):
- Multi-domain (the only OSS to index code + docs + legal + research)
- Extensible parser architecture (~50 lines)
- Metadata-search-then-expand pattern
- Multi-corpus / multi-source
- Zero-dependency core

### The real angle of the paper:
**Not the tool. The empirical thesis.** None of these tools has published a controlled study showing the measurable impact of pre-indexed retrieval on a coding agent's performance (resolve rate, cost, duration) on a standardized benchmark (FeatureBench).

Augment claims "+80%" without a published protocol. Sourcegraph has no public benchmark. Open-source MCPs have no evaluation. The RTFM paper would be the **first to empirically measure, on FeatureBench, the impact of giving a coding agent a retrieval tool** — under controlled conditions (4 configs, same tasks, same model).

---

## References

1. Augment Code (2026). Context Engine MCP. https://www.augmentcode.com/blog/context-engine-mcp-now-live
2. Sourcegraph (2025). Cody MCP Integration. https://sourcegraph.com/docs/api/mcp
3. Greptile (2026). MCP Overview. https://www.greptile.com/docs/mcp/overview
4. Cursor (2025). Codebase Indexing. https://cursor.com/docs/context/codebase-indexing
5. johnhuang316. Code-Index-MCP. https://github.com/johnhuang316/code-index-mcp
6. ViperJuice. Code-Index-MCP. https://github.com/ViperJuice/Code-Index-MCP
7. mcp-codebase-index. https://pypi.org/project/mcp-codebase-index/
8. Navigation Paradox (2026). CodeCompass. arXiv:2602.20048.
9. Aider (2023). Repo Map. https://aider.chat/docs/repomap.html
10. Continue.dev. MCP Integration. https://docs.continue.dev/customize/deep-dives/mcp
11. Context7. https://github.com/upstash/context7
