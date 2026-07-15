# Digest Pilot Sales Segment

## One-Slide Pitch

**Digest: private document extraction before AI, search, compliance, or automation**

- Self-hosted Docker runtime for normalized text and metadata extraction.
- Handles PDFs, scanned PDFs, Office files, images, text, markup, and ZIP archives.
- Runs inside the customer's network.
- No customer documents sent to Kwip.
- No generative AI, no GPU, no hosted document-processing API.
- Signed private GHCR image, SBOM/license artifacts, vulnerability scan, and release notes.
- Pricing is for distribution and maintenance rights, not page volume.

**Pilot offer:** $1,500-$3,000 for 90 days, credited toward annual license.

## Cold Call Opener

Do you have workflows where business documents need to be extracted inside your network, without
sending files to an AI API or third-party document processor?

Kwip has a self-hosted Docker runtime called Digest. It gives teams a private extraction API for
normalized text and metadata from PDFs, Office documents, images, and archives. The goal is not to
replace AI. The goal is to give AI, search, compliance, and automation systems a deterministic
ingestion layer first.

## Qualification Questions

- What document types are painful today?
- Are any documents sensitive enough that hosted AI or document APIs are blocked?
- Where would the runtime need to run: Docker host, Kubernetes, AWS, Azure, or something else?
- Do you need OCR for scanned documents or images?
- Is the output used for search, compliance review, workflow automation, or AI analysis?
- Who owns the security review?
- What would make a 90-day pilot successful?

## Objection: Why Not Just Use AI?

Use AI after extraction when the workflow calls for reasoning. Do not use AI as the first document
ingestion boundary.

Digest is deterministic, local, and auditable. It returns text, metadata, page details, warnings,
and extractor provenance without sending customer documents outside the customer's environment. AI
is useful for summarization, classification, and reasoning after the private extraction layer has
done its job.

## Follow-Up Email

Subject: Private document extraction runtime

Thanks for the conversation today.

Digest is Kwip's self-hosted document extraction runtime. It runs as a Docker image in your network
and exposes a stable API for normalized text and metadata extraction across PDFs, Office files,
images, text, markup, and archives.

The security posture is intentionally simple:

- no customer documents sent to Kwip;
- no generative AI;
- no GPU;
- no usage-based processing bill from Kwip;
- private GHCR image access;
- signed image, SBOM/license artifacts, and vulnerability scan.

The pilot shape we discussed is a 90-day paid pilot, usually $1,500-$3,000 and credited toward an
annual license if it moves forward.

Useful links:

- Digest page: https://kwip.tech/digest
- Platform docs: https://kwip.tech/docs/platform/digest-runtime.md

If this looks aligned, the next step is a short technical intake: document types, deployment target,
security review needs, and success criteria for the pilot.
