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
