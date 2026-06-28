SHELL := /bin/sh

COMPOSE ?= docker compose
TAIL ?= 200
LOG_SERVICES ?= app worker frontend

.DEFAULT_GOAL := help

.PHONY: help config up restart down ps logs logs-all

help:
	@printf '%s\n' "GuideSync Docker Compose targets:"
	@printf '%s\n' "  make config    Validate the resolved Docker Compose configuration"
	@printf '%s\n' "  make up        Build and start the full local stack"
	@printf '%s\n' "  make restart   Recreate the full stack after code/config changes"
	@printf '%s\n' "  make down      Stop containers without deleting named volumes"
	@printf '%s\n' "  make ps        Show service status"
	@printf '%s\n' "  make logs      Follow app, worker, and frontend logs"
	@printf '%s\n' "  make logs-all  Follow all Compose service logs"

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
