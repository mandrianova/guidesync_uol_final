SHELL := /bin/sh

COMPOSE ?= docker compose
GOOGLE_APPLICATION_CREDENTIALS_HOST ?= $(if $(GOOGLE_APPLICATION_CREDENTIALS),$(GOOGLE_APPLICATION_CREDENTIALS),$(HOME)/.config/gcloud/application_default_credentials.json)
GOOGLE_CLOUD_PROJECT ?= $(shell gcloud config get-value project 2>/dev/null)
GOOGLE_CLOUD_LOCATION ?= global
TAIL ?= 200
LOG_SERVICES ?= app worker frontend
LMS ?= lms
CURL ?= curl
PYTHON ?= python3
PROJECT ?= Ardor
LM_STUDIO_PORT ?= 1234
LM_STUDIO_BIND ?= 127.0.0.1
LM_STUDIO_BASE_URL ?= http://127.0.0.1:$(LM_STUDIO_PORT)/v1
GUIDESYNC_EMBEDDING_MODEL ?= text-embedding-nomic-embed-text-v1.5
GUIDESYNC_EMBEDDING_CONTEXT_LENGTH ?= 2048
GUIDESYNC_EMBEDDING_HEALTH_TEXT ?= GuideSync embedding health check

export GOOGLE_APPLICATION_CREDENTIALS_HOST
export GOOGLE_CLOUD_PROJECT
export GOOGLE_CLOUD_LOCATION

.DEFAULT_GOAL := help

.PHONY: help config up restart down ps logs logs-all lmstudio-embedding google-adc-check seed-google-models ui-auth-json

help:
	@printf '%s\n' "GuideSync Docker Compose targets:"
	@printf '%s\n' "  make config    Validate Compose with Google ADC mounted"
	@printf '%s\n' "  make up        Build and start the full local stack with Google ADC mounted"
	@printf '%s\n' "  make restart   Recreate the full stack with Google ADC mounted"
	@printf '%s\n' "  make down      Stop containers without deleting named volumes"
	@printf '%s\n' "  make ps        Show service status"
	@printf '%s\n' "  make logs      Follow app, worker, and frontend logs"
	@printf '%s\n' "  make logs-all  Follow all Compose service logs"
	@printf '%s\n' "  make lmstudio-embedding Start and verify the local LM Studio embedding model"
	@printf '%s\n' "  make seed-google-models Seed Google role profiles in Postgres"
	@printf '%s\n' "  make ui-auth-json Update a project's saved UI accessToken"

config: google-adc-check
	$(COMPOSE) config

up: google-adc-check
	$(COMPOSE) up -d --build --remove-orphans

restart: google-adc-check
	$(COMPOSE) down --remove-orphans
	$(COMPOSE) up -d --build --remove-orphans

down:
	$(COMPOSE) down --remove-orphans

ps:
	$(COMPOSE) ps

logs:
	$(COMPOSE) logs -f --tail=$(TAIL) $(LOG_SERVICES)

logs-all:
	$(COMPOSE) logs -f --tail=$(TAIL)

lmstudio-embedding:
	@command -v $(LMS) >/dev/null || { printf '%s\n' "LM Studio CLI not found: $(LMS)"; exit 1; }
	$(LMS) server start --port $(LM_STUDIO_PORT) --bind $(LM_STUDIO_BIND)
	@if $(LMS) ps | grep -Fq "$(GUIDESYNC_EMBEDDING_MODEL)"; then \
		printf '%s\n' "LM Studio embedding model already loaded: $(GUIDESYNC_EMBEDDING_MODEL)"; \
	else \
		$(LMS) load $(GUIDESYNC_EMBEDDING_MODEL) \
			--identifier $(GUIDESYNC_EMBEDDING_MODEL) \
			--context-length $(GUIDESYNC_EMBEDDING_CONTEXT_LENGTH) \
			-y; \
	fi
	@$(CURL) --fail --silent --show-error "$(LM_STUDIO_BASE_URL)/embeddings" \
		-H "Content-Type: application/json" \
		-d '{"model":"$(GUIDESYNC_EMBEDDING_MODEL)","input":"$(GUIDESYNC_EMBEDDING_HEALTH_TEXT)"}' \
		>/dev/null
	@printf '%s\n' "LM Studio embeddings ready for GuideSync: http://host.docker.internal:$(LM_STUDIO_PORT)/v1"

google-adc-check:
	@test -f "$(GOOGLE_APPLICATION_CREDENTIALS_HOST)" || { \
		printf '%s\n' "Missing Google ADC JSON: $(GOOGLE_APPLICATION_CREDENTIALS_HOST)"; \
		printf '%s\n' "Run: gcloud auth application-default login"; \
		exit 1; \
	}
	@test -n "$(GOOGLE_CLOUD_PROJECT)" && test "$(GOOGLE_CLOUD_PROJECT)" != "(unset)" || { \
		printf '%s\n' "Set GOOGLE_CLOUD_PROJECT or run: gcloud config set project <project-id>"; \
		exit 1; \
	}

seed-google-models: google-adc-check
	$(COMPOSE) run --rm app uv run python -m guidesync_agent.google_model_profiles

ui-auth-json:
	@$(PYTHON) scripts/ui_auth/export_project_auth.py --project "$(PROJECT)"
