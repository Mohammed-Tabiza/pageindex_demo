---
type: Playbook
title: Fuite de données personnelles
description: Violation de données personnelles — décision et délai de notification, information des personnes concernées.
tags: [securite, donnees-personnelles, dpo, notification]
status: stable
generated: { by: human:lgarnier, at: 2026-10-10T15:00:00Z }
verified: { by: human:sroux, at: 2026-10-15T10:30:00Z }
stale_after: 2027-04-30T00:00:00Z
sources:
  - id: politique-donnees
    resource: https://wiki.exemple.invalid/dpo/politique-donnees-2026
    title: Politique de protection des données 2026 (fictive)
    author: team:dpo
    last_modified: 2026-09-01T00:00:00Z
---

# Déclenchement

Toute suspicion d'accès non autorisé à des données personnelles déclenche cette
procédure. C'est aussi un incident de sécurité : appliquer la procédure
[incident de sécurité](/procedures/incident-securite.md#alerte).

# Notification

Le [DPO](/roles/dpo.md) décide seul de la notification à l'autorité de contrôle.
Lorsqu'elle est requise, elle est faite au plus tard 72 heures après la prise de
connaissance de la violation. Aucune autre personne ne notifie l'autorité.[^politique-donnees]

# Personnes concernées

Si le risque pour les personnes concernées est élevé, elles sont informées sans retard
injustifié, par un message validé par le [DPO](/roles/dpo.md).

# Registre

Chaque violation, notifiée ou non, est consignée dans le registre des violations tenu
par le DPO : faits, effets et mesures prises.[^politique-donnees]

[^politique-donnees]: Politique de protection des données 2026 (fictive)
