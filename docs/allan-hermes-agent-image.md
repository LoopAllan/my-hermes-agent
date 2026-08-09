# Allan Hermes Agent image

`Dockerfile.allan` builds `ghcr.io/loopallan/allan-hermes-agent` separately from the existing `my-hermes-agent` image. It extends the digest-pinned upstream image and does not alter the default Dockerfile or its publishing workflow.

The extension deliberately preserves the base image's root startup user: the inherited s6 bootstrap performs volume ownership reconciliation and drops normal services to `hermes` afterwards.

## Add a tool

1. Verify the version is available from the digest-pinned base image's configured APT sources.
2. Add the package as an exact `name=version` entry to `docker/allan/apt-packages.txt`.
3. Open a PR and verify the `Build Allan Hermes Agent Image` workflow.
4. After that PR is merged to `main`, the workflow builds, tests, and publishes the exact tested image. Pin the resulting image digest in the intended GitOps profile.

Pull requests only build and execute the tool smoke test. Publishing is restricted to a `main` push. The package list is deliberately declarative and minimal; do not install runtime dependencies ad hoc from a gateway session.
