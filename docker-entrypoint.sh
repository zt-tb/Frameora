#!/bin/sh
set -eu

if [ "$#" -eq 0 ]; then
    set -- python main.py
fi

exec "$@"
