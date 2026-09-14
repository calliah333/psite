#!/bin/sh
set -eu

site_link=${SITE_LINK:-/git/site}
success_file=${SYNC_SUCCESS_FILE:-/git/.sync-success}

zola build
rm -f "${site_link}.next"
ln -s "$PWD/public" "${site_link}.next"
mv -f "${site_link}.next" "$site_link"
: > "$success_file"
