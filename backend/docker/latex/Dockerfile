# All five allowlisted LaTeX engines (services/latex/engines.py::ENGINE_NAMES)
# in one image, so the host needs nothing but Docker itself:
#
#   - pdflatex, xelatex, lualatex, latexmk  come from a curated TeX Live install
#   - tectonic                              is not part of TeX Live; installed below
#
# TeX Live's scheme-full is ~4-5GB and installs entire subject areas (music
# notation, chemistry, CJK typesetting) no resume template touches. This
# builds scheme-basic (pdflatex + the core LaTeX format) and layers on just
# the collections resume templates actually use — extra LaTeX packages, extra
# fonts, XeTeX/LuaTeX for fontspec-based templates, tikz for icon/timeline
# CVs, and latexmk. If an upload 422s on a package outside this set, add it
# (or its collection) to the `tlmgr install` line below rather than widening
# the scheme — see ARCHITECTURE.md §7.6.
#
# compiler.py runs this image once per compile (`docker run --rm ...`),
# bind-mounting a scratch temp dir at /work. It is never `docker compose up`'d
# as a long-running service.
FROM debian:bookworm-slim

ARG TECTONIC_VERSION=0.17.0
ARG CTAN_MIRROR=https://mirror.ctan.org/systems/texlive/tlnet

RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        ca-certificates curl perl xz-utils fontconfig \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /tmp/texlive-install
COPY texlive.profile .
RUN curl -fsSL "${CTAN_MIRROR}/install-tl-unx.tar.gz" | tar -xz --strip-components=1 \
    && ./install-tl -profile texlive.profile -repository "${CTAN_MIRROR}" \
    && /usr/local/texlive/*/bin/x86_64-linux/tlmgr install \
        collection-latexrecommended collection-latexextra \
        collection-fontsrecommended collection-fontsextra \
        collection-xetex collection-luatex collection-pictures \
        collection-langenglish collection-plaingeneric latexmk \
    && ln -sf /usr/local/texlive/*/bin/x86_64-linux/* /usr/local/bin/ \
    && cd / && rm -rf /tmp/texlive-install

# musl over gnu: a static binary with no glibc-version coupling to whatever
# base image this Dockerfile happens to build FROM.
RUN curl -fsSL \
        "https://github.com/tectonic-typesetting/tectonic/releases/download/tectonic%40${TECTONIC_VERSION}/tectonic-${TECTONIC_VERSION}-x86_64-unknown-linux-musl.tar.gz" \
        | tar -xz -C /usr/local/bin \
    && chmod +x /usr/local/bin/tectonic

WORKDIR /work
