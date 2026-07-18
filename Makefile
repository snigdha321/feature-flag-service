.PHONY: help venv install install-prod run migrate revision test lint typecheck fmt cov up down build clean

help: ## Show this help
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | \
		awk 'BEGIN {FS = ":.*?## "}; {printf "  \033[36m%-12s\033[0m %s\n", $$1, $$2}'

venv: ## Create a local virtual environment in .venv
	python3 -m venv .venv
	@echo "Activate with: source .venv/bin/activate"

install: ## Install runtime + dev dependencies (from requirements-dev.txt)
	pip install -r requirements-dev.txt

install-prod: ## Install runtime dependencies only (from requirements.txt)
	pip install -r requirements.txt

run: ## Run the API locally with autoreload
	uvicorn app.main:app --reload --host 0.0.0.0 --port 8000

migrate: ## Apply database migrations
	alembic upgrade head

revision: ## Autogenerate a new migration (make revision m="message")
	alembic revision --autogenerate -m "$(m)"

test: ## Run the test suite
	pytest

cov: ## Run tests with coverage report
	pytest --cov=app --cov-report=html --cov-report=term-missing

lint: ## Lint + format check with ruff (whole repo, matches CI)
	ruff check --output-format=github .
	ruff format --check .

fmt: ## Auto-format / fix with ruff (whole repo)
	ruff check --fix .
	ruff format .

typecheck: ## Static type-check with mypy
	mypy app

up: ## Start the full stack (Postgres + API) via docker compose
	docker compose up --build

down: ## Stop the stack and remove volumes
	docker compose down -v

build: ## Build the Docker image
	docker build -t feature-flag-service:local .

clean: ## Remove caches and build artifacts
	rm -rf .pytest_cache .mypy_cache .ruff_cache htmlcov .coverage coverage.xml
	find . -type d -name __pycache__ -exec rm -rf {} +
