---
command: doc-extraction
name: Document — Extraction d'informations
description: Extrait de manière exhaustive et structurée des informations ciblées d'un document.
---

## Extraction d'informations

Extrais les informations demandées du document joint.

**Paramètres** — si non précisés, demande-les en une seule fois :
- Type d'informations : dates | montants | noms et entités | clauses et obligations | risques | actions à mener | autre : [préciser]
- Format de sortie : tableau | liste à puces | JSON
- Langue de sortie : (même que le document par défaut)

Quand les paramètres sont clairs, applique ce plan :

1. **Parcours le document de façon systématique**, section par section, sans sauter de passage
2. **Repère chaque occurrence** correspondant au type d'information demandé — ne pas filtrer prématurément
3. **Note la localisation exacte** de chaque entrée (page, section, paragraphe)
4. **Dédoublonne** les entrées redondantes tout en conservant les nuances importantes entre occurrences similaires
5. **Structure la sortie** dans le format demandé (tableau, liste à puces, JSON) avec une colonne ou un champ "Source"
6. **Signale explicitement** tout passage ambigu, incomplet ou contradictoire dans le document
