# Infisical — Runbook

Gestion des secrets pour les environnements dev / UAT / prod.
Remplace chaque `<PLACEHOLDER>` par la valeur réelle avant d'exécuter.

---

## Sommaire

1. [Installer le serveur Infisical (self-hosted)](#1-installer-le-serveur-infisical-self-hosted)
2. [Installer le CLI (par développeur)](#2-installer-le-cli-par-développeur)
3. [Initialiser le projet dans le repo](#3-initialiser-le-projet-dans-le-repo)
4. [Peupler les secrets par environnement](#4-peupler-les-secrets-par-environnement)
5. [Machine Identity (déploiements serveur / CI-CD)](#5-machine-identity-déploiements-serveur--ci-cd)
6. [Lancer docker-compose par environnement](#6-lancer-docker-compose-par-environnement)

---

## 1. Installer le serveur Infisical (self-hosted)

> À faire une seule fois sur ton serveur.

```bash
# Récupérer le docker-compose officiel
curl -o docker-compose.infisical.yml \
  https://raw.githubusercontent.com/Infisical/infisical/main/docker-compose.prod.yml

# Créer le fichier d'environnement
cp .env.example .env   # fourni dans le même repo Infisical

# Variables minimales à renseigner dans .env :
#   ENCRYPTION_KEY   → générer : openssl rand -hex 16
#   AUTH_SECRET      → générer : openssl rand -hex 32
#   DB_CONNECTION_URI=postgresql://<USER>:<PASSWORD>@<HOST>:5432/<DB>
#   REDIS_URL=redis://<HOST>:6379
#   SITE_URL=https://<TON_DOMAINE>

# Démarrer
docker compose -f docker-compose.infisical.yml up -d
```

Ouvre `https://<TON_DOMAINE>` dans le navigateur pour créer le compte admin et le premier projet.

---

## 2. Installer le CLI (par développeur)

```bash
# macOS
brew install infisical/get-cli/infisical

# Linux
curl -1sLf 'https://dl.cloudsmith.io/public/infisical/infisical-cli/setup.deb.sh' | sudo bash
sudo apt-get install -y infisical

# Vérifier
infisical --version
```

### Se connecter à l'instance self-hosted

```bash
# Pointe vers ton serveur (à faire une seule fois par machine)
infisical login --domain=https://<TON_DOMAINE>
```

Un navigateur s'ouvre pour s'authentifier. Sur un serveur sans UI :

```bash
infisical login \
  --domain=https://<TON_DOMAINE> \
  --method=universal-auth \
  --client-id=<MACHINE_CLIENT_ID> \
  --client-secret=<MACHINE_CLIENT_SECRET> \
  --plain
```

---

## 3. Initialiser le projet dans le repo

> À faire une seule fois par développeur, dans la racine du repo.

```bash
infisical init
# → sélectionner l'organisation et le projet créé sur l'UI
# → génère .infisical.json (à committer)
```

Le fichier `.infisical.json` créé ressemble à :

```json
{
  "workspaceId": "<PROJECT_ID>"
}
```

---

## 4. Peupler les secrets par environnement

Les environnements Infisical correspondent à : `dev`, `staging` (UAT), `prod`.

### 4a. Import depuis un fichier .env (le plus rapide)

```bash
# Dev
infisical secrets set --file=.env.development --env=dev

# UAT
infisical secrets set --file=.env.uat --env=staging

# Prod
infisical secrets set --file=.env.production --env=prod
```

### 4b. Clé par clé en CLI

```bash
# Dev
infisical secrets set \
  LITELLM_MASTER_KEY=<sk-dev-...> \
  LITELLM_OPENWEBUI_KEY=<sk-dev-owui-...> \
  WEBUI_SECRET_KEY=<hex-32-chars> \
  OPENAI_API_KEY=<sk-...> \
  ANTHROPIC_API_KEY=<sk-ant-...> \
  GEMINI_API_KEY=<AIza...> \
  --env=dev

# UAT — mêmes clés, valeurs différentes
infisical secrets set \
  LITELLM_MASTER_KEY=<sk-uat-...> \
  LITELLM_OPENWEBUI_KEY=<sk-uat-owui-...> \
  WEBUI_SECRET_KEY=<hex-32-chars> \
  OPENAI_API_KEY=<sk-...> \
  ANTHROPIC_API_KEY=<sk-ant-...> \
  GEMINI_API_KEY=<AIza...> \
  --env=staging

# Prod
infisical secrets set \
  LITELLM_MASTER_KEY=<sk-prod-...> \
  LITELLM_OPENWEBUI_KEY=<sk-prod-owui-...> \
  WEBUI_SECRET_KEY=<hex-32-chars> \
  OPENAI_API_KEY=<sk-...> \
  ANTHROPIC_API_KEY=<sk-ant-...> \
  GEMINI_API_KEY=<AIza...> \
  --env=prod
```

### 4c. Script Python (bulk, programmatique)

Utile pour automatiser ou pour seeder depuis une source existante.

```bash
pip install infisical-python
```

```python
# infisical/seed_secrets.py
# Usage : python infisical/seed_secrets.py --env dev
import argparse
from infisical_client import InfisicalClient, ClientSettings, AuthenticationOptions, UniversalAuthMethod

INFISICAL_URL   = "https://<TON_DOMAINE>"
PROJECT_ID      = "<PROJECT_ID>"
CLIENT_ID       = "<MACHINE_CLIENT_ID>"
CLIENT_SECRET   = "<MACHINE_CLIENT_SECRET>"

# Secrets par environnement — remplacer les valeurs
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

    client = InfisicalClient(ClientSettings(
        auth=AuthenticationOptions(
            universal_auth=UniversalAuthMethod(
                client_id=CLIENT_ID,
                client_secret=CLIENT_SECRET,
            )
        ),
        site_url=INFISICAL_URL,
    ))

    for key, value in SECRETS[args.env].items():
        client.secrets().create(
            secret_name=key,
            secret_value=value,
            project_id=PROJECT_ID,
            environment_slug=args.env,
            secret_path="/",
        )
        print(f"  ✓ {key}")

    print(f"\nSecrets seedés pour l'environnement : {args.env}")

if __name__ == "__main__":
    main()
```

---

## 5. Machine Identity (déploiements serveur / CI-CD)

> Permet d'authentifier un serveur ou un pipeline sans compte utilisateur.

### Créer une Machine Identity

1. Aller dans **Infisical UI → Project → Access Control → Machine Identities**
2. Créer une identité (ex: `deploy-server`)
3. Lui donner le rôle **Developer** (ou **Member**) sur le projet
4. Générer un **Client ID** et un **Client Secret**
5. Stocker ces deux valeurs en lieu sûr — le Client Secret n'est affiché qu'une fois

### Obtenir un access token depuis le serveur

```bash
export INFISICAL_TOKEN=$(infisical login \
  --domain=https://<TON_DOMAINE> \
  --method=universal-auth \
  --client-id=<MACHINE_CLIENT_ID> \
  --client-secret=<MACHINE_CLIENT_SECRET> \
  --plain \
  --silent)
```

Ce token est temporaire (TTL configurable). À régénérer au besoin ou via un wrapper de démarrage.

---

## 6. Lancer docker-compose par environnement

### Développement (local, login navigateur)

```bash
# Depuis la racine du repo
infisical run --env=dev \
  -- docker compose -f litellm/docker-compose.dev.yml up -d
```

### UAT (serveur, machine identity)

```bash
export INFISICAL_TOKEN=$(infisical login \
  --domain=https://<TON_DOMAINE> \
  --method=universal-auth \
  --client-id=<MACHINE_CLIENT_ID> \
  --client-secret=<MACHINE_CLIENT_SECRET> \
  --plain --silent)

infisical run \
  --token=$INFISICAL_TOKEN \
  --projectId=<PROJECT_ID> \
  --env=staging \
  -- docker compose -f litellm/docker-compose.uat.yml up -d
```

### Prod (serveur, machine identity)

```bash
export INFISICAL_TOKEN=$(infisical login \
  --domain=https://<TON_DOMAINE> \
  --method=universal-auth \
  --client-id=<MACHINE_CLIENT_ID> \
  --client-secret=<MACHINE_CLIENT_SECRET> \
  --plain --silent)

infisical run \
  --token=$INFISICAL_TOKEN \
  --projectId=<PROJECT_ID> \
  --env=prod \
  -- docker compose -f litellm/docker-compose.prod.yml up -d
```

### Wrapper pratique (optionnel)

Pour éviter de retaper la commande complète, créer `infisical/deploy.sh` :

```bash
#!/usr/bin/env bash
# Usage : ./infisical/deploy.sh dev | uat | prod
set -euo pipefail

ENV=${1:?Usage: $0 [dev|uat|prod]}

COMPOSE_FILES=( [dev]="litellm/docker-compose.dev.yml" [uat]="litellm/docker-compose.uat.yml" [prod]="litellm/docker-compose.prod.yml" )
INFISICAL_ENVS=( [dev]="dev" [uat]="staging" [prod]="prod" )

COMPOSE_FILE=${COMPOSE_FILES[$ENV]}
INFISICAL_ENV=${INFISICAL_ENVS[$ENV]}

if [[ "$ENV" == "dev" ]]; then
  # Dev : login interactif
  infisical run --env="$INFISICAL_ENV" \
    -- docker compose -f "$COMPOSE_FILE" up -d
else
  # UAT / Prod : machine identity
  TOKEN=$(infisical login \
    --domain=https://<TON_DOMAINE> \
    --method=universal-auth \
    --client-id="${INFISICAL_MACHINE_CLIENT_ID:?}" \
    --client-secret="${INFISICAL_MACHINE_CLIENT_SECRET:?}" \
    --plain --silent)

  infisical run \
    --token="$TOKEN" \
    --projectId="<PROJECT_ID>" \
    --env="$INFISICAL_ENV" \
    -- docker compose -f "$COMPOSE_FILE" up -d
fi

echo "✓ Stack $ENV démarrée"
```

```bash
chmod +x infisical/deploy.sh

# Utilisation
./infisical/deploy.sh dev
./infisical/deploy.sh uat
./infisical/deploy.sh prod
```

> Pour UAT et Prod, exporter `INFISICAL_MACHINE_CLIENT_ID` et `INFISICAL_MACHINE_CLIENT_SECRET`
> sur le serveur avant d'appeler le script (via les secrets du CI/CD ou un fichier système).

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
