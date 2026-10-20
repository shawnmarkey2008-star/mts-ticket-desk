#!/bin/bash
cd "$(dirname "$0")" || exit 1
export MTS_HOST=127.0.0.1
python3 server.py
