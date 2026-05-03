#!/bin/bash
# Inject a FkWeb cmd_code command (for devices in FkWeb HTTP mode).
# The device picks it up on its next receive_cmd poll (~3 seconds).
#
# Example cmd_codes (see docs/cmd-catalog.md for full list):
#   GET_USER_ID_LIST   GET_USER_INFO   GET_DEVICE_STATUS   SET_TIME

CMD_QUEUE="${BIOFACE_CMD_QUEUE:-/tmp/secureeye-cmd-queue.jsonl}"
CMD_CODE="${1:-GET_DEVICE_STATUS}"
BODY="${2:-}"

echo "{\"cmd_code\":\"${CMD_CODE}\",\"body\":\"${BODY}\"}" >> "$CMD_QUEUE"
echo "Queued FkWeb cmd_code=${CMD_CODE}"
