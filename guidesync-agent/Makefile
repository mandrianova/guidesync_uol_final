SHELL := /bin/sh

COMPOSE ?= docker compose
TAIL ?= 200
LOG_SERVICES ?= app worker frontend
LMS ?= lms
CURL ?= curl
LM_STUDIO_PORT ?= 1234
LM_STUDIO_BIND ?= 127.0.0.1
LM_STUDIO_BASE_URL ?= http://127.0.0.1:$(LM_STUDIO_PORT)/v1
GUIDESYNC_EMBEDDING_MODEL ?= text-embedding-nomic-embed-text-v1.5
GUIDESYNC_EMBEDDING_CONTEXT_LENGTH ?= 2048
GUIDESYNC_EMBEDDING_HEALTH_TEXT ?= GuideSync embedding health check

.DEFAULT_GOAL := help

.PHONY: help config up restart down ps logs logs-all lmstudio-embedding

help:
	@printf '%s\n' "GuideSync Docker Compose targets:"
	@printf '%s\n' "  make config    Validate the resolved Docker Compose configuration"
	@printf '%s\n' "  make up        Build and start the full local stack"
	@printf '%s\n' "  make restart   Recreate the full stack after code/config changes"
	@printf '%s\n' "  make down      Stop containers without deleting named volumes"
	@printf '%s\n' "  make ps        Show service status"
	@printf '%s\n' "  make logs      Follow app, worker, and frontend logs"
	@printf '%s\n' "  make logs-all  Follow all Compose service logs"
	@printf '%s\n' "  make lmstudio-embedding Start and verify the local LM Studio embedding model"

config:
	$(COMPOSE) config

up:
	$(COMPOSE) up -d --build --remove-orphans

restart:
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
