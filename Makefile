PYTHON := PYTHONPATH=. python

.PHONY: help setup install test test-coverage run-api run-worker clean \
        db-init migrate migrate-auth migrate-phase2 \
        generate-data recover lint docs logs \
        create-admin token \
        install-ui run-ui build-ui \
        dev build-docker deploy railway-logs secret fmt

help:
	@echo "AutonomousSDR - Available Commands"
	@echo ""
	@echo "Setup & Installation:"
	@echo "  make setup            - Full setup (install deps + run all migrations)"
	@echo "  make install          - Install Python dependencies"
	@echo "  make install-ui       - Install frontend npm dependencies"
	@echo "  make db-init          - Initialize core database tables"
	@echo "  make migrate          - Run all migrations in order"
	@echo "  make migrate-auth     - Run Phase 3 auth migration (users, api_keys)"
	@echo ""
	@echo "Development:"
	@echo "  make run-api          - Start FastAPI server (port 8000)"
	@echo "  make run-worker       - Start background worker"
	@echo "  make run-ui           - Start frontend dev server (port 3000)"
	@echo "  make build-ui         - Build frontend for production"
	@echo "  make test             - Run all tests (fast, in-memory DB)"
	@echo "  make test-coverage    - Run tests with HTML coverage report"
	@echo ""
	@echo "Auth Utilities:"
	@echo "  make create-admin     - Seed initial admin user (EMAIL= PASSWORD=)"
	@echo "  make token            - Get a login token (EMAIL= PASSWORD=)"
	@echo ""
	@echo "Utilities:"
	@echo "  make generate-data    - Generate 100 test leads"
	@echo "  make clean            - Remove cache files and .pyc"
	@echo "  make lint             - Run code linting"
	@echo "  make docs             - Show API docs URLs"
	@echo "  make logs             - Show log locations"

# ---------------------------------------------------------------------------
# Setup
# ---------------------------------------------------------------------------

setup: install migrate
	@echo "✓ Setup complete — run 'make run-api' and 'make run-worker' in separate terminals"

install:
	pip install -r requirements.txt

# ---------------------------------------------------------------------------
# Migrations (run in order)
# ---------------------------------------------------------------------------

db-init:
	$(PYTHON) scripts/init_db.py

migrate: db-init migrate-phase2-fields migrate-auth
	@echo "✓ All migrations applied"

migrate-phase2-fields:
	$(PYTHON) scripts/migrate_phase2_fields.py

migrate-auth:
	$(PYTHON) scripts/migrate_auth.py

# ---------------------------------------------------------------------------
# Run
# ---------------------------------------------------------------------------

run-api:
	python -m uvicorn app.main:app --reload --host 0.0.0.0 --port 8000

run-worker:
	python -m app.worker.lead_worker

# ---------------------------------------------------------------------------
# Frontend
# ---------------------------------------------------------------------------

install-ui:
	cd frontend && npm install

run-ui:
	cd frontend && npm run dev

build-ui:
	cd frontend && npm run build

# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

test:
	TESTING=1 pytest tests/ -v

test-coverage:
	TESTING=1 pytest tests/ --cov=app --cov-report=html --cov-report=term
	@echo "✓ Coverage report: htmlcov/index.html"

# ---------------------------------------------------------------------------
# Auth utilities
# ---------------------------------------------------------------------------

# Usage: make create-admin EMAIL=admin@company.com PASSWORD=yourpassword
create-admin:
	$(PYTHON) scripts/create_admin.py

# Usage: make token EMAIL=admin@company.com PASSWORD=yourpassword
token:
	$(PYTHON) scripts/get_token.py

# ---------------------------------------------------------------------------
# Utilities
# ---------------------------------------------------------------------------

generate-data:
	$(PYTHON) scripts/generate_test_data.py

recover:
	$(PYTHON) scripts/recover_leads.py

clean:
	find . -type f -name "*.pyc" -delete
	find . -type d -name "__pycache__" -delete
	find . -type d -name ".pytest_cache" -delete
	find . -type f -name ".coverage" -delete
	find . -type d -name "htmlcov" -delete

lint:
	python -m flake8 app tests --max-line-length=120 --exclude=venv

docs:
	@echo "API docs (server must be running):"
	@echo "  Swagger UI : http://localhost:8000/docs"
	@echo "  ReDoc      : http://localhost:8000/redoc"
	@echo ""
	@echo "Auth endpoints:"
	@echo "  POST /auth/register    - Create account"
	@echo "  POST /auth/login       - Get tokens"
	@echo "  POST /auth/refresh     - Refresh access token"
	@echo "  GET  /auth/me          - Current user"
	@echo "  POST /auth/api-keys    - Create API key"

logs:
	@echo "Log locations:"
	@echo "  API logs    : stdout of 'make run-api'"
	@echo "  Worker logs : stdout of 'make run-worker'"
	@echo "  DB logs     : /var/log/postgresql/"

# ---------------------------------------------------------------------------
# Docker Compose (full stack — no local deps needed)
# ---------------------------------------------------------------------------

dev:
	docker compose up --build

build-docker:
	docker compose build

seed-docker:
	docker compose run --rm migrate python scripts/seed_demo_data.py

# ---------------------------------------------------------------------------
# Railway deployment
# ---------------------------------------------------------------------------

deploy:
	railway up

railway-logs:
	railway logs

# ---------------------------------------------------------------------------
# Code quality
# ---------------------------------------------------------------------------

fmt:
	ruff format app/ tests/

# ---------------------------------------------------------------------------
# Security helpers
# ---------------------------------------------------------------------------

secret:
	@python -c "import secrets; print(secrets.token_hex(32))"
