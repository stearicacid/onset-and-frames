#!/usr/bin/env bash

cd environments/mic
docker compose build onset-and-frames
docker compose up onset-and-frames -d
docker compose exec onset-and-frames bash