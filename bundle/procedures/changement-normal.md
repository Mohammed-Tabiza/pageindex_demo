---
type: Playbook
title: Changement normal
description: Contenu d'une demande de changement normal, validation avant exécution et retour arrière.
tags: [changement, validation]
status: stable
generated: { by: human:lmartin, at: 2026-05-12T09:00:00Z }
verified: { by: human:cdurand, at: 2026-05-20T10:00:00Z }
stale_after: 2027-05-20T00:00:00Z
sources:
  - id: politique-changement
    resource: https://wiki.exemple.invalid/ops/politique-changement
    title: Politique de gestion des changements (fictive)
    author: team:ops-qualite
---

# Demande

Une demande de changement décrit le service, le risque, le plan de retour arrière
et le responsable.

# Validation

Un changement normal nécessite la validation du
[responsable de service](/roles/responsable-service.md) avant exécution. Le
demandeur ne peut pas approuver sa propre demande.[^politique-changement]

# Retour arrière

Si le contrôle de santé échoue après un changement, appliquer le plan de retour
arrière et informer le responsable de service.

[^politique-changement]: Politique de gestion des changements (fictive)
