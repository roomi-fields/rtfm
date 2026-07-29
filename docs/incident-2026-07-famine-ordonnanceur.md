# Incident — famine d'ordonnancement du superviseur mutualisé

**Date** : 27–29 juillet 2026
**Version** : rtfm-ai installée via pipx, superviseur unique (0.25.x, `af82038`)
**Machine** : 12 cœurs, 30 Go, 18 projets enregistrés
**Projet victime** : `/home/romi/dev/obsidian/un-chemin` (85 ouvrages, 465 Mo)

## Résumé

85 livres déposés sur disque par un processus externe n'ont **jamais** été indexés.
Deux causes enchaînées : ils n'ont d'abord été **détectés** par personne, puis une fois
mis en file, ils sont restés **24 h sans qu'aucune tâche ne soit servie**. Zéro document
traité, zéro embedding. Le contournement (traiter la file du projet dans un processus
dédié) a indexé les 85 ouvrages en **16 minutes** — la lenteur n'était donc pas en cause.

## A. Bogue principal — famine par ordre alphabétique

`Supervisor._dispatch` (`rtfm/core/supervisor.py:306`) documente une rotation :

```python
# Rotate the project order by wall tick so busy projects share fairly.
slots = [s for s in self._slots.values() if s.queue is not None and not s.active]
```

**La rotation n'est pas implémentée.** L'itération suit l'ordre d'insertion du dict,
c'est-à-dire l'ordre du registre — et `_save_registry` (`rtfm/cli_worker.py:56`) trie
la liste : `cleaned = sorted(...)`. L'ordre de service est donc **alphabétique et figé**.

Conséquence observée : `/home/romi/dev` (116 490 tâches en attente) est premier
alphabétiquement et occupe une voie en permanence ; `BPscript` et `atlas` prennent les
suivantes. Avec `max_concurrent_indexers = 2`, les 14 projets suivants ne sont
**jamais** servis. `un-chemin` (14ᵉ) a attendu 24 h avec 2 tâches en attente et 0 servie.

Ce n'est pas un retard, c'est une famine : avec 116 000 tâches devant lui à ~9
documents/minute, son tour serait arrivé dans plusieurs jours.

**Correctifs possibles**
1. Implémenter la rotation annoncée (compteur de tour, ou tri par « servi le moins
   récemment »).
2. Réserver au moins une voie au projet dont la tâche la plus ancienne attend depuis
   le plus longtemps (anti-famine strict).
3. Plafonner la part d'un même projet quand d'autres ont des tâches en attente.

À noter : un projet ne peut de toute façon exécuter **qu'une tâche à la fois**
(un seul écrivain par `library.db`, `supervisor.py:158`). Augmenter la concurrence ne
sert donc qu'à servir **plus de projets en parallèle** — ce qui est précisément le
levier anti-famine, mais n'accélère en rien le rattrapage d'un gros projet.

## B. Aucun rattrapage des fichiers arrivés hors agent

L'indexation est déclenchée uniquement par les crochets : `PostToolUse` enregistre les
fichiers écrits par l'agent, `Stop` les indexe. `hooks/rtfm_sync.py:14` l'affirme :
« *Crucially: no full source scan.* »

Un fichier déposé par un processus externe (téléchargement, `rsync`, script) n'est donc
vu par personne. Le balayage périodique du superviseur existe (`_enqueue_periodic`) mais
dépend d'une voie libre — donc soumis à la même famine.

Ici : 66 livres arrivés le 27 au soir, toujours invisibles le 28 au matin. Il a fallu un
`rtfm sync` explicite.

**Piste** : soit un balayage périodique garanti hors pool, soit un signal clair dans
`rtfm status` (« N fichiers non balayés depuis X »).

## C. `rtfm worker status` ment

Après `rtfm worker restart-all`, la commande affiche **« supervisor not running »** alors
que le démon tourne normalement (PID présent dans `~/.rtfm/supervisor.lock`, journal actif,
tâches traitées). Reproduit deux fois. Le fichier d'état n'est pas réécrit par le
superviseur relancé.

Effet de bord : plus aucun compteur de débit lisible, donc plus aucun moyen simple de
diagnostiquer... exactement ce qu'on cherchait à diagnostiquer.

## D. `rtfm sync` bloque sans rien dire

`rtfm sync` reste bloqué indéfiniment (tué à 180 s) quand aucun ouvrier ne sert le projet.
Aucun message n'indique que les tâches sont en file mais non servies. Un simple
« N tâches en attente, aucune voie disponible » aurait fait gagner 24 h.

## E. Ré-enfilage impossible après échec

Pour deux fichiers en échec d'ingestion :
- `rtfm sync --files <a> <b>` → « Queued 0 P0 ingest job(s) » (fichiers déjà connus) ;
- `rtfm queue retry-failed` → « moved 0 failed row(s) back to pending ».

Il a fallu appeler l'API Python directement (`Queue.enqueue("ingest", ...)`) pour les
relancer. Il manque un `--force` sur `sync --files`, ou un `retry-failed` qui reprenne
réellement les lignes en échec.

## F. Ingestion d'un fichier en cours d'écriture

`Bateson - Steps to an Ecology of Mind - EN.pdf` a été ingéré pendant que son
téléchargement se terminait → `PDFExtractionError: PDFium: Data format error`, classé
`pdf-format-invalid`, **sans reprise**. Le fichier était parfaitement valide 20 secondes
plus tard.

**Piste** : vérifier la stabilité (taille/mtime inchangés sur un court intervalle) avant
d'ingérer, et réessayer une fois un échec de format avant de le classer définitif.

## G. Extensions annoncées sans lecteur installé

`rtfm status` liste `.epub`, `.mobi`, `.azw`, `.djvu` parmi les extensions supportées,
alors que les extras correspondants n'étaient pas installés. L'échec n'apparaît qu'au
moment de l'ingestion, fichier par fichier. Les extras `pdf` et `embeddings`, eux, sont
bien signalés comme installés ou non.

**Piste** : étendre la section « Optional extras » à epub / mobi / djvu / office, et ne
plus annoncer une extension dont le lecteur manque (ou l'annoncer barrée).

## H. `rtfm worker stop` est un no-op quand l'état est faux (superviseurs en double)

Conséquence directe du bogue C : `rtfm worker stop` répond « supervisor not running » et
ne tue rien, alors que le démon tourne. `rtfm worker start` lancé ensuite en démarre un
**second**. Observé ici : deux superviseurs simultanés, l'un à 12 voies, l'autre à 2 —
soit 14 voies réelles sur une machine réglée à 2. Le premier n'a cédé qu'à `kill -9`
(SIGTERM ignoré, l'arrêt « propre » attend visiblement des tâches en vol qui ne rendent
jamais la main).

Le verrou `~/.rtfm/supervisor.lock` contient pourtant le bon PID : `stop` devrait s'en
servir plutôt que du fichier d'état.

## Mesures de débit

| Configuration | Débit superviseur | Charge machine (12 cœurs) |
|---|---|---|
| 3 voies | 196 tâches/min | 6 à 11 |
| 12 voies | non concluant (voir ci-dessous) | 17 à 25 |

Le superviseur tourne en priorité minimale (`nice 19` + `ionice -c 3`,
`cli_worker.py:161`), ce qui protège correctement les activités interactives.

À 12 voies, la charge a doublé sans gain mesurable : toutes les voies sont des fils
d'exécution d'**un seul processus Python** (`ThreadPoolExecutor`, `supervisor.py:213`),
donc en concurrence sur le verrou global, et chaque session ONNX ouvre en plus ses propres
fils → sur-souscription massive. La mesure a de surcroît été rendue difficile par le
bogue C (compteur illisible). **À reprendre avec un protocole propre** avant toute
recommandation chiffrée.

## Contournement retenu

`un-chemin/.rtfm/drain.py` : exécute les mêmes gestionnaires (`rtfm.core.handlers`) sur la
file d'un seul projet, dans un processus dédié à priorité basse. 85 ouvrages ingérés en
16 minutes (37 968 fragments), embeddings enchaînés derrière. À supprimer une fois
l'ordonnanceur corrigé.

## Priorités suggérées

1. **A** — famine (bloquant : rend le produit inutilisable en multi-projets)
2. **C** + **H** — état du superviseur faux, `stop` inopérant, superviseurs en double
3. **B** — fichiers externes jamais vus (silencieux, donc pernicieux)
4. **E**, **F** — reprise après échec
5. **D**, **G** — ergonomie
