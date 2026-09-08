# Responsive frontend release

## Scope

- Deploy the responsive frontend source merge `be65e7b5f1aae165286cbbf1a69ee3e419e6224a`.
- Update only the frontend image digest.
- Leave backend services, database schema, authentication, model routing, quota, domains, Nginx configuration and every subsystem deployment unchanged.

## Immutable artifacts

- Previous frontend image: `sha256:dbb557d65d1a27bfccfe334aee2dc08b79c21a4da8f7a0c858f440bf9ff33cda`.
- Candidate frontend image: `sha256:da8f96f31f03eb1643e5ff3ff1eb1d1ecab5c9e1708117712c5c67e1914380f7`.
- Image OCI revision: `be65e7b5f1aae165286cbbf1a69ee3e419e6224a`.
- Image source: `https://github.com/ZhuoJian-AI/ai-platform`.

## Verification before deployment

- Frontend production build passed locally and in the immutable image build.
- Responsive browser acceptance passed across eight viewports in Chromium, WebKit and Firefox.
- Existing frontend regression scripts passed.
- The candidate image was started on the production Docker network without replacing the live container; it became healthy and returned HTTP 200 from `/health` and the SPA entry point.
- Registry-first Compose changes only the frontend digest. There is no database migration and rollback is frontend-image-only.

## Deployment completion

- Pending manifest merge and Coolify deployment verification.
