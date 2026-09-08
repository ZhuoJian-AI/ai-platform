.PHONY: help dev dev-fe setup migrate migrate-gen seed test lint dev-db dev-stop

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
