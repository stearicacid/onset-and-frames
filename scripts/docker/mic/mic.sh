#!/usr/bin/env bash

cd environments/mic
docker compose build ascender
docker compose up ascender -d
docker compose exec ascender bash