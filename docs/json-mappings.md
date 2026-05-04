# JSON Schema Mappings

RTFM lets you declaratively map *any* JSON schema to chunks and edges via
small YAML files. Drop a mapping into `.rtfm/mappings/`, RTFM reads it at sync
time, and matching JSON files in your project are extracted into typed chunks
without writing a single line of Python.

This is how RTFM stays generic: instead of shipping format-specific parsers
for every JSON-based tool out there (NotebookLM exports, Linear exports,
Notion dumps, OpenAPI specs, structured logs…), the project that produces the
format ships its own mapping. Anyone can add support for any JSON schema in
~30 lines of YAML.

## Quick example

A NotebookLM batch export `answer.json`:

```json
{
  "type": "nblm-answer",
  "asked_at": "2026-05-04T13:30:00Z",
  "notebook": { "id": "n-1", "url": "https://notebooklm.google.com/..." },
  "question": "What is the OSBD process?",
  "answer": { "text": "OSBD is the four-step acronym at the core of CNV..." },
  "citations": [
    { "marker": "[1]", "source_name": "Keller.pdf", "source_text": "Observation neutre..." },
    { "marker": "[2]", "source_name": "Rosenberg.pdf", "source_text": "..." }
  ]
}
```

The matching mapping at `.rtfm/mappings/nblm-answer.yaml`:

```yaml
name: nblm-answer-v1

match:
  schema_url: "https://schemas.roomi-fields.com/nblm-answer-v1.json"
  discriminator:
    type: nblm-answer

chunks:
  - title: "Q: {{ question }}"
    content: "{{ answer.text }}"
    metadata:
      notebook_id: "{{ notebook.id }}"
      asked_at: "{{ asked_at }}"

  - foreach: citations
    title: "{{ marker }} {{ source_name }}"
    content: "{{ source_text }}"
    metadata:
      source_name: "{{ source_name }}"
      citation_marker: "{{ marker }}"

edges:
  - relation: cites
    foreach: citations
    target: "{{ source_name }}"
```

After `rtfm sync`, the JSON file produces:

- 1 chunk for the answer body, retrievable by question keywords or answer text
- N chunks for citations, each independently retrievable by source name or
  excerpt content
- Typed metadata in `chunks.metadata` (notebook_id, source_name, marker…)
- `cites` edge candidates per citation

## Mapping reference

### Top-level fields

```yaml
name: my-mapping            # required, unique per project
match: { ... }              # required, see "Match rules"
chunks: [ ... ]             # at least one required
edges: [ ... ]              # optional
```

### Match rules

A mapping is applied to a JSON document when **any** declared rule matches.

| Field | Description |
|---|---|
| `match.schema_url` | Matches the document's `$schema` or `$id` field |
| `match.discriminator` | Dict of `{ field_path: expected_value }` — all entries must match |

Discriminator paths support dotted notation (`meta.kind: foo` walks into
nested objects).

### Chunk specs

```yaml
chunks:
  - title: "..."          # template, becomes chapter_title
    content: "..."        # template, becomes chunk content (required, non-empty)
    foreach: <path>       # optional — emit one chunk per item in the list at <path>
    metadata: { ... }     # template values, stored in chunks.metadata
```

When `foreach` is set, templates inside the spec evaluate against each
**item** of the list. Otherwise they evaluate against the **root** document.

### Edge specs

```yaml
edges:
  - relation: cites       # stored as edges.relation_type
    foreach: <path>       # optional, like chunks
    target: "..."         # template producing the target reference
    target_kind: literal  # informational hint: literal | slug | url
```

Edge resolution to the database happens in the sync layer. Edges with
relation types `import` / `link` / `include` are resolved against indexed
files. **Custom relation types** (e.g. `cites`) currently land as
`EdgeCandidate`s but are not yet materialized in the `edges` table — index
the cited sources alongside the JSON file if you want a navigable graph.

## Templating

Template expressions use `{{ dotted.path.to.field }}` syntax. Rules:

- `{{ a.b.c }}` walks nested dicts/lists (numeric segments index lists)
- Missing paths render as empty strings
- No control flow, no expressions, no eval — paths only

Anything more sophisticated is intentionally out of scope. If your schema
needs computation, write a Python parser instead.

## Discovery

RTFM scans `.rtfm/mappings/` (next to your library DB) at every `Library`
initialization. Drop `.yaml`, `.yml`, or `.json` files there. Subdirectories
are not scanned.

Malformed mapping files are silently skipped (log entry pending) — a bad
mapping never breaks sync.

## How matches are dispatched

When the JSON parser encounters a `.json` file:

1. Parse to a Python dict
2. Ask `MappingRegistry.find_mapping(data)` — first match wins
3. If matched: apply the mapping (chunks + edges)
4. If not matched: fall back to the generic structural parser
   (one chunk per top-level key)

Order of evaluation is registration order. If two mappings can match the
same document, the one loaded first wins. File names in `.rtfm/mappings/`
are processed in sorted order.

## Why this lives outside RTFM

RTFM doesn't bundle any mappings. The NotebookLM project ships its own
`nblm-answer.yaml` — copy it into `.rtfm/mappings/` and you're done. Same
goes for any other tool: the project that produces a JSON schema is best
positioned to define how it should be indexed.

This keeps RTFM honest about its scope: a generic retrieval layer that
extends through pluggable conventions, not a registry of every format
under the sun.

## Examples to look at

- **Start here**: NotebookLM `answer.json` — see the full
  [RTFM × NotebookLM recipe](notebooklm-integration.md) for the
  ready-to-copy mapping and the markdown-only alternative path.
- **OpenAPI specs**: one chunk per `paths.<route>` operation, edges for
  `$ref`s.
- **Linear/Jira exports**: one chunk per issue, edges for `parent_id`,
  `blocks`.
- **Test reports** (Vitest, pytest JSON): one chunk per failure, metadata
  with `file`, `line`, `error_type`.

If you write a useful mapping, share it — open a PR adding the snippet to
this page.
