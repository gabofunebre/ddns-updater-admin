FROM python:3.12-slim
WORKDIR /app

# para poder ejecutar `docker restart` (botón de reinicio)
RUN apt-get update \
 && apt-get install -y --no-install-recommends docker-cli ca-certificates \
 && rm -rf /var/lib/apt/lists/*

RUN pip install --no-cache-dir flask waitress
COPY app.py /app/
ENV PYTHONUNBUFFERED=1

CMD ["waitress-serve","--port=8080","--call","app:create_app"]
