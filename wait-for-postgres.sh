#!/bin/bash

set -e

host="$1"
user="$2"
password="$3"
shift 3
cmd="$@"

until python3 test_db.py "$host" "$user" "$password" >/dev/null 2>&1; do
  >&2 echo "Postgres is unavailable - sleeping"
  sleep 1
done

>&2 echo "Postgres is up - executing command"
exec $cmd