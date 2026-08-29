FROM registry.k8s.io/git-sync/git-sync:v4.7.1 AS git-sync

FROM alpine:3.22
RUN apk add --no-cache git zola
COPY --from=git-sync /git-sync /git-sync
COPY docker/build-site.sh /usr/local/bin/build-site
ENTRYPOINT ["/git-sync"]
