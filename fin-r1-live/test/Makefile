# Makefile for running tests

.PHONY: test test-unit test-integration test-coverage test-ci clean help

# Default target
.DEFAULT_GOAL := help

# Variables
PYTEST = pytest
COVERAGE = coverage
TEST_DIR = test
COVERAGE_THRESHOLD = 99

help: ## Show this help message
	@echo "Available commands:"
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | awk 'BEGIN {FS = ":.*?## "}; {printf "  \033[36m%-20s\033[0m %s\n", $$1, $$2}'

test: ## Run all tests
	$(PYTEST) $(TEST_DIR) -v

test-unit: ## Run unit tests only
	$(PYTEST) $(TEST_DIR)/test_api_middleware $(TEST_DIR)/test_data_hub -v -m "not integration and not slow"

test-integration: ## Run integration tests only
	$(PYTEST) $(TEST_DIR)/test_integration -v -m integration

test-coverage: ## Run tests with coverage report
	$(PYTEST) $(TEST_DIR) -v \
		--cov=. \
		--cov-report=term-missing \
		--cov-report=html:$(TEST_DIR)/coverage_html \
		--cov-report=xml:$(TEST_DIR)/coverage.xml \
		--cov-fail-under=$(COVERAGE_THRESHOLD)

test-ci: ## Run tests for CI (no interactive)
	$(PYTEST) $(TEST_DIR) -v \
		--cov=. \
		--cov-report=xml:$(TEST_DIR)/coverage.xml \
		--cov-fail-under=$(COVERAGE_THRESHOLD) \
		--junitxml=$(TEST_DIR)/results/junit.xml \
		-p no:warnings

test-parallel: ## Run tests in parallel
	$(PYTEST) $(TEST_DIR) -v -n auto

test-debug: ## Run tests with debugging
	$(PYTEST) $(TEST_DIR) -v --pdb --pdbcls=IPython.terminal.debugger:TerminalPdb

test-specific: ## Run specific test file (use: make test-specific TEST_FILE=test_main.py)
	$(PYTEST) $(TEST_DIR)/$(TEST_FILE) -v

test-specific-k: ## Run specific test by keyword (use: make test-specific-k KEYWORD=test_name)
	$(PYTEST) $(TEST_DIR) -v -k $(KEYWORD)

test-missing: ## Show which lines are missing coverage
	$(PYTEST) $(TEST_DIR) -v --cov=. --cov-report=term-missing

coverage-report: ## Generate HTML coverage report
	$(COVERAGE) html -d $(TEST_DIR)/coverage_html
	@echo "Coverage report generated at: $(TEST_DIR)/coverage_html/index.html"

coverage-view: ## Open coverage report in browser (macOS)
	open $(TEST_DIR)/coverage_html/index.html

clean: ## Clean test artifacts
	rm -rf $(TEST_DIR)/__pycache__
	rm -rf $(TEST_DIR)/*/__pycache__
	rm -rf $(TEST_DIR)/.pytest_cache
	rm -rf $(TEST_DIR)/coverage_html
	rm -f $(TEST_DIR)/coverage.xml
	rm -f $(TEST_DIR)/.coverage
	rm -f $(TEST_DIR)/results/*.xml
	rm -f $(TEST_DIR)/results/*.html
	rm -rf .pytest_cache
	find . -type d -name __pycache__ -exec rm -rf {} + 2>/dev/null || true

docker-test: ## Run tests in Docker container
	docker build -f test/Dockerfile -t finr1-test:latest .
	docker run --rm -v $(PWD)/test/results:/test/results finr1-test:latest

docker-test-shell: ## Run interactive shell in test container
	docker build -f test/Dockerfile -t finr1-test:latest .
	docker run --rm -it -v $(PWD)/test/results:/test/results finr1-test:latest /bin/bash

lint: ## Run linting checks
	flake8 api-middleware data-hub --max-line-length=120 --ignore=E501,W503
	black --check api-middleware data-hub
	isort --check-only api-middleware data-hub

format: ## Format code
	black api-middleware data-hub
	isort api-middleware data-hub

type-check: ## Run type checking
	mypy api-middleware data-hub --ignore-missing-imports
