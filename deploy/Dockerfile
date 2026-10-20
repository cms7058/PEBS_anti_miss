FROM python:3.12-slim
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 \
    HOST=0.0.0.0 PORT=8087 DATABASE_PATH=/data/family.sqlite3 BACKUP_DIR=/data/backups
WORKDIR /app
COPY backend/requirements.txt backend/requirements.txt
COPY deploy/requirements.txt deploy/requirements.txt
RUN pip install --no-cache-dir -r deploy/requirements.txt \
    && groupadd --gid 10001 familyguard \
    && useradd --uid 10001 --gid 10001 --no-create-home familyguard \
    && install -d -m 0700 -o familyguard -g familyguard /data
COPY backend/ backend/
COPY deploy/gunicorn.conf.py deploy/backup.py deploy/
USER 10001:10001
EXPOSE 8087
CMD ["gunicorn", "--config", "deploy/gunicorn.conf.py", "backend.wsgi:create_app()"]
