set positional-arguments

# List available commands.
default:
    @just --list

# Read-only anti-slop candidates for all source languages; optional file/directory scope.
anti-slop *paths:
    python3 -B tools/quality/check.py "$@"

# Python: unused bindings, redundant constructs and selected bug patterns.
anti-slop-python *paths:
    python3 -B tools/quality/check.py --language python "$@"

# C#: Roslyn compiler and .NET SDK analyzers; expands scope to compilation units.
anti-slop-csharp *paths:
    python3 -B tools/quality/check.py --language csharp "$@"

# Optional syntax-only C# hints; does not replace Roslyn or run in the main gate.
anti-slop-structural *paths:
    python3 -B tools/quality/check.py --language csharp --structural "$@"

# Save the fixed game's Managed DLL path locally; verify the installed Roslyn SDK.
quality-setup-csharp managed:
    python3 -B tools/quality/roslyn.py --configure "$1"

# Swift: selected SwiftLint candidate rules; never execute the hover helper.
anti-slop-swift *paths:
    python3 -B tools/quality/check.py --language swift "$@"

# Verify scope/error handling and positive/negative detector fixtures.
anti-slop-test:
    python3 -B -m unittest discover -s tools/quality -p 'test_*.py' -v
    ast-grep test -c tools/quality/sgconfig.yml --skip-snapshot-tests

# Print local tool versions (does not install or upgrade tools).
quality-tools:
    python3 --version
    just --version
    ruff --version
    cd tools/quality/roslyn && dotnet --version
    ast-grep --version
    swiftlint version
