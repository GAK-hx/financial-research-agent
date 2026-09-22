FROM python:3.11-slim

WORKDIR /app

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DEFAULT_TIMEOUT=240 \
    PIP_RETRIES=10

ARG INSTALL_PROFILE=core
RUN apt-get -o Acquire::Retries=10 -o Acquire::http::Timeout=60 update && \
    apt-get -o Acquire::Retries=10 -o Acquire::http::Timeout=60 \
    install -y --no-install-recommends \
    ca-certificates curl libgomp1 && \
    if [ "$INSTALL_PROFILE" = "analysis" ]; then \
      apt-get -o Acquire::Retries=10 -o Acquire::http::Timeout=60 \
      install -y --no-install-recommends default-jre-headless; \
    fi && \
    rm -rf /var/lib/apt/lists/*

# Keep downloaded wheels across BuildKit retries. This is build cache only and
# is not copied into the runtime image.
ENV PIP_NO_CACHE_DIR=off \
    PIP_DEFAULT_TIMEOUT=600 \
    PIP_RETRIES=20 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

COPY requirements-core.txt /app/
RUN --mount=type=cache,target=/root/.cache/pip pip install -r requirements-core.txt
COPY requirements-ingestion.txt /app/
RUN --mount=type=cache,target=/root/.cache/pip \
    if [ "$INSTALL_PROFILE" = "ingestion" ]; then pip install -r requirements-ingestion.txt; fi
COPY requirements-analysis.txt /app/
RUN --mount=type=cache,target=/root/.cache/pip \
    if [ "$INSTALL_PROFILE" = "analysis" ]; then pip install -r requirements-analysis.txt; fi
COPY requirements-rag.txt /app/
RUN --mount=type=cache,target=/root/.cache/pip \
    if [ "$INSTALL_PROFILE" = "rag" ]; then \
      pip install torch==2.7.1 --index-url https://download.pytorch.org/whl/cpu && \
      pip install -r requirements-rag.txt; \
    fi
COPY requirements-harness.txt /app/
ARG INSTALL_HARNESS=false
RUN --mount=type=cache,target=/root/.cache/pip \
    if [ "$INSTALL_HARNESS" = "true" ]; then \
      pip install -r requirements-harness.txt; \
    fi
COPY requirements-persistence.txt /app/
ARG INSTALL_PERSISTENCE=false
RUN --mount=type=cache,target=/root/.cache/pip \
    if [ "$INSTALL_PERSISTENCE" = "true" ]; then \
      pip install -r requirements-persistence.txt; \
    fi
COPY requirements-search.txt /app/
ARG INSTALL_SEARCH=false
RUN --mount=type=cache,target=/root/.cache/pip \
    if [ "$INSTALL_SEARCH" = "true" ]; then \
      pip install -r requirements-search.txt; \
    fi
COPY requirements-shared-state.txt /app/
ARG INSTALL_SHARED_STATE=false
RUN --mount=type=cache,target=/root/.cache/pip \
    if [ "$INSTALL_SHARED_STATE" = "true" ]; then \
      pip install -r requirements-shared-state.txt; \
    fi
COPY pyproject.toml README.md /app/
COPY src /app/src
RUN pip install --no-build-isolation --no-deps .
COPY tests /app/tests
COPY alembic.ini /app/
COPY migrations /app/migrations

CMD ["uvicorn", "financial_research_agent.api:app", "--host", "0.0.0.0", "--port", "8000", "--no-access-log"]
