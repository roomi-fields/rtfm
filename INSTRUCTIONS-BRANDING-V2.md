# RTFM — Instructions v2 : Repositionnement "Open Retrieval Layer"

## Contexte stratégique

RTFM évolue de "projet intelligence pour Claude Code" vers un positionnement plus ambitieux et défendable :

**RTFM est le retrieval layer ouvert et extensible pour agents AI.**

Deux concurrents existent déjà sur le retrieval de code :
- **Augment Code** — Context Engine propriétaire, fermé, payant (enterprise SaaS). Indexe du code. Vient de scorer #1 sur SWE-bench Pro grâce à son retrieval.
- **Sourcegraph** — Recherche de code enterprise, lance un MCP. Payant, fermé.

Ces deux-là prouvent que le retrieval est le facteur différenciant pour les agents AI (Augment : même modèle, meilleurs résultats juste grâce au retrieval). Mais ils sont :
1. Fermés (propriétaires)
2. Limités au code
3. Chers (enterprise pricing)

**RTFM est l'alternative open source, multi-domaine, extensible.** N'importe qui peut écrire un parser en 50 lignes de Python pour n'importe quel format. C'est le modèle VS Code (extensions ouvertes) vs IDE propriétaire.

## Nouveau positionnement

### Tagline principale
"RTFM — The open retrieval layer for AI agents."

### Sous-tagline
"Because your AI doesn't read the docs either."

### One-liner pour les annuaires MCP, bio GitHub, etc.
"Open-source retrieval layer for AI coding agents. Indexes code, docs, legal, research, data — any format. Extensible parser system. Serves surgical context via MCP. Works with Claude Code, and alongside GSD, Taskmaster, or any workflow tool."

### Le pitch fondamental
Augment et Sourcegraph ont prouvé que le retrieval change tout — même modèle, meilleurs résultats. Mais leur retrieval est fermé et limité au code. RTFM c'est le retrieval ouvert : n'importe quel format, n'importe quel domaine, extensible par la communauté, gratuit.

### Métaphore clé
"Augment indexes your code. RTFM indexes everything — and anyone can teach it a new format in 50 lines of Python."

---

## Tâche 1 : Réécrire README.md

Réécrire le README avec cette structure exacte. Le ton est direct, technique, provocateur. Pas de bullshit marketing. Chaque section doit être concise.

### Structure cible

```markdown
# RTFM — Read The Fucking Manual

> The open retrieval layer for AI agents.

<!-- TODO: [GIF DEMO — 15 seconds showing rtfm discover + rtfm context] -->

## Why retrieval matters

Augment Code just proved it: same model (Claude Opus 4.5), same benchmark (SWE-bench Pro), **6 points higher** — just because of better context retrieval. Not a better model. Better retrieval.

Your AI coding agent is blind. It greps randomly through your project, loses context every session, hallucinates modules that don't exist. The fix isn't a smarter model — it's smarter retrieval.

**The problem with existing retrieval:**

| | Augment | Sourcegraph | RTFM |
|---|---|---|---|
| Code indexing | ✅ | ✅ | ✅ |
| Docs, specs, markdown | ❌ | ❌ | ✅ |
| Legal / regulatory | ❌ | ❌ | ✅ |
| Research (LaTeX, PDF) | ❌ | ❌ | ✅ |
| Custom formats | ❌ | ❌ | ✅ (50 lines) |
| Open source | ❌ | Partial | ✅ MIT |
| Self-hosted | ❌ | ✅ | ✅ |
| MCP native | Coming soon | Coming soon | ✅ Now |
| Install time | Enterprise onboarding | Enterprise onboarding | 30 seconds |
| Price | $$$/month | $$$/month | Free |

RTFM is the open alternative. Any format, any domain, extensible by anyone.

## What it does

RTFM indexes your entire project — code, docs, specs, legal texts, research papers, data — and serves your AI agent exactly the context it needs, when it needs it.

```bash
cd your-project
pip install -e ".[mcp]" && rtfm init
```

That's it. Claude Code now searches RTFM before grepping.

| Metric | Without RTFM | With RTFM | Improvement |
|-----|------|------|------|
| Tokens per task | ~45K | ~8K | -82% |
| Context setup time | ~10 min | 0 sec | -100% |
| Hallucination rate | ~35% | ~5% | -86% |
| Cross-domain answers | Never | Always | ∞ |

*Internal benchmarks on a 4GB multi-domain project. Your mileage may vary.*

## The plugin architecture

This is what makes RTFM different from everything else.

Need to index a format nobody supports? Write a parser:

```python
from rtfm.parsers.base import BaseParser, ParserRegistry
from rtfm.core.models import Chunk

@ParserRegistry.register
class FHIRParser(BaseParser):
    """Parse HL7 FHIR medical records."""
    extensions = ['.fhir.json']
    name = "fhir"

    def parse(self, path, metadata=None):
        data = json.loads(path.read_text())
        for entry in data.get('entry', []):
            resource = entry.get('resource', {})
            yield Chunk(
                id=resource.get('id', str(uuid4())),
                content=json.dumps(resource, indent=2),
                book_title=f"FHIR {resource.get('resourceType', 'Unknown')}",
                book_slug=resource.get('id', 'unknown'),
                page_start=1,
                page_end=1,
            )
```

50 lines. Now your medical AI agent understands FHIR records.

RTFM ships with 10 parsers out of the box:

[GARDER LE TABLEAU DES PARSERS EXISTANT DANS LE README ACTUEL — Markdown, Python AST, LaTeX, YAML, JSON, Shell, PDF, Legifrance XML, BOFiP HTML, Plain text]

But the real power is that **you can add any format**. Financial data (XBRL), CAD files (STEP), music scores (MusicXML), genomics (VCF), architecture docs (AsciiDoc) — whatever your project needs.

## Works with your workflow tools

RTFM isn't a task manager. It's a knowledge layer.

| Tool | Role | Analogy |
|------|------|---------|
| GSD / Taskmaster / Claude Flow | Orchestrate WHAT to do | The GPS |
| **RTFM** | **Provide WHAT the agent needs to know** | **The map** |
| Claude Code | Execute the work | The engine |

Without RTFM, your workflow tool orchestrates an agent that hallucinates.
With RTFM, your agent knows what it's building on.

Use both. They're complementary.

```
┌─────────────────────────────────┐
│  GSD / Taskmaster / Claude Flow │  ← Workflow
├─────────────────────────────────┤
│           RTFM                  │  ← Knowledge
├─────────────────────────────────┤
│        Claude Code              │  ← Execution
└─────────────────────────────────┘
```

## Quick Start

### Install

```bash
pip install -e ".[mcp]"
```

### Initialize

```bash
cd /path/to/your-project
rtfm init
```

[GARDER LA DESCRIPTION DE CE QUE FAIT rtfm init — .rtfm/library.db, .mcp.json, CLAUDE.md, hooks, .gitignore]

### MCP Tools

[GARDER LE TABLEAU DES MCP TOOLS]

### Key tools

[GARDER rtfm_context et rtfm_discover avec exemples]

## CLI Reference

[GARDER TOUTE LA SECTION CLI DU README ACTUEL — search, semantic-search, sync, etc.]

## Python API

[GARDER TOUTE LA SECTION API DU README ACTUEL — Library, SearchResults, tags, versioning]

## Architecture

[GARDER LE TREE]

## Use cases

RTFM works anywhere your project isn't just code:

- **LegalTech / RegTech** — Code + tax law articles + regulatory specs. RTFM ships with Legifrance XML and BOFiP parsers.
- **HealthTech** — Code + medical records (HL7/FHIR) + clinical guidelines. Write a FHIR parser in 50 lines.
- **Academic research** — Code + LaTeX papers + datasets + methodology docs. RTFM ships with LaTeX parser.
- **FinTech** — Code + financial regulations + XBRL reports. Write an XBRL parser.
- **Defense / Aerospace** — Code + technical specs + compliance docs. Fully self-hosted, no cloud dependency.
- **Any regulated industry** — If your project mixes code with domain-specific documents, RTFM is for you.

## Contributing

See [CONTRIBUTING.md](CONTRIBUTING.md). Adding a parser is the easiest way to contribute — and the most impactful.

## License

MIT — use it, fork it, extend it, ship it.
```

### Notes importantes pour le README :
- La section "Why retrieval matters" avec la référence à Augment est CRITIQUE — c'est ce qui donne de la crédibilité. On cite un résultat factuel (Augment SWE-bench Pro) pour prouver que le retrieval compte, puis on montre que RTFM est l'alternative ouverte.
- Le tableau comparatif Augment/Sourcegraph/RTFM doit être factuel et honnête. Ne pas mentir. Si un concurrent fait quelque chose bien, le dire.
- L'exemple de parser FHIR est illustratif — il montre le CONCEPT (50 lignes pour un nouveau format) avec un cas réel (medical). Ne pas prétendre que le parser FHIR existe déjà dans RTFM.
- La section "Use cases" est nouvelle et importante — elle montre l'étendue du marché.
- Retirer le "npx rtfm init — coming soon" qui faisait cheap. Garder `pip install -e ".[mcp]" && rtfm init`.

---

## Tâche 2 : Mettre à jour pyproject.toml

```toml
[project]
description = "RTFM — The open retrieval layer for AI agents. Indexes code, docs, legal, research, data. Extensible parser system. Serves surgical context via MCP."
keywords = [
    "mcp", "claude-code", "retrieval", "context", "rag",
    "search", "indexing", "fts5", "sqlite", "embeddings",
    "ai-agent", "knowledge-base", "developer-tools",
    "open-source", "extensible", "multi-domain"
]
```

Ne modifier QUE description et keywords. Garder tout le reste identique.

---

## Tâche 3 : Mettre à jour CLAUDE.md

Remplacer la section "What is RTFM?" :

```markdown
## What is RTFM?

The open retrieval layer for AI coding agents. Indexes entire projects (code, docs, legal, research, data) and serves surgical context via MCP.

Key differentiator: extensible parser architecture. Anyone can add support for any file format in ~50 lines of Python. Ships with 10 parsers, but the community can add any format.

Not a task manager — a knowledge layer that complements GSD, Taskmaster, Claude Flow, and any workflow tool.

## Positioning

- Augment Context Engine / Sourcegraph = closed, code-only, enterprise pricing
- RTFM = open source, multi-domain, extensible, free
- "Augment indexes your code. RTFM indexes everything."
- Works WITH workflow tools (GSD = GPS, RTFM = map)
```

Garder tout le reste du CLAUDE.md actuel (architecture, commands, design principles).

---

## Tâche 4 : Mettre à jour CONTRIBUTING.md

Ajouter cette section EN HAUT du fichier existant, juste après le titre :

```markdown
## The easiest way to contribute: write a parser

RTFM's real power comes from its parser ecosystem. If you work in a domain with specific file formats — medical (HL7/FHIR), financial (XBRL), scientific (NetCDF), music (MusicXML), architecture (AsciiDoc), or anything else — writing a parser is the most impactful contribution you can make.

A parser is typically 30-80 lines of Python. See `rtfm/parsers/markdown.py` for the simplest example.

### Parser template

```python
from rtfm.parsers.base import BaseParser, ParserRegistry
from rtfm.core.models import Chunk

@ParserRegistry.register
class MyFormatParser(BaseParser):
    extensions = ['.myext']
    name = "myformat"

    def parse(self, path, metadata=None):
        metadata = metadata or {}
        content = path.read_text()
        # Your parsing logic here
        yield Chunk(
            id="unique-chunk-id",
            content=content,
            book_title=metadata.get('title', path.stem),
            book_slug=path.stem.lower(),
            page_start=1,
            page_end=1,
        )
```

Submit a PR with your parser + tests, and your domain's AI agents get superpowers.
```

Garder le reste du CONTRIBUTING.md existant.

---

## Tâche 5 : NE PAS toucher

- `CHANGELOG.md` — déjà OK
- `.gitignore` — déjà OK
- `LICENSE` — déjà OK
- Tout le code source dans `rtfm/`
- Les tests dans `tests/`

---

## Récapitulatif

| Fichier | Action | Criticité |
|---------|--------|-----------|
| `README.md` | Réécriture majeure — nouveau positionnement | 🔴 Haute |
| `pyproject.toml` | Mise à jour description + keywords uniquement | 🟡 Moyenne |
| `CLAUDE.md` | Mise à jour section positioning | 🟡 Moyenne |
| `CONTRIBUTING.md` | Ajout section parsers en haut | 🟢 Basse |

## Ton et style

- Direct, technique, pas de fluff
- Provocateur mais factuel — citer Augment/Sourcegraph avec des faits vérifiables
- Le tableau comparatif doit être honnête : si un concurrent fait bien quelque chose, le dire
- Assumer le nom RTFM — c'est le brand, pas s'en excuser
- Parler à des devs qui souffrent, pas à des managers qui achètent
- L'extensibilité (parser en 50 lignes) est le message central, le marteler
