FROM registry.k8s.io/git-sync/git-sync:v4.7.1 AS git-sync

FROM alpine:3.22
RUN apk add --no-cache git zola
COPY --from=git-sync /git-sync /git-sync
COPY --chmod=0755 docker/sync-entrypoint.sh /usr/local/bin/sync-entrypoint
COPY --chmod=0755 docker/build-site.sh /usr/local/bin/build-site
ENTRYPOINT ["/usr/local/bin/sync-entrypoint"]
