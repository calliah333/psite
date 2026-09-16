#!/bin/sh
set -eu

site_link=${SITE_LINK:-/git/site}
success_file=${SYNC_SUCCESS_FILE:-/git/.sync-success}

zola build
site_parent=$(cd "$(dirname "$site_link")" && pwd -P)
site_target=$PWD/public
site_prefix=${site_parent%/}/
case "$site_target" in
    "$site_prefix"*) site_target=${site_target#"$site_prefix"} ;;
esac
rm -f "${site_link}.next"
ln -s "$site_target" "${site_link}.next"
mv -f "${site_link}.next" "$site_link"
: > "$success_file"
