#!/bin/bash
# Door unlock via WebSocket F500 LockControl command.
# Device must be in WebSocket-Client mode (ws://<server>:<port>).
#
# Mode values: 1=ForceOpen (permanent), 2=ForceClose, 3=NormalOpen (momentary buzz)
# All 3 confirmed working on Secureye S-FB3K / BIOFACE M61BH firmware.

CMD_QUEUE="${BIOFACE_CMD_QUEUE:-/tmp/secureeye-cmd-queue.jsonl}"
MODE="${1:-3}"   # default: NormalOpen (momentary)

XML="<?xml version=\"1.0\"?><Message><Request>LockControl</Request><Mode>${MODE}</Mode></Message>"

echo "{\"label\":\"door-unlock-mode${MODE}\",\"xml\":\"${XML}\"}" >> "$CMD_QUEUE"
echo "Queued LockControl Mode=${MODE}"
echo "  1=ForceOpen (permanent unlock)  2=ForceClose  3=NormalOpen (momentary buzz)"
