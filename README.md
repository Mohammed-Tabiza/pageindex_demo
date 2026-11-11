# Démonstrateur PageIndex — procédures IT fictives

Kit préparé le 11 novembre 2026. SDK officiel PageIndex 0.5.3. La configuration uv utilise Python 3.13 ou ultérieur.

## Ce que vous allez voir

Trois PDF textuels de quatre pages chacun, cinq questions et leurs réponses de référence :
- règle simple : fréquence des points de situation ;
- renvoi entre deux documents : escalade après 10 minutes ;
- exception : un exercice appelle l'animateur, pas le coordinateur de crise ;
- absence : aucun numéro personnel n'existe dans le corpus ;
- validation : le demandeur ne peut pas approuver son propre changement.

Le script utilise le vrai SDK pour indexer les PDF, exporter les arbres puis interroger les documents. Le mode `check` contrôle seulement les données et leurs références ; ce n'est pas un moteur RAG ni une simulation. Les documents sont stockés localement, mais leur contenu est transmis à l'endpoint LLM configuré. Aucun service PageIndex Cloud n'est utilisé par notre configuration.

## Installation Windows / PowerShell sans Docker

### Depuis un clonage neuf

Prérequis : Git, uv et Python 3.13 ou ultérieur. Configurez un endpoint LLM autorisé ; pour Ollama local, installez Ollama et le modèle choisi.

```powershell
git clone https://github.com/Mohammed-Tabiza/pageindex_demo.git
cd pageindex_demo
uv sync --locked
Copy-Item .env.example .env
notepad .env
```

Après avoir renseigné `.env` selon les exemples ci-dessous :

```powershell
uv run .\demo.py check
uv run .\demo.py index --timeout 600
uv run .\web.py
```

Les répertoires dont le nom commence par un point sont exclus de Git, ainsi que `.env`, les résultats de `runs/` et `index_manifest.json`. Chaque clonage doit créer son propre environnement et son index. `.env.example`, `.gitignore` et `.python-version` sont des fichiers de configuration versionnés.

Pour les contrôles hors ligne : `uv run python -m unittest test_models test_retrieval test_web_questions -v`.

### Interface web avec uv

Dans le dossier du projet, lancez le serveur web. La recherche en direct utilise le serveur du modèle configuré dans `.env`.

Le menu « Choisir une question » propose les cinq cas du corpus : communication, renvoi entre procédures, exception pendant un exercice, information absente et validation d’un changement. La question complète s’affiche sous le menu ; cliquez sur « Lancer la recherche » pour l’envoyer au modèle. Changer de question efface la réponse et la trace précédentes. Le choix est désactivé pendant une recherche. Le bouton de trace CLI, lorsqu’une archive existe, affiche uniquement celle de la question sélectionnée. Les réponses de référence de `questions.json` ne sont pas envoyées au navigateur ni au modèle.

```powershell
uv run .\web.py
```

Ouvrez [http://127.0.0.1:8765](http://127.0.0.1:8765). Le serveur utilise la bibliothèque standard de Python et les dépendances du projet. Avec l’index déjà créé, le sommaire, les pages et les traces CLI archivées sont consultables sans appeler le modèle.

Si l’index manque ou que les PDF ont changé, configurez `.env`, lancez `uv run .\demo.py index`, puis rechargez la page. L’option `--port` permet de changer le port d’écoute.

#### Diagnostic du cas « renvoi »

- L’interface associe les documents à leur identifiant et au nom réellement stocké par le SDK (`incidents_1.pdf`, par exemple), tout en affichant le nom du PDF d’origine. Les textes intermédiaires suivis d’un appel d’outil ne sont pas affichés comme une réponse finale.
- L’essai navigateur du 11 novembre 2026 avec `gemma4:31b-cloud` a répondu « contacter le coordinateur de crise », avec l’exception de l’exercice, et deux citations ouvrant `incidents.pdf` p. 2 et `astreintes.pdf` p. 2. Le PDF cité a également été servi avec HTTP 200. Les 14 tests hors ligne couvrent notamment la poursuite d’un renvoi, les noms suffixés, la lecture des pages citées et le rejet d’une réponse dont les sources restent incomplètes. Commande : `uv run python -m unittest test_models test_retrieval -v`.
- Avant d’afficher une réponse, le serveur récupère les pages citées via le SDK et suit les renvois explicites vers une section d’un autre document du corpus. Ces lectures sont distinguées des appels du modèle dans la trace. Si des passages ont été ajoutés ou que le parcours reste incomplet, il transmet les textes récupérés au modèle pour une seconde recherche/synthèse. Les citations doivent correspondre à des pages du corpus effectivement récupérées, notamment dans les documents visés par les renvois explicites. Le document intermédiaire peut rester consultable parmi les pages récupérées sans être cité dans la conclusion. Un échec après cette seconde tentative reste signalé comme incomplet. Ce contrôle vérifie la couverture des sources, pas la vérité de chaque affirmation ; aucune réponse de référence n’est transmise au modèle.
- Si le journal affiche `http_status: 402`, le fournisseur refuse la requête pour paiement requis. Pour un modèle Ollama Cloud, vérifiez les crédits et l’offre du compte connecté à Ollama. Le statut HTTP 200 de `/api/query` signifie que le flux web est ouvert ; un événement d’erreur peut ensuite signaler le refus du modèle. L’index existant peut être conservé.
- La trace CLI du 11 novembre 2026 contient deux appels réussis à `get_document_structure` et deux à `get_page_content`. Les pages 2 d’`incidents.pdf` et d’`astreintes.pdf` ont été récupérées. `execution.json` enregistre le code 1 et la trace se termine après les résultats d’outils. Le journal Ollama enregistre trois réponses HTTP 200 sur `/v1/chat/completions` pendant cette exécution.
- La relance avec PageIndex 0.5.3 et `gemma4:e4b` a reproduit `PageIndexAPIError` avec `finish_reason=length`. Le dernier appel a consommé 4 096 jetons, dont 3 873 d’entrée et 223 de raisonnement. PageIndex signale alors une réponse inachevée. Les deux pages avaient déjà été transmises au modèle.
- Pour les modèles locaux `gemma4:*` (hors variantes cloud) sur Ollama au port 11434, l’interface web transmet `reasoning_effort="none"` pour la recherche. Le réglage est affiché à l’écran et s’applique uniquement à cette requête web. L’essai a généré la réponse attendue et cité les deux pages. [Documentation Ollama](https://github.com/ollama/ollama/blob/main/docs/api/openai-compatibility.mdx)

### Ligne de commande

Décompresser l'archive puis ouvrir PowerShell dans le dossier `pageindex_demo`.

```powershell
py -3.13 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe demo.py check
Copy-Item .env.example .env
notepad .env
```

Compléter `.env` localement, sans coller de clé dans le chat :
- `OPENAI_API_KEY` : clé de votre endpoint autorisé ; pour un serveur sans authentification, une valeur factice uniquement si sa configuration le permet ;
- `OPENAI_BASE_URL` : URL de base réelle, incluant `/v1` si requis ;
- `DEMO_INDEX_MODEL` : modèle utilisé pour indexer les PDF ;
- `DEMO_CHAT_MODEL` : modèle utilisé pour explorer les documents et générer les réponses, ainsi que pour la baseline.

Pour indexer avec Gemma local et répondre avec Gemma Cloud via votre serveur Ollama :

```dotenv
OPENAI_API_KEY=ollama
OPENAI_BASE_URL=http://localhost:11434/v1
DEMO_INDEX_MODEL=openai/gemma4:e4b
DEMO_CHAT_MODEL=openai/gemma4:31b-cloud
```

Votre serveur Ollama doit être connecté à un compte disposant d’un accès et de crédits pour le modèle cloud. L’indexation utilise le modèle local ; les questions transmettent les passages au modèle cloud. Ces réglages s’appliquent à la CLI et à l’interface web ; redémarrez le serveur web après modification.

`DEMO_MODEL` reste compatible avec l’ancienne configuration : il sert de repli pour chaque modèle non renseigné. Utilisez les noms LiteLLM `openai/NOM_DU_MODELE` pour un endpoint compatible OpenAI. Changer uniquement `DEMO_CHAT_MODEL` ne nécessite pas de réindexer. Le manifeste vérifie le modèle d’indexation et les empreintes des PDF ; les anciens manifestes sont acceptés, y compris sans le préfixe `openai/`. Les métadonnées des réponses enregistrent les deux modèles.

Pour générer localement, la fenêtre de 4 096 jetons d’Ollama peut saturer dès que les consignes, les outils et les pages récupérées sont réunis. Le fichier `Modelfile.gemma4-16k` prépare une variante des mêmes poids avec 16 384 jetons de contexte et un plafond de sortie de 2 048 jetons :

```powershell
ollama create gemma4:e4b-pageindex-16k -f .\Modelfile.gemma4-16k
```

Utilisez ensuite `DEMO_CHAT_MODEL=openai/gemma4:e4b-pageindex-16k` dans `.env`, en conservant `DEMO_INDEX_MODEL` pour réutiliser l’index. Le contexte agrandi utilise davantage de mémoire. Après une requête, `ollama ps` permet de vérifier le contexte effectivement chargé. L’API compatible OpenAI ne permet pas de régler la fenêtre de contexte par `max_tokens` ; cette valeur concerne la sortie. [Documentation Ollama](https://docs.ollama.com/api/openai-compatibility#setting-the-local-context-size)

Cette démo ne démontre pas une économie de jetons : une capture hors ligne du premier appel a mesuré environ 4 100 caractères de consignes, 3 900 caractères de schémas d’outils et 1 600 caractères de catalogue et de question, avant de lire les pages. Ces longueurs sont des caractères, pas des jetons Gemma. Les résultats d’outils grossissent ensuite l’historique, et la vérification des sources peut entraîner un second appel. Sur 12 pages, la baseline en contexte complet peut être plus simple et moins coûteuse ; il faut mesurer les deux approches pour conclure.

Les variables déjà définies dans PowerShell ont priorité sur `.env`.
La compatibilité du modèle avec les outils et les réponses structurées reste à vérifier. Une API dite compatible OpenAI ne suffit pas à garantir le fonctionnement. Ne pas désactiver TLS. Configurer proxy et certificats via les mécanismes approuvés de votre environnement.

```powershell
# Indexation : peut appeler le LLM, avec une limite globale de 10 minutes.
.\.venv\Scripts\python.exe demo.py index --timeout 600
# Cas nominal avec renvoi, arbre et appels d'outils visibles.
.\.venv\Scripts\python.exe demo.py ask --case renvoi
# Même question avec les 12 pages dans le contexte, même modèle.
.\.venv\Scripts\python.exe demo.py baseline --case renvoi
# Échec révélateur attendu : constater l'absence, ne pas inventer.
.\.venv\Scripts\python.exe demo.py ask --case absent
# Exception à ne pas manquer.
.\.venv\Scripts\python.exe demo.py ask --case exception
```

Sous Linux/WSL : `python3 -m venv .venv`, puis utiliser `.venv/bin/python` au lieu de `.\.venv\Scripts\python.exe`. L'activation de l'environnement n'est pas nécessaire.

## Résultats et traces

Chaque exécution crée un dossier distinct dans `runs/` :
- index : `*_tree.json`, manifeste et empreintes des PDF ;
- interrogation PageIndex : `trace.txt` (appels/outils et réponse, sans affichage du raisonnement interne), `metadata.json` (modèle de génération dans `model`, modèle d’indexation dans `index_model`) et `execution.json` ;
- baseline : `answer.txt`, consommation retournée par le fournisseur et durée ;
- durée dépassée : statut TIMEOUT et code 124, sans verdict de qualité.

Les résultats des outils peuvent être tronqués à 4 000 caractères dans la trace. Les arbres sont conservés séparément. Le script ne calcule pas un score de vérité automatique : remplir `evaluation.csv` après lecture de la réponse finale et des pages citées. La présence d'une citation ne garantit pas qu'elle justifie la réponse.

Limiter d'abord le test à une question. La CLI autorise huit tours d’agent par interrogation. L’interface web autorise jusqu’à deux recherches de huit tours chacune, dans un délai global de 120 secondes. Le timeout CLI est également de 120 secondes par défaut (modifiable). Les limites ne sont pas un plafond de facturation : fixer, si disponible, un quota côté fournisseur. Budget exploratoire proposé : 10 euros, à contrôler hors script. L'arrêt local ne révoque pas les requêtes déjà reçues côté serveur.

## Démonstration en cinq minutes

Pré-indexer avant la présentation ; le temps d'indexation reste mesuré séparément.
- 0:00–0:45 : ouvrir `astreintes.pdf`, rappeler le caractère fictif et la question.
- 0:45–1:30 : montrer un arbre exporté et la baseline document complet.
- 1:30–3:00 : lancer `ask --case renvoi`, observer les outils puis vérifier la source.
- 3:00–4:15 : lancer `ask --case absent` ou `exception` ; analyser l'abstention ou l'erreur.
- 4:15–5:00 : distinguer ce qui a été observé de ce qui reste non démontré.

## Protocole et limites

Question : sur ce petit corpus, l'agent retrouve-t-il les bonnes preuves et sait-il constater une absence ?
Critères proposés : quatre réponses présentes correctes avec pages pertinentes, aucune invention pour la question absente, durée sous 120 s. Répéter les cinq questions trois fois avec chacune des deux approches (30 interrogations). Conserver le même corpus et le même modèle de génération pour PageIndex et la baseline ; consigner séparément le modèle d’indexation. La configuration interne des appels PageIndex n'est pas identique à un unique appel de baseline. Ce n'est donc pas une ablation scientifique stricte.

**Le protocole initial de comparaison avec un RAG vectoriel n'est pas réalisé dans ce kit minimal.** La baseline choisie est le contexte complet, plus simple sur 12 pages. Ce corpus court démontre le mécanisme ; il ne prouve aucun gain de passage à l'échelle, de coût, de conformité ou de précision sur des procédures réelles. Élargir ensuite à des documents plus longs, des titres ambigus et un vrai RAG de référence.

## Reproductibilité et nettoyage

`requirements.txt` fixe les deux dépendances directes. `requirements-lock.txt` contient toutes les versions installées lors du contrôle Linux/Python 3.12 ; ce gel n'est pas une garantie de compatibilité Windows. Les PDF sont déjà fournis. Pour les régénérer : `python build_corpus.py`, puis réindexer. Le script refuse les PDF dont l'empreinte a changé depuis l'indexation.

Ctrl+C arrête la commande. Les dossiers `.pageindex` et `runs`, ainsi que `index_manifest.json`, peuvent être supprimés pour repartir à zéro. Ne supprimez pas `.env` sans conserver votre configuration dans votre gestionnaire habituel. Ne partagez jamais `.env`.

## Sources primaires

Consultées le 11 novembre 2026 :
- https://github.com/VectifyAI/PageIndex
- https://pageindex.ai/docs/sdk/client
- https://pageindex.ai/docs/sdk/documents
- https://pageindex.ai/docs/sdk/chat
- https://pypi.org/pypi/pageindex/0.5.3/json

La distribution officielle a été téléchargée et ses signatures utiles inspectées avant les contrôles. Le SDK tiers reste soumis à sa licence MIT ; il n'est pas recopié dans ce dépôt.
