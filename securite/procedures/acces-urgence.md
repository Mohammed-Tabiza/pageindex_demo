---
type: Playbook
title: Accès d'urgence
description: Activation, durée et clôture du compte d'accès d'urgence aux serveurs Orion.
tags: [securite, acces, urgence, rssi]
status: stable
generated: { by: human:lgarnier, at: 2026-10-12T09:00:00Z }
verified: { by: human:sroux, at: 2026-10-15T11:00:00Z }
stale_after: 2027-04-30T00:00:00Z
sources:
  - id: pssi
    resource: https://wiki.exemple.invalid/secu/pssi-2026
    title: Politique de sécurité du SI 2026 (fictive)
    author: team:secu-orion
    last_modified: 2026-09-15T00:00:00Z
---

# Activation

Le compte d'accès d'urgence n'est activé qu'après la validation du [RSSI](/roles/rssi.md)
ou, en son absence, de son suppléant désigné. Le responsable d'astreinte ne peut pas
l'activer seul. La validation est consignée dans le ticket d'incident.[^pssi]

# Durée

Une activation dure au plus 4 heures. Le RSSI peut la prolonger une seule fois.

# Après usage

Le secret du compte est renouvelé dans les 24 heures suivant la désactivation, et
l'équipe sécurité relit le journal des commandes passées. Le secret n'est jamais
écrit dans un ticket, un message ou ce bundle.[^pssi]

[^pssi]: Politique de sécurité du SI 2026 (fictive)
