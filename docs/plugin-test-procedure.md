# RTFM Plugin — Procédure de test complète

Valider que le plugin `rtfm` (v0.5, serveur MCP pur Python, sans pip côté user) fonctionne end-to-end.

## Contexte du testeur

- **Machine de dev principale** : Claude Code CLI dans **WSL2** (Ubuntu), lancé depuis VSCode (terminal intégré).
- **Cible plugin** : WSL + Windows natif (hors WSL).
- **Repo RTFM** : `/mnt/d/Claude/RTFM` côté WSL = `D:\Claude\RTFM` côté Windows natif.

## Pré-requis (à exécuter une fois avant tout test)

### Côté WSL

```bash
python3 --version                          # doit afficher 3.10+
python3 -c "import sqlite3; sqlite3.connect(':memory:').execute('CREATE VIRTUAL TABLE t USING fts5(x)')"   # silence = FTS5 présent
cd /mnt/d/Claude/RTFM && git status        # doit voir les fichiers non-commit : .claude-plugin/, hooks/, skills/, rtfm/_mcp/, etc.
which claude                               # confirme que Claude Code est dispo dans WSL
```

Si un de ces checks échoue, stopper et noter lequel.

### Côté Windows natif

Ouvrir **PowerShell** ou **cmd** (PAS un terminal WSL) :

```powershell
python --version                           # doit afficher 3.10+ (ou `py --version`)
python -c "import sqlite3; sqlite3.connect(':memory:').execute('CREATE VIRTUAL TABLE t USING fts5(x)')"
where claude                               # doit montrer un claude.exe natif Windows (PAS un chemin WSL)
```

**Si `claude.exe` n'est pas installé sous Windows natif** : installer Claude Code pour Windows depuis claude.ai/download. La phase Windows ne peut pas se dérouler sans ça.

---

## Phase 1 — Tests sous WSL

### Test 1 — Serveur MCP standalone (pas de Claude)

Vérifie que le serveur MCP maison répond correctement au protocole JSON-RPC 2.0, sans Claude Code.

```bash
cat > /tmp/mcp_probe.py <<'PYEOF'
import subprocess, json, os
env = os.environ.copy(); env['RTFM_DB'] = '/tmp/nonexistent.db'
cmd = ['python3', '-c',
       "import sys; sys.path.insert(0, '/mnt/d/Claude/RTFM'); from rtfm.mcp import main; main()"]
proc = subprocess.Popen(cmd, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                        stderr=subprocess.PIPE, env=env)
msgs = [
  {"jsonrpc":"2.0","id":1,"method":"initialize","params":{"protocolVersion":"2025-06-18","capabilities":{},"clientInfo":{"name":"t","version":"1"}}},
  {"jsonrpc":"2.0","method":"notifications/initialized"},
  {"jsonrpc":"2.0","id":2,"method":"tools/list"},
]
out, err = proc.communicate(input=('\n'.join(json.dumps(m) for m in msgs)+'\n').encode(), timeout=10)
lines = out.decode().splitlines()
print(f"Responses: {len(lines)}  (expected 2)")
if lines:
    r = json.loads(lines[-1])
    print(f"Tools: {len(r['result']['tools'])}  (expected 13)")
    print("Tool names:", [t['name'] for t in r['result']['tools']])
if err: print("STDERR (first 300 chars):", err.decode()[:300])
PYEOF
python3 /tmp/mcp_probe.py
```

**Attendu** :
- `Responses: 2  (expected 2)`
- `Tools: 13  (expected 13)`
- La liste des 13 tool names : rtfm_search, rtfm_stats, rtfm_tags, rtfm_books, rtfm_sync, rtfm_ingest, rtfm_tag_chunks, rtfm_remove, rtfm_discover, rtfm_context, rtfm_expand, rtfm_graph, rtfm_history.

**Fail** si :
- Moins de 2 réponses ou 0 tools → traceback dans STDERR à partager.

---

### Test 2 — Install plugin local dans un projet vierge

Crée un projet de test, lance Claude Code avec le plugin en mode `--plugin-dir`.

```bash
rm -rf ~/rtfm-test
mkdir -p ~/rtfm-test && cd ~/rtfm-test
cat > README.md <<'EOF'
# Hello RTFM

A short test project with some text so we can search "hello" and find content.
EOF
echo "def greet(name): return 'hi ' + name" > main.py
claude --plugin-dir /mnt/d/Claude/RTFM
```

Dans le REPL Claude Code qui s'ouvre, taper :

```
/rtfm:search hello
```

**Attendu au premier run** :
- Apparition d'un prompt de permission : *"Do you want to proceed? (plugin:rtfm:rtfm - rtfm_search)"*. **Normal** au premier run (les permissions viennent d'être écrites par le bootstrap pendant cette session).
- Choisir *"Yes, and don't ask again"*.
- Résultat : `README.md` remonte avec un score.

**Fail si** :
- Pas de résultat ("Aucun résultat pour 'hello'"). → problème parser (re-vérifier le fix markdown).
- Le skill `/rtfm:search` n'apparaît pas du tout dans l'autocomplete. → plugin non chargé.
- Erreur "server not connected" ou timeout. → MCP server ne démarre pas.

---

### Test 3 — 2e run sans prompt de permission

Quitter Claude (Ctrl+C puis confirmer). Relancer exactement la même commande :

```bash
cd ~/rtfm-test
claude --plugin-dir /mnt/d/Claude/RTFM
```

Dans Claude : `/rtfm:search greet`.

**Attendu** :
- **Pas de prompt de permission** (les permissions sont chargées au boot depuis `.claude/settings.local.json` écrit au run 1).
- `main.py` remonte dans les résultats.

**Fail si** :
- Prompt toujours présent → vérifier que `~/rtfm-test/.claude/settings.local.json` contient bien les 4 règles `mcp__rtfm`, `mcp__rtfm__*`, `mcp__plugin_rtfm_rtfm`, `mcp__plugin_rtfm_rtfm__*`.

---

### Test 4 — Idempotence du bootstrap

Après les 2 premières sessions, vérifier hors Claude :

```bash
grep "initializing project" ~/rtfm-test/.rtfm/rtfm.log
```

**Attendu** : **une seule ligne**, correspondant au run 1.

---

### Test 5 — Parser fix sur fichiers courts

Ajouter un markdown minuscule :

```bash
echo "# TinyNote" > ~/rtfm-test/tiny.md
```

Dans Claude (en session) :

```
/rtfm:search tinynote
```

**Attendu** : `tiny.md` apparaît. Avant le fix parser, un fichier markdown réduit à un header sans body était silencieusement ignoré (0 chunks).

---

### Test 6 — `/rtfm:expand`

Dans Claude :

```
/rtfm:expand README.md
```

**Attendu** : contenu complet de `README.md` renvoyé. Vérifier en parallèle dans `~/rtfm-test/.rtfm/rtfm.log` qu'une ligne `expand | source='…/README.md'` apparaît — c'est la preuve que le tool a tourné (et pas un fallback Read).

---

### Test 7 — Hooks auto-sync

Demander à Claude, en langage naturel :

> Crée un fichier `hello.py` avec une fonction `saluer(nom)` qui renvoie "Bonjour " + nom.

Claude crée le fichier. Quand il a fini de répondre (fin de turn), le hook `Stop` doit déclencher un `stop-sync`.

Hors Claude :

```bash
tail -5 ~/rtfm-test/.rtfm/rtfm.log
```

**Attendu** : une ligne récente `stop-sync done +1 ~0` (1 fichier ajouté).

Puis dans Claude :

```
/rtfm:search saluer
```

**Attendu** : `hello.py` remonte. L'indexation automatique post-turn a fonctionné.

---

### Test 8 — Données lisibles SQLite

Hors Claude :

```bash
sqlite3 ~/rtfm-test/.rtfm/library.db \
  "SELECT indexed_files.book_slug, substr(chunks.content, 1, 60)
   FROM chunks JOIN indexed_files ON chunks.book_id = indexed_files.id
   LIMIT 10;"
```

**Attendu** : 4 à 6 chunks affichés correspondant à README.md, main.py, tiny.md, hello.py, CLAUDE.md.

> Note : `book_slug` est dans la table `indexed_files`, pas `chunks`. `chunks` stocke le contenu, les métadonnées fichier sont dans `indexed_files` (joint via `book_id`).

---

### Test 9 — Dégradation propre si Python absent

Simule un PATH sans `python3` :

```bash
PATH_SANS_PY=$(echo $PATH | tr ':' '\n' | grep -v -E "python|conda|pyenv" | tr '\n' ':')
env -i PATH="$PATH_SANS_PY" HOME="$HOME" which python3 || echo "OK: python3 introuvable"
env -i PATH="$PATH_SANS_PY" HOME="$HOME" claude --plugin-dir /mnt/d/Claude/RTFM
```

Dans Claude : `/rtfm:search hello`.

**Attendu** :
- Les skills `/rtfm:*` apparaissent toujours (le plugin est chargé).
- L'appel échoue proprement : message type "MCP server failed to start" ou "server not connected". Pas de crash de Claude Code.

Quitter et restaurer le PATH normal ensuite (`exit` du terminal puis nouveau terminal).

---

## Phase 2 — Tests sous Windows natif

**Important** : utiliser un terminal **PowerShell ou cmd de Windows**, pas un terminal WSL. Les chemins sont en `D:\Claude\RTFM`. Claude Code doit être la version Windows native (`claude.exe`).

### Test W1 — Serveur MCP standalone sous Windows

```powershell
$env:RTFM_DB = "C:\Windows\Temp\nonexistent.db"
cd D:\Claude\RTFM
python -c "import sys; sys.path.insert(0, 'D:/Claude/RTFM'); from rtfm.mcp import main; main()"
```

Là ça attend du stdin. Taper manuellement, ligne par ligne, Enter après chaque :

```json
{"jsonrpc":"2.0","id":1,"method":"initialize","params":{"protocolVersion":"2025-06-18","capabilities":{},"clientInfo":{"name":"t","version":"1"}}}
{"jsonrpc":"2.0","method":"notifications/initialized"}
{"jsonrpc":"2.0","id":2,"method":"tools/list"}
```

**Attendu** : après la 3e ligne, voir un gros JSON contenant 13 tools. Fermer avec Ctrl+C.

**Fail si** :
- `python` introuvable → installer Python 3.10+ depuis python.org.
- `python3` n'existe pas sous Windows → c'est normal, utiliser `python` ou `py`. **Bug plugin à signaler** si `.mcp.json` utilise `python3` et ne fonctionne pas sous Windows.

---

### Test W2 — Plugin dans Claude Code Windows natif

```powershell
Remove-Item -Recurse -Force $HOME\rtfm-test -ErrorAction SilentlyContinue
mkdir $HOME\rtfm-test
cd $HOME\rtfm-test
"# Hello RTFM`n`nA short test project." | Out-File -Encoding utf8 README.md
"def greet(name): return 'hi ' + name" | Out-File -Encoding utf8 main.py
claude --plugin-dir D:\Claude\RTFM
```

Dans Claude : `/rtfm:search hello`.

**Attendu** : même comportement que sous WSL (Test 2).

**Bugs à signaler spécifiquement Windows** :
- Chemin plugin dans `.mcp.json` mal échappé (backslash vs forward slash).
- Commande `python3` non reconnue (vs `python` ou `py`).
- Hooks qui timeout car la commande Python n'existe pas.
- Encodage UTF-8 cassé dans les logs (BOM, CRLF).

> ⚠️ **Piège observé sous Windows** : quand le MCP est cassé (stub `python3` du Microsoft Store, etc.),
> Claude Code fait un fallback silencieux sur Grep/Read et met en forme la réponse comme si
> le tool avait répondu. **Le plugin peut sembler marcher alors qu'il est mort.**
>
> Pour confirmer que le MCP répond vraiment : vérifier `.rtfm/rtfm.log` (doit contenir des lignes
> `server | starting` et `search | query='...'`). Si le log est vide ou ne contient que les hooks,
> le MCP server ne tourne pas et la réponse vient de Grep/Read.

---

### Test W3 — 2e run sous Windows

Quitter Claude. Relancer :

```powershell
cd $HOME\rtfm-test
claude --plugin-dir D:\Claude\RTFM
```

`/rtfm:search greet` → pas de prompt, résultat `main.py`.

---

## Ce qu'il faut rapporter

Pour chaque test, coller dans un fichier `test-report.md` ou en réponse :

```
## Test X — [nom]
Status: PASS | FAIL | WEIRD
Environment: WSL | Windows
Output (si FAIL ou WEIRD) : colle la sortie pertinente ou screenshot
```

Les FAIL et WEIRD sont les plus utiles : décrire **ce qui s'est réellement passé** vs ce qui était attendu.

---

## Déléguer à Claude Cowork (optionnel)

Si tu confies la Phase 1 à Cowork :

**Ce que Cowork peut faire seul** :
- Tests 1, 4, 8, 9 (non-interactifs, ou analyses post-hoc de logs).
- Tests 2, 3, 5, 6, 7 si Cowork peut lancer une session Claude Code interactive et taper dans son REPL.

**Ce qu'il faut dire à Cowork** :
1. Lire ce fichier.
2. Exécuter Phase 1 intégralement dans `~/rtfm-test`.
3. Pour chaque test, coller la sortie et le statut.
4. Ne PAS modifier le code RTFM — seulement tester.
5. Rapporter les FAIL / WEIRD en priorité.

La Phase 2 (Windows) reste toi, sauf si Cowork a accès à un environnement Windows natif.
