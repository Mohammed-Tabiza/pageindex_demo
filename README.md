# Démonstrateur PageIndex — bundle OKF de procédures IT fictives

Le corpus est un **bundle [Open Knowledge Format](https://github.com/GoogleCloudPlatform/knowledge-catalog/blob/main/okf/SPEC.md) (OKF) v0.2**. Il remplace les trois PDF de la première version. Un bundle OKF est un dossier de concepts Markdown avec un frontmatter YAML, reliés par des liens Markdown. Il fournit aussi des métadonnées de provenance, de confiance et de cycle de vie. Les bases de connaissances des agents s'organisent de plus en plus ainsi : wikis versionnés dans Git, souvent rédigés ou mis à jour par des agents.

Kit mis à jour le 11 novembre 2026. SDK officiel PageIndex 0.5.3, Python 3.13 ou ultérieur via uv.

## Ce que vous allez voir

Le dossier `bundle/` contient 11 concepts répartis en 25 sections et reliés par 14 liens. On y trouve aussi les fichiers réservés `index.md` et `log.md`. Tout est fictif.

```
bundle/
  index.md                    okf_version: "0.2", liste des groupes
  log.md                      journal daté (§9)
  procedures/  index.md, incident-p1.md, astreinte-relais.md, communication-crise.md,
               escalade-p1-v1.md (obsolète), changement-normal.md, changement-urgent.md (brouillon)
  roles/       index.md, coordinateur-crise.md, responsable-astreinte.md, animateur-exercice.md, responsable-service.md
  services/    index.md, orion.md
```

Huit questions (`questions.json`), avec leurs réponses de référence :

| Cas | Ce qui est testé |
|---|---|
| `nominal` | règle simple : fréquence des points de situation |
| `renvoi` | lien OKF d'un concept vers la section d'un autre (`/procedures/astreinte-relais.md#relais`) |
| `exception` | un exercice appelle l'animateur, pas le coordinateur de crise |
| `absent` | aucun numéro personnel n'existe dans le bundle |
| `validation` | le demandeur ne peut pas approuver son propre changement |
| `obsolete` | piège : un concept `status: deprecated` donne une ancienne règle (15 min, directeur) |
| `perime` | la seule source est périmée (`stale_after` dépassé) : répondre **en le signalant** |
| `brouillon` | la seule source est un brouillon non vérifié (`status: draft`, aucun `verified`) |

Les trois derniers cas sont nouveaux. Ils reproduisent une difficulté des bases réelles : une information présente n'est pas forcément en vigueur ni fiable.

## Ce que le démonstrateur fait d'un bundle OKF

| OKF v0.2 | Utilisation ici |
|---|---|
| Concept (`.md` + frontmatter, ID = chemin sans `.md`) | un document PageIndex, nommé `procedures.incident-p1.md` (le SDK interdit `/`) |
| Titres Markdown du corps | l'arbre PageIndex ; **chaque section devient une « page »**, donc une citation désigne une section |
| `type`, `title`, `description`, `tags` | description et métadonnées visibles par l'agent dans `browse_documents` et `get_document` |
| `verified` (§5.2–5.3) | niveau de confiance : `human-reviewed`, `machine-confirmed` ou `unverified` |
| `status`, `stale_after` (§5.4–5.5) | indicateurs OBSOLÈTE, BROUILLON et PÉRIMÉ, recalculés à chaque requête |
| `sources` et notes `[^id]` (§5.1) | chaque page lue par l'agent se termine par les sources des affirmations citées (URL, auteur, date) |
| Liens `/chemin.md#ancre` (§6) | annotés `{→ document, page N}` dans le texte de l'agent ; l'application suit les **renvois** cités |
| `index.md`, `log.md` (§8–9) | validés ; libellés des groupes dans l'interface |
| `superseded_by` (clé producteur, §4.1) | un concept obsolète cité impose de citer son remplaçant |

**Indexation sans LLM.** Le SDK 0.5.3 n'accepte que des PDF en mode local. Or un bundle OKF est déjà structuré. `okf.py` construit donc lui-même l'arbre, les pages et les résumés de façon déterministe, puis les dépose dans le stockage local du SDK (`pageindex.local_store.DocStore`). La recherche, les outils de l'agent et la résolution des citations restent ceux du SDK. L'indexation est **incrémentale** : seuls les concepts modifiés, ajoutés ou supprimés sont réécrits. Un concept qui devient périmé est aussi réécrit. La synchronisation est relancée automatiquement avant chaque question, en CLI comme dans l'interface web.

**Contrôles avant publication d'une réponse** (`web.py`). Le serveur relit les sections citées. Il suit les liens de **renvoi** (« appliquer la section Relais de [relais d'astreinte](…) ») et les remplacements des concepts obsolètes, mais pas les simples mentions. Exception : un concept **en brouillon ou non vérifié** qui pointe vers un concept relu **du même type** est traité comme un renvoi, quel que soit le verbe employé, car il réécrit peut-être cette règle (« cette proposition modifierait… »). Il refuse une réponse qui s'appuie seulement sur un concept obsolète ou sur un tel brouillon, ou qui ne cite pas la cible d'un renvoi cité. Les renvois ne s'enchaînent qu'à partir des pages que le modèle a choisies, qu'il les ait lues ou citées. Une page que le contrôle a lui-même fournie comme cible d'un renvoi n'impose pas de nouveau renvoi, sauf si le modèle l'ouvre ensuite. Sans cette règle, un lien vers une procédure entière (« appliquer en parallèle la procédure incident P1 ») pouvait imposer de citer des procédures sans rapport avec la question. Dans ce cas, il relance une fois le modèle avec les passages récupérés. Une réponse publiée affiche des **avertissements OKF** pour chaque concept cité périmé, en brouillon, obsolète ou non vérifié, dans l'esprit du « gate » décrit au §10.5 de la spécification. Ces contrôles portent sur la couverture et le cycle de vie des sources, pas sur la vérité des affirmations. Aucune réponse de référence n'est transmise au modèle.

## Installation (Windows / PowerShell, sans Docker)

Prérequis : Git, uv et Python 3.13 ou ultérieur. Configurez un endpoint LLM autorisé ; pour Ollama local, installez Ollama et le modèle choisi.

```powershell
git clone https://github.com/Mohammed-Tabiza/pageindex_demo.git
cd pageindex_demo
uv sync --locked
uv run .\demo.py check
uv run .\demo.py index
Copy-Item .env.example .env
notepad .env
uv run .\web.py
```

`check`, `lint` et `index` fonctionnent hors ligne, sans clé ni appel LLM. Seules les questions (`ask`, `baseline`, interface web) appellent le modèle configuré. Sous Linux/WSL, remplacez `.\demo.py` par `demo.py`.

Contrôles hors ligne (66 tests) :

```powershell
uv run python -m unittest test_okf test_models test_retrieval test_web_questions -v
```

### Configuration `.env`

Compléter `.env` localement, sans coller de clé dans le chat :
- `OPENAI_API_KEY` : clé de votre endpoint autorisé ; pour un serveur sans authentification, une valeur factice si sa configuration le permet ;
- `OPENAI_BASE_URL` : URL de base réelle, incluant `/v1` si requis ;
- `DEMO_CHAT_MODEL` : modèle qui explore les concepts et rédige les réponses, aussi utilisé pour la baseline ;
- `DEMO_INDEX_MODEL` : facultatif depuis le passage à OKF, car l'indexation n'appelle plus de LLM. S'il est vide, il reprend `DEMO_CHAT_MODEL`. `DEMO_MODEL` reste un repli commun ;
- `DEMO_BUNDLE`, `DEMO_QUESTIONS` : facultatifs, pour utiliser votre propre bundle, ou plusieurs (voir plus bas) ;
- `DEMO_REASONING_EFFORT` : facultatif. Vide = réglage du modèle (recommandé) ; `none` accélère les réponses mais les petits modèles sautent alors souvent la lecture des sections.
- `DEMO_NOW` : facultatif. Instant ISO 8601 (`2026-11-11T12:00:00Z`) qui fige la date du calcul de fraîcheur, pour rejouer une démonstration à l'identique.

Exemple Ollama, avec réponses par un modèle cloud :

```dotenv
OPENAI_API_KEY=ollama
OPENAI_BASE_URL=http://localhost:11434/v1
DEMO_CHAT_MODEL=openai/gemma4:31b-cloud
```

Utilisez les noms LiteLLM `openai/NOM_DU_MODELE` pour un endpoint compatible OpenAI. Les variables déjà définies dans PowerShell ont priorité sur `.env`. Redémarrez le serveur web après modification. La compatibilité du modèle avec les outils reste à vérifier : une API dite compatible OpenAI ne suffit pas à la garantir. Ne désactivez pas TLS ; configurez proxy et certificats via les mécanismes approuvés de votre environnement.

## Utiliser votre propre bundle OKF

```powershell
# Conformité OKF v0.2 (§11) et recommandations (§5–§10) ; code de sortie 1 si non conforme.
uv run .\demo.py lint --bundle C:\chemin\vers\mon-bundle
```

Sont des **erreurs**, conformément au §11 : un concept sans frontmatter YAML lisible, un `type` absent ou vide, un `index.md` portant un frontmatter autre que `okf_version` à la racine, un titre de date non ISO dans `log.md`. Sont de simples **avertissements**, jamais bloquants : liens cassés, ancres introuvables, acteurs hors convention (`human:`, `process:`, `agent/version`), dates sans fuseau, `sources` sans `resource`, notes `[^id]` sans source correspondante, `status` inconnu, ancien champ v0.1 `timestamp`. Les types inconnus et les clés supplémentaires sont acceptés. Les fichiers et dossiers dont le nom commence par un point sont ignorés.

Pour interroger votre bundle, définissez `DEMO_BUNDLE` (ou passez `--bundle`) et fournissez un fichier de questions `DEMO_QUESTIONS` au même format que `questions.json`. Les sources s'écrivent `id/du/concept#ancre-de-section`, l'ancre étant celle de GitHub, accents conservés. Lancez ensuite `demo.py check`, puis `demo.py index`. Un bundle non conforme n'est pas indexé.

### Plusieurs bundles

Plusieurs bundles peuvent être interrogés ensemble. Il suffit de répéter `--bundle` ou de séparer les chemins dans `DEMO_BUNDLE` par `;` sous Windows (`:` sous Linux/WSL) :

```powershell
uv run .\demo.py lint --bundle .\bundle --bundle C:\chemin\vers\rh
$env:DEMO_BUNDLE = ".\bundle;C:\chemin\vers\rh"; uv run .\web.py
```

- **Noms.** Chaque bundle est désigné par le nom de son dossier, qui doit être unique. Quand plusieurs bundles sont interrogés, les documents prennent ce nom en préfixe (`rh.procedures.incident-p1.md`). Dans les sources des questions, le préfixe (`rh:procedures/incident-p1#communication`) n'est obligatoire que si le concept existe dans plusieurs bundles. Sinon, `procedures/incident-p1#communication` désigne le seul bundle qui le contient. Un fichier de questions écrit pour un bundle reste donc valable quand on en ajoute d'autres. `DEMO_QUESTIONS` accepte plusieurs fichiers, séparés comme pour `DEMO_BUNDLE`. Les identifiants de questions doivent être uniques entre les fichiers. Avec un seul bundle, les noms des documents ne changent pas.
- **Index.** Chaque document enregistre son bundle. Synchroniser un bundle ne modifie ni ne supprime jamais les documents d'un autre, même si deux bundles contiennent les mêmes chemins de concepts. Une question n'interroge que les bundles configurés.
- **Liens.** Un chemin OKF reste interne à son bundle : `/procedures/x.md` désigne toujours le concept de ce bundle-là. Pour viser un autre bundle, nommez-le devant le chemin : `[procédure P1](bundle:/procedures/incident-p1.md#communication)`, comme dans les sources des questions. Ce lien n'est suivi que si ce bundle est chargé aussi. L'agent lit alors `{→ bundle.procedures.incident-p1.md, page 3}`, et un renvoi de ce type est exigé par les contrôles comme un renvoi interne. Si le bundle n'est pas chargé, le lien est signalé (« non chargé : non suivi ») et ignoré. `demo.py lint` avec plusieurs `--bundle` contrôle ces liens. Le lien dépend du nom du dossier visé : renommer ce dossier casse le lien, qui est alors signalé.
- **Interface.** Les concepts sont groupés par bundle (« rh · Procédures »), et la synthèse de conformité couvre l'ensemble des bundles. Le choix des bundles se fait par la configuration, pas depuis l'interface.

#### Scénario fourni : exploitation + sécurité

Le dossier `securite/` est un second bundle fictif, tenu par une autre équipe : 6 concepts sur l'incident de sécurité, la fuite de données et le compte d'accès d'urgence, plus les rôles RSSI et DPO. Il contient volontairement un **faux concept** : `procedures/acces-urgence-astreinte.md`, brouillon généré par un agent et jamais vérifié, qui contredit la procédure d'accès d'urgence en vigueur. Ses cinq questions sont dans `questions-multi.json` :

| Question | Ce qui est testé | Réponse attendue |
|---|---|---|
| `croise` | croiser les deux bundles | le RSSI dans les 15 minutes ; c'est aussi un P1 : point toutes les 30 minutes, validé par le RSSI |
| `fuite` | un seul bundle, celui de la sécurité | le DPO seul, au plus tard 72 heures |
| `contradiction` | faux concept contradictoire | non : validation du RSSI, 4 heures au plus ; la règle contraire est un brouillon |
| `premisse` | question piège, à prémisse fausse | la procédure de fuite ne mentionne pas le directeur des opérations (ancienne règle P1, obsolète) |
| `secret` | secret absent des deux bundles | ne pas inventer de mot de passe |

```powershell
$env:DEMO_QUESTIONS = "questions-multi.json"
uv run .\demo.py check --bundle .\bundle --bundle .\securite
uv run .\demo.py ask --case contradiction --bundle .\bundle --bundle .\securite
$env:DEMO_BUNDLE = ".\bundle;.\securite"; uv run .\web.py
```

Pour interroger les deux bundles comme un seul corpus, avec les 13 questions (les 8 de l'exploitation et les 5 de la sécurité) :

```powershell
$env:DEMO_BUNDLE = ".\bundle;.\securite"; $env:DEMO_QUESTIONS = "questions.json;questions-multi.json"
uv run .\demo.py check
uv run .\web.py
```

Sous WSL, séparez les chemins par `:` (`DEMO_BUNDLE="bundle:securite"`). Ce mode montre aussi si le second bundle perturbe les réponses du premier.

Les documents s'appellent alors `bundle.procedures.…` et `securite.procedures.…`. Revenir à un seul bundle renomme les documents au prochain `index`, sans appel LLM.

La procédure `incident-securite` renvoie à la procédure P1 de l'exploitation par deux liens entre bundles, ce qui rend la question `croise` possible.

Premiers passages avec `gemma4:e4b-32k`, indicatifs (température 1, une seule répétition sauf `croise`) :

- `fuite` et `secret` sont justes.
- `contradiction` : au premier essai par l'interface web, l'agent n'avait lu que le brouillon et répondait « oui », avertissements OKF compris. Le brouillon ne pointait vers la règle en vigueur que par une simple mention, que les contrôles n'exigeaient pas de lire. Depuis la règle sur les brouillons ci-dessus, 3 passages sur 3 sont justes. Dans l'un d'eux, c'est le contrôle qui a fait lire la règle en vigueur, et la relance a corrigé la réponse.
- `croise` est juste 2 fois sur 3. À chaque passage, l'agent a suivi le lien vers le bundle d'exploitation et cité la fréquence de 30 minutes. Le troisième passage oublie de prévenir le RSSI dans les 15 minutes. Avant l'ajout des liens, l'agent n'ouvrait jamais le bundle d'exploitation.
- `premisse` est **faux** : l'agent répond « 72 heures » sans relever que le directeur des opérations n'existe pas dans cette procédure. Les contrôles de citations ne peuvent pas détecter cette erreur, puisque la page citée existe.

## Interface web

```powershell
uv run .\web.py
```

Ouvrez [http://127.0.0.1:8765](http://127.0.0.1:8765). Le serveur n'écoute que sur la boucle locale et utilise la bibliothèque standard.

- **Colonne de gauche** : synthèse de conformité (version OKF, niveaux de confiance, concepts obsolètes, périmés ou en brouillon, avertissements de validation), puis les concepts groupés selon `index.md`, avec leurs badges et leur arbre de sections.
- **Lecteur de concept** : badges (type, statut, confiance, tags), métadonnées (fraîcheur, auteur, remplaçant, sources avec indicateurs de crédibilité), rendu Markdown de la section. Les liens internes ouvrent directement la section cible. La **Vue agent** montre le texte exact transmis à PageIndex : ligne de statut, liens annotés et sources résolues. **Source OKF ↗** affiche le fichier brut.
- **Réponse** : les citations ouvrent la section citée. Un encadré d'**avertissements OKF** apparaît si un concept cité est périmé, obsolète, en brouillon ou non vérifié.
- **Trace** : appels `get_document_structure` et `get_page_content`. Les lectures faites par l'application pour vérifier les sources sont distinguées de celles du modèle.

Le menu propose les huit questions. Les réponses de référence ne sont envoyées ni au navigateur ni au modèle. Le bouton de trace CLI, lorsqu'une archive existe, rejoue celle de la question sélectionnée, citations et avertissements compris.

## Ligne de commande

```powershell
uv run .\demo.py index                      # synchronise l'index et exporte les arbres dans runs/
uv run .\demo.py ask --case renvoi          # agent PageIndex, mêmes contrôles des sources que l'interface web
uv run .\demo.py baseline --case renvoi     # même modèle, bundle brut complet (frontmatter compris) en contexte
uv run .\demo.py baseline-okf --case renvoi # même modèle, toutes les pages telles que l'agent PageIndex les lit
uv run .\demo.py ask-once --case renvoi     # agent PageIndex sans relance, réponse gardée même si refusée
uv run .\demo.py ask --case obsolete        # le modèle doit écarter la règle obsolète
uv run .\demo.py ask --case perime          # le modèle doit signaler la fiche périmée
uv run .\demo.py ask --case absent          # abstention attendue, aucun numéro inventé
```

Chaque exécution crée un dossier dans `runs/` :
- index : un `*_tree.json` par concept, `index_manifest.json` (empreintes, concepts modifiés ou supprimés), `okf_report.json` ;
- interrogation : `trace.txt` (outils, réponse, citations et avertissements OKF, sans le raisonnement interne), `events.jsonl` (événements exacts, rejoués par l'interface web), `metadata.json`, `execution.json` ;
- baselines : `answer.txt`, citations résolues et refus des contrôles dans `metadata.json`, consommation retournée par le fournisseur et durée ;
- durée dépassée : statut TIMEOUT et code 124, sans verdict de qualité.

Le script ne calcule pas de score automatique. Remplissez `evaluation.csv` après lecture de la réponse et des sections citées ; la colonne `statut_okf_signale` indique si la réponse a mentionné l'obsolescence, la péremption ou le brouillon. `demo.py ask` et l'interface web suivent le même parcours : même consigne, mêmes contrôles des citations, au plus deux recherches de huit tours. Le délai global est de 120 s (`--timeout` pour la CLI). Une réponse refusée après la seconde tentative donne le code de sortie 1. Ces limites ne plafonnent pas la facturation : fixez un quota côté fournisseur si possible.

## Diagnostic

- `http_status: 402` : le fournisseur refuse la requête pour paiement requis. Vérifiez les crédits du compte (Ollama Cloud, par exemple). L'index peut être conservé.
- `finish_reason=length` : la fenêtre de contexte ou le plafond de sortie est atteint. Ollama limite le contexte à 4 096 jetons par défaut. `Modelfile.gemma4-16k` prépare une variante à 16 384 jetons : `ollama create gemma4:e4b-pageindex-16k -f .\Modelfile.gemma4-16k`, puis `DEMO_CHAT_MODEL=openai/gemma4:e4b-pageindex-16k`. [Documentation Ollama](https://docs.ollama.com/api/openai-compatibility#setting-the-local-context-size)
- « Citez les pages lues… » après une seconde tentative : le modèle a répondu sans lire de section. Mesuré le 12 novembre 2026 sur la question `renvoi` avec `gemma4:e4b-pageindex-16k` : sans raisonnement (`reasoning_effort="none"`), 3 réponses sur 7 étaient sans lecture ni citation valide ; avec le raisonnement du modèle, 4 sur 4 étaient correctes, en 23 à 35 s. Le raisonnement reste donc actif par défaut. `DEMO_REASONING_EFFORT=none` (ou `low`, `medium`, `high`) dans `.env` force un autre réglage, affiché à l'écran. Une citation d'une section que le modèle n'a jamais lue est refusée, même si l'application l'a récupérée pour vérification.
- « Serveur du modèle injoignable » : avant chaque question, l'application vérifie en 5 s que `OPENAI_BASE_URL` répond. Sous WSL en réseau NAT (par défaut), le `localhost` de Windows n'est pas visible : un Ollama lancé sous Windows n'est pas joignable par `http://localhost:11434`. Activez le réseau en miroir (`[wsl2]` puis `networkingMode=mirrored` dans `%UserProfile%\.wslconfig`, puis `wsl --shutdown`) ou lancez le démonstrateur sous Windows. Une adresse de passerelle WSL (`172.x.x.1`) ou une instance Ollama lancée à la main ne survit pas au redémarrage du PC.
- « Bundle OKF non conforme » : lancez `demo.py lint` et corrigez les erreurs listées.
- L'historique des essais de la version PDF (11 novembre 2026) et l'évaluation des 48 interrogations (14 et 15 novembre 2026, résultats dans `evaluation.csv`) sont résumés dans `BILAN.md`.

## Protocole et limites

Question : sur ce bundle, l'agent retrouve-t-il les bonnes preuves, suit-il les renvois, écarte-t-il les règles obsolètes, signale-t-il les sources périmées ou non validées, et sait-il constater une absence ?

Répéter les huit questions trois fois avec chacune des quatre approches (`ask`, `ask-once`, `baseline`, `baseline-okf` : 96 interrogations), avec le même bundle et le même modèle de génération. Toutes reçoivent la même consigne, hormis les phrases sur les outils réservées à PageIndex, et citent avec les mêmes balises, contrôlées de la même façon. Chaque paire isole un facteur : `baseline` / `baseline-okf` mesure le prétraitement OKF, `baseline-okf` / `ask-once` la recherche PageIndex, et `ask-once` / `ask` la relance. La configuration interne des appels PageIndex reste différente d'un appel unique : ce n'est pas une ablation stricte. Résultats du 15 novembre 2026 dans `BILAN.md`.

Ce que le kit **ne démontre pas** : un gain de coût ou de précision à grande échelle (11 concepts tiennent largement en contexte complet), la comparaison avec un RAG vectoriel, la qualité des résumés (ici extractifs, sans LLM), ni les *Attested Computations* OKF (§10). Celles-ci sont validées (`runtime` requis) mais ne sont pas exécutées. La détection des renvois repose sur une liste explicite de formes verbales françaises et anglaises (« appliquer », « suivez », « voir », « remplacée », « see »…), afin d'ignorer « suivant », « suivi » ou « rapport » : elle est à ajuster pour un autre vocabulaire (`REFERRAL` dans `okf.py`). La fraîcheur dépend de l'horloge du poste, ou de `DEMO_NOW`.

## Reproductibilité et nettoyage

`pyproject.toml` et `uv.lock` fixent les dépendances (`pageindex`, `pyyaml`, ainsi que `litellm` et `python-dotenv`, importés directement). `requirements-lock.txt` reste un gel indicatif d'un contrôle Linux. Les dossiers `.pageindex` et `runs`, ainsi que `index_manifest.json`, peuvent être supprimés pour repartir de zéro : `demo.py index` les reconstruit en quelques millisecondes. Ne partagez jamais `.env`.

## Sources primaires

Consultées le 11 novembre 2026 :
- https://github.com/GoogleCloudPlatform/knowledge-catalog/blob/main/okf/SPEC.md (OKF v0.2)
- https://github.com/VectifyAI/PageIndex
- https://pageindex.ai/docs/sdk/client
- https://pageindex.ai/docs/sdk/chat
- https://pypi.org/pypi/pageindex/0.5.3/json

Le SDK tiers reste soumis à sa licence MIT ; il n'est pas recopié dans ce dépôt.
