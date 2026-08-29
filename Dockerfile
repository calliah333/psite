FROM alpine:3.22 AS build
RUN apk add --no-cache zola
WORKDIR /site
COPY . .
RUN zola build

FROM alpine:3.22
RUN apk add --no-cache busybox-extras
COPY --from=build /site/public /site
EXPOSE 1111
CMD ["httpd", "-f", "-p", "1111", "-h", "/site"]
