#!/bin/sh
set -eu
zola build
rm -f /git/site.next
ln -s "$PWD/public" /git/site.next
mv -f /git/site.next /git/site
