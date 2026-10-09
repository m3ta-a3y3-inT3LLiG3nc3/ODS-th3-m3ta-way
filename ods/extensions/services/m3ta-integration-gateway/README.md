# M3ta Integration Gateway

Governed integration boundary for QB, Hermes, and the MetaHuman OS platform mesh.

Phase 1 is intentionally validation-only. All external writes are disabled until
the corresponding live endpoint, secret reference, permissions, and health probe
have been verified.

The Plane adapter currently performs read-only current-user and project-list
probes using Plane's supported `X-API-Key` authentication. Webhook signature
verification is available, but webhook ingestion and event delivery remain
disabled until a live Plane workspace is verified.

Plane Cloud uses `PLANE_BASE_URL=https://api.plane.so`. For a self-hosted
deployment, replace that value with the instance root URL; the adapter appends
the versioned `/api/v1/...` paths itself.

## Initial platform surfaces

- Plane: authoritative work ledger
- Open Notebook: source-grounded research
- Nimbalyst: visual agent sessions and reviewed diffs
- Colanode: human collaboration
- HyNote: multimodal capture inbox
- Raycast: desktop commands and approval surface
- BrainOutside: approved durable knowledge

## Verify

```bash
python3 -m pip install -r tests/requirements-test.txt
pytest -q
curl http://127.0.0.1:8094/health
```

Never store credentials in `platforms.yaml`. Configuration records secret
reference names only; runtime secrets belong in the established ODS secret path.
