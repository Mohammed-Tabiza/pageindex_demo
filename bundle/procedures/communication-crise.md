---
type: Playbook
title: Communication de crise
description: Canaux et contenu des messages envoyés aux utilisateurs pendant un incident sur Orion.
tags: [communication, incident, utilisateurs]
status: stable
generated: { by: reference_agent/gemma4-31b, at: 2026-06-15T14:00:00Z }
verified: { by: process:okf-lint, at: 2026-06-16T02:00:00Z }
stale_after: 2026-09-30T00:00:00Z
sources:
  - id: guide-com
    resource: https://wiki.exemple.invalid/com/guide-incidents
    title: Guide de communication incidents (fictif)
    author: team:communication
    usage_count: 42
    last_modified: 2026-05-10T00:00:00Z
usage_window: { from: 2026-05-01T00:00:00Z, to: 2026-05-31T00:00:00Z }
---

# Canaux

Pendant un incident P1 ou P2, informer les utilisateurs sur la page de statut
`statut.orion.exemple.invalid`. Les clients grands comptes reçoivent en plus un
courriel de leur interlocuteur habituel.[^guide-com]

# Contenu des messages

Chaque message indique l'heure, le périmètre touché et l'heure du prochain point.
Il ne contient ni donnée client ni hypothèse sur la cause.[^guide-com]

[^guide-com]: Guide de communication incidents (fictif)
