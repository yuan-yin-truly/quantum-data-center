# Evaluation environment for the beat-the-hotspot hill.
#
# Why this base: the hill ships a pinned Linux x86-64 HotSpot build that imports
# GLIBC_2.34 symbols and links libc and libm dynamically. So the base needs
# glibc 2.34 or newer. Debian 12 (bookworm) ships 2.36. Debian 11 ships 2.31 and
# will not run it, and Alpine will not either, because musl is not glibc.
#
# The base is pinned by digest rather than by tag, so this image is the same
# image next month. Re-resolve the digest only when deliberately upgrading:
#   curl -s "https://auth.docker.io/token?service=registry.docker.io&scope=repository:library/python:pull"
# then read docker-content-digest from a HEAD of the tag's manifest.
FROM python:3.12-slim-bookworm@sha256:34386ef0cb081344d7ec1c103ba398e6e9f64e9ab3a1509accc92a4e24a07258

# numpy is what the evaluator needs to build traces and read temperature grids.
# pytest is only for the hill's own tests under `hills check`, which run inside
# this image and use the image's interpreter, never the host's packages.
RUN pip install --no-cache-dir numpy==2.3.5 pytest==8.3.4

# The hill root is bind-mounted at evaluation time and the evaluator runs as the
# invoking user, so nothing is copied in and no entrypoint is declared. The
# tooling supplies the command.
WORKDIR /hill
