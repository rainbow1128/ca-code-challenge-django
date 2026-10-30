FROM python:3.13-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /app

# The shared package (repo's shared/, passed in as the "shared" build context)
# becomes a wheel in /wheels. requirements.txt installs exactly that file (a
# direct reference, never PyPI); a version mismatch fails the build.
COPY --from=shared pyproject.toml /tmp/ca-shared/pyproject.toml
COPY --from=shared src /tmp/ca-shared/src
RUN pip wheel --no-deps --wheel-dir /wheels /tmp/ca-shared && rm -rf /tmp/ca-shared

COPY requirements.txt .
RUN pip install -r requirements.txt

COPY . .

# Same uid as a typical host user, so files created through the dev bind
# mount (e.g. new migrations) are not owned by root.
RUN useradd --uid 1000 --create-home app \
    && mkdir -p /keys/public && chown app /keys/public
USER app

EXPOSE 8000
CMD ["python", "manage.py", "runserver", "0.0.0.0:8000"]
