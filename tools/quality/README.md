# anti-slop 検査

冗長・未使用・重複した構文や一部の誤りを、修正候補として検出する静的検査。AI が書いたコードかどうかは判定しない。自動修正、ゲーム起動、入力送信は行わない。

## 実行

| コマンド | 対象 |
|---|---|
| `just` | コマンド一覧 |
| `just anti-slop` | 全言語の現行ソース |
| `just anti-slop harness tools` | 指定ディレクトリだけ |
| `just anti-slop "path with spaces/file.py"` | 個別ファイル。複数指定も可能 |
| `just anti-slop-python` | Python |
| `just anti-slop-csharp` | C# の Roslyn 解析 |
| `just anti-slop-structural` | 任意の C# 構文検査。主検査には含めない |
| `just quality-setup-csharp /absolute/path/to/Managed` | 固定ゲーム DLL の場所をローカルに保存 |
| `just anti-slop-swift` | Swift |
| `just anti-slop-test` | 実アナライザー、実行経路、構文ルールの陽性・陰性例 |
| `just quality-tools` | 導入済みツールの版確認 |

リポジトリ配下で実行する。`just` はルートへ移動してレシピを実行するため、引数の相対パスはルート基準。検出位置・ルール ID は標準出力へ出る。

Python ランナーの終了値は **0: 候補なし、1: 候補あり、2: 実行不備**。候補やツール不足があっても他言語は検査する。対象が空、存在しないパス、リポジトリ外のパスはエラー。`just` 自体はレシピの失敗を非ゼロで返す。

## 対象・ルール

| 言語 | ツール／設定 | 検出対象 |
|---|---|---|
| Python | Ruff・[ruff.toml](ruff.toml) | 未使用 import・ローカル変数、再定義、可変デフォルト値、無意味な式、冗長な内包表記・条件分岐など |
| C# | Roslyn・[quality.globalconfig](roslyn/quality.globalconfig) | データフロー上の到達不能条件、戻り値の無視、無駄なコレクション操作、例外の再送出、コンパイラー警告など |
| Swift | SwiftLint・[swiftlint.yml](swiftlint.yml) | 重複 import・条件、同一オペランド、不要な nil 合体や override、未使用クロージャ引数など |

`.py`・`.cs`・`.swift` を未追跡ファイルも含めて列挙する。隠しディレクトリ／ファイル、`archives`、`results`、`bin`、`obj`、`__pycache__`、`node_modules`、`tools/quality/fixtures` は除外する。シンボリックリンクは辿らない。除外は明示的なパス指定にも適用される。列挙・除外の正本は [check.py](check.py)。Markdown・JSON・XML はコードの anti-slop 検査対象外。

専用ツールの既存ルールを優先し、構文だけで判定できる不足分を ast-grep で補う。型・シンボル・データフローが必要な検査は専用アナライザー側で扱う。[既存の AST ルール](rules/)は空の catch、再 throw だけの catch、真偽値の三項演算子を扱う任意の補助検査。Roslyn が使えない場合の自動代替にはしない。

## C# の解析設定

| 設定 | 内容 |
|---|---|
| [global.json](roslyn/global.json) | 解析用 SDK を 10.0.100＋同 feature band のパッチ更新に固定 |
| [quality.globalconfig](roslyn/quality.globalconfig) | CA1508、CA1806、CA1825、CA1827、CA1829、CA1851、CA1854、CA2200、CA2012 を選択 |
| [units.json](roslyn/units.json) | 本体・プローブ7単位とテスト5単位のソース・依存関係 |
| `.runtime/quality/settings.json` | このマシンの固定ゲーム Managed パス。Git 管理対象外 |

本体・プローブは固定ゲーム DLL、テストは .NET 10 参照パックで解析する。既存の `mod/check_compile.py` と同じ直接コンパイル経路に SDK 同梱アナライザーを追加した。既存のゲーム／テストプロジェクト、ゲーム側のビルドやロード経路は変更しない。

個別ファイルを指定しても、型解決のため対応する単位全体と依存ソースを読み、その単位の診断をすべて出す。新しい C# 配置やテスト依存を追加したら `units.json` も更新する。単位の `defines` 配列は、その単位のコンパイルに渡すプリプロセッサー記号を指定する（例: SurfaceCheck のゲーム非依存テスト用 `LLMOFQUD_SURFACE_TESTS`）。未登録ソースはエラー。DLL と SARIF は OS の一時ディレクトリに生成し、診断後に削除する。ゲームや生成 DLL は実行しない。

パス指定の優先順位は `--managed` → 環境変数 `QUD_MANAGED` → ローカル設定。初回設定は `just quality-setup-csharp /absolute/path/to/Managed`。既定の `just anti-slop` にも Roslyn が含まれる。

## 準備

Python 3.12 以上、`just`、`ruff`、`dotnet`、`swiftlint` が PATH に必要。補助検査とルールテストには `ast-grep` も必要。ゲーム用 Python の依存とは分離しており、`pyproject.toml` と `uv.lock` の変更は不要。

macOS で不足しているツールだけを導入する場合の例:

```sh
brew install just ruff ast-grep swiftlint
```

上記に加え .NET SDK 10.0.100（または解析用 `global.json` が許すパッチ版）が必要。Roslyn と .NET アナライザーは SDK に同梱され、追加 NuGet パッケージは不要。

確認済みの版: just 1.56.0 / Ruff 0.15.10 / .NET SDK 10.0.100 / ast-grep 0.42.0 / SwiftLint 0.63.2。版を変えた場合は `just anti-slop-test` で検出契約を確認する。テストは外部ツールを実際に呼ぶため、未導入時は失敗する。検査器テスト自体にはゲーム DLL は不要。

## 検出後の判断

| 分類 | 対応 |
|---|---|
| REMOVE | 挙動が変わらない余剰だと確認できたものだけ削除する |
| RETAIN | 境界条件・互換性・外部呼び出しなどの根拠を確認して残す |
| DEFECT | 挙動を変える修正は、不具合の回帰テストとともに別扱いにする |

空の catch はコメント付きでも候補になる。意図的な例外の無視、演算子のオーバーロード、コールバック／リフレクションによる参照は個別確認が必要。検査を緑にするためだけの一括修正や一括抑制はしない。

Roslyn でも過剰な抽象化や意味的重複の全容、スレッド間更新やリフレクションの意図までは判定できない。CA1508 の到達不能判定は特に実行契約との照合が必要。候補なしでも設計・実機の正しさを保証しない。既存の動作テスト／コンパイル検証は別途必要。

参照: [.NET アナライザー設定](https://learn.microsoft.com/dotnet/fundamentals/code-analysis/configuration-files)、[コンパイラーの診断・SARIF](https://learn.microsoft.com/dotnet/csharp/language-reference/compiler-options/errors-warnings)。LLM 向けのコマンド一覧と棲み分けは [TOOLS.md](../../TOOLS.md) に集約する。
