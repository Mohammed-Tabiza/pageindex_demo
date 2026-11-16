# Bilan initial — 11 novembre 2026

Ce document décrit la préparation initiale du kit, avant les essais sur Windows et Ollama. Les validations ultérieures, les corrections et les commandes actuelles sont décrites dans `README.md`.

## Environnement réellement contrôlé

| Capacité | État | Preuve / conséquence |
|---|---|---|
| Runtime ChatGPT Linux / Python 3.12.14 | Confirmé | Installation dans un venv isolé |
| Accès PyPI et installation SDK 0.5.3 | Confirmé | requirements-lock.txt et package_metadata.json |
| PDF textuels | Confirmé | 3 PDF / 12 pages ; extraction et références contrôlées |
| Clé LLM | Non configurée | Précontrôle bloque avant appel |
| Poste Windows, proxy, certificats, GPU utilisateur | Non vérifiés | Instructions fournies, aucune validation distante |
| Endpoint et outils du modèle | Non testés | Condition de l'intégration réelle |

## Observations

| Critère | Attendu | Observé | Verdict |
|---|---|---|---|
| Syntaxe Python | Compilation | Réussie pour les deux scripts | Réussi |
| Corpus | 12 pages textuelles, références valides | 12 pages, 5 questions | Réussi |
| SDK installé | Import et paramètres requis disponibles | Signatures vérifiées sur 0.5.3 | Réussi, limité au contrat Python |
| Sans configuration | Aucun appel réel | Arrêt explicite | Réussi |
| Indexation PageIndex | Arbres réels produits | Non lancée : pas de clé | Non testé |
| Réponses et citations | Exactes et pertinentes | Aucune réponse générée | Non testé |
| Baseline et comparaison | Même corpus / modèle | Non exécutées | Non testé |

Les artefacts des contrôles initiaux ne sont pas inclus dans ce dépôt. La syntaxe et les signatures seules ne démontrent pas une intégration fonctionnelle. Aucun mock ni réponse préenregistrée n'avait été employé lors de cette préparation initiale ; les tests de régression ajoutés ensuite utilisent des doubles hors ligne. Les réponses de référence de questions.json sont un corrigé humain fictif, jamais une sortie PageIndex.

Décision : kit prêt à configurer et à tester sur un endpoint autorisé ; bénéfice technique encore non établi. Le format réduit de 12 pages remplace le corpus plus long du protocole candidat pour une première démonstration du mécanisme.


# Évaluation — 14 et 15 novembre 2026

Protocole du README : 8 questions × 3 répétitions × 2 approches, soit 48 interrogations. Les deux approches utilisent le même bundle et le même modèle, `gemma4:e4b-32k` (Ollama local : poids de `gemma4:e4b`, contexte de 32 768 jetons, température 1), avec le raisonnement du modèle activé. L'heure de référence est fixée par `DEMO_NOW=2026-11-14T12:00:00Z`.
- **PageIndex** passe par `demo.py ask`, qui applique les mêmes contrôles des sources que l'interface web.
- **Contexte complet** passe par `demo.py baseline` : un seul appel, avec les 11 fichiers bruts (frontmatter compris) dans le prompt.

Les 48 exécutions retenues se sont terminées normalement, et leur `metadata.json` confirme le modèle utilisé.

La notation figure dans `evaluation.csv`, ligne par ligne, avec un commentaire. **Elle a été faite par Claude (assistant IA), à la lecture des réponses et des sections citées, en connaissant l'approche évaluée ; elle n'a pas été relue par une personne.** Règles appliquées :
- citation **pertinente** : elle désigne la ou les sections attendues ;
- citation **partielle** : seul le document est désigné, ou la section qui porte le renvoi manque ;
- `s.o.` (sans objet) : la colonne ne s'applique pas au cas.

Les dossiers `runs/…` cités comme preuves sont locaux à ce poste : ils ne sont pas versionnés.

## Résultats retenus

| | PageIndex | Contexte complet |
|---|---|---|
| Réponse correcte | 24/24 | 24/24 |
| Citation pertinente | 22/24 | 19/24 |
| Abstention correcte (`absent`) | 3/3 | 3/3 |
| Statut OKF signalé — `obsolete` | 3/3 | 3/3 |
| Statut OKF signalé — `perime` | 3/3 | 0/3 |
| Statut OKF signalé — `brouillon` | 3/3 | 3/3 |
| Durée médiane (min–max) | 30,1 s (21,3–54,0) | 13,6 s (10,8–23,1) |
| Relances nécessaires | 6/24 | sans objet |

## Historique des mesures PageIndex

1. **Première mesure** (14 novembre, avant correction) : 21/24 réponses correctes, 3 partielles, et `obsolete` à 0/3. Le modèle n'ouvrait jamais le concept obsolète `escalade-p1-v1`. Il donnait la règle en vigueur, mais affirmait qu'aucun document ne parlait du directeur des opérations. Il a fallu 11 relances sur 24.

   Le fichier `.env` a été modifié pendant cette mesure : les 12 premières interrogations ont tourné sur `gemma4:e4b-pageindex-16k`, les suivantes sur `gemma4:e4b-32k`. Les 6 baselines concernées ont ensuite été relancées sur 32k ; ce sont elles qui sont retenues.
2. **Correction n° 1** : la ligne de statut du remplaçant indique « remplace procedures.escalade-p1-v1.md (OBSOLÈTE…) », et la consigne demande de lire le concept obsolète. **Sans effet** : `obsolete` reste à 0/3, car le modèle n'ouvre toujours pas le concept.

   Cette mesure a aussi subi deux coupures du serveur Ollama dans la nuit, sans doute une mise en veille du PC, qui ont fait échouer 3 interrogations. Elle a aussi donné un vrai échec de vérification sur `brouillon` : une citation d'un document non lu.
3. **Correction n° 2** (retenue) : la ligne de statut **recopie l'ancienne règle**, marquée « n'est plus en vigueur ». Le modèle n'a plus besoin d'ouvrir le concept obsolète. Résultat : `obsolete` passe à 3/3, sans régression sur les autres cas.

   Effet secondaire observé : sur `renvoi`, une réponse sur trois mentionne l'ancienne règle sans qu'on le lui demande. C'est exact, mais superflu.

## Comparaison équitable (15 novembre 2026)

La comparaison ci-dessus n'était pas équitable : PageIndex recevait des indicateurs calculés, une consigne propre et une relance. Trois approches ont donc été ajoutées et mesurées (3 × 24 interrogations, toutes sur `gemma4:e4b-32k`, aucun échec d'exécution). Elles reçoivent toutes la même consigne : la consigne générale, plus les phrases de `QUERY_PARTS` qui ne parlent pas des outils. Elles doivent aussi toutes citer avec les mêmes balises `<cite doc=… page=…/>`, contrôlées comme pour PageIndex.

| Approche | Commande | Texte fourni au modèle | Relance |
|---|---|---|---|
| `contexte_brut` | `baseline` | fichiers bruts (frontmatter compris), découpés en PAGE numérotées | non |
| `contexte_okf` | `baseline-okf` | exactement les pages lues par PageIndex : statut calculé, ancienne règle recopiée, liens annotés, sources | non |
| `pageindex_sans_relance` | `ask-once` | les pages que l'agent choisit d'ouvrir ; réponse conservée même si les contrôles la refusent | non |
| `pageindex` | `ask` | idem, avec contrôles et une relance (mesure précédente) | oui |

La consigne PageIndex est restée identique au caractère près, donc la mesure `pageindex` précédente reste valable.

| | contexte_brut | contexte_okf | pageindex_sans_relance | pageindex |
|---|---|---|---|---|
| Réponse correcte | 24/24 | 24/24 | 24/24 | 24/24 |
| Citation pertinente | 23/24 | 21/24 | 22/24 | 22/24 |
| Statut OKF signalé (`obsolete`, `perime`, `brouillon`) | 6/9 | 9/9 | 9/9 | 9/9 |
| — dont `perime` | 0/3 | 3/3 | 3/3 | 3/3 |
| Réponses refusées par les contrôles | 0/24 | 2/24 | 6/24 | 0/24 (après 6 relances) |
| Durée médiane | 20,8 s | 18,9 s | 28,0 s | 30,1 s |

Dans `evaluation.csv`, une citation sans balise `<cite>` est notée `non`, même quand la référence en texte libre désigne la bonne section : c'est le cas des 2 réponses `contexte_okf` refusées.

## Lecture des résultats

Chaque paire d'approches isole un seul facteur :
- **Prétraitement OKF** (`contexte_brut` → `contexte_okf`) : c'est lui qui fait signaler la péremption (0/3 → 3/3). Le modèle ne compare pas une date `stale_after` avec la date du jour ; il répète un « PÉRIMÉ » déjà calculé. L'avantage de PageIndex sur `perime`, observé plus haut, venait donc du prétraitement et non de la recherche.
- **Recherche PageIndex** (`contexte_okf` → `pageindex_sans_relance`) : **aucun gain** sur ce corpus. La justesse est identique (24/24), le temps est plus long (28,0 s contre 18,9 s), et les réponses refusées sont plus nombreuses (6 contre 2). Les 6 refus sont tous du même type : le modèle a répondu juste, mais sans ouvrir de section. Il s'est appuyé sur les résumés extractifs de `get_document_structure`, qui contiennent ici presque tout le texte des sections courtes.
- **Contrôle et relance** (`pageindex_sans_relance` → `pageindex`) : la relance ne change pas le contenu des réponses. Elle transforme seulement des réponses justes mais non vérifiées en réponses vérifiées.

Conclusion sur ce corpus : **la valeur mesurée vient du format OKF prétraité et du contrôle des citations, pas de la recherche PageIndex.** Les deux premiers s'appliquent aussi bien en contexte complet, qui reste le plus rapide. Ce résultat était attendu : avec 11 concepts (environ 4 500 jetons), tout le bundle tient dans la fenêtre du modèle. L'intérêt de PageIndex ne peut apparaître que sur un corpus qui la dépasse, et ce point n'est toujours pas mesuré.

Effet secondaire de l'ancienne règle recopiée dans la ligne de statut : plusieurs réponses sur `renvoi` ou `exception` la mentionnent sans qu'on le leur demande. C'est exact, mais superflu. Les réponses en contexte brut le font aussi, puisqu'elles voient le concept obsolète.

Limites qui demeurent :
- notation par Claude, en connaissant l'approche, sans relecture humaine ;
- 3 répétitions par cas, à température 1 ;
- la correction de `obsolete` a été mise au point et validée sur la même question.

## Pistes

- Des corpus de taille croissante, jusqu'à dépasser la fenêtre de contexte : c'est la seule façon de mesurer l'intérêt de PageIndex. L'indexation de plusieurs bundles à la fois permettrait d'ajouter des bundles distracteurs.
- Des questions nouvelles, absentes de la mise au point, en particulier sur d'autres règles obsolètes.
- Une notation en aveugle, avec une seconde correction humaine.
- Plus de répétitions, ou une température à 0.
- Enregistrer les jetons consommés par PageIndex, pour comparer les coûts et pas seulement les durées.
- Raccourcir ou retirer les résumés de `get_document_structure` quand les sections sont courtes, pour obliger l'agent à lire les pages qu'il cite.
