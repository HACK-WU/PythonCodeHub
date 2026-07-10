# CODEBUDDY.md

This file provides guidance to CodeBuddy Code when working with code in this repository.

## Project Overview

PythonCodeHub is a repository of reusable Python code snippets for daily development. It's designed to provide a centralized, verified code library to avoid duplicate code across projects.

## Development Commands

### Environment Setup

```bash
# Install dependencies (recommended)
uv sync

# Or install with pip
pip install -e .
```

### Code Quality & Linting

```bash
# Run pre-commit hooks on all files
pre-commit run --all-files

# Run Ruff linter with auto-fix
ruff check --fix .

# Run Ruff formatter
ruff format .

# Check specific file types
pre-commit run ruff --all-files
pre-commit run codespell --all-files
```

### Testing

```bash
# Run all tests
pytest

# Run tests with verbose output
pytest -v

# Run tests for a specific module
pytest tests/test_http_client/
pytest tests/test_distributed_lock/

# Run a single test file
pytest tests/test_http_client/test_client.py

# Run a specific test class or function
pytest tests/test_http_client/test_client.py::TestClient::test_request
pytest tests/test_http_client/test_client.py::TestClient::test_request -v

# Run tests with coverage (default threshold: 90%)
pytest --cov=http_client --cov-report=term-missing

# Run tests with specific markers
pytest -m unit
pytest -m slow
pytest -m redis
pytest -m celery
pytest -m network

# Run tests in parallel (faster)
pytest -n auto
```

### Git Workflow

Follow Conventional Commits:
```bash
# Format: <type>(<scope>): <subject>
git commit -m "feat(hash): add MD5 hash utility"
git commit -m "fix(string): fix string truncation issue"
git commit -m "docs: update README"
```

Allowed types: `feat`, `fix`, `docs`, `style`, `refactor`, `test`, `chore`, `perf`, `ci`, `build`, `revert`, `release`, `merge`

## Architecture

### Directory Structure

The project is organized into independent, reusable Python modules:

- **`ab_*` modules**: Atomic, reusable code libraries by category
  - `ab_cache/` - Caching utilities
  - `ab_celery/` - Celery task queue utilities
  - `ab_elasticsearch/` - Elasticsearch helpers
  - `ab_hash/` - Hashing utilities
  - `ab_thread/` - Thread/coroutine-local storage (Werkzeug-style `Local`)
  - `ab_lock/` - Distributed locking mechanisms
  - `ab_object/` - Object utilities
  - `ab_redis/` - Redis utilities
  - `ab_string/` - String manipulation

- **`http_client/`**: Core HTTP client framework with pluggable architecture
  - `client.py` - BaseClient, DRFClient, CacheClient implementations
  - `cache.py` - In-memory (LRU) and Redis cache backends
  - `async_executor.py` - Thread pool and Celery async executors
  - `parser.py` - Response parsers (JSON, Content, Raw, File, Stream)
  - `formatter.py` - Response formatters
  - `validator.py` - Request/response validators
  - `serializer.py` - DRF serializer integration
  - `exceptions.py` - Exception hierarchy

- **`tsdetect/`**: Time series detection module
  - `algorithms/` - Detection algorithms (ring_ratio, amplitude, threshold, etc.)
  - `core/` - Base classes and interfaces
  - `units/` - Unit handling

- **`tests/`**: Test suite organized by module
  - `conftest.py` - Pytest configuration
  - Test directories mirror source structure

### Key Design Patterns

1. **Pluggable Architecture** (http_client): Components like parsers, formatters, validators, and executors can be replaced via class attributes
2. **Dependency Injection** (ab_lock): Redis clients injected via constructor, supporting mocks and custom implementations
3. **Protocol-based Interfaces**: Uses `typing.Protocol` for loose coupling (see `ab_lock/protocols.py`)
4. **Context Managers**: Locks and HTTP clients support `with` statements for automatic resource cleanup

### Testing Patterns

- Tests use `pytest` with markers: `unit`, `slow`, `redis`, `celery`, `network`
- Mock dependencies: `pytest-mock`, `requests-mock`, `responses`, `fakeredis`
- Coverage requirement: 90% minimum for `http_client`
- Test files follow `test_*.py` naming convention
- Test classes use `Test*` prefix
- Test functions use `test_*` prefix

### Code Style

- Line length: 120 characters
- Linting: Ruff (E4, E7, E9, F, UP rules)
- Formatting: Ruff format
- Commit messages: Conventional Commits format (enforced by commitlint)

## Important Files

- `pyproject.toml` - Project configuration, dependencies, tool settings
- `.pre-commit-config.yaml` - Pre-commit hooks configuration
- `.commitlintrc.json` - Commit message validation rules
- `http_client/README.md` - Comprehensive HTTP client documentation
- `ab_lock/distributed_lock/README.md` - Distributed lock module documentation

## Common Tasks

### Adding a New Code Module

1. Create directory: `ab_<name>/`
2. Add `__init__.py` with exports
3. Implement utilities in `utils.py` or similar
4. Add tests in `tests/test_<name>/`
5. Update `pyproject.toml` if new dependencies needed

### Working with HTTP Client

```python
from http_client import BaseClient, JSONResponseParser

class MyClient(BaseClient):
    base_url = "https://api.example.com"
    endpoint = "/users/{user_id}"
    response_parser_class = JSONResponseParser

# Single request
result = MyClient.request({"user_id": 123})

# Batch request with concurrency
results = MyClient.request([
    {"user_id": i} for i in range(10)
], is_async=True)
```

### Working with Distributed Locks

```python
import redis
from ab_lock.distributed_lock import RedisLock

client = redis.StrictRedis(host="127.0.0.1", port=6379, decode_responses=True)

# With context manager (recommended)
with RedisLock("resource:123", client=client, ttl=30):
    do_critical_work()

# Manual acquire/release
lock = RedisLock("resource:123", client=client, ttl=30)
if lock.acquire(wait=1.0):
    try:
        do_critical_work()
    finally:
        lock.release()
```
