#!/bin/bash

# Improved entrypoint script with better error handling
set -e

echo "Starting Webshark container..."

# Check if required environment variables are set
if [ -z "$SHARKD_SOCKET" ]; then
    echo "ERROR: SHARKD_SOCKET environment variable not set"
    exit 1
fi

if [ -z "$CAPTURES_PATH" ]; then
    echo "ERROR: CAPTURES_PATH environment variable not set"
    exit 1
fi

echo "Socket path: $SHARKD_SOCKET"
echo "Captures path: $CAPTURES_PATH"

# Remove existing socket if it exists (sharkd daemon fails to start if the socket already exists)
if [ -S "$SHARKD_SOCKET" ]; then
    echo "Removing existing socket: $SHARKD_SOCKET"
    rm -f "$SHARKD_SOCKET"
fi

# Ensure captures directory exists
if [ ! -d "$CAPTURES_PATH" ]; then
    echo "Creating captures directory: $CAPTURES_PATH"
    mkdir -p "$CAPTURES_PATH"
fi

# Check and fix directory ownership
if [ -d "$CAPTURES_PATH" ]; then
    dir_owner=$(stat -c "%U:%G" "${CAPTURES_PATH}" 2>/dev/null || echo "unknown:unknown")
    echo "Captures directory owner: $dir_owner"
    
    if [ "x${dir_owner}" = "xroot:root" ]; then
        # assume CAPTURES_PATH owned by root:root is unintentional
        # (probably created by docker-compose)
        echo "Fixing ownership of captures directory..."
        chown node: "${CAPTURES_PATH}"
    fi
else
    echo "Warning: Captures directory does not exist: $CAPTURES_PATH"
fi

# Check if sharkd binary exists
if ! command -v sharkd >/dev/null 2>&1; then
    echo "ERROR: sharkd binary not found in PATH"
    exit 1
fi

echo "Starting application as node user..."
exec su node -c "npm start"