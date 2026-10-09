# TeX 論文の日英切替ビルド

元の UTF-8 の TeX ソースを変更せず、日本語版・英語版を生成する Bash スクリプトです。
翻訳ペアは通常の LaTeX コメントで記述するため、元ソースを直接コンパイルすることもできます。
現在の標準ビルドは、日本語と英語の混在に対応する pLaTeX を使用します。

## 実行方法

```bash
./build.sh main.tex       # 元ソースをそのままビルド → main.pdf
./build.sh main.tex ja    # 日本語版 → main-ja.pdf
./build.sh main.tex en    # 元ソースをビルド＋日本語検出 → main-en.pdf
./build.sh main.tex all   # 日本語版と英語版
```

PDF は指定した TeX ファイルと同じディレクトリに出力します。
別の作業ディレクトリから絶対パス・相対パスで指定しても利用できます。
`paper.tex` なら `paper.pdf`、`paper-ja.pdf`、`paper-en.pdf` になります。
引数不足、過剰な引数、不明な言語指定、空の言語指定はエラーです。

### alias から利用する

リポジトリを原稿とは別の場所に置き、Bash の `~/.bashrc` などに alias を登録できます。
`build.sh` と同梱の `scripts/` は同じリポジトリ内に保持してください。

```bash
alias texlingua='/workspace/texlingua/build.sh'

cd /path/to/paper
texlingua paper.tex en
TEXLINGUA_BUILDER=./compile-paper.sh texlingua paper.tex all
```

リポジトリのパスに空白がある場合は、alias の値の中でもパスを引用します。

```bash
alias texlingua='"/path with spaces/texlingua/build.sh"'
```

パスの基準は次のとおりです。リポジトリの場所へ `cd` する必要はありません。

| 対象 | 基準 |
|---|---|
| 引数の `paper.tex` | コマンドを実行したディレクトリ |
| 相対指定の `TEXLINGUA_BUILDER` | コマンドを実行したディレクトリ |
| 同梱の補助プログラム・標準ビルダー | `build.sh` があるディレクトリ |
| コピーする原稿・画像・設定ファイル | 指定 TeX があるディレクトリ以下 |
| ビルダー実行中の相対パス | `/tmp` 内の原稿コピーのルート |
| 完成した PDF の出力先 | 指定 TeX と同じディレクトリ |

たとえば `texlingua papers/paper.tex en` では原稿のコピー範囲と PDF 出力先は `papers/` ですが、
`TEXLINGUA_BUILDER=./compile.sh` は起動場所の `./compile.sh` を指します。
このパス解決は、シェルの `CDPATH` の設定に影響されません。

### 必要な環境

共通の依存関係は Bash、Perl（標準モジュールのみ）、GNU tar、一般的な Unix コマンドです。
標準ビルダーでは `ptex2pdf` と pLaTeX・dvipdfmx、BibTeX 文献を使用するときは `pbibtex` も必要です。
独自ビルダーを指定した場合は、そのビルダーが使う TeX 環境を用意してください。
サンプルは `jsarticle`、`amsmath`、`amssymb`、`amsthm`、`graphicx`、`jplain.bst` を使用します。
Linux / WSL を想定しています。実行環境へ自動でパッケージを導入する処理はありません。

## 執筆方法

```latex
    %j 任意の $n$ に対して成立する。
    This holds for every $n$.
```

`ja` ではこれを次の一行に変換します。

```latex
    任意の $n$ に対して成立する。
```

- 行頭のインデントを保持し、`%j` とその直後の空白・タブを取り除きます。
- 直後の物理的な一行を英訳として取り除きます。
- `%japanese` や空白を伴わない `%j` は通常のコメントとして保持します。
- 英訳行がない、空白だけ、コメントだけの場合は `%j` のファイル名と行番号でエラーを報告します。
- 未翻訳の日本語、数式、コマンドなど、翻訳ペア以外の行はそのままです。
- 省略時と `en` では変換も翻訳ペアの検証も行いません。

サンプルの構成は次のとおりです。

```text
main.tex                       文書クラス、タイトル、文献指定
sections/introduction.tex      翻訳ペア、未翻訳の段落、図・文献参照
sections/proof.tex             インデント付き翻訳ペア、補題・数式・ラベル
figures/diagram.tex            picture 環境による図（外部画像不要）
references.bib                 文献データ
```

`\input` と `\include` の両方を使用しています。
英語版でも未翻訳の一段落が残り、その行が警告される想定です。
画像を使う論文では、`figures/` などの PDF・PNG・EPS もコピーされます。

## コンパイル方法

`TEXLINGUA_BUILDER` に実行可能なスクリプトのパスを指定すると、コンパイル手順を差し替えられます。

```bash
TEXLINGUA_BUILDER=./scripts/compile-paper.sh ./build.sh main.tex all
```

相対パスはコマンドを実行したディレクトリを基準に解決します。
パスは引数付きのコマンド文字列として解釈せず、一つの実行ファイルとして扱います。
ビルダーは一時コピー内で実行され、第1引数に `./main.tex`、第2引数に `default`・`ja`・`en` のいずれかを受け取ります。
同じ作業ディレクトリに `main.pdf` を生成し、失敗時は非ゼロ終了してください。
ビルダー未指定または空文字の場合は、同梱の ptex2pdf / pbibtex ビルダーを使用します。
詳細は [ビルダーの設定と契約](docs/build-backends.md) を参照してください。

### 標準ビルダー

標準ビルドでは、次の処理を一時ディレクトリ内で行います。

```bash
ptex2pdf -l -ot '-interaction=nonstopmode -kanji=utf8 -synctex=1 -halt-on-error -file-line-error -recorder' ./main.tex
pbibtex main -kanji=utf8
ptex2pdf -l -ot '-interaction=nonstopmode -kanji=utf8 -synctex=1 -halt-on-error -file-line-error -recorder' ./main.tex
ptex2pdf -l -ot '-interaction=nonstopmode -kanji=utf8 -synctex=1 -halt-on-error -file-line-error -recorder' ./main.tex
```

`-l` により pLaTeX を使用し、dvipdfmx で PDF にします。
エンジン向けのオプションは、[ptex2pdf の公式仕様](https://github.com/texjporg/ptex2pdf/blob/master/ptex2pdf.lua)
に従い、`-ot` の一つの引数にまとめています。
作業場所そのものを一時ディレクトリにするため、出力ディレクトリ指定は不要です。

最初の実行で生成された `.aux` と、その `\@input` 先に `\bibdata` があれば上記の四段階のビルドを実行します。
なければ `pbibtex` を省略し、ptex2pdf を合計二回実行します。
途中のコマンドが失敗したら、その言語の処理を停止します。
latexmk、別の TeX エンジン、Biber、索引生成などを使う場合は、これらを呼び出す独自ビルダーを指定してください。

元ソースは通常の LaTeX 文書なので、LaTeX Workshop から直接ビルドする場合に専用の設定は不要です。
エディター側のレシピには、文書クラスや使用パッケージに対応する TeX エンジンを指定してください。
`build.sh` 自体は LaTeX Workshop の設定や `.latexmkrc` を読み取りません。
独自ビルダーから latexmk を呼ぶ場合は、コピーされたプロジェクトの `.latexmkrc` を利用できます。
本スクリプトは PDF のみ持ち帰るため、スクリプト生成 PDF 用の SyncTeX ファイルは残りません。
エディターからの SyncTeX は従来の LaTeX Workshop のビルドで利用してください。

## 一時ファイルと出力の保護

`mktemp -d /tmp/texlingua.XXXXXXXX` で作業領域を作り、指定 TeX のあるディレクトリ以下を複製します。
さらに言語ごとの作業ディレクトリを作るため、日英の中間生成物は混ざりません。
日本語版ではコピーされたすべての `.tex` に変換を適用します。

`.git` などの VCS 管理領域、`.agents`、`.aws`、`.codex`、`node_modules`、`target`、`.venv`、
代表的な中間生成物、エントリーポイントの既存 PDF 三種類をコピー対象から除外します。
図版を失わないよう PDF 全般は除外しません。任意の大容量ファイルを自動判別する機能はありません。
`.aux`、`.bbl`、`.blg`、`.log`、`.dvi`、`.xdv`、`.fls`、`.fdb_latexmk`、`.synctex*`、
`.toc`、`.out`、`.lof`、`.lot`、`.nav`、`.snm` は中間生成物として除外します。

ビルドが成功し、空でない PDF が存在する場合だけ出力先へコピーします。
既存 PDF を途中まで上書きしないよう、同じ出力先ディレクトリに一時的な `.texlingua-pdf.*` を置き、
コピーが完了してから rename します。ビルド失敗時には既存 PDF を保持します。
`all` では両方を試し、成功した言語だけ出力し、片方でも失敗したら全体を非ゼロ終了とします。
終了時・エラー時・INT/TERM 受信時に `trap` で一時ファイルを削除します。
SIGKILL や電源断時の削除は保証できません。

## 未翻訳の日本語の検出

Perl の Unicode プロパティ `Hiragana`、`Katakana`、`Han` と、`〆`・長音符を使用します。
`々` や CJK 拡張漢字も検出対象です。利用できる Unicode データの版は Perl に依存します。

標準ビルダーは `-recorder` で生成される `.fls` を各コンパイル後に収集し、その和集合を残します。
独自ビルダーではビルダーが残した `.fls` を使用します。その記録から、
実際に読み込まれたコピー領域内の `.tex` とエントリーファイルを検査します。
重複読み込みを除き、未使用の TeX ファイルは通常検査しません。
`.fls` が生成されなかった場合は、その旨を警告してコピー内のすべての `.tex` を検査します。

各行の `%` の直前にある連続バックスラッシュが偶数ならコメント開始、奇数ならエスケープと判定します。
通常コメントと `%j` コメント内の日本語は検出しません。
警告には元のソースに対応する相対ファイル名・行番号・元の行を表示します。
日本語の存在はビルド失敗にはしません。`all` でも英語版の成功後に一回だけ報告します。
コンパイル自体が失敗した場合には未翻訳検査を実行しません。

## 制約

- コピー範囲はエントリー TeX のあるディレクトリ以下です。親・兄弟ディレクトリへの参照、
  絶対パスや `TEXINPUTS` で外部に置いた独自ソースはコピー・翻訳・検査の対象外です。
  依存ファイルをエントリー以下へ配置してください。
- コピー内のシンボリックリンクは明示的なエラーにします。リンク先の原本を編集・参照することを避けるためです。
- `ja` はコピー内の全 `.tex` を変換するため、未使用ファイルでも不正な翻訳ペアがあるとエラーになります。
- エントリーファイル名は英数字または `_` で始め、ASCII 英数字・空白・`_`・`-`・`.` のみ使用できます。
  ptex2pdf 内部のシェルコマンド生成を考慮した制限です。親ディレクトリ名には空白・日本語を使用できます。
- 原稿は UTF-8、TeX ファイルの拡張子は小文字 `.tex` を想定します。
- TeX の完全な構文解析はしません。`verbatim`、`\verb`、catcode 変更、マクロ展開、条件分岐で無効な本文などは
  特別扱いしません。`.fls` も読み込みファイル単位の記録なので、無効な分岐内の日本語を警告する場合があります。
- `.sty`・`.cls`・`.bib`・生成された `.bbl` 内の日本語は検査・変換しません。
  BibTeX を実行せず既成 `.bbl` を配布する構成は、コピー除外設定の調整が必要です。
- ビルダーの差し替えは文書クラスやプリアンブルを変更しません。別エンジンへ切り替える場合は、文書側の互換性も確認してください。

## 検証

自動テストはスクリプトの処理を検証します。実際の TeX による PDF の組版、図、定理番号、
ラベル・文献引用の解決、LaTeX Workshop との連携は検証範囲に含まれません。

```bash
bash -n build.sh
bash -n scripts/build-ptex2pdf.sh
perl -c scripts/tex-source.pl
python3 tests/test_build.py
```

Python 3 標準ライブラリによる動作テストを用意しています。
テストは一時的な模擬 `ptex2pdf` / `pbibtex` や独自ビルダーを使うため、TeX がなくても実行できます。
四つのビルドモード、翻訳ペアとエラー、CRLF、Unicode 検出、コメントのエスケープ、複数ファイル、
読み込み記録、文献レシピ、ビルダー差し替え、失敗時の既存 PDF 保護、`all` の継続、コピー除外、原本保持、一時領域削除を確認します。
別ディレクトリへの配置、alias 経由の起動、空白を含むパス、`CDPATH` を設定した環境でのパス解決も検証します。

## 実装ファイル

- `build.sh`: 引数検証、コピー、ビルド、PDF 公開、終了処理。
- `scripts/build-ptex2pdf.sh`: ptex2pdf / pbibtex を使う標準ビルダー。
- `scripts/tex-source.pl`: 翻訳ペア変換、Unicode 検査、読み込み記録・aux の処理。
- `main.tex`、`sections/*.tex`、`figures/diagram.tex`、`references.bib`: サンプル原稿。
- `tests/test_build.py`: TeX 不要の動作テスト。
- `.gitignore`: サンプルの生成 PDF と中間生成物の除外。

## ライセンス

このプロジェクトは MIT ライセンスで公開しています。詳細は [LICENSE](LICENSE) を参照してください。
