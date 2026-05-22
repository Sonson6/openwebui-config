# Cahier des charges — Projet RAG

Ce document liste l'ensemble des décisions et prérequis à clarifier avant de démarrer le développement d'un système RAG, en impliquant les parties prenantes concernées (métier, IT, sécurité, direction).

---

## 1. Sources et accès aux documents

### 1.1 Localisation des documents

**Où sont physiquement stockés les fichiers ?**

Si les documents sont sur **SharePoint** (hypothèse évoquée), il existe deux approches Python pour s'y connecter :

- **Microsoft Graph API** + [`msgraph-sdk-python`](https://github.com/microsoftgraph/msgraph-sdk-python) : approche officielle, bien documentée, authentification via `msal`.
- **`Office365-REST-Python-Client`** : librairie communautaire plus simple mais moins maintenue.

**SharePoint est cependant sous-optimal comme source directe pour un pipeline RAG.** C'est un outil de collaboration humaine, pas de batch I/O : l'API Graph impose un throttling strict, les SDKs Python sont des wrappers REST verbeux non conçus pour ingérer des milliers de documents, et la gestion de métadonnées custom (hash, statut de parsing, date d'ingestion) y est laborieuse. Un object storage (Azure Blob, S3) offre des lectures en streaming parallèles, une latence prévisible, des métadonnées natives et des SDKs (`azure-storage-blob`, `boto3`) pensés exactement pour ce cas d'usage.

**Compromis recommandé si SharePoint reste la source de vérité :** garder SharePoint pour les utilisateurs, et mettre en place une synchronisation automatique (webhook Graph API ou Azure Logic Apps) vers un blob storage qui sert de source pour le pipeline RAG. La gouvernance documentaire existante est préservée sans handicaper le pipeline -> ça reste de l'over-engineering

> **Décision requise :** Confirmer la source des documents et évaluer la faisabilité d'un blob storage dédié au pipeline. 

### 1.2 Droits d'accès techniques

**Le service qui fait tourner la pipeline d'ingestion a-t-il le droit de lire ces fichiers ?**

La pipeline d'ingestion tournera sur un **serveur dédié**, non distinct de celui hébergeant OpenWebUI. Il faut s'assurer que ce serveur puisse atteindre SharePoint / Object Storage en réseau (pas de blocage firewall, proxy configuré si nécessaire) et disposer des credentials de l'App Registration.

> **Décision requise :** Validation IT/sécurité de la connectivité réseau entre le serveur d'ingestion et SharePoint / Object Storage, et création des credentials de service.

### 1.3 Gouvernance et qualité des données sources

**Qui est responsable des documents dans la source, et selon quels critères ?**

C'est l'un des points les plus sous-estimés dans les projets RAG. En pratique, on se heurte systématiquement aux problèmes suivants :

- **Fraîcheur** : si un document est mis à jour dans SharePoint / Object Storage, comment et quand le RAG en est-il informé ? Un RAG qui répond à partir de données obsolètes est potentiellement plus dangereux qu'un RAG inexistant.
- **Fiabilité** : tous les documents présents dans le répertoire source sont-ils fiables et validés ? Des brouillons, des documents en cours de révision ou des fichiers erronés vont dégrader la qualité des réponses.
- **Format LLM-friendly** : des documents mal structurés (mise en page complexe, tableaux en image, texte dans des en-têtes/pieds de page) donnent un texte extrait incohérent, que le modèle ne peut pas interpréter correctement.
- **Ownership** : qui décide qu'un document entre ou sort du périmètre du RAG ? Sans responsable désigné, le corpus se dégrade progressivement.

> **Décision requise :** Désigner une personne ou une équipe responsable de la qualité et du cycle de vie des documents sources. Sans ce rôle clairement défini, la qualité du RAG ne peut pas être garantie dans le temps.

---

## 2. Nature des documents

### 2.1 Formats présents
**Quels types de fichiers composent le corpus ?** PDF natif, PDF scanné, Word, Excel, PowerPoint, emails, HTML, mixte ?

> Chaque format nécessite un traitement spécifique. Un PDF scanné n'est pas du texte : c'est une image, et en extraire du texte (OCR) est une étape supplémentaire coûteuse en temps et en ressources, qui peut produire des erreurs. Un corpus 100% mixte multiplie la complexité par autant de formats présents.

### 2.2 Qualité des documents scannés
**Si des PDF scannés sont présents : sont-ils lisibles ? Y a-t-il des tampons, annotations manuscrites, mauvaises résolutions ?**

> L'OCR sur des scans de mauvaise qualité produit du texte corrompu. Un RAG qui ingère du texte corrompu donnera des réponses incorrectes. Il faut auditer la qualité des scans avant de s'engager sur un périmètre.

### 2.3 Langue(s)
**Les documents sont-ils en français uniquement, ou en plusieurs langues ?**

> Le modèle d'embedding et le LLM doivent être choisis en fonction des langues présentes. Un corpus multilingue implique des contraintes supplémentaires sur le choix des composants.

### 2.4 Documents tabulaires ou complexes
**Y a-t-il des fichiers Excel avec des données chiffrées, des tableaux imbriqués, des graphiques dont le contenu est clé pour répondre aux questions métier ?**

> Extraire le sens de tableaux complexes pour le rendre interrogeable n'est pas trivial. Il faut que le métier précise si ces formats sont dans le périmètre et quelle importance ils ont pour les cas d'usage visés.

---

## 3. Cycle de vie des documents

### 3.1 Volume initial
**Combien de documents composent le corpus de départ ?** (ordre de grandeur : dizaines, centaines, milliers ?)

> Le volume détermine les ressources nécessaires pour l'ingestion initiale (temps, stockage, capacité du vector store). Un corpus de 10 000 documents PDF ne s'ingère pas en quelques minutes.

### 3.2 Fréquence d'ajout
**À quelle fréquence de nouveaux documents sont-ils ajoutés ?** (quotidien, hebdomadaire, ponctuel, jamais ?)

> Si des documents sont ajoutés régulièrement, il faut une pipeline d'ingestion automatisée et planifiée. Si c'est ponctuel, une procédure manuelle peut suffire. Ce choix impacte significativement l'architecture.

### 3.3 Mises à jour de documents existants
**Est-ce que des documents existants peuvent être modifiés ou remplacés par une version plus récente ?**

> Un document mis à jour dans la source doit être re-traité et ré-indexé dans le système. Sans mécanisme de détection des modifications, le RAG peut répondre à partir de données obsolètes. Quelqu'un doit décider qui déclenche ce processus et comment.

### 3.4 Suppression de documents
**Est-ce que des documents peuvent être retirés du périmètre (document confidentiel, obsolète, retiré) ?**

> Un document supprimé de la source doit également être supprimé de l'index. Sans processus clair, le RAG continuera de répondre à partir de documents qui ne devraient plus exister. Il faut désigner un responsable de cette gouvernance.

---

## 4. Cas d'usage et qualité attendue

### 4.1 Types de questions cibles
**Quelles sont concrètement les questions que les utilisateurs vont poser ?** Donner 10 à 20 exemples réels par périmètre métier.

> Le RAG n'est pas un moteur de recherche universel, et il a des limites structurelles importantes à anticiper dès le cadrage.
>
> Un RAG fonctionne en récupérant un nombre limité de passages pertinents (_chunks_) dans le corpus, puis en demandant au LLM de répondre **uniquement à partir de ces passages**. Cela fonctionne bien pour des questions précises et localisées :
> - *"Quel est le délai de préavis pour une démission cadre selon notre convention collective ?"*
> - *"Quel est le ratio de fonds propres exigé dans la directive CRR2 pour les expositions en actions ?"*
>
> En revanche, cela **ne fonctionne pas** pour des questions synthétiques qui nécessitent une vision globale du corpus :
> - *"Quels sont les thèmes majeurs de l'AI Act ?"* → répondre correctement exigerait de lire l'intégralité du texte, pas quelques extraits.
> - *"Donne-moi une synthèse des risques identifiés dans nos rapports trimestriels de l'année dernière."*
>
> Si les utilisateurs attendent ce type de réponses synthétiques, une architecture différente (ou complémentaire) doit être envisagée. C'est un point de cadrage fondamental qui doit être discuté avec le métier avant tout engagement.

### 4.2 Tolérance aux erreurs
**Que se passe-t-il si le RAG donne une mauvaise réponse ?** Simple inconvénient ou risque opérationnel/réglementaire ?

> Un RAG peut se tromper ou produire une réponse plausible mais incorrecte. Si le cas d'usage est critique (décision RH, conformité réglementaire, risk management), des garde-fous supplémentaires doivent être prévus dès la conception. Ce niveau de tolérance au risque doit être décidé par le métier et la direction.

### 4.3 Organisation projet et référents métier
**Qui, côté métier, est disponible et désigné pour travailler avec l'équipe technique tout au long du projet ?**

> Un projet RAG ne peut pas être mené par le Data Scientist seul dans son coin. Il nécessite une **équipe projet dédiée** avec, au minimum :
> - Un **référent métier** disponible (pas ponctuellement) pour répondre aux questions sur les documents, valider les cas d'usage, tester les réponses et prioriser les ajustements.
> - Un **interlocuteur IT** pour les accès, l'infrastructure et la connectivité.
>
> Sans cette disponibilité structurée, les allers-retours s'étirent, les incompréhensions s'accumulent et la qualité finale du système s'en ressent directement.

### 4.4 Jeu de test de référence
**Le métier peut-il fournir un ensemble de questions + réponses attendues pour évaluer le système ?**

> Sans référentiel de validation, il n'est pas possible de mesurer objectivement si le RAG fonctionne bien ou non. Ce livrable est à la charge du métier.

---

## 5. Sécurité, confidentialité et conformité

### 5.1 Niveau de confidentialité des données
**Les documents contiennent-ils des données personnelles (RGPD), des données sensibles (salaires, données médicales, données de risque) ?**

> Si oui, le traitement de ces données doit être validé par le DPO et/ou la sécurité. Cela peut imposer des contraintes fortes sur l'architecture (hébergement on-premise, pas de service cloud externe).

### 5.2 Traçabilité des usages
**Faut-il logger qui pose quelles questions et quelles réponses sont données ?**

> Dans certains contextes réglementaires ou de gouvernance interne, un audit trail est requis. Ce besoin doit être exprimé en amont car il impacte la conception.

---

## Note sur la généricité inter-départements

Il est tentant de penser qu'une pipeline générique couvrirait tous les départements (RH, Finance, Risk...). En pratique, chaque département diffère sur **au minimum** les points 2, 4 et 5 de ce document — formats de documents, cas d'usage, et niveau de confidentialité. **Un projet RAG = un périmètre métier à cadrer.** La réutilisation technique est réelle (infrastructure, code), mais le cadrage fonctionnel est à refaire à chaque fois. Lancer plusieurs RAG en parallèle avant d'avoir validé le premier multiplie les risques.

---

## Annexe — Architecture technique retenue

### Principe

```
[Source (SharePoint / Object Storage)]
        ↓
[Pipeline Python d'ingestion]
  - Parsing des documents (PDF, Word, Excel...)
  - Chunking (découpage en passages)
  - Embedding (via API OpenAI/Anthropic)
  - Indexation dans Qdrant
        ↓
[Qdrant — Vector Store] ←──── [Pipe OpenWebUI]
                                      ↓
                              [OpenWebUI / LLM]
                                      ↓
                               [Utilisateur final]
```

### Pourquoi cette architecture ?

OpenWebUI propose un RAG natif (Knowledge Base), mais son API ne permet pas d'importer des chunks pré-découpés : tout document uploadé est **systématiquement re-chunké** par OpenWebUI selon ses propres paramètres globaux. Déléguer l'ingestion à OpenWebUI revient donc à perdre le contrôle sur la partie la plus critique du pipeline.

L'architecture retenue sépare clairement les responsabilités :

| Composant | Rôle | Contrôle |
|---|---|---|
| Pipeline Python | Parse, chunke, embedde, indexe | Total — c'est notre code |
| Qdrant | Stocke et recherche les vecteurs | Total — instance dédiée |
| Pipe OpenWebUI | Retrieval depuis Qdrant + injection du contexte dans le prompt | ~50 lignes Python, minimal |
| OpenWebUI + LLM | Interface utilisateur + génération de la réponse | Standard |

### Avantages

- **Contrôle total sur le chunking**, qui est le facteur le plus déterminant pour la qualité du RAG.
- **Qdrant indépendant d'OpenWebUI** : si l'interface change ou est remplacée, les données restent exploitables.
- **Évolutivité** : le Pipe peut être enrichi (re-ranking, hybrid search, filtrage par métadonnées) sans toucher à la pipeline d'ingestion.