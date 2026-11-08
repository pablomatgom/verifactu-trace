# Task runner of the project: the same commands run locally and in the CI.
#
# Run `make help` to list the targets. The tests need PostgreSQL and Redis; see `make test`.

SERVICES := document-service traceability-service submission-service
PYTHON ?= python

# Limit `make test` to one service: `make test SERVICE=document-service`.
SERVICE ?=
ifneq ($(SERVICE),)
ifeq ($(filter $(SERVICE),$(SERVICES)),)
$(error SERVICE must be one of: $(SERVICES))
endif
endif

# Extra arguments for pytest: `make test PYTEST_ARGS="-x -k invoice"`.
PYTEST_ARGS ?=

.DEFAULT_GOAL := help
.PHONY: help test lint format up down clean

help: ## List the targets
	@grep -hE '^[a-z]+:.*## ' $(MAKEFILE_LIST) | awk -F':.*## ' '{printf "  %-8s %s\n", $$1, $$2}'

# pytest runs once per service, from its own folder: the three services have a package called
# `app`, so running them together would import only one of them. A failing service does not stop
# the others, so one run shows every result, and the target fails at the end.
test: ## Run the tests (needs DATABASE_URL and REDIS_URL; SERVICE=<name> for one service)
	@if [ -z "$$DATABASE_URL" ] || [ -z "$$REDIS_URL" ]; then \
		echo "WARNING: DATABASE_URL or REDIS_URL is not set: the tests that need PostgreSQL" \
			"or Redis will be skipped (they fail in the CI)."; \
	fi
	@status=0; \
	for service in $(or $(SERVICE),$(SERVICES)); do \
		echo "==> $$service"; \
		(cd services/$$service && $(PYTHON) -m pytest $(PYTEST_ARGS)) || status=1; \
	done; \
	exit $$status

lint: ## Check the style and that the code is formatted
	ruff check .
	ruff format --check .

format: ## Format the code and sort the imports
	ruff check --fix .
	ruff format .

.env:
	cp .env.example .env

up: .env ## Build and start the system, waiting until every container is healthy
	docker compose up --build --wait --wait-timeout 180

down: ## Stop the system, keeping its data
	docker compose down

clean: ## Stop the system and delete its data (the volumes)
	docker compose down -v
