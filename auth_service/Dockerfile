FROM python:3.13-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /app

# The shared package (repo's shared/, passed in as the "shared" build context)
# becomes a wheel in a local wheelhouse; requirements.txt pins its version
# like any other dependency, so pip fails if the pin and the source disagree.
COPY --from=shared pyproject.toml /tmp/ca-shared/pyproject.toml
COPY --from=shared src /tmp/ca-shared/src
RUN pip wheel --no-deps --wheel-dir /wheels /tmp/ca-shared && rm -rf /tmp/ca-shared

COPY requirements.txt .
RUN pip install --find-links /wheels -r requirements.txt

COPY . .

# Same uid as a typical host user, so files created through the dev bind
# mount (e.g. new migrations) are not owned by root.
# /keys/* are mount points for the key volumes; created here so a new named
# volume starts out owned by the app user, not root.
RUN useradd --uid 1000 --create-home app \
    && mkdir -p /keys/private /keys/public && chown app /keys/private /keys/public
USER app

EXPOSE 8000
CMD ["python", "manage.py", "runserver", "0.0.0.0:8000"]
