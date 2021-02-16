#!/bin/bash
set -e

echo localhost:5432:${POSTGRES_DB}:${POSTGRES_USER}:${POSTGRES_PASSWORD} > ~/.pgpass
chmod 600 ~/.pgpass
psql -h localhost -U ${POSTGRES_USER} -f /opt/smile_music_db.dump ${POSTGRES_DB}