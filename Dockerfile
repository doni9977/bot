FROM golang:1.26.1-bookworm AS build
WORKDIR /src
COPY go.mod ./
COPY cmd/bot ./cmd/bot
COPY pkg/pilot ./pkg/pilot
COPY pkg/protocol ./pkg/protocol
COPY pkg/arena ./pkg/arena
ENV CGO_ENABLED=0 GOOS=linux GOARCH=amd64 GOFLAGS=-mod=mod GOTOOLCHAIN=local
RUN go build -trimpath -ldflags="-s -w" -o /out/mechbot ./cmd/bot

FROM scratch
COPY --from=build /out/mechbot /mechbot
COPY arena /arena
USER 65534:65534
ENTRYPOINT ["/mechbot"]
