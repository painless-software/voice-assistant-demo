# Voice Assistant Demo -- task runner
# Run `just` to see available recipes.
# Requires: uv, just, ngrok (for dev)

set dotenv-load := true
set dotenv-required := true

port := env("PORT", "8080")

# ── Default ────────────────────────────────────────────────────────────────────

# Show this usage screen (default)
@help:
    just --list --unsorted

# ── Setup ──────────────────────────────────────────────────────────────────────

# List all Twilio phone numbers on your account
[group('setup')]
twilio-list:
    uv run --no-project tools/twilio_ops.py --list-numbers

# Buy a new Twilio phone number (PUBLIC_URL must be set in .env)
[group('setup')]
twilio-buy country="CH":
    uv run --no-project tools/twilio_ops.py --buy \
        --country {{ country }} \
        --webhook "${PUBLIC_URL}/voice"

# Update the voice webhook on an existing Twilio number
[group('setup')]
twilio-set-webhook phone=env("TWILIO_PHONE_NUMBER"):
    uv run --no-project tools/twilio_ops.py \
        --update-webhook {{ phone }} "${PUBLIC_URL}/voice"

# List, show, or create a Google Cloud project (use --all to list all projects)
[group('setup')]
gcloud-project project=env("GCP_PROJECT"):
    #!/usr/bin/env bash
    set -euo pipefail
    if [ "{{ project }}" = "--all" ]; then
        gcloud projects list
        echo "Run 'just gcloud-project $(gcloud config get project)' to display details or go to https://console.cloud.google.com/cloud-resource-manager"
    elif gcloud projects describe "{{ project }}" 2>/dev/null; then
        billing_account=$(gcloud billing projects describe "{{ project }}" --format="value(billingAccountName)")
        if [ -n "$billing_account" ]; then
            gcloud billing accounts describe "$billing_account"
        else
            echo "No billing account linked."
        fi
        if gcloud services list --project "{{ project }}" --filter="name:run.googleapis.com" --format="value(name)" | grep -q run; then
            gcloud run services list --project "{{ project }}"
        else
            read -rp "Cloud Run API is not enabled. Enable it? [y/N] " answer
            if [ "$answer" = "y" ] || [ "$answer" = "Y" ]; then
                gcloud services enable run.googleapis.com --project "{{ project }}"
            fi
        fi
        if ! gcloud iam service-accounts describe "github-deploy@{{ project }}.iam.gserviceaccount.com" &>/dev/null; then
            echo "Workload Identity Federation is not set up. Run 'just gcloud-identity {{ project }}' to configure it."
        fi
        echo "See https://console.cloud.google.com/run?project={{ project }} for details."
    else
        read -rp "Project '{{ project }}' not found. Create it? [y/N] " answer
        if [ "$answer" = "y" ] || [ "$answer" = "Y" ]; then
            gcloud projects create "{{ project }}"
            gcloud config set project "{{ project }}"
        fi
    fi

# Set up Workload Identity Federation for GitHub Actions
[group('setup')]
gcloud-identity project=env("GCP_PROJECT"):
    #!/usr/bin/env bash
    set -euo pipefail
    repo=$(gh repo view --json nameWithOwner -q .nameWithOwner)
    project_number=$(gcloud projects describe "{{ project }}" --format="value(projectNumber)")
    echo "Enabling required APIs..."
    gcloud services enable iamcredentials.googleapis.com cloudbuild.googleapis.com artifactregistry.googleapis.com --project="{{ project }}"
    echo "Creating Workload Identity Pool..."
    gcloud iam workload-identity-pools create github-actions \
        --project="{{ project }}" \
        --location=global \
        --display-name="GitHub Actions" 2>/dev/null || true
    echo "Adding GitHub OIDC Provider..."
    gcloud iam workload-identity-pools providers create-oidc github \
        --project="{{ project }}" \
        --location=global \
        --workload-identity-pool=github-actions \
        --issuer-uri="https://token.actions.githubusercontent.com" \
        --attribute-mapping="google.subject=assertion.sub,attribute.repository=assertion.repository" \
        --attribute-condition="assertion.repository=='$repo'" 2>/dev/null || true
    echo "Creating service account..."
    gcloud iam service-accounts create github-deploy \
        --project="{{ project }}" \
        --display-name="GitHub Actions Deploy" 2>/dev/null || true
    sa="github-deploy@{{ project }}.iam.gserviceaccount.com"
    echo "Waiting for service account to propagate..."
    until gcloud iam service-accounts describe "$sa" --project="{{ project }}" &>/dev/null; do sleep 2; done
    echo "Granting IAM roles..."
    for role in roles/run.admin roles/iam.serviceAccountUser roles/cloudbuild.builds.editor roles/artifactregistry.admin roles/storage.admin roles/serviceusage.serviceUsageConsumer roles/secretmanager.secretAccessor; do
        gcloud projects add-iam-policy-binding "{{ project }}" \
            --member="serviceAccount:$sa" \
            --role="$role" --quiet
    done
    echo "Allowing GitHub Actions to impersonate the service account..."
    gcloud iam service-accounts add-iam-policy-binding "$sa" \
        --project="{{ project }}" \
        --member="principalSet://iam.googleapis.com/projects/$project_number/locations/global/workloadIdentityPools/github-actions/attribute.repository/$repo" \
        --role="roles/iam.workloadIdentityUser" --quiet
    provider=$(gcloud iam workload-identity-pools providers describe github \
        --project="{{ project }}" \
        --location=global \
        --workload-identity-pool=github-actions \
        --format="value(name)")
    echo ""
    echo "Run this to configure GitHub Actions:"
    echo "  just github-env $provider $sa"

# Create a Google API key for the Gemini API
[group('setup')]
gcloud-apikey project=env("GCP_PROJECT"):
    #!/usr/bin/env bash
    set -euo pipefail
    echo "Enabling Generative Language API..."
    gcloud services enable generativelanguage.googleapis.com --project "{{ project }}" 2>/dev/null || true
    key_id=$(gcloud services api-keys list --project "{{ project }}" --filter="displayName='Voice Assistant'" --format="value(uid)")
    if [ -z "$key_id" ]; then
        echo "Creating API key..."
        gcloud services api-keys create --display-name="Voice Assistant" --project "{{ project }}"
        key_id=$(gcloud services api-keys list --project "{{ project }}" --filter="displayName='Voice Assistant'" --format="value(uid)")
    else
        echo "API key already exists."
    fi
    if [ -n "$key_id" ]; then
        echo "Restricting key to Generative Language API..."
        gcloud services api-keys update "$key_id" \
            --project "{{ project }}" \
            --api-target=service=generativelanguage.googleapis.com 2>/dev/null || true
    fi
    key_string=$(gcloud services api-keys get-key-string "$key_id" --project "{{ project }}" --format="value(keyString)")
    echo ""
    echo "GOOGLE_API_KEY=$key_string"
    echo "See https://console.cloud.google.com/apis/credentials?project={{ project }}"
    echo "or  https://aistudio.google.com/apikey to verify."

# Push .env secrets to Google Cloud Secret Manager
[group('setup')]
[confirm("This will create/update secrets in Google Cloud Secret Manager. Continue? [y/N]")]
gcloud-secrets project=env("GCP_PROJECT"):
    gcloud services enable secretmanager.googleapis.com --project {{ project }}
    gcloud secrets create TWILIO_ACCOUNT_SID --project {{ project }} 2>/dev/null || true
    gcloud secrets create TWILIO_AUTH_TOKEN --project {{ project }} 2>/dev/null || true
    gcloud secrets create TWILIO_PHONE_NUMBER --project {{ project }} 2>/dev/null || true
    gcloud secrets create GOOGLE_API_KEY --project {{ project }} 2>/dev/null || true
    echo "${TWILIO_ACCOUNT_SID}" | gcloud secrets versions add TWILIO_ACCOUNT_SID --project {{ project }} --data-file=-
    echo "${TWILIO_AUTH_TOKEN}" | gcloud secrets versions add TWILIO_AUTH_TOKEN --project {{ project }} --data-file=-
    echo "${TWILIO_PHONE_NUMBER}" | gcloud secrets versions add TWILIO_PHONE_NUMBER --project {{ project }} --data-file=-
    echo "${GOOGLE_API_KEY}" | gcloud secrets versions add GOOGLE_API_KEY --project {{ project }} --data-file=-
    gcloud projects add-iam-policy-binding "{{ project }}" \
        --member="serviceAccount:$(gcloud projects describe "{{ project }}" --format="value(projectNumber)")-compute@developer.gserviceaccount.com" \
        --role="roles/secretmanager.secretAccessor" --quiet

# Configure GitHub Actions environment for Cloud Run deployment
[group('setup')]
github-env provider service_account:
    gh api repos/{owner}/{repo}/environments/production -X PUT --silent
    gh variable set GCP_WORKLOAD_IDENTITY_PROVIDER --env production --body "{{ provider }}"
    gh variable set GCP_SERVICE_ACCOUNT --env production --body "{{ service_account }}"
    @echo "See https://github.com/$(gh repo view --json nameWithOwner -q .nameWithOwner)/settings/environments"

# Verify that Google Cloud and GitHub are set up for deployment
[group('setup')]
preflight project=env("GCP_PROJECT"):
    #!/usr/bin/env bash
    ok=true
    check() { if "$@" &>/dev/null; then echo "✓ $desc"; else echo "✗ $desc"; ok=false; fi; }
    desc="GCP project exists"
    check gcloud projects describe "{{ project }}"
    desc="Billing account linked"
    check test -n "$(gcloud billing projects describe '{{ project }}' --format='value(billingAccountName)' 2>/dev/null)"
    desc="Cloud Run API enabled"
    check gcloud services list --project "{{ project }}" --filter="name:run.googleapis.com" --format="value(name)" --limit=1
    desc="Cloud Build API enabled"
    check gcloud services list --project "{{ project }}" --filter="name:cloudbuild.googleapis.com" --format="value(name)" --limit=1
    desc="Artifact Registry API enabled"
    check gcloud services list --project "{{ project }}" --filter="name:artifactregistry.googleapis.com" --format="value(name)" --limit=1
    desc="IAM Credentials API enabled"
    check gcloud services list --project "{{ project }}" --filter="name:iamcredentials.googleapis.com" --format="value(name)" --limit=1
    desc="Service account exists"
    check gcloud iam service-accounts describe "github-deploy@{{ project }}.iam.gserviceaccount.com" --project="{{ project }}"
    desc="Workload Identity Pool exists"
    check gcloud iam workload-identity-pools describe github-actions --project="{{ project }}" --location=global
    desc="Workload Identity Provider exists"
    check gcloud iam workload-identity-pools providers describe github --project="{{ project }}" --location=global --workload-identity-pool=github-actions
    desc="Gemini API key exists"
    check bash -c "gcloud services api-keys list --project '{{ project }}' --filter=\"displayName='Voice Assistant'\" --format='value(uid)' | grep -q ."
    desc="Secret Manager API enabled"
    check gcloud services list --project "{{ project }}" --filter="name:secretmanager.googleapis.com" --format="value(name)" --limit=1
    desc="Service account has Secret Manager access"
    check bash -c "gcloud projects get-iam-policy '{{ project }}' --flatten='bindings[].members' --filter='bindings.members:github-deploy@{{ project }}.iam.gserviceaccount.com AND bindings.role:roles/secretmanager.secretAccessor' --format='value(bindings.role)' | grep -q ."
    desc="GitHub environment variables set"
    check bash -c "gh variable list --env production --json name -q '.[].name' | grep -q GCP_WORKLOAD_IDENTITY_PROVIDER"
    echo ""
    if [ "$ok" = true ]; then
        echo "All checks passed. Ready to deploy."
    else
        echo "Some checks failed. Run the corresponding setup recipes to fix."
        exit 1
    fi

# ── Development ────────────────────────────────────────────────────────────────

# ADK web UI (test agent without Twilio)
[group('dev')]
adk: clean
    uv run adk web .

# ADK terminal REPL (test agent without Twilio)
[group('dev')]
repl:
    uv run adk run voice_assistant

# Start the server locally (no ngrok) -- PUBLIC_URL must be set in .env
[group('dev')]
serve:
    uv run python -m voice_assistant

# Start ngrok tunnel + server (full dev flow)
[group('dev')]
dev:
    uv run --no-project tools/ngrok.py

# ── Testing ────────────────────────────────────────────────────────────────────

# Run the test suite
[group('testing')]
test: pytest eval

# Run unit tests with coverage
[group('testing')]
pytest *args:
    uv run pytest --cov {{ args }}

# Run ADK evaluation tests
[group('testing')]
[env("PYTHONWARNINGS", "ignore::UserWarning")]
eval:
    uv run adk eval voice_assistant tests/evals/*.evalset.json \
        --config_file_path tests/evals/test_config.json

# ── Quality ────────────────────────────────────────────────────────────────────

# Run all checks (lint, types)
[group('quality')]
check: lint types

# Type-check with pyright
[group('quality')]
types:
    uv run pyright voice_assistant/

# Lint + format check with ruff
[group('quality')]
lint:
    uvx ruff check voice_assistant/
    uvx ruff format --check voice_assistant/

# Auto-fix lint issues and format in place
[group('quality')]
fmt:
    uvx ruff check --fix voice_assistant/
    uvx ruff format voice_assistant/

# ── Lifecycle ─────────────────────────────────────────────────────────────────

# Clean up Python bytecode, test and build artifacts
[group('lifecycle')]
clean *args:
    uvx pyclean . -d all {{ args }}

# ── Operations ────────────────────────────────────────────────────────────────

# Deploy to Google Cloud Run
[group('ops')]
deploy region="europe-west6":
    gcloud run deploy voice-assistant \
        --source . \
        --region {{ region }} \
        --allow-unauthenticated \
        --memory 1Gi \
        --quiet \
        --set-env-vars "DEFAULT_LANGUAGE=${DEFAULT_LANGUAGE}" \
        --set-secrets "TWILIO_ACCOUNT_SID=TWILIO_ACCOUNT_SID:latest,TWILIO_AUTH_TOKEN=TWILIO_AUTH_TOKEN:latest,TWILIO_PHONE_NUMBER=TWILIO_PHONE_NUMBER:latest,GOOGLE_API_KEY=GOOGLE_API_KEY:latest"
    gcloud run services update voice-assistant \
        --region {{ region }} \
        --update-env-vars "PUBLIC_URL=$(gcloud run services describe voice-assistant --region {{ region }} --format='value(status.url)')" \
        --quiet

# List container images in Artifact Registry
[group('ops')]
images project=env("GCP_PROJECT"):
    gcloud artifacts repositories list --project {{ project }}

# Tail Cloud Run logs in real time
[group('ops')]
logs project=env("GCP_PROJECT"):
    gcloud alpha logging tail --project {{ project }}

# Show Twilio and Google Cloud billing summary
[group('ops')]
balance:
    @echo "── Twilio ──"
    uv run --no-project tools/twilio_ops.py --balance
    @echo ""
    @echo "── Google Cloud ──"
    gcloud billing budgets list --billing-account ${GCP_BILLING_ACCOUNT} \
        --format="table(displayName:label=BILLING_ACCOUNT, amount.specifiedAmount.units:label=BUDGET, amount.specifiedAmount.currencyCode:label=CURRENCY, budgetFilter.calendarPeriod:label=PERIOD, thresholdRules.thresholdPercent.list():label=THRESHOLDS)"
    @echo ""
    @echo "See https://console.cloud.google.com/billing/${GCP_BILLING_ACCOUNT}/reports"
    @echo ""
    @echo "── Gemini (AI Studio) ──"
    @echo "Billed via Google Cloud billing account above."
    @echo "See https://aistudio.google.com/rate-limit?timeRange=last-28-days"
