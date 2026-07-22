#!/bin/bash
cd "$(dirname "$0")"
unset PYTHONPATH
exec .venv/bin/python talk.py "$@"
