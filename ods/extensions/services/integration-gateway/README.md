# ODS Integration Gateway

The optional integration-gateway extension provides a platform inventory,
field-authority and classification policies, readiness checks, and validation
against the shared integration JSON Schemas. Plane is the first adapter and
only performs authenticated GET requests.

To activate Plane, set `ODS_PLANE_BASE_URL` to the verified instance URL,
`ODS_PLANE_WORKSPACE_SLUG` to the workspace slug, and mount the Plane API key
as a read-only file at the path in `ODS_PLANE_API_KEY_FILE` (default
`/run/secrets/plane_api_key`). Plane credentials are sent only as `X-API-Key`.
The service does not bind a host port; other services on its Compose network
can access it at `integration-gateway:8092`.

The Plane current-user, workspace, and project probes use GET only. Webhook
signature verification is provided for future use, but no webhook ingestion or
event delivery route is active. External writes remain disabled.
