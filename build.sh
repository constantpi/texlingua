#!/usr/bin/env bash
set -euo pipefail

usage() {
    echo "Usage: $0 FILE.tex [ja|en|all]" >&2
}
die() { echo "Error: $*" >&2; exit 1; }

if (( $# < 1 || $# > 2 )); then usage; exit 2; fi
mode=${2-default}
case "$mode" in default|ja|en|all) ;; *) usage; exit 2 ;; esac
if [[ $# == 2 && $mode == default ]]; then usage; exit 2; fi
if [[ ! -f $1 || $1 != *.tex ]]; then usage; die "TeX file not found: $1"; fi

script_dir=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P)
source_dir=$(cd -- "$(dirname -- "$1")" && pwd -P)
entry=$(basename -- "$1")
# ptex2pdf itself constructs shell commands; keep the entry name shell-safe.
if [[ ! $entry =~ ^[a-zA-Z0-9_][a-zA-Z0-9_.\ -]*\.tex$ ]]; then
    usage
    die "Use an ASCII entry filename starting with a letter, digit or underscore (letters, digits, spaces, _, -, . only)."
fi
stem=${entry%.tex}
helper="$script_dir/scripts/tex-source.pl"
for tool in perl tar mktemp ptex2pdf; do
    command -v "$tool" >/dev/null || die "Required command not found: $tool"
done
[[ -f $helper ]] || die "Helper not found: $helper"

work=$(mktemp -d /tmp/texlingua.XXXXXXXX)
publish=''
cleanup() {
    if [[ -n $publish ]]; then rm -f -- "$publish"; fi
    rm -rf -- "$work"
}
trap cleanup EXIT
trap 'exit 130' INT
trap 'exit 143' TERM

# Snapshot once, then give each language a separate, clean working directory.
mkdir "$work/source"
tar -C "$source_dir" --exclude-vcs \
    --exclude='.agents' --exclude='.aws' --exclude='.codex' \
    --exclude='node_modules' --exclude='target' --exclude='.venv' \
    --exclude='*.aux' --exclude='*.log' --exclude='*.dvi' --exclude='*.xdv' \
    --exclude='*.fls' --exclude='*.fdb_latexmk' --exclude='*.synctex*' \
    --exclude='*.bbl' --exclude='*.blg' --exclude='*.toc' --exclude='*.out' \
    --exclude='*.lof' --exclude='*.lot' --exclude='*.nav' --exclude='*.snm' \
    --exclude="./$stem.pdf" --exclude="./$stem-ja.pdf" --exclude="./$stem-en.pdf" \
    -cf - . | tar -C "$work/source" -xf -
perl "$helper" check-tree "$work/source"

# Run as a separate Bash process with errexit enabled even when the caller
# checks the exit status (Bash suppresses errexit inside conditional functions).
build_one() (
    set -euo pipefail
    language=$1
    build_dir="$work/$language"
    mkdir "$build_dir"
    cp -R "$work/source/." "$build_dir/"
    cd "$build_dir"
    if [[ $language == ja ]]; then
        perl "$helper" preprocess .
    fi
    tex_options='-interaction=nonstopmode -kanji=utf8 -synctex=1 -halt-on-error -file-line-error -recorder'
    run_tex() {
        ptex2pdf -l -ot "$tex_options" "./$entry"
        # Preserve the union of inputs, including files read only on early passes.
        if [[ -f $stem.fls ]]; then cat "$stem.fls" >> "$work/$language.inputs"; fi
    }
    echo "Building: $entry ($language)"
    run_tex
    # Status 0 means a bibliography is requested; 1 means no bibliography.
    if perl "$helper" needs-bib "$stem.aux"; then
        command -v pbibtex >/dev/null || { echo 'Error: Required command not found: pbibtex' >&2; exit 1; }
        pbibtex "$stem" -kanji=utf8
        run_tex
    else
        bib_status=$?
        if (( bib_status != 1 )); then exit "$bib_status"; fi
    fi
    run_tex
    [[ -s $stem.pdf ]] || { echo "Error: PDF was not generated: $stem.pdf" >&2; exit 1; }
    if [[ $language == en ]]; then
        perl "$helper" scan . "$work/$language.inputs" "$entry"
    fi
)

export -f build_one
export work helper entry stem
status=0
languages=("$mode")
if [[ $mode == all ]]; then languages=(ja en); fi
for language in "${languages[@]}"; do
    if bash -c 'build_one "$1"' bash "$language"; then
        output="$source_dir/$stem.pdf"
        if [[ $language != default ]]; then output="$source_dir/$stem-$language.pdf"; fi
        # Publish only a successful build. Staging on the destination filesystem
        # also avoids truncating an existing PDF if copying fails.
        if publish=$(mktemp "$source_dir/.texlingua-pdf.XXXXXXXX") &&
            cp -- "$work/$language/$stem.pdf" "$publish" && mv -f -- "$publish" "$output"; then
            echo "PDF: $output"
        else
            rm -f -- "$publish"
            status=1
        fi
        publish=''
    else
        echo "Error: Build failed ($language)." >&2
        status=1
    fi
done
exit "$status"
