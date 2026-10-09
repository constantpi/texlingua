"""Behavioral tests with fake TeX commands; no TeX installation is used."""
import hashlib
import json
import os
from pathlib import Path
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


class BuildTests(unittest.TestCase):
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


if __name__ == '__main__':
    unittest.main(verbosity=2)
