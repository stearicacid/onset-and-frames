#!/usr/bin/env bash

cd environments/A6000_1st
docker compose build ascender
docker compose up ascender -d
docker compose exec ascender bash