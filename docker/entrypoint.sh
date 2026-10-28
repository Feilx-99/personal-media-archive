#!/bin/sh
set -eu
mkdir -p /data/downloads /data/cookies /data/db /data/cache
if [ "$(id -u)" = "0" ]; then
  chown -R appuser:appuser /data
  exec gosu appuser "$@"
fi
exec "$@"
