---
type: Service
title: Orion
description: Service fictif de réservation en ligne exploité par l'équipe Ops Orion.
resource: https://orion.exemple.invalid
tags: [orion, service, priorites]
generated: { by: human:mbenali, at: 2026-03-01T09:00:00Z }
verified: { by: process:okf-lint, at: 2026-11-10T02:00:00Z }
---

# Description

Orion permet aux clients fictifs de réserver des créneaux en ligne. Il est
exploité 24 h/24 par l'équipe Ops Orion.

# Niveaux de priorité

| Priorité | Définition                                   | Procédure                                      |
|----------|----------------------------------------------|------------------------------------------------|
| P1       | Indisponibilité totale du service            | [Incident P1](/procedures/incident-p1.md)      |
| P2       | Service dégradé pour une partie des clients  | [Communication](/procedures/communication-crise.md) |
| P3       | Anomalie sans impact client immédiat         | Ticket standard                                |
| P4       | Demande d'amélioration                       | Backlog                                        |
