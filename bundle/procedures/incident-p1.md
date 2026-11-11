---
type: Playbook
title: Incident P1 sur Orion
description: Qualification, première escalade, communication et clôture d'un incident P1 sur le service Orion.
tags: [incident, p1, orion, astreinte]
status: stable
generated: { by: human:mbenali, at: 2026-09-28T10:00:00Z }
verified:
  - { by: human:cdurand, at: 2026-10-02T09:00:00Z }
  - { by: process:okf-lint, at: 2026-11-10T02:00:00Z }
stale_after: 2027-03-31T00:00:00Z
sources:
  - id: runbook-orion
    resource: https://wiki.exemple.invalid/ops/orion/runbook-p1
    title: Runbook P1 Orion (fictif)
    author: team:ops-orion
    last_modified: 2026-09-20T00:00:00Z
  - id: comite-ops
    resource: https://wiki.exemple.invalid/ops/comite/2026-09-25
    title: Compte rendu du comité d'exploitation du 25 septembre 2026 (fictif)
    author: team:ops-direction
---

# Qualification

Un incident P1 correspond à une indisponibilité totale du service [Orion](/services/orion.md).
Le pilote ouvre un ticket INC et note l'heure de début.[^runbook-orion]

# Première escalade

Pour un incident P1, contacter le [responsable d'astreinte](/roles/responsable-astreinte.md).
Sans réponse après 10 minutes, appliquer la section Relais de la procédure
[relais d'astreinte](/procedures/astreinte-relais.md#relais).[^comite-ops]

# Communication

Le pilote publie un point de situation toutes les 30 minutes. Il ne communique
aucune donnée client. Les canaux à utiliser sont décrits dans la fiche
[communication de crise](/procedures/communication-crise.md#canaux).[^runbook-orion]

# Clôture

Clôturer après confirmation du rétablissement par le pilote. Conserver les heures
de début et de fin et la chronologie des actions.

[^runbook-orion]: Runbook P1 Orion (fictif)
[^comite-ops]: Compte rendu du comité d'exploitation du 25 septembre 2026 (fictif)
