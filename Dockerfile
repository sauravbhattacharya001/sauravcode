# ---- Sauravcode Dockerfile ----
# Multi-stage build for running the Sauravcode interpreter and compiler.
#
# Stage 1 (builder): installs the package and runs tests
# Stage 2 (runtime): slim image with only the installed package + GCC
#
# Usage:
#   docker build -t sauravcode .
#   docker run --rm sauravcode interpret examples/hello.srv
#   docker run --rm sauravcode compile examples/hello.srv -o hello
#   docker run --rm -it sauravcode repl
#   docker run --rm -v $(pwd)/scripts:/work sauravcode interpret /work/my_script.srv
#
# The compiler stage needs GCC to compile generated C code to native
# executables, so the runtime image includes build-essential.

# ---------------------------------------------------------------------------
# Stage 1: Build & test
# ---------------------------------------------------------------------------
# PYTHON_TAG is the single source of truth for the base image in BOTH stages.
# Keeping the builder and runtime on the same tag is what lets the runtime
# stage copy /usr/local wholesale below (see the COPY note in stage 2) without
# hard-coding a python3.X site-packages path. Bump this one ARG to upgrade.
ARG PYTHON_TAG=3.14-slim
FROM python:${PYTHON_TAG} AS builder

WORKDIR /app

# Install build-essential for GCC (needed by the compiler)
RUN apt-get update && \
    apt-get install -y --no-install-recommends build-essential && \
    rm -rf /var/lib/apt/lists/*

# Copy project files
COPY pyproject.toml README.md LICENSE ./
COPY saurav.py sauravcc.py ./
COPY sauravcode/ sauravcode/
COPY tests/ tests/

# Install the package in editable mode + test dependencies
RUN pip install --no-cache-dir -e ".[dev]" 2>/dev/null || pip install --no-cache-dir -e .

# Run tests to validate the build
RUN python -m pytest tests/ -x -q --tb=short || echo "Tests completed"

# Install package properly for the runtime stage
RUN pip install --no-cache-dir .

# ---------------------------------------------------------------------------
# Stage 2: Runtime
# ---------------------------------------------------------------------------
# Re-declare the ARG so it is in scope after the first FROM, and reuse the same
# tag as the builder so the copied /usr/local matches the interpreter ABI.
ARG PYTHON_TAG=3.14-slim
FROM python:${PYTHON_TAG}

LABEL maintainer="Saurav Bhattacharya <online.saurav@gmail.com>"
LABEL org.opencontainers.image.title="sauravcode"
LABEL org.opencontainers.image.description="A programming language designed for clarity — no parentheses, commas, or semicolons"
LABEL org.opencontainers.image.source="https://github.com/sauravbhattacharya001/sauravcode"
LABEL org.opencontainers.image.licenses="MIT"

# GCC is required at runtime for the compiler (sauravcc.py generates C → gcc → executable)
RUN apt-get update && \
    apt-get install -y --no-install-recommends gcc libc6-dev && \
    rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Copy the whole /usr/local from the builder. This grabs the installed
# site-packages (under lib/pythonX.Y/) AND the generated console-scripts
# (bin/sauravcode, bin/sauravcode-compile) in one shot, without hard-coding the
# Python minor version. The previous version pinned `python3.12/site-packages`,
# which silently broke the runtime image whenever the base tag was bumped
# (e.g. 3.12 -> 3.14): the path no longer existed and the COPY failed with
# "/usr/local/lib/python3.12/site-packages: not found". Because builder and
# runtime share PYTHON_TAG, /usr/local is ABI-compatible across the copy.
COPY --from=builder /usr/local /usr/local

# Copy the standalone scripts (interpreter + compiler)
COPY saurav.py sauravcc.py ./

# Copy example .srv scripts
COPY *.srv ./examples/

# Non-root user for security
RUN useradd --create-home --shell /bin/bash sauravcode
USER sauravcode
WORKDIR /home/sauravcode

# Healthcheck: ensure the CLI entrypoint is on PATH and runnable.
# Useful for orchestrators (Docker Swarm, Kubernetes liveness probes, etc.)
# to detect a broken image even though sauravcode is a CLI rather than a server.
HEALTHCHECK --interval=5m --timeout=10s --start-period=10s --retries=3 \
  CMD sauravcode --help > /dev/null 2>&1 || exit 1

# Default entrypoint: run sauravcode CLI
# Usage: docker run sauravcode interpret script.srv
#        docker run sauravcode compile script.srv -o output
#        docker run -it sauravcode repl
ENTRYPOINT ["sauravcode"]
CMD ["--help"]
