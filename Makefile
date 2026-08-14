.PHONY: help dev dev-fe setup migrate migrate-gen seed test lint dev-db dev-stop mock-up mock-up-bg mock-stop mock-export mock-seed

help: ## Show this help
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | sort | awk 'BEGIN {FS = ":.*?## "}; {printf "\033[36m%-20s\033[0m %s\n", $$1, $$2}'

setup: ## Install backend dependencies
	cd llm_router/backend && pip install -e ".[dev]"

dev: ## Start development environment (docker compose up)
	docker compose up -d postgres redis
	cd llm_router/backend && uvicorn app.main:app --reload --port 8000

dev-fe: ## Start the platform console (Vite dev server)
	cd frontend && npm run dev

migrate: ## Run database migrations
	cd llm_router/backend && alembic upgrade head

migrate-gen: ## Generate a new migration
	cd llm_router/backend && alembic revision --autogenerate -m "$(msg)"

seed: ## Import preset demo data (idempotent)
	cd llm_router/backend && python scripts/seed_preset_data.py

test: ## Run tests
	cd llm_router/backend && pytest tests/ -v --tb=short

lint: ## Run linter
	cd llm_router/backend && ruff check app/ tests/

dev-db: ## Start only postgres & redis
	docker compose up -d postgres redis

dev-stop: ## Stop all services
	docker compose down

mock-up: ## Start the mock gateway (MES/CRM/...) in foreground on :8010
	cd mock && python -m mock

mock-up-bg: ## Start the mock gateway in background on :8010
	cd mock && nohup python -m mock > /tmp/ai_infra_mock.log 2>&1 & echo "mock started (pid=$$!), log=/tmp/ai_infra_mock.log"

mock-stop: ## Stop the background mock gateway
	@pkill -f "python -m mock" || true

mock-export: ## Export mock OpenAPI snapshots to mock/openapi/
	cd mock && python -m mock openapi

mock-seed: ## Register mock systems as connectors/interfaces/skills (idempotent, needs mock-up)
	cd llm_router/backend && python scripts/seed_mock_connectors.py
