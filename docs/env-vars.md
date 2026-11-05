# Environment variables

Configuration is read exclusively from environment variables. Defaults below are the application defaults. The deployed values are set per environment in the system's gitops-app repo (`system.yaml`: a component's `env`, and `replicas`, `resources` under `instances.<env>`).

## Core

| Variable | Default | Description |
|---|---|---|
| `PORT` | `8080` | HTTP port the service listens on. |
| `LOG_LEVEL` | `INFO` | Logging level. One of `DEBUG`, `INFO`, `WARNING`, `ERROR`. |

## Database

| Variable | Default | Description |
|---|---|---|
| `DATABASE_URL` | _(unset)_ | libpq URL of the Postgres database, of the form `postgresql://<user>:<password>@<host>:5432/<db>`; set by the system's gitops `uses: postgres`. When unset or empty the API still starts, but does not connect at all (no fallback to `PG*`), `/ready` answers 503 and `/tasks` answers 503 `{"detail": "database unavailable"}`. libpq may still fill parts the URL leaves out from `PG*`. |

## Observability

| Variable | Default | Description |
|---|---|---|
| `OTEL_EXPORTER_OTLP_ENDPOINT` | _(unset — tracing disabled)_ | Standard OpenTelemetry endpoint, e.g. `http://otel-collector:4318`; injected by the platform's observability setting of the environment. When set, `configure_tracing()` runs at startup. |
| `OTEL_EXPORTER_OTLP_PROTOCOL` | `http/protobuf` | `http/protobuf` or `grpc`. |
| `OTEL_SERVICE_NAME`, `OTEL_RESOURCE_ATTRIBUTES` | _(project name)_ | Resource attributes; set by the observability setting of the environment. |
| `OTLP_ENDPOINT` | _(unset)_ | Legacy gRPC endpoint (kept for compatibility); prefer the standard variables. |
| `METRICS_PORT` | `8080` | Port serving `/metrics` (same as the main HTTP port unless overridden). |
