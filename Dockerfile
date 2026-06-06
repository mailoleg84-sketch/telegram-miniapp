FROM python:3.11-slim

WORKDIR /app
EXPOSE 8080

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Непривилегированный пользователь вместо root.
# useradd/groupadd из пакета passwd есть в любом debian-базовом образе.
RUN groupadd --system app && useradd --system --gid app --home-dir /app app
COPY --chown=app:app . .
USER app

# Liveness-проба (Docker). На Render основная проверка — healthCheckPath в render.yaml.
HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
  CMD python -c "import os,urllib.request; urllib.request.urlopen('http://127.0.0.1:%s/healthz' % os.getenv('PORT','8080'))" || exit 1

CMD ["python", "main.py"]
