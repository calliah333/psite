#!/bin/sh
set -u

sync_bin=${GIT_SYNC_BIN:-/git-sync}
error_file=${GITSYNC_ERROR_FILE:-/git/sync-error.json}
success_file=${SYNC_SUCCESS_FILE:-/git/.sync-success}
retry_base=${SYNC_RETRY_BASE_SECONDS:-30}
retry_max=${SYNC_RETRY_MAX_SECONDS:-300}
jitter_percent=${SYNC_RETRY_JITTER_PERCENT:-25}
retry_sleep_bin=${SYNC_RETRY_SLEEP_BIN:-sleep}
retry_count=0
child_pid=
sleep_pid=

stop() {
    trap - INT TERM
    if [ -n "$child_pid" ]; then
        kill -TERM "$child_pid" 2>/dev/null || true
        wait "$child_pid" 2>/dev/null || true
    fi
    if [ -n "$sleep_pid" ]; then
        kill -TERM "$sleep_pid" 2>/dev/null || true
        wait "$sleep_pid" 2>/dev/null || true
    fi
    exit 0
}
trap stop INT TERM

pause_for_operator() {
    echo "sync supervisor: permanent or configuration failure; automatic retries disabled" >&2
    while :; do
        sleep 3600 &
        sleep_pid=$!
        wait "$sleep_pid" 2>/dev/null || true
        sleep_pid=
    done
}

valid_uint() {
    case "$1" in
        ''|*[!0-9]*) return 1 ;;
        *) return 0 ;;
    esac
}

if ! valid_uint "$retry_base" || ! valid_uint "$retry_max" || ! valid_uint "$jitter_percent" || \
   [ "$retry_base" -lt 1 ] || [ "$retry_max" -lt "$retry_base" ] || [ "$jitter_percent" -gt 100 ]; then
    echo "sync supervisor: invalid retry policy" >&2
    pause_for_operator
fi

is_transient_error() {
    [ -s "$error_file" ] || return 1
    error=$(tr '[:upper:]' '[:lower:]' < "$error_file")
    case "$error" in
        *"could not resolve host"*|*"could not resolve proxy"*|*"temporary failure in name resolution"*|\
        *"network is unreachable"*|*"no route to host"*|*"failed to connect"*|\
        *"connection refused"*|*"connection reset"*|*"connection timed out"*|*"operation timed out"*|\
        *"tls handshake timeout"*|*"tls connection was non-properly terminated"*|\
        *"remote end hung up unexpectedly"*|*"unexpected disconnect"*|*"empty reply from server"*|\
        *"early eof"*|*"requested url returned error: 408"*|*"requested url returned error: 429"*|\
        *"requested url returned error: 500"*|*"requested url returned error: 502"*|\
        *"requested url returned error: 503"*|*"requested url returned error: 504"*)
            return 0
            ;;
    esac
    return 1
}

retry_delay() {
    delay=$retry_base
    remaining=$retry_count
    while [ "$remaining" -gt 0 ] && [ "$delay" -lt "$retry_max" ]; do
        if [ "$delay" -gt $((retry_max / 2)) ]; then
            delay=$retry_max
        else
            delay=$((delay * 2))
        fi
        remaining=$((remaining - 1))
    done

    jitter_window=$((delay * jitter_percent / 100))
    if [ "$jitter_window" -gt 0 ]; then
        seed=$(od -An -N4 -tu4 /dev/urandom 2>/dev/null | tr -d ' ')
        if ! valid_uint "$seed"; then
            seed=$(date +%s)
        fi
        delay=$((delay - seed % (jitter_window + 1)))
    fi
    if [ "$delay" -gt "$retry_max" ]; then
        delay=$retry_max
    fi
    printf '%s\n' "$delay"
}

export GITSYNC_ERROR_FILE="$error_file"
export SYNC_SUCCESS_FILE="$success_file"

while :; do
    rm -f "$error_file" "$success_file"
    "$sync_bin" "$@" &
    child_pid=$!
    wait "$child_pid"
    status=$?
    child_pid=

    if [ "$status" -eq 0 ]; then
        exit 0
    fi

    if [ -f "$success_file" ]; then
        retry_count=0
    fi

    if ! is_transient_error; then
        pause_for_operator
    fi

    delay=$(retry_delay)
    echo "sync supervisor: transient failure; retrying git-sync in ${delay}s" >&2
    retry_count=$((retry_count + 1))
    "$retry_sleep_bin" "$delay" &
    sleep_pid=$!
    wait "$sleep_pid" 2>/dev/null || true
    sleep_pid=
done
