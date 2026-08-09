# Allan Hermes Agent image

`Dockerfile.allan` builds `ghcr.io/loopallan/allan-hermes-agent` separately from the existing `my-hermes-agent` image. It extends a pinned base image and does not alter the default Dockerfile or its publishing workflow.

## Add a tool

1. Add the Debian package name to `docker/allan/apt-packages.txt`.
2. Open a PR and verify the `Build Allan Hermes Agent Image` workflow.
3. Pin the resulting image digest in the intended GitOps profile.

The package list is deliberately declarative and minimal. Do not install runtime dependencies ad hoc from a gateway session.
