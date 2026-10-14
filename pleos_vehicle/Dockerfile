ARG BUILD_FROM

# Stage 1: build the React frontend
FROM node:22-alpine AS frontend
WORKDIR /src
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci --no-audit --no-fund
COPY frontend/ ./
RUN npm run build

# Stage 2: Python backend on the Home Assistant base image
FROM ${BUILD_FROM}
WORKDIR /app
COPY backend/requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt
COPY backend/app ./app
COPY --from=frontend /src/dist ./static
COPY run.sh /run.sh
RUN chmod a+x /run.sh

CMD [ "/run.sh" ]
