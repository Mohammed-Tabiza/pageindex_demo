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

**Contrôles avant publication d'une réponse** (`web.py`). Le serveur relit les sections citées. Il suit les liens de **renvoi** (« appliquer la section Relais de [relais d'astreinte](…) ») et les remplacements des concepts obsolètes, mais pas les simples mentions. Il refuse une réponse qui s'appuie seulement sur un concept obsolète ou qui ne cite pas la cible d'un renvoi cité. Dans ce cas, il relance une fois le modèle avec les passages récupérés. Une réponse publiée affiche des **avertissements OKF** pour chaque concept cité périmé, en brouillon, obsolète ou non vérifié, dans l'esprit du « gate » décrit au §10.5 de la spécification. Ces contrôles portent sur la couverture et le cycle de vie des sources, pas sur la vérité des affirmations. Aucune réponse de référence n'est transmise au modèle.

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

Contrôles hors ligne (43 tests) :

```powershell
uv run python -m unittest test_okf test_models test_retrieval test_web_questions -v
```

### Configuration `.env`

Compléter `.env` localement, sans coller de clé dans le chat :
- `OPENAI_API_KEY` : clé de votre endpoint autorisé ; pour un serveur sans authentification, une valeur factice si sa configuration le permet ;
- `OPENAI_BASE_URL` : URL de base réelle, incluant `/v1` si requis ;
- `DEMO_CHAT_MODEL` : modèle qui explore les concepts et rédige les réponses, aussi utilisé pour la baseline ;
- `DEMO_INDEX_MODEL` : facultatif depuis le passage à OKF, car l'indexation n'appelle plus de LLM. S'il est vide, il reprend `DEMO_CHAT_MODEL`. `DEMO_MODEL` reste un repli commun ;
- `DEMO_BUNDLE`, `DEMO_QUESTIONS` : facultatifs, pour utiliser votre propre bundle (voir plus bas) ;
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

## Interface web

```powershell
uv run .\web.py
```

Ouvrez [http://127.0.0.1:8765](http://127.0.0.1:8765). Le serveur n'écoute que sur la boucle locale et utilise la bibliothèque standard.

- **Colonne de gauche** : synthèse de conformité (version OKF, niveaux de confiance, concepts obsolètes, périmés ou en brouillon, avertissements de validation), puis les concepts groupés selon `index.md`, avec leurs badges et leur arbre de sections.
- **Lecteur de concept** : badges (type, statut, confiance, tags), métadonnées (fraîcheur, auteur, remplaçant, sources avec indicateurs de crédibilité), rendu Markdown de la section. Les liens internes ouvrent directement la section cible. La **Vue agent** montre le texte exact transmis à PageIndex : ligne de statut, liens annotés et sources résolues. **Source OKF ↗** affiche le fichier brut.
- **Réponse** : les citations ouvrent la section citée. Un encadré d'**avertissements OKF** apparaît si un concept cité est périmé, obsolète, en brouillon ou non vérifié.
- **Trace** : appels `get_document_structure` et `get_page_content`. Les lectures faites par l'application pour vérifier les sources sont distinguées de celles du modèle.

Le menu propose les huit questions. Les réponses de référence ne sont envoyées ni au navigateur ni au modèle. Le bouton de trace CLI, lorsqu'une archive existe, affiche celle de la question sélectionnée.

## Ligne de commande

```powershell
uv run .\demo.py index                      # synchronise l'index et exporte les arbres dans runs/
uv run .\demo.py ask --case renvoi          # agent PageIndex, appels d'outils visibles
uv run .\demo.py baseline --case renvoi     # même modèle, bundle complet (frontmatter compris) en contexte
uv run .\demo.py ask --case obsolete        # le modèle doit écarter la règle obsolète
uv run .\demo.py ask --case perime          # le modèle doit signaler la fiche périmée
uv run .\demo.py ask --case absent          # abstention attendue, aucun numéro inventé
```

Chaque exécution crée un dossier dans `runs/` :
- index : un `*_tree.json` par concept, `index_manifest.json` (empreintes, concepts modifiés ou supprimés), `okf_report.json` ;
- interrogation : `trace.txt` (outils et réponse, sans le raisonnement interne), `metadata.json`, `execution.json` ;
- baseline : `answer.txt`, consommation retournée par le fournisseur et durée ;
- durée dépassée : statut TIMEOUT et code 124, sans verdict de qualité.

Le script ne calcule pas de score automatique. Remplissez `evaluation.csv` après lecture de la réponse et des sections citées ; la colonne `statut_okf_signale` indique si la réponse a mentionné l'obsolescence, la péremption ou le brouillon. La CLI autorise huit tours d'agent et 120 s par défaut (`--timeout`). L'interface web autorise deux recherches de huit tours, dans un délai global de 120 s. Ces limites ne plafonnent pas la facturation : fixez un quota côté fournisseur si possible.

## Diagnostic

- `http_status: 402` : le fournisseur refuse la requête pour paiement requis. Vérifiez les crédits du compte (Ollama Cloud, par exemple). L'index peut être conservé.
- `finish_reason=length` : la fenêtre de contexte ou le plafond de sortie est atteint. Ollama limite le contexte à 4 096 jetons par défaut. `Modelfile.gemma4-16k` prépare une variante à 16 384 jetons : `ollama create gemma4:e4b-pageindex-16k -f .\Modelfile.gemma4-16k`, puis `DEMO_CHAT_MODEL=openai/gemma4:e4b-pageindex-16k`. [Documentation Ollama](https://docs.ollama.com/api/openai-compatibility#setting-the-local-context-size)
- Pour les modèles locaux `gemma4:*` (hors variantes cloud) sur Ollama au port 11434, l'interface web transmet `reasoning_effort="none"`. Le réglage est affiché à l'écran.
- « Bundle OKF non conforme » : lancez `demo.py lint` et corrigez les erreurs listées.
- L'historique des essais de la version PDF (11 novembre 2026) est résumé dans `BILAN.md` et dans l'historique Git.

## Protocole et limites

Question : sur ce bundle, l'agent retrouve-t-il les bonnes preuves, suit-il les renvois, écarte-t-il les règles obsolètes, signale-t-il les sources périmées ou non validées, et sait-il constater une absence ?

Répéter les huit questions trois fois avec chacune des deux approches (48 interrogations), avec le même bundle et le même modèle de génération. La configuration interne des appels PageIndex n'est pas identique à un unique appel de baseline : ce n'est pas une ablation stricte.

Ce que le kit **ne démontre pas** : un gain de coût ou de précision à grande échelle (11 concepts tiennent largement en contexte complet), la comparaison avec un RAG vectoriel, la qualité des résumés (ici extractifs, sans LLM), ni les *Attested Computations* OKF (§10). Celles-ci sont validées (`runtime` requis) mais ne sont pas exécutées. La détection des renvois repose sur des verbes français et anglais courants (« appliquer », « suivre », « voir », « remplacé », « see »…) : elle est à ajuster pour un autre vocabulaire. La fraîcheur dépend de l'horloge du poste, ou de `DEMO_NOW`.

## Reproductibilité et nettoyage

`pyproject.toml` et `uv.lock` fixent les dépendances (`pageindex`, `pyyaml`). `requirements-lock.txt` reste un gel indicatif d'un contrôle Linux. Les dossiers `.pageindex` et `runs`, ainsi que `index_manifest.json`, peuvent être supprimés pour repartir de zéro : `demo.py index` les reconstruit en quelques millisecondes. Ne partagez jamais `.env`.

## Sources primaires

Consultées le 11 novembre 2026 :
- https://github.com/GoogleCloudPlatform/knowledge-catalog/blob/main/okf/SPEC.md (OKF v0.2)
- https://github.com/VectifyAI/PageIndex
- https://pageindex.ai/docs/sdk/client
- https://pageindex.ai/docs/sdk/chat
- https://pypi.org/pypi/pageindex/0.5.3/json

Le SDK tiers reste soumis à sa licence MIT ; il n'est pas recopié dans ce dépôt.
