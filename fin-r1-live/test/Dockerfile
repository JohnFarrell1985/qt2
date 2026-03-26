# Test environment Dockerfile
# Creates a container for running all tests with coverage

FROM python:3.9-slim

WORKDIR /test

# Install system dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc \
    g++ \
    libpq-dev \
    curl \
    git \
    && rm -rf /var/lib/apt/lists/*

# Copy project requirements
COPY api-middleware/requirements.txt /tmp/api-requirements.txt
COPY data-hub/requirements.txt /tmp/data-requirements.txt
COPY test/requirements.txt /tmp/test-requirements.txt

# Install all dependencies
RUN pip install --no-cache-dir -r /tmp/api-requirements.txt \
    && pip install --no-cache-dir -r /tmp/data-requirements.txt \
    && pip install --no-cache-dir -r /tmp/test-requirements.txt

# Copy test configuration
COPY test/pytest.ini /test/
COPY test/.coveragerc /test/
COPY test/conftest.py /test/

# Copy test files
COPY test/test_api_middleware /test/test_api_middleware/
COPY test/test_data_hub /test/test_data_hub/
COPY test/test_integration /test/test_integration/

# Copy source code for testing
COPY api-middleware /test/api-middleware/
COPY data-hub /test/data-hub/

# Create test results directory
RUN mkdir -p /test/results /test/coverage_html

# Run tests as default command
CMD ["pytest", "-v", "--cov=.", "--cov-report=term-missing", "--cov-report=html:results/coverage_html", "--cov-report=xml:results/coverage.xml", "--html=results/report.html", "--self-contained-html"]
