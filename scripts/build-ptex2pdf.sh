#!/usr/bin/env bash
# Default builder. The caller supplies a copied project as the working directory.
set -euo pipefail

entry=$1
stem=${entry#./}
stem=${stem%.tex}
script_dir=$(CDPATH= cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P)
command -v ptex2pdf >/dev/null || { echo 'Error: Required command not found: ptex2pdf' >&2; exit 1; }

inputs=$(mktemp .texlingua-inputs.XXXXXXXX)
trap 'rm -f -- "$inputs"' EXIT
trap 'exit 130' INT
trap 'exit 143' TERM
recorded=false
tex_options='-interaction=nonstopmode -kanji=utf8 -synctex=1 -halt-on-error -file-line-error -recorder'
run_tex() {
    ptex2pdf -l -ot "$tex_options" "$entry"
    # Preserve inputs that were read only on an early pass.
    if [[ -f $stem.fls ]]; then
        cat "$stem.fls" >> "$inputs"
        recorded=true
    fi
}

run_tex
# Status 0 means a bibliography is requested; 1 means no bibliography.
if perl "$script_dir/tex-source.pl" needs-bib "$stem.aux"; then
    command -v pbibtex >/dev/null || { echo 'Error: Required command not found: pbibtex' >&2; exit 1; }
    pbibtex "$stem" -kanji=utf8
    run_tex
else
    bib_status=$?
    if (( bib_status != 1 )); then exit "$bib_status"; fi
fi
run_tex
if [[ $recorded == true ]]; then cp -- "$inputs" "$stem.fls"; fi
