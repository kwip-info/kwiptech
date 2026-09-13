FROM python:3.13-slim

ENV PYTHONUNBUFFERED=1
ENV PYTHONDONTWRITEBYTECODE=1

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

RUN python manage.py collectstatic --noinput --settings=show.settings

EXPOSE 8000
CMD ["gunicorn", "show.wsgi:application", "--bind", "0.0.0.0:8000"]
