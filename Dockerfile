# Dockerfile for the Flowise Development Agent HTTP API
# Runs the FastAPI service that wraps the LangGraph co-pilot.
#
# Build:  docker build -t flowise-dev-agent .
# Run:    docker run --env-file .env -p 8000:8000 flowise-dev-agent

FROM python:3.11-slim

# Don't write .pyc files and don't buffer stdout/stderr
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app

# Copy only what we need (avoids invalidating cache on code changes when deps haven't changed)
COPY pyproject.toml README.md ./
COPY flowise_dev_agent/ flowise_dev_agent/

# Install the package with Claude as the default reasoning engine
RUN pip install --no-cache-dir -e ".[claude]"

EXPOSE 8000

# flowise-agent is registered in pyproject.toml [project.scripts]
# It calls flowise_dev_agent.api:serve(host="0.0.0.0", port=8000)
CMD ["flowise-agent"]
