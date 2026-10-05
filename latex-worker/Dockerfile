# All four allowlisted LaTeX engines (services/latex/engines.py::ENGINE_NAMES)
# come from one curated TeX Live install, so the host needs nothing but Docker
# itself: pdflatex, xelatex, lualatex, latexmk.
#
# TeX Live's scheme-full is ~4-5GB and installs entire subject areas (music
# notation, chemistry, CJK typesetting) no resume template touches. This
# builds scheme-basic (pdflatex + the core LaTeX format) and layers on just
# the collections resume templates actually use — extra LaTeX packages, extra
# fonts, XeTeX/LuaTeX for fontspec-based templates, tikz for icon/timeline
# CVs, and latexmk. If an upload 422s on a package outside this set, add it
# (or its collection) to the `tlmgr install` line below rather than widening
# the scheme — see ARCHITECTURE.md §6.5.
#
# This image runs as a long-lived service, not a one-shot `docker run --rm`:
# server.py (stdlib-only, no extra dependency worth a layer here) wraps the
# engines in a tiny HTTP API on :8100, so the backend never needs to create,
# exec into, or otherwise manage this container itself — it just makes HTTP
# requests. See app/services/latex/compiler.py for why that split matters.
FROM debian:bookworm-slim

ARG CTAN_MIRROR=https://mirror.ctan.org/systems/texlive/tlnet

RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        ca-certificates curl perl xz-utils fontconfig python3 \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /tmp/texlive-install
COPY texlive.profile .
# The binary directory is named after the platform (x86_64-linux,
# aarch64-linux, ...), so it is globbed rather than hard-coded — the same
# Dockerfile builds natively on Intel and on Apple Silicon / ARM servers.
RUN set -eux \
    && curl -fsSL "${CTAN_MIRROR}/install-tl-unx.tar.gz" | tar -xz --strip-components=1 \
    && ./install-tl -profile texlive.profile -repository "${CTAN_MIRROR}" \
    && TL_BIN="$(echo /usr/local/texlive/*/bin/*-linux)" \
    && "${TL_BIN}/tlmgr" install \
        collection-latexrecommended collection-latexextra \
        collection-fontsrecommended collection-fontsextra \
        collection-xetex collection-luatex collection-pictures \
        collection-langenglish collection-plaingeneric latexmk \
    && ln -sf "${TL_BIN}"/* /usr/local/bin/ \
    && cd / && rm -rf /tmp/texlive-install

# The documents compiled here are untrusted (uploaded, then rewritten by an
# LLM). Shell escape is already off (server.py), but there is no reason for
# the engine process to hold root inside the container either. The home
# directory is where LuaTeX and fontconfig keep their font caches.
RUN useradd --system --create-home --uid 10001 latex
WORKDIR /home/latex

COPY server.py /usr/local/bin/server.py

USER latex
EXPOSE 8100
HEALTHCHECK --interval=15s --timeout=5s --start-period=15s --retries=5 \
    CMD curl -fsS http://localhost:8100/health || exit 1
CMD ["python3", "-u", "/usr/local/bin/server.py"]
