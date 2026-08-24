# DSH runtime provenance

The DSH packages in `vendor/` are pinned build artifacts from DeepSeek Harness
commit `47f943859bef60e4160492346772ded9b24f765a` (`0.1.0-rc.5`).  That release is
not published as a complete installable set on npm, so the service intentionally
uses repository-owned tarballs plus `pnpm-lock.yaml` instead of resolving a
moving branch during Docker builds.

The runtime image is fixed to Node `22.19.0`.  Verify vendored artifacts with
`vendor/SHA256SUMS` before replacing or upgrading them.
