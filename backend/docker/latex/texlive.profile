# install-tl profile: scheme-basic only. Everything else this image needs
# (LaTeX extras, fonts, XeTeX, LuaTeX, tikz, latexmk) is layered on top via
# explicit `tlmgr install` in the Dockerfile — see the comment there for why.
selected_scheme scheme-basic
option_doc 0
option_src 0
option_autobackup 0
instopt_adjustpath 0
tlpdbopt_autobackup 0
