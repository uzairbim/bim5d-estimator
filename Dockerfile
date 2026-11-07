# BIM 5D Estimator - one container: Python API + web app

# Stage 1: fetch the web dependencies (three.js)
FROM node:20-slim AS web
WORKDIR /web
COPY web/package.json web/package-lock.json ./
RUN npm ci --omit=dev

# Stage 2: the app
FROM python:3.12-slim
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY . .
COPY --from=web /web/node_modules web/node_modules
# Projects and your edited rates live in volumes so they survive updates.
VOLUME ["/app/projects", "/app/data"]
EXPOSE 8000
CMD ["uvicorn", "server:app", "--host", "0.0.0.0", "--port", "8000"]
