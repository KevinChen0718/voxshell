#!/bin/bash
set -e

cd "$(dirname "$0")"
unset PYTHONPATH
exec .venv/bin/python ptt.py "$@"
