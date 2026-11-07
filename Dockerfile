# BIM 5D Estimator - free and open source.
# Works locally (docker compose up) and on free hosts such as Hugging Face Spaces.
FROM python:3.12-slim
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY . .
# Projects and your prices live here; mount volumes to keep them between updates.
VOLUME ["/app/projects", "/app/data"]
ENV PORT=8000
EXPOSE 8000
CMD ["sh", "-c", "uvicorn server:app --host 0.0.0.0 --port ${PORT}"]
