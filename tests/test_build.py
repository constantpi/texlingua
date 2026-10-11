"""Behavioral tests with fake TeX commands; no TeX installation is used."""
import hashlib
import json
import os
from pathlib import Path
import shutil
import shlex
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
BUILD = ROOT / "build.sh"
HELPER = ROOT / "scripts/tex-source.pl"

FAKE_TEX = r'''#!/usr/bin/env python3
import json, os, sys
from pathlib import Path
cwd = Path.cwd()
language = cwd.name
state = Path(os.environ['MOCK_STATE'])
tool = Path(sys.argv[0]).name
events = state / 'events.jsonl'
previous = [json.loads(x) for x in events.read_text().splitlines()] if events.exists() else []
call = sum(x['tool'] == tool and x['language'] == language for x in previous) + 1
record = dict(tool=tool, language=language, cwd=str(cwd), args=sys.argv[1:],
              sources={str(p.relative_to(cwd)): p.read_text() for p in cwd.rglob('*.tex')},
              files=sorted(str(p.relative_to(cwd)) for p in cwd.rglob('*') if p.is_file()))
with events.open('a') as f:
    f.write(json.dumps(record) + '\n')
if tool == 'pbibtex':
    assert sys.argv[-1] == '-kanji=utf8'
    if os.environ.get('MOCK_BIB_FAIL'): sys.exit(9)
    Path(sys.argv[1] + '.bbl').write_text('mock bibliography')
    sys.exit(0)
assert sys.argv[1:3] == ['-l', '-ot']
assert len(sys.argv) == 5
assert set(sys.argv[3].split()) == {'-interaction=nonstopmode', '-kanji=utf8',
    '-synctex=1', '-halt-on-error', '-file-line-error', '-recorder'}
entry = Path(sys.argv[-1])
stem = entry.stem
if language in os.environ.get('MOCK_FAIL_LANGUAGE', '').split(','):
    # A failing command can leave a partial PDF, which must never be published.
    Path(stem + '.pdf').write_text('partial PDF')
    sys.exit(7)
if os.environ.get('MOCK_FAIL_LATE') and call == 2: sys.exit(8)
if not os.environ.get('MOCK_NO_PDF'):
    Path(stem + '.pdf').write_text('mock PDF ' + language)
bib = '\\bibdata{references}\n' if '\\bibliography{' in entry.read_text() else ''
if os.environ.get('MOCK_NESTED_BIB'):
    Path('sections').mkdir(exist_ok=True)
    Path('sections/nested.aux').write_text('\\bibdata{references}\n')
    bib = '\\@input{sections/nested.aux}\n'
Path(stem + '.aux').write_text(bib)
if not os.environ.get('MOCK_NO_FLS'):
    inputs = [str(entry)] + os.environ.get('MOCK_INPUTS', '').split('|')
    if os.environ.get('MOCK_EARLY_INPUT') and call == 1: inputs.append('early.tex')
    lines = ['PWD ' + str(cwd)]
    for name in inputs:
        if name and Path(name).is_file():
            # Duplicate and absolute entries exercise canonicalization.
            lines += ['INPUT ' + name, 'INPUT ' + str(Path(name).resolve())]
    lines.append('INPUT /usr/share/texmf/system.tex')
    Path(stem + '.fls').write_text('\n'.join(lines) + '\n')
'''


FAKE_BUILDER = r'''#!/usr/bin/env python3
import json, os, sys
from pathlib import Path
assert len(sys.argv) == 3
entry, language = sys.argv[1:]
assert entry.startswith('./')
assert language in ('default', 'ja', 'en', 'both')
cwd = Path.cwd()
assert cwd.name == language
state = Path(os.environ['MOCK_STATE'])
record = dict(tool='custom', language=language, cwd=str(cwd), args=sys.argv[1:],
    sources={str(p.relative_to(cwd)): p.read_text() for p in cwd.rglob('*.tex')})
with (state / 'events.jsonl').open('a') as f:
    f.write(json.dumps(record) + '\n')
stem = Path(entry).stem
if language in os.environ.get('MOCK_FAIL_LANGUAGE', '').split(','):
    Path(stem + '.pdf').write_text('partial custom PDF')
    sys.exit(7)
if not os.environ.get('MOCK_NO_PDF'):
    Path(stem + '.pdf').write_text('custom PDF ' + language)
if not os.environ.get('MOCK_NO_FLS'):
    inputs = [entry] + os.environ.get('MOCK_INPUTS', '').split('|')
    lines = ['PWD ' + str(cwd)] + ['INPUT ' + p for p in inputs if p]
    Path(stem + '.fls').write_text('\n'.join(lines) + '\n')
'''


class BuildFixture(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="texlingua-tests.")
        self.addCleanup(self.temp.cleanup)
        self.base = Path(self.temp.name)
        self.project = self.base / "論文 with spaces"
        self.project.mkdir()
        self.bin = self.base / "bin"
        self.bin.mkdir()
        self.state = self.base / "state"
        self.state.mkdir()
        for name in ("ptex2pdf", "pbibtex"):
            tool = self.bin / name
            tool.write_text(FAKE_TEX)
            tool.chmod(0o755)
        self.env = dict(os.environ, PATH=f"{self.bin}:{os.environ['PATH']}", MOCK_STATE=str(self.state))
        self.env.pop('TEXLINGUA_BUILDER', None)
        self.write("main.tex", "%j 日本語 $n$。\nEnglish $n$.\n未翻訳。\n")

    def write(self, name, content):
        path = self.project / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
        return path

    def run_build(self, mode=None, *, success=True, entry="main.tex", **env):
        cmd = [str(BUILD), str(self.project / entry)]
        if mode is not None:
            cmd.append(mode)
        result = subprocess.run(cmd, cwd=self.base, env=dict(self.env, **env), capture_output=True, text=True)
        self.assertEqual(result.returncode == 0, success, result.stdout + result.stderr)
        for event in self.events():
            self.assertFalse(Path(event["cwd"]).parent.exists(), "Temporary directory leaked")
        self.assertEqual(list(self.project.glob('.texlingua-pdf.*')), [])
        return result.stdout + result.stderr

    def events(self):
        path = self.state / "events.jsonl"
        return [json.loads(x) for x in path.read_text().splitlines()] if path.exists() else []


class BuildTests(BuildFixture):
    def test_default_is_unmodified_and_silent(self):
        original = (self.project / "main.tex").read_bytes()
        output = self.run_build()
        self.assertNotIn("Untranslated", output)
        self.assertEqual((self.project / "main.pdf").read_text(), "mock PDF default")
        self.assertEqual(self.events()[0]["sources"]["main.tex"], original.decode())
        self.assertEqual((self.project / "main.tex").read_bytes(), original)
        self.assertEqual([x['tool'] for x in self.events()], ['ptex2pdf'] * 2)

    def test_japanese_pairs_and_indentation(self):
        source = "%j \\section{日本語}\\label{a}\n\\section{English}\\label{a}\n\t  %j  任意の $n$。\nEnglish.\n%japanese 通常コメント\nそのまま。\n"
        self.write("main.tex", source)
        self.run_build("ja")
        self.assertEqual(self.events()[0]['sources']['main.tex'], "\\section{日本語}\\label{a}\n\t  任意の $n$。\n%japanese 通常コメント\nそのまま。\n")

    def test_english_warning_preserves_source_line_numbers(self):
        output = self.run_build("en")
        self.assertIn("main.tex:3", output)
        self.assertIn("Total: 1 untranslated lines", output)
        self.assertIn("%j 日本語", self.events()[0]['sources']['main.tex'])
        self.assertTrue((self.project / "main-en.pdf").is_file())

    def test_all_independent_builds_single_warning(self):
        output = self.run_build("all")
        self.assertEqual(output.count("Untranslated Japanese detected:"), 1)
        self.assertTrue((self.project / "main-ja.pdf").is_file())
        self.assertTrue((self.project / "main-en.pdf").is_file())
        self.assertNotIn('%j ', self.events()[0]['sources']['main.tex'])
        self.assertIn('%j ', self.events()[-1]['sources']['main.tex'])

    def test_invalid_pairs(self):
        for tail in ("", "\n", "  \n", "% comment\n", "\t%j next\n"):
            with self.subTest(tail=tail):
                self.write("main.tex", "%j 本文\n" + tail)
                output = self.run_build("ja", success=False)
                self.assertIn("main.tex:1:", output)
                self.assertEqual(self.events(), [])

    def test_invalid_pair_ignored_in_default_and_en(self):
        self.write("main.tex", "%j 本文\n")
        self.run_build()
        self.run_build("en")

    def test_crlf_and_missing_final_newline(self):
        (self.project / "main.tex").write_bytes("%j 日本語\r\nEnglish\r\n最後".encode())
        subprocess.run(['perl', str(HELPER), 'preprocess', str(self.project)], check=True)
        self.assertEqual((self.project / "main.tex").read_bytes(), "日本語\r\n最後".encode())

    def test_comment_escape_parity(self):
        self.write("main.tex", "% コメント\n%j 翻訳済み\nEnglish.\nText % コメント\nText \\% 日本語\nText \\\\% コメント\nText \\\\\\% 日本語\n")
        output = self.run_build("en")
        self.assertIn("Total: 2 untranslated lines", output)
        self.assertIn("main.tex:5", output)
        self.assertIn("main.tex:7", output)
        self.assertNotIn("main.tex:6", output)

    def test_unicode_scripts(self):
        self.write("main.tex", "あ\nア\n漢\n𠀀\n々\n〆\nー\nｶ\n")
        self.assertIn("Total: 8 untranslated lines", self.run_build("en"))

    def test_multiple_files_only_recorded_sources_warn(self):
        self.write("main.tex", "\\input{sections/read}\n")
        self.write("sections/read.tex", "%j 訳文\nTranslated.\n日本語\n")
        self.write("unused.tex", "未使用\n")
        output = self.run_build("all", MOCK_INPUTS="sections/read.tex")
        self.assertIn("sections/read.tex:3", output)
        self.assertNotIn("unused.tex:", output)
        self.assertIn("Total: 1 untranslated lines", output)
        self.assertEqual(self.events()[0]['sources']['sections/read.tex'], "訳文\n日本語\n")

    def test_early_pass_inputs_are_retained(self):
        self.write("main.tex", "English\n")
        self.write("early.tex", "日本語\n")
        self.assertIn("early.tex:1", self.run_build("en", MOCK_EARLY_INPUT="1"))

    def test_missing_recorder_warns_and_falls_back(self):
        self.write("unused.tex", "未使用\n")
        output = self.run_build("en", MOCK_NO_FLS="1")
        self.assertIn("No .fls record", output)
        self.assertIn("unused.tex:1", output)

    def test_bibliography_recipe(self):
        self.write("main.tex", "\\bibliography{references}\n")
        self.write("references.bib", "@misc{example,title={Example}}\n")
        self.run_build()
        self.assertEqual([x['tool'] for x in self.events()], ['ptex2pdf', 'pbibtex', 'ptex2pdf', 'ptex2pdf'])

    def test_nested_aux_bibliography(self):
        self.run_build(MOCK_NESTED_BIB="1")
        self.assertIn('pbibtex', [x['tool'] for x in self.events()])

    def test_build_failure_preserves_pdf(self):
        self.write("main-en.pdf", "old PDF")
        self.run_build("en", success=False, MOCK_FAIL_LANGUAGE="en")
        self.assertEqual((self.project / "main-en.pdf").read_text(), "old PDF")

    def test_late_failure_preserves_pdf(self):
        self.write("main.pdf", "old PDF")
        self.run_build(success=False, MOCK_FAIL_LATE="1")
        self.assertEqual((self.project / "main.pdf").read_text(), "old PDF")

    def test_bib_failure_stops_before_publication(self):
        self.write("main.tex", "\\bibliography{references}\n")
        self.write("main.pdf", "old PDF")
        self.run_build(success=False, MOCK_BIB_FAIL="1")
        self.assertEqual([x['tool'] for x in self.events()], ['ptex2pdf', 'pbibtex'])
        self.assertEqual((self.project / "main.pdf").read_text(), "old PDF")

    def test_no_pdf_is_failure_even_if_command_succeeds(self):
        self.write("main.pdf", "old PDF")
        self.run_build(success=False, MOCK_NO_PDF="1")
        self.assertEqual((self.project / "main.pdf").read_text(), "old PDF")

    def test_all_keeps_success_when_one_language_fails(self):
        for failure in ('ja', 'en'):
            with self.subTest(failure=failure):
                for language in ('ja', 'en'):
                    self.write(f'main-{language}.pdf', 'old PDF')
                self.run_build('all', success=False, MOCK_FAIL_LANGUAGE=failure)
                other = 'en' if failure == 'ja' else 'ja'
                self.assertEqual((self.project / f'main-{failure}.pdf').read_text(), 'old PDF')
                self.assertEqual((self.project / f'main-{other}.pdf').read_text(), 'mock PDF ' + other)

    def test_all_attempts_en_after_preprocessing_error(self):
        self.write('main.tex', '%j 本文\n')
        self.run_build('all', success=False)
        self.assertTrue((self.project / 'main-en.pdf').exists())

    def test_assets_copied_artifacts_excluded_sources_unchanged(self):
        self.write('figures/figure.pdf', 'figure asset')
        self.write('custom.sty', '% style')
        self.write('main.aux', 'stale aux')
        self.write('main.pdf', 'old PDF')
        self.write('.git/config', 'excluded')
        self.write('target/large', 'excluded')
        before = {p: hashlib.sha256(p.read_bytes()).digest() for p in self.project.rglob('*') if p.is_file()}
        self.run_build('all')
        copied = self.events()[0]['files']
        self.assertIn('figures/figure.pdf', copied)
        self.assertIn('custom.sty', copied)
        for name in ('main.aux', 'main.pdf', '.git/config', 'target/large'):
            self.assertNotIn(name, copied)
        for path, digest in before.items():
            self.assertEqual(hashlib.sha256(path.read_bytes()).digest(), digest)
        after = {p for p in self.project.rglob('*') if p.is_file()}
        self.assertEqual(after - before.keys(), {self.project / 'main-ja.pdf', self.project / 'main-en.pdf'})

    def test_symlink_rejected_without_modifying_target(self):
        external = self.base / 'external.tex'
        external.write_text('%j 日本語\nEnglish\n')
        (self.project / 'linked.tex').symlink_to(external)
        output = self.run_build('ja', success=False)
        self.assertIn('symbolic links', output)
        self.assertEqual(external.read_text(), '%j 日本語\nEnglish\n')

    def test_alternate_entry_and_spaces(self):
        self.write('my paper.tex', 'English\n')
        self.run_build('en', entry='my paper.tex')
        self.assertTrue((self.project / 'my paper-en.pdf').exists())

    def test_bad_arguments(self):
        for args in ([], ['missing.tex'], [str(self.project/'main.tex'), 'fr'],
                     [str(self.project/'main.tex'), 'default'],
                     [str(self.project/'main.tex'), ''], [str(self.project/'main.tex'), 'en', 'extra']):
            with self.subTest(args=args):
                result = subprocess.run([str(BUILD), *args], env=self.env, capture_output=True, text=True)
                self.assertNotEqual(result.returncode, 0)
                self.assertIn('Usage:', result.stderr)

    def test_preprocessing_error_also_cleans_tmp(self):
        before = set(Path('/tmp').glob('texlingua.*'))
        self.write('main.tex', '%j 本文\n')
        self.run_build('ja', success=False)
        self.assertEqual(set(Path('/tmp').glob('texlingua.*')) - before, set())


class CustomBuilderTests(BuildFixture):
    def setUp(self):
        super().setUp()
        self.builder = self.base / 'tools with spaces' / 'compile paper.sh'
        self.builder.parent.mkdir()
        self.builder.write_text(FAKE_BUILDER)
        self.builder.chmod(0o755)
        self.env['TEXLINGUA_BUILDER'] = str(self.builder)

    def test_custom_builder_receives_each_mode_and_transformed_sources(self):
        for mode in (None, 'ja', 'en', 'all'):
            with self.subTest(mode=mode):
                self.run_build(mode)
        events = self.events()
        self.assertEqual([x['language'] for x in events], ['default', 'ja', 'en', 'ja', 'en'])
        self.assertTrue(all(x['tool'] == 'custom' for x in events))
        self.assertIn('%j ', events[0]['sources']['main.tex'])
        self.assertNotIn('%j ', events[1]['sources']['main.tex'])
        self.assertIn('%j ', events[2]['sources']['main.tex'])

    def test_custom_builder_requires_no_tex_tools(self):
        minimal = self.base / 'minimal-bin'
        minimal.mkdir()
        for name in ('bash', 'perl', 'tar', 'mktemp', 'dirname', 'basename',
                     'mkdir', 'cp', 'rm', 'mv', 'python3'):
            (minimal / name).symlink_to(shutil.which(name))
        self.run_build('all', PATH=str(minimal))
        self.assertTrue(all(x['tool'] == 'custom' for x in self.events()))

    def test_relative_builder_is_resolved_from_invocation_directory(self):
        relative = str(self.builder.relative_to(self.base))
        self.run_build('en', TEXLINGUA_BUILDER=relative)
        self.assertEqual((self.project / 'main-en.pdf').read_text(), 'custom PDF en')

    def test_empty_builder_uses_default(self):
        self.run_build('en', TEXLINGUA_BUILDER='')
        self.assertEqual([x['tool'] for x in self.events()], ['ptex2pdf', 'ptex2pdf'])

    def test_invalid_builder_fails_before_copy_or_compilation(self):
        plain = self.base / 'not-executable'
        plain.write_text('#!/bin/sh\nexit 0\n')
        for path in (str(self.base / 'missing'), str(plain), str(self.base),
                     str(self.builder) + ' --option'):
            with self.subTest(path=path):
                output = self.run_build('en', success=False, TEXLINGUA_BUILDER=path)
                self.assertIn('Builder must be an executable file', output)
                self.assertEqual(self.events(), [])

    def test_builder_path_is_not_evaluated_as_shell_code(self):
        literal = self.builder.parent / 'compile $(touch INJECTED);.sh'
        self.builder.rename(literal)
        self.run_build('en', TEXLINGUA_BUILDER=str(literal))
        self.assertFalse((self.base / 'INJECTED').exists())
        self.assertFalse((self.project / 'INJECTED').exists())

    def test_recorder_excludes_unused_sources(self):
        self.write('main.tex', '\\input{sections/read}\n')
        self.write('sections/read.tex', '日本語\n')
        self.write('unused.tex', '未使用\n')
        output = self.run_build('all', MOCK_INPUTS='sections/read.tex')
        self.assertIn('sections/read.tex:1', output)
        self.assertNotIn('unused.tex:', output)
        self.assertEqual(output.count('Untranslated Japanese detected:'), 1)

    def test_missing_recorder_uses_fallback(self):
        self.write('unused.tex', '未使用\n')
        output = self.run_build('en', MOCK_NO_FLS='1')
        self.assertIn('No .fls record', output)
        self.assertIn('unused.tex:1', output)

    def test_all_publishes_only_successful_language(self):
        for failed in ('ja', 'en'):
            with self.subTest(failed=failed):
                for language in ('ja', 'en'):
                    self.write(f'main-{language}.pdf', 'old PDF')
                self.run_build('all', success=False, MOCK_FAIL_LANGUAGE=failed)
                other = 'en' if failed == 'ja' else 'ja'
                self.assertEqual((self.project / f'main-{failed}.pdf').read_text(), 'old PDF')
                self.assertEqual((self.project / f'main-{other}.pdf').read_text(), 'custom PDF ' + other)

    def test_success_without_pdf_preserves_previous_pdf(self):
        self.write('main-en.pdf', 'old PDF')
        self.run_build('en', success=False, MOCK_NO_PDF='1')
        self.assertEqual((self.project / 'main-en.pdf').read_text(), 'old PDF')


class BothTests(BuildFixture):
    def test_prose_pair_is_small_gray_then_english_without_new_paragraph(self):
        original = '%j 日本語の文章。\nEnglish text.\n\n未翻訳。\n'
        self.write('main.tex', original)
        output = self.run_build('both')
        converted = self.events()[0]['sources']['main.tex']
        self.assertTrue(converted.endswith(
            '{\\small\\color[gray]{0.45}%\n日本語の文章。\n\\unskip}\\space\n'
            'English text.\n\n未翻訳。\n'))
        self.assertNotIn('\\par', converted)
        self.assertNotIn('\\begin{quote}', converted)
        self.assertNotIn('Untranslated Japanese', output)
        self.assertEqual((self.project / 'main-both.pdf').read_text(), 'mock PDF both')
        self.assertEqual((self.project / 'main.tex').read_text(), original)

    def test_leading_commands_on_either_side_select_english(self):
        pairs = [
            ('\\section{日本語}', '\\section{English}'),
            ('\\subsection{準備}', '\\subsection{Preliminaries}'),
            ('\\caption{図}', '\\caption{Figure}'),
            ('\\emph{日本語}', 'English.'),
            ('日本語。', '\\emph{English.}'),
        ]
        source = ''.join('%j ' + japanese + '\n' + english + '\n' for japanese, english in pairs)
        self.write('main.tex', source)
        self.run_build('both')
        converted = self.events()[0]['sources']['main.tex']
        self.assertTrue(converted.endswith(''.join(english + '\n' for _, english in pairs)))
        self.assertNotIn('\\small', converted)
        for japanese, _ in pairs:
            self.assertNotIn(japanese, converted)

    def test_indentation_preserved_and_ignored_for_classification(self):
        self.write('main.tex', '\t  %j \t日本語。\n    English.\n'
                   '  %j   \\emph{除外}\n\tEnglish only.\n'
                   '\t%j 除外。\n  \t\\emph{English only.}\n')
        self.run_build('both')
        converted = self.events()[0]['sources']['main.tex']
        self.assertTrue(converted.endswith(
            '\t  {\\small\\color[gray]{0.45}%\n\t  日本語。\n\t  \\unskip}\\space\n'
            '    English.\n\tEnglish only.\n  \t\\emph{English only.}\n'))

    def test_inline_commands_math_and_citations_are_retained(self):
        japanese = '式 $n^2$ と図~\\ref{fig:sample} を参照する~\\cite{sample}。'
        english = 'See $n^2$ and Figure~\\ref{fig:sample}~\\cite{sample}.'
        self.write('main.tex', f'%j {japanese}\n{english}\n')
        self.run_build('both')
        converted = self.events()[0]['sources']['main.tex']
        self.assertIn(japanese + '\n\\unskip}\\space\n' + english, converted)
        self.assertEqual(converted.count('\\small\\color[gray]{0.45}'), 1)

    def test_unpaired_lines_and_ordinary_comments_are_unchanged(self):
        source = '未翻訳の段落。\n% 通常コメント\n%japanese comment\n%j\n\\section{Title}\n'
        self.write('main.tex', source)
        self.run_build('both')
        self.assertTrue(self.events()[0]['sources']['main.tex'].endswith(source))

    def test_comment_cannot_swallow_closing_group(self):
        self.write('main.tex', '%j 割合は $50\\%$。 % 日本語側コメント\n'
                   'The ratio is $50\\%$. % English comment\n')
        self.run_build('both')
        converted = self.events()[0]['sources']['main.tex']
        self.assertIn('% 日本語側コメント\n\\unskip}\\space\n', converted)
        self.assertTrue(converted.endswith('The ratio is $50\\%$. % English comment\n'))

    def test_multiple_files_and_color_support_only_in_entry(self):
        self.write('main.tex', '\\documentclass{jsarticle}\n'
                   '\\usepackage[dvipdfmx,dvipsnames]{xcolor}\n'
                   '\\begin{document}\n\\input{sections/read}\n\\end{document}\n')
        self.write('sections/read.tex', '%j 日本語。\nEnglish.\n')
        self.write('unused.tex', '%j 未使用の翻訳。\nUnused translation.\n')
        self.run_build('both')
        sources = self.events()[0]['sources']
        self.assertIn('\\AddToHook{begindocument/before}', sources['main.tex'])
        self.assertIn('\\ifdefined\\color\\else', sources['main.tex'])
        self.assertIn('\\RequirePackage[dvipdfmx]{color}', sources['main.tex'])
        self.assertIn('\\RequirePackage{color}', sources['main.tex'])
        self.assertIn('\\usepackage[dvipdfmx,dvipsnames]{xcolor}', sources['main.tex'])
        for file in ('sections/read.tex', 'unused.tex'):
            self.assertIn('\\small\\color[gray]{0.45}', sources[file])
            self.assertNotIn('\\AddToHook', sources[file])

    def test_both_invalid_pairs_preserve_pdf_and_clean_tmp(self):
        self.write('main-both.pdf', 'old PDF')
        before = set(Path('/tmp').glob('texlingua.*'))
        for tail in ('', '\n', ' \t\n', '% comment\n', '  %j next\n'):
            with self.subTest(tail=tail):
                self.write('main.tex', '%j 日本語\n' + tail)
                output = self.run_build('both', success=False)
                self.assertIn('main.tex:1:', output)
                self.assertEqual(self.events(), [])
        self.assertEqual((self.project / 'main-both.pdf').read_text(), 'old PDF')
        self.assertEqual(set(Path('/tmp').glob('texlingua.*')) - before, set())

    def test_both_failure_does_not_affect_existing_modes(self):
        self.write('main-both.pdf', 'old both PDF')
        self.run_build('both', success=False, MOCK_FAIL_LANGUAGE='both')
        for mode in (None, 'ja', 'en', 'all'):
            with self.subTest(mode=mode):
                self.run_build(mode, MOCK_FAIL_LANGUAGE='both')
        self.assertEqual((self.project / 'main-both.pdf').read_text(), 'old both PDF')

    def test_all_never_runs_both_or_creates_its_pdf(self):
        self.run_build('all', MOCK_FAIL_LANGUAGE='both')
        self.assertEqual({x['language'] for x in self.events()}, {'ja', 'en'})
        self.assertFalse((self.project / 'main-both.pdf').exists())
        self.assertTrue(all('\\AddToHook' not in x['sources']['main.tex'] for x in self.events()))

    def test_all_preserves_existing_both_pdf_even_if_a_build_fails(self):
        pdf = self.write('main-both.pdf', 'existing both PDF')
        before = (pdf.read_bytes(), pdf.stat().st_mtime_ns, pdf.stat().st_ino)
        for failure in ('', 'ja', 'en'):
            with self.subTest(failure=failure):
                self.run_build('all', success=not failure, MOCK_FAIL_LANGUAGE=failure)
                self.assertEqual((pdf.read_bytes(), pdf.stat().st_mtime_ns, pdf.stat().st_ino), before)
        self.assertEqual({x['language'] for x in self.events()}, {'ja', 'en'})
        self.assertTrue(all('main-both.pdf' not in x['files'] for x in self.events()))

    def test_custom_builder_receives_both_and_no_scan_is_run(self):
        builder = self.base / 'custom-builder'
        builder.write_text(FAKE_BUILDER)
        builder.chmod(0o755)
        output = self.run_build('both', TEXLINGUA_BUILDER=str(builder), MOCK_NO_FLS='1')
        self.assertEqual([x['args'] for x in self.events()], [['./main.tex', 'both']])
        self.assertIn('\\small\\color', self.events()[0]['sources']['main.tex'])
        self.assertNotIn('Untranslated Japanese', output)
        self.assertNotIn('No .fls', output)

    def test_both_pdf_name_follows_entry(self):
        self.write('my paper.tex', '%j 日本語。\nEnglish.\n')
        self.run_build('both', entry='my paper.tex')
        self.assertEqual((self.project / 'my paper-both.pdf').read_text(), 'mock PDF both')
        self.assertFalse((self.project / 'main-both.pdf').exists())

    def test_both_without_pdf_preserves_existing_pdf(self):
        self.write('main-both.pdf', 'old PDF')
        self.run_build('both', success=False, MOCK_NO_PDF='1')
        self.assertEqual((self.project / 'main-both.pdf').read_text(), 'old PDF')

    def test_both_keeps_original_tree_and_publishes_only_one_pdf(self):
        self.write('sections/read.tex', '%j 日本語。\nEnglish.\n')
        self.write('main-ja.pdf', 'ja PDF')
        self.write('main-en.pdf', 'en PDF')
        before = {p: p.read_bytes() for p in self.project.rglob('*') if p.is_file()}
        self.run_build('both')
        for path, data in before.items():
            self.assertEqual(path.read_bytes(), data)
        after = {p for p in self.project.rglob('*') if p.is_file()}
        self.assertEqual(after - before.keys(), {self.project / 'main-both.pdf'})

    def test_crlf_bom_and_missing_final_newline(self):
        path = self.project / 'main.tex'
        original = '\ufeff\\documentclass{jsarticle}\r\n%j 日本語\r\nEnglish'.encode()
        path.write_bytes(original)
        subprocess.run(['perl', str(HELPER), 'both', str(self.project), 'main.tex'], check=True)
        converted = path.read_bytes()
        self.assertTrue(converted.startswith(b'\xef\xbb\xbf% texlingua:'))
        self.assertEqual(converted.count(b'\xef\xbb\xbf'), 1)
        self.assertNotIn(b'\n', converted.replace(b'\r\n', b''))
        self.assertTrue(converted.endswith('日本語\r\n\\unskip}\\space\r\nEnglish'.encode()))


class InvocationTests(BuildFixture):
    def setUp(self):
        super().setUp()
        # Install just the runtime in a separate directory, as for an alias.
        self.install = self.base / 'installed tools' / 'texlingua'
        (self.install / 'scripts').mkdir(parents=True)
        shutil.copy2(BUILD, self.install / 'build.sh')
        for name in ('tex-source.pl', 'build-ptex2pdf.sh'):
            shutil.copy2(ROOT / 'scripts' / name, self.install / 'scripts' / name)

    def invoke_alias(self, cwd, entry, mode='en', **env):
        before = {p: p.read_bytes() for p in self.install.rglob('*') if p.is_file()}
        # The alias value itself contains shell quoting for the installation path.
        alias_value = shlex.quote(str(self.install / 'build.sh'))
        script = 'alias texlingua=' + shlex.quote(alias_value) + '\ntexlingua "$1" "$2"\n'
        result = subprocess.run(
            ['bash', '--noprofile', '--norc', '-O', 'expand_aliases', '-c', script, 'bash', entry, mode],
            cwd=cwd, env=dict(self.env, **env), text=True, capture_output=True)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual({p: p.read_bytes() for p in self.install.rglob('*') if p.is_file()}, before)
        for event in self.events():
            self.assertFalse(Path(event['cwd']).parent.exists())
        return result.stdout + result.stderr

    def test_alias_uses_paper_directory_and_installed_helpers(self):
        original = (self.project / 'main.tex').read_bytes()
        self.invoke_alias(self.project, 'main.tex', 'all')
        self.assertEqual((self.project / 'main-ja.pdf').read_text(), 'mock PDF ja')
        self.assertEqual((self.project / 'main-en.pdf').read_text(), 'mock PDF en')
        self.assertEqual((self.project / 'main.tex').read_bytes(), original)
        self.assertEqual(self.events()[0]['sources'].keys(), {'main.tex'})

    def test_alias_accepts_absolute_document_from_unrelated_directory(self):
        launch = self.base / 'launch'
        launch.mkdir()
        self.invoke_alias(launch, str(self.project / 'main.tex'))
        self.assertTrue((self.project / 'main-en.pdf').exists())
        self.assertEqual(list(launch.iterdir()), [])

    def test_alias_can_build_both_from_separate_installation(self):
        self.invoke_alias(self.project, 'main.tex', 'both')
        self.assertEqual((self.project / 'main-both.pdf').read_text(), 'mock PDF both')

    def test_alias_resolves_document_and_builder_from_caller(self):
        tool = self.base / 'local tools' / 'compile.sh'
        tool.parent.mkdir()
        tool.write_text(FAKE_BUILDER)
        tool.chmod(0o755)
        # Identical relative names near the paper must not override caller paths.
        decoy = self.write('local tools/compile.sh', '#!/bin/sh\nexit 99\n')
        decoy.chmod(0o755)
        self.invoke_alias(self.base, str((self.project / 'main.tex').relative_to(self.base)),
                          TEXLINGUA_BUILDER='local tools/compile.sh')
        self.assertEqual((self.project / 'main-en.pdf').read_text(), 'custom PDF en')
        self.assertEqual([x['args'] for x in self.events()], [['./main.tex', 'en']])

    def test_cdpath_does_not_redirect_relative_document(self):
        shadow = self.base / 'cdpath'
        decoy = shadow / self.project.name
        decoy.mkdir(parents=True)
        (decoy / 'main.tex').write_text('Wrong project\n')
        self.invoke_alias(self.base, str((self.project / 'main.tex').relative_to(self.base)),
                          CDPATH=str(shadow))
        self.assertTrue((self.project / 'main-en.pdf').exists())
        self.assertFalse((decoy / 'main-en.pdf').exists())

    def test_cdpath_does_not_redirect_relative_builder(self):
        local = self.base / 'tools' / 'compile.sh'
        local.parent.mkdir()
        local.write_text(FAKE_BUILDER)
        local.chmod(0o755)
        shadow = self.base / 'cdpath'
        decoy = shadow / 'tools' / 'compile.sh'
        decoy.parent.mkdir(parents=True)
        decoy.write_text('#!/bin/sh\nexit 99\n')
        decoy.chmod(0o755)
        self.invoke_alias(self.base, str(self.project / 'main.tex'),
                          TEXLINGUA_BUILDER='tools/compile.sh', CDPATH=str(shadow))
        self.assertEqual((self.project / 'main-en.pdf').read_text(), 'custom PDF en')

    def test_relative_script_path_ignores_cdpath(self):
        shadow = self.base / 'cdpath'
        (shadow / 'installed tools' / 'texlingua').mkdir(parents=True)
        result = subprocess.run(
            [str((self.install / 'build.sh').relative_to(self.base)), str(self.project / 'main.tex'), 'en'],
            cwd=self.base, env=dict(self.env, CDPATH=str(shadow)), text=True, capture_output=True)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertTrue((self.project / 'main-en.pdf').exists())


if __name__ == '__main__':
    unittest.main(verbosity=2)
