# Bitwarden Secrets Manager — Runbook

Gestion des secrets pour les environnements dev / UAT / prod.
Le serveur Bitwarden est déjà en place — ce runbook couvre uniquement
la configuration des secrets et le déploiement.

Remplace chaque `<PLACEHOLDER>` par la valeur réelle avant d'exécuter.

---

## Sommaire

1. [Installer le CLI bws (par développeur)](#1-installer-le-cli-bws-par-développeur)
2. [Authentification développeur](#2-authentification-développeur)
3. [Structure des projets Bitwarden](#3-structure-des-projets-bitwarden)
4. [Peupler les secrets par environnement](#4-peupler-les-secrets-par-environnement)
5. [Machine Account (déploiements serveur / CI-CD)](#5-machine-account-déploiements-serveur--ci-cd)
6. [Lancer docker-compose par environnement](#6-lancer-docker-compose-par-environnement)

---

## 1. Installer le CLI bws (par développeur)

> `bws` est le CLI dédié à Bitwarden **Secrets Manager** — distinct du CLI `bw` du gestionnaire de mots de passe.

```bash
# macOS
brew install bitwarden/brew/bws

# Linux
curl -fsSL https://github.com/bitwarden/sdk-sm/releases/latest/download/bws-x86_64-unknown-linux-gnu.tar.gz \
  | tar -xz -C /usr/local/bin

# Vérifier
bws --version
```

---

## 2. Authentification développeur

Bitwarden Secrets Manager n'a pas de login interactif via navigateur pour le CLI — l'auth se fait via un **access token** généré dans l'UI.

### Générer son access token (une fois par développeur)

1. Ouvrir **Bitwarden Secrets Manager → <TON_ORGANISATION> → Machine Accounts**
2. Créer un Machine Account personnel (ex: `dev-<prenom>`)
3. Lui donner accès en **Read** aux projets `openwebui-dev`
4. Générer un **Access Token** → le copier immédiatement (affiché une seule fois)

### Configurer le token en local

```bash
# Option A — variable d'environnement (session courante)
export BWS_ACCESS_TOKEN=<TON_ACCESS_TOKEN>

# Option B — permanent dans ton shell (recommandé)
echo 'export BWS_ACCESS_TOKEN=<TON_ACCESS_TOKEN>' >> ~/.zshrc
source ~/.zshrc
```

### Vérifier l'accès

```bash
bws secret list --project-id <PROJECT_ID_DEV>
```

---

## 3. Structure des projets Bitwarden

Bitwarden Secrets Manager organise les secrets par **Projets**.
On crée un projet par environnement — à faire une seule fois dans l'UI par l'admin.

| Projet Bitwarden | Environnement | Usage |
|---|---|---|
| `openwebui-dev` | Développement local | Tous les devs en Read |
| `openwebui-uat` | UAT / Staging | Machine Account serveur UAT |
| `openwebui-prod` | Production | Machine Account serveur Prod |

> Noter les **Project IDs** de chaque projet (visibles dans l'URL de l'UI ou via `bws project list`).

```bash
# Lister les projets et leurs IDs
bws project list
```

---

## 4. Peupler les secrets par environnement

> Fait par l'admin uniquement. Nécessite un Machine Account avec accès **Write** sur les trois projets.

### 4a. Clé par clé en CLI

```bash
# ── Dev ──────────────────────────────────────────────────────────────────────
for entry in \
  "LITELLM_MASTER_KEY=sk-dev-..." \
  "LITELLM_OPENWEBUI_KEY=sk-dev-owui-..." \
  "WEBUI_SECRET_KEY=<hex-32-chars>" \
  "OPENAI_API_KEY=sk-..." \
  "ANTHROPIC_API_KEY=sk-ant-..." \
  "GEMINI_API_KEY=AIza..."
do
  KEY="${entry%%=*}"
  VALUE="${entry#*=}"
  bws secret create "$KEY" "$VALUE" <PROJECT_ID_DEV>
done

# ── UAT ──────────────────────────────────────────────────────────────────────
for entry in \
  "LITELLM_MASTER_KEY=sk-uat-..." \
  "LITELLM_OPENWEBUI_KEY=sk-uat-owui-..." \
  "WEBUI_SECRET_KEY=<hex-32-chars>" \
  "OPENAI_API_KEY=sk-..." \
  "ANTHROPIC_API_KEY=sk-ant-..." \
  "GEMINI_API_KEY=AIza..."
do
  KEY="${entry%%=*}"
  VALUE="${entry#*=}"
  bws secret create "$KEY" "$VALUE" <PROJECT_ID_UAT>
done

# ── Prod ─────────────────────────────────────────────────────────────────────
for entry in \
  "LITELLM_MASTER_KEY=sk-prod-..." \
  "LITELLM_OPENWEBUI_KEY=sk-prod-owui-..." \
  "WEBUI_SECRET_KEY=<hex-32-chars>" \
  "OPENAI_API_KEY=sk-..." \
  "ANTHROPIC_API_KEY=sk-ant-..." \
  "GEMINI_API_KEY=AIza..."
do
  KEY="${entry%%=*}"
  VALUE="${entry#*=}"
  bws secret create "$KEY" "$VALUE" <PROJECT_ID_PROD>
done
```

### 4b. Script Python (bulk, programmatique)

```bash
pip install bitwarden-sdk
```

```python
# bitwarden/seed_secrets.py
# Usage : BWS_ACCESS_TOKEN=<token> python bitwarden/seed_secrets.py --env dev
import argparse, os, subprocess, sys

PROJECT_IDS = {
    "dev":     "<PROJECT_ID_DEV>",
    "staging": "<PROJECT_ID_UAT>",
    "prod":    "<PROJECT_ID_PROD>",
}

SECRETS = {
    "dev": {
        "LITELLM_MASTER_KEY":    "sk-dev-...",
        "LITELLM_OPENWEBUI_KEY": "sk-dev-owui-...",
        "WEBUI_SECRET_KEY":      "<hex-32-chars>",
        "OPENAI_API_KEY":        "sk-...",
        "ANTHROPIC_API_KEY":     "sk-ant-...",
        "GEMINI_API_KEY":        "AIza...",
    },
    "staging": {
        "LITELLM_MASTER_KEY":    "sk-uat-...",
        "LITELLM_OPENWEBUI_KEY": "sk-uat-owui-...",
        "WEBUI_SECRET_KEY":      "<hex-32-chars>",
        "OPENAI_API_KEY":        "sk-...",
        "ANTHROPIC_API_KEY":     "sk-ant-...",
        "GEMINI_API_KEY":        "AIza...",
    },
    "prod": {
        "LITELLM_MASTER_KEY":    "sk-prod-...",
        "LITELLM_OPENWEBUI_KEY": "sk-prod-owui-...",
        "WEBUI_SECRET_KEY":      "<hex-32-chars>",
        "OPENAI_API_KEY":        "sk-...",
        "ANTHROPIC_API_KEY":     "sk-ant-...",
        "GEMINI_API_KEY":        "AIza...",
    },
}

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--env", choices=["dev", "staging", "prod"], required=True)
    args = parser.parse_args()

    token = os.environ.get("BWS_ACCESS_TOKEN")
    if not token:
        sys.exit("Erreur : BWS_ACCESS_TOKEN non défini")

    project_id = PROJECT_IDS[args.env]

    for key, value in SECRETS[args.env].items():
        result = subprocess.run(
            ["bws", "secret", "create", key, value, project_id],
            env={**os.environ, "BWS_ACCESS_TOKEN": token},
            capture_output=True, text=True
        )
        if result.returncode == 0:
            print(f"  ✓ {key}")
        else:
            print(f"  ✗ {key} — {result.stderr.strip()}")

    print(f"\nSecrets seedés pour l'environnement : {args.env}")

if __name__ == "__main__":
    main()
```

```bash
BWS_ACCESS_TOKEN=<ADMIN_TOKEN> python bitwarden/seed_secrets.py --env dev
BWS_ACCESS_TOKEN=<ADMIN_TOKEN> python bitwarden/seed_secrets.py --env staging
BWS_ACCESS_TOKEN=<ADMIN_TOKEN> python bitwarden/seed_secrets.py --env prod
```

---

## 5. Machine Account (déploiements serveur / CI-CD)

> Pour les serveurs UAT et Prod — pas de navigateur, auth headless.

### Créer un Machine Account serveur (dans l'UI Bitwarden, par l'admin)

1. **Secrets Manager → Machine Accounts → New Machine Account**
2. Nom : `deploy-uat` / `deploy-prod`
3. Accès **Read** sur le projet correspondant (`openwebui-uat` ou `openwebui-prod`)
4. Générer un **Access Token** → stocker en lieu sûr (variable système ou secret CI/CD)

### Sur le serveur

```bash
# Stocker le token de façon permanente sur le serveur
echo 'export BWS_ACCESS_TOKEN=<SERVER_ACCESS_TOKEN>' >> /etc/environment
# ou dans le profil du user de déploiement
echo 'export BWS_ACCESS_TOKEN=<SERVER_ACCESS_TOKEN>' >> ~/.zshrc
```

---

## 6. Lancer docker-compose par environnement

### Développement (local)

```bash
# Depuis la racine du repo
bws run --project-id <PROJECT_ID_DEV> \
  -- docker compose -f litellm/docker-compose.dev.yml up -d
```

### UAT (serveur)

```bash
bws run --project-id <PROJECT_ID_UAT> \
  -- docker compose -f litellm/docker-compose.uat.yml up -d
```

### Prod (serveur)

```bash
bws run --project-id <PROJECT_ID_PROD> \
  -- docker compose -f litellm/docker-compose.prod.yml up -d
```

### Wrapper pratique

```bash
#!/usr/bin/env bash
# bitwarden/deploy.sh
# Usage : ./bitwarden/deploy.sh dev | uat | prod
set -euo pipefail

ENV=${1:?Usage: $0 [dev|uat|prod]}

declare -A PROJECT_IDS=(
  [dev]="<PROJECT_ID_DEV>"
  [uat]="<PROJECT_ID_UAT>"
  [prod]="<PROJECT_ID_PROD>"
)

declare -A COMPOSE_FILES=(
  [dev]="litellm/docker-compose.dev.yml"
  [uat]="litellm/docker-compose.uat.yml"
  [prod]="litellm/docker-compose.prod.yml"
)

: "${BWS_ACCESS_TOKEN:?La variable BWS_ACCESS_TOKEN doit être définie}"

bws run \
  --project-id "${PROJECT_IDS[$ENV]}" \
  -- docker compose -f "${COMPOSE_FILES[$ENV]}" up -d

echo "✓ Stack $ENV démarrée"
```

```bash
chmod +x bitwarden/deploy.sh

./bitwarden/deploy.sh dev
./bitwarden/deploy.sh uat
./bitwarden/deploy.sh prod
```

---

## Différences clés avec Infisical

| | Infisical | Bitwarden Secrets Manager |
|---|---|---|
| Auth dev | `infisical login` (navigateur) | `BWS_ACCESS_TOKEN` (variable d'env) |
| Auth serveur | Machine Identity (client-id + secret) | Machine Account (access token) |
| Organisation | Environnements (`dev`, `staging`, `prod`) | Projets (un par environnement) |
| Injection | `infisical run --env=dev --` | `bws run --project-id <ID> --` |
| Import bulk | `infisical secrets set --file=.env` | Script CLI (pas d'import fichier natif) |

---

## Référence des secrets du projet

| Variable | Dev | UAT | Prod | Description |
|---|---|---|---|---|
| `LITELLM_MASTER_KEY` | `sk-dev-...` | `sk-uat-...` | `sk-prod-...` | Admin LiteLLM |
| `LITELLM_OPENWEBUI_KEY` | `sk-dev-owui-...` | `sk-uat-owui-...` | `sk-prod-owui-...` | Virtual key OpenWebUI |
| `WEBUI_SECRET_KEY` | hex 32 chars | hex 32 chars | hex 32 chars | Sessions OpenWebUI |
| `OPENAI_API_KEY` | `sk-...` | `sk-...` | `sk-...` | OpenAI |
| `ANTHROPIC_API_KEY` | `sk-ant-...` | `sk-ant-...` | `sk-ant-...` | Anthropic |
| `GEMINI_API_KEY` | `AIza...` | `AIza...` | `AIza...` | Google AI Studio |
