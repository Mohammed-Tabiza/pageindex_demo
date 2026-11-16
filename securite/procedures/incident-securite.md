---
type: Playbook
title: Incident de sécurité sur Orion
description: Qualification d'un incident de sécurité, alerte du RSSI, communication et conservation des preuves.
tags: [securite, incident, orion, rssi]
status: stable
generated: { by: human:lgarnier, at: 2026-10-10T14:00:00Z }
verified: { by: human:sroux, at: 2026-10-15T10:00:00Z }
stale_after: 2027-04-30T00:00:00Z
sources:
  - id: pssi
    resource: https://wiki.exemple.invalid/secu/pssi-2026
    title: Politique de sécurité du SI 2026 (fictive)
    author: team:secu-orion
    last_modified: 2026-09-15T00:00:00Z
---

# Qualification

Un incident de sécurité est une compromission avérée ou suspectée d'un compte,
d'un poste ou du service Orion : connexion anormale, logiciel malveillant,
exfiltration ou modification non autorisée de données.[^pssi]

# Alerte

Prévenir le [RSSI](/roles/rssi.md) dans les 15 minutes suivant la détection.
Si le service Orion est totalement indisponible, l'incident est aussi un incident P1 :
appliquer en parallèle la [procédure incident P1](bundle:/procedures/incident-p1.md)
du bundle d'exploitation.

# Communication

Le [RSSI](/roles/rssi.md) valide le contenu de chaque point de situation avant sa
publication. Aucun message ne mentionne la cause supposée, l'attaquant ni les données
touchées. Pour la fréquence des points de situation, appliquer la section Communication
de la [procédure incident P1](bundle:/procedures/incident-p1.md#communication).

# Preuves

Ne pas redémarrer ni réinstaller un système compromis avant la copie de ses journaux.
Les journaux copiés sont conservés 12 mois.[^pssi]

[^pssi]: Politique de sécurité du SI 2026 (fictive)
