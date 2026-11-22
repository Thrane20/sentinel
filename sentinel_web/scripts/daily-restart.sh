#!/bin/sh
# Restart the services that hold recorder connections once a day, shortly
# after the recorder's own 07:10 auto-reboot, so go2rtc, Frigate, the worker
# and live-view FFmpeg start the day with clean connections.
# Runs inside the daily-restart container with the Docker socket mounted.
set -eu

RESTART_AT="${RESTART_AT:-07:25}"
RESTART_SERVICES="${RESTART_SERVICES:-frigate animal-alert-worker sentinel}"
case "$RESTART_AT" in
  [01][0-9]:[0-5][0-9] | 2[0-3]:[0-5][0-9]) ;;
  *) echo "daily-restart: RESTART_AT must be HH:MM (24-hour), got '$RESTART_AT'" >&2; exit 1 ;;
esac

# Restart only this Compose project's containers, whatever the project is named.
project=$(docker inspect -f '{{ index .Config.Labels "com.docker.compose.project" }}' "$(hostname)")
if [ -z "$project" ]; then
  echo "daily-restart: could not determine the Compose project" >&2
  exit 1
fi
echo "daily-restart: will restart '$RESTART_SERVICES' in project '$project' daily at $RESTART_AT ($(date +%Z))"

last=""
while true; do
  today=$(date +%F)
  if [ "$(date +%H:%M)" = "$RESTART_AT" ] && [ "$last" != "$today" ]; then
    last=$today
    for service in $RESTART_SERVICES; do
      ids=$(docker ps -q \
        --filter "label=com.docker.compose.project=$project" \
        --filter "label=com.docker.compose.service=$service")
      if [ -z "$ids" ]; then
        echo "daily-restart: $(date '+%F %T') $service is not running; skipped"
        continue
      fi
      # shellcheck disable=SC2086
      if docker restart --time 20 $ids >/dev/null; then
        echo "daily-restart: $(date '+%F %T') restarted $service"
      else
        echo "daily-restart: $(date '+%F %T') failed to restart $service" >&2
      fi
    done
  fi
  sleep 20
done
