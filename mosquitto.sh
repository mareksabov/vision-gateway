#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"
source "$ROOT_DIR/secret/mqtt.env"

mosquitto_sub -h "192.168.30.173" -p 1883 -u "$MQTT_USERNAME" -P "$MQTT_PASSWORD" -t 'ha/electricity/#' -v
