FROM python:3.13-slim

ENV PYTHONUNBUFFERED=1
ENV PYTHONDONTWRITEBYTECODE=1

RUN apt-get update && apt-get install -y --no-install-recommends \
    libpq-dev \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

# Sync pyscoped docs from PyPI at build time (production fallback)
RUN python manage.py sync_pyscoped_docs --output /app/pyscoped-docs 2>/dev/null || true
ENV PYSCOPED_DOCS_PATH=/app/pyscoped-docs

RUN python manage.py collectstatic --noinput 2>/dev/null || true

EXPOSE 8000
CMD ["gunicorn", "plane.wsgi:application", "--bind", "0.0.0.0:8000"]
