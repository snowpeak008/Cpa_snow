#!/bin/sh
set -eu
cd /src
go mod tidy
gofmt -w *.go
GOMAXPROCS=1 go test -race -count=1 ./...
GOMAXPROCS=1 go build -trimpath -buildmode=c-shared -o account-concurrency.so .
sha256sum account-concurrency.so
