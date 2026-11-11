#!/bin/sh
# Runs once, when the Postgres volume is first created.
set -e
psql -v ON_ERROR_STOP=1 -U postgres <<SQL
CREATE ROLE n8n LOGIN PASSWORD '${N8N_DB_PASSWORD}';
CREATE DATABASE n8n OWNER n8n;
CREATE ROLE demo LOGIN PASSWORD '${DEMO_DB_PASSWORD}';
CREATE DATABASE demo OWNER demo;
SQL
psql -v ON_ERROR_STOP=1 -U demo -d demo -f /schema/schema.sql
