SHELL := /bin/bash

.PHONY: dev dev-down docker-up docker-down logs

dev:
	./scripts/dev-up.sh

dev-down:
	./scripts/dev-down.sh

docker-up:
	docker compose up -d --build

docker-down:
	docker compose down

logs:
	@echo "Backend log:"
	@tail -n 40 .run/backend.log 2>/dev/null || true
	@echo
	@echo "Frontend log:"
	@tail -n 40 .run/frontend.log 2>/dev/null || true
