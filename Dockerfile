# Use a slim official Python image
FROM python:3.11-slim

# Set environment variables
ENV PYTHONDONTWRITEBYTECODE=1     PYTHONUNBUFFERED=1     PYTHONPATH=/app

WORKDIR /app

# Install system dependencies
RUN apt-get update && apt-get install -y --no-install-recommends     curl     && rm -rf /var/lib/apt/lists/*

# Install build/runtime dependencies
RUN pip install --no-cache-dir --upgrade pip setuptools uvicorn

# Copy pyproject.toml first to leverage Docker layer caching
COPY pyproject.toml /app/

# Install dependencies (editable mode allows mapping volumes easily)
RUN pip install --no-cache-dir -e .

# Copy the core primitives and examples
COPY primitives /app/primitives/
COPY examples /app/examples/

# Expose the default Truss Proxy port
EXPOSE 8000

# Default environment configuration
ENV TRUSS_POLICIES_DIR=/app/examples/policies
ENV TRUSS_RECEIPTS_DIR=/root/.truss/ledger/receipts
ENV TRUSS_TAXONOMIES=/app/primitives/audit/taxonomies/phi.yaml

# Run the proxy on port 8000
CMD ["uvicorn", "primitives.audit.proxy:create_app_from_env", "--factory", "--host", "0.0.0.0", "--port", "8000"]
