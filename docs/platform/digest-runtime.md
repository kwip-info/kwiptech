---
title: Digest Runtime
description: Self-hosted universal document extraction runtime positioning, deployment, and platform boundary.
---

# Digest Runtime

Digest is a private, self-hosted API for extracting normalized text and metadata from
business documents, images, PDFs, and archives.

The customer runs the container inside their network. Customer documents are not routed
through the Kwip platform and are not stored by Kwip.

## Positioning

- Runs inside the customer's network.
- No customer documents are sent to Kwip.
- No generative AI.
- No GPU.
- No usage-based processing bill.
- Deterministic output where underlying extractors permit it.
- Docker deployment.
- Broad documented format support.
- Maintained security updates and compatibility tests.

The product is the commercially maintained integration boundary around mature open-source
tools: stable API, Docker distribution, compatibility tests, security updates, release
documentation, and support.

## Platform Boundary

The Kwip platform should treat Digest as a control-plane product:

- publish documentation;
- expose image tags, image digests, and release channels;
- manage entitlement and update access;
- provide security and licensing documentation.

The Kwip platform must not proxy extraction requests or receive customer documents. Extraction
traffic remains local to the customer's data plane.

## Pricing Model

Digest pricing reflects maintenance and distribution rights, not page volume. Customers provide
the compute, so page-based pricing would be artificial.

The correct economic claim is near-zero marginal compute cost and no customer-document storage
cost. Do not claim zero cost; Kwip still bears registry transfer, build infrastructure, security
scanning, signing, provenance, dependency update, support, documentation, and compliance costs.

## Runtime Status

The MVP runtime supports text, markup, PDF native text and OCR fallback, office formats, image
OCR, and opt-in ZIP archive extraction. Release-candidate controls include PDF page limits,
read-only runtime verification, SBOM generation, license inventory, vulnerability scanner wrapper,
and a release checklist.

## Current Image

```text
ghcr.io/kwip-info/digest:0.1.0
```

Private registry access is the entitlement gate. The container keeps running after a subscription
expires; expiration only removes access to new images, patches, and support.

Customer pull test:

```bash
docker login ghcr.io
docker pull ghcr.io/kwip-info/digest:0.1.0
docker run --rm \
  --read-only \
  --tmpfs /tmp:rw,noexec,nosuid,size=1g \
  --cap-drop ALL \
  --security-opt no-new-privileges:true \
  -p 8080:8080 \
  --env-file .env.example \
  ghcr.io/kwip-info/digest:0.1.0
```

Use immutable digests for production deployments. Moving tags are for release-channel discovery.
