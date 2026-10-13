# ODS Integration Gateway

The optional integration-gateway extension provides a platform inventory,
field-authority and classification policies, readiness checks, and validation
against the shared integration JSON Schemas. Plane is the first adapter and
only performs authenticated GET requests.

To activate Plane, set `ODS_PLANE_BASE_URL` to the verified HTTPS instance
URL, `ODS_PLANE_WORKSPACE_SLUG` to the workspace slug, and
`ODS_PLANE_API_KEY_HOST_FILE` to a host file containing the Plane API key.
Compose mounts the file read-only at `/run/secrets/plane_api_key`; the empty
example file keeps the adapter inactive until configured. The service runs as
the configured ODS UID/GID so it can read an operator-owned secret file.
Plain HTTP is rejected unless `ODS_PLANE_ALLOW_INSECURE_HTTP=true` is
deliberately set for a trusted private network. Plane credentials are sent
only as `X-API-Key`. The service does not bind a host port; other services on
its Compose network can access it at `integration-gateway:8092`.

The Plane current-user, workspace, and project probes use GET only. Webhook
signature verification is provided for future use, but no webhook ingestion or
event delivery route is active. External writes remain disabled.
