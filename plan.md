# Plan v0.2.4 — Améliorations RTFM Search/Expand/Embeddings

## Ordre d'implémentation

### P1: Pénalité score fichiers test
- **Fichier**: `rtfm/mcp.py`
- Ajouter `_is_test_file(filepath)` — détecte `test_*`, `*_test.py`, `/tests/`, `/test/`
- Modifier `_deduplicate_by_source()` — appliquer `_adjusted_score = score * 0.7` pour les tests
- Le score affiché reste le score original, seul le ranking change
- Tests: `TestTestFileScorePenalty` dans `tests/test_mcp.py`

### P3: Slug dans search + préfixe commun factorisé
- **Fichier**: `rtfm/mcp.py`
- `_format_source_line()` : toujours afficher `slug:` + accepter `root_prefix` pour chemins relatifs
- Ajouter `_compute_common_root(paths)` — `os.path.commonpath` sur les paths absolus
- `rtfm_search()` : calculer le root commun, afficher `(root: /testbed)` dans le header
- Format résultat: `[1] mlflow/genai/base.py > class X — score: 33.4 — 8 chunks — slug: mlflow-genai-base`
- Tests: `TestSlugInSearchResults`, `TestCommonRootPrefix`

### P0: Expand accepte les chemins de fichiers
- **Fichier**: `rtfm/mcp.py`
- Ajouter `_resolve_source_to_slug(source)` — résolution en 3 étapes:
  1. Essai comme slug (existant)
  2. Match par `books.filename` ou `indexed_files.filepath` (exact puis suffixe)
  3. Conversion path→slug via `_path_to_slug()`
- Modifier `rtfm_expand()` pour utiliser ce resolver en fallback
- Backward compatible : les slugs existants fonctionnent toujours
- Tests: `TestExpandFilePathResolution`

### P2: Migration FastEmbed (ONNX)
- **Fichiers**: `rtfm/core/embeddings.py`, `rtfm/core/library.py`, `pyproject.toml`
- Remplacer `sentence-transformers` + `torch` par `fastembed>=0.4.0`
- `DEFAULT_MODEL` → `"sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2"`
- `SentenceTransformer.encode()` → `list(TextEmbedding.embed())`
- `library.py`: changer default model param en `None`, utiliser `DEFAULT_MODEL`
- `pyproject.toml`: `embeddings = ["fastembed>=0.4.0"]`
- Tests: mettre à jour `pytest.importorskip("fastembed")`

## Vérification
- Après chaque étape: `.venv/bin/pytest tests/ -v`
- Version finale: bump 0.2.3 → 0.2.4
