#!/bin/bash

# Number of clients to spawn
NUM_CLIENTS=${1:-30}
NUM_REPEAT=${2:-10}

# Number of clients to keep alive at the end
NUM_KEEP_ALIVE=20

# Directory to store log files
LOG_DIR="client_logs"

# Array to store PIDs
declare -a CLIENT_PIDS=()

# Function to handle cleanup when script is terminated
cleanup() {
    echo "Cleaning up and terminating all client processes..."
    for pid in "${CLIENT_PIDS[@]}"; do
        kill "$pid" 2>/dev/null
    done
    exit
}

# Set up trap to catch SIGINT (Ctrl+C) and SIGTERM
trap cleanup SIGINT SIGTERM

# Create the log directory if it doesn't exist
mkdir -p "$LOG_DIR"

echo "Starting $NUM_CLIENTS client instances (one per second)..."

# Spawn the clients
for i in $(seq 1 $NUM_CLIENTS); do
    LOG_FILE="$LOG_DIR/client_${i}_log.txt"
    python client.py --num_repeat $NUM_REPEAT > "$LOG_FILE" 2>&1 &
    PID=$!
    CLIENT_PIDS+=("$PID")
    echo "Started client $i (PID: $PID), logging to $LOG_FILE"
    sleep 5
done

echo "All $NUM_CLIENTS clients started."
echo "Waiting 400 seconds before starting to terminate clients..."
sleep 400

# Terminate clients one by one, waiting 30s in between, skipping the last 5
NUM_TO_TERMINATE=$((NUM_CLIENTS - NUM_KEEP_ALIVE))

for i in $(seq 0 $((NUM_TO_TERMINATE - 1))); do
    PID=${CLIENT_PIDS[$i]}
    echo "Terminating client $((i+1)) (PID: $PID)..."
    kill "$PID" 2>/dev/null
    sleep 30
done

echo "Termination complete. Last $NUM_KEEP_ALIVE clients are still running."

wait
