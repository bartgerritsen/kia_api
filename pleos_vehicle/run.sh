#!/usr/bin/with-contenv bashio
# shellcheck shell=bash
bashio::log.info "Starting Pleos Vehicle backend..."
cd /app || exit 1
exec python3 -m uvicorn app.main:app --host 0.0.0.0 --port 8099 --no-access-log
