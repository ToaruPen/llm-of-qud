"""Compile analysis units with SDK analyzers; never execute or deploy output."""

import argparse
import json
import os
import subprocess
import sys
import tempfile
from functools import lru_cache
from pathlib import Path
from urllib.parse import unquote, urlparse

CONFIG = Path(__file__).resolve().parent / "roslyn"
ROOT = CONFIG.parent.parent.parent
SETTINGS = ROOT / ".runtime/quality/settings.json"


@lru_cache(maxsize=1)
def sdk_paths():
    version = subprocess.check_output(["dotnet", "--version"], cwd=CONFIG, text=True).strip()
    installed = subprocess.check_output(["dotnet", "--list-sdks"], text=True)
    for line in installed.splitlines():
        candidate, location = line.split(" ", 1)
        if candidate == version:
            sdk = Path(location.strip("[]")) / version
            required = [sdk / "Roslyn/bincore/csc.dll", *analyzers(sdk)]
            if not all(path.is_file() for path in required):
                raise ValueError(f"SDK compiler/analyzers missing from {sdk}")
            return sdk
    raise ValueError(f"Selected SDK {version} is not installed")


def analyzers(sdk):
    directory = sdk / "Sdks/Microsoft.NET.Sdk/analyzers"
    return [directory / f"Microsoft.CodeAnalysis.{name}.dll"
            for name in ("NetAnalyzers", "CSharp.NetAnalyzers")]


def framework_references(sdk):
    packs = sdk.parent.parent / "packs/Microsoft.NETCore.App.Ref"
    candidates = list(packs.glob("10.0.*/ref/net10.0"))
    if not candidates:
        raise ValueError("Install the .NET 10 SDK reference pack to analyze net10.0 test units")
    latest = max(candidates, key=lambda path: tuple(map(int, path.parent.parent.name.split("."))))
    return sorted(latest.glob("*.dll"))


def compile_sources(sources, references, *, target="library", implicit_usings=False, defines=()):
    if not all(name.isidentifier() for name in defines):
        raise ValueError(f"Invalid preprocessor symbol in {list(defines)}")
    sdk = sdk_paths()
    with tempfile.TemporaryDirectory(prefix="qud-roslyn-") as directory:
        output = Path(directory)
        sources = list(sources)
        if implicit_usings:
            generated = output / "GlobalUsings.cs"
            generated.write_text("\n".join(f"global using {name};" for name in (
                "System", "System.Collections.Generic", "System.IO", "System.Linq",
                "System.Net.Http", "System.Threading", "System.Threading.Tasks")))
            sources.append(generated)
        report = output / "diagnostics.sarif"
        command = ["dotnet", str(sdk / "Roslyn/bincore/csc.dll"), "/nologo", "/nostdlib+",
                   f"/target:{target}", "/langversion:latest" if implicit_usings else "/langversion:9",
                   "/nullable:disable", f"/out:{output / 'Analysis.dll'}",
                   f"/errorlog:{report},version=2.1", f"/analyzerconfig:{CONFIG / 'quality.globalconfig'}"]
        if defines:
            command.append("/define:" + ";".join(defines))
        command += [f"/analyzer:{path}" for path in analyzers(sdk)]
        command += [f"/reference:{path}" for path in references]
        command += list(map(str, sources))
        result = subprocess.run(command, cwd=CONFIG, capture_output=True, text=True, check=False)
        if not report.is_file():
            raise ValueError(f"Roslyn did not produce diagnostics: {result.stdout}{result.stderr}")
        runs = json.loads(report.read_text())["runs"]
        diagnostics = [item for run in runs for item in run.get("results", [])
                       if item.get("level") in ("warning", "error")]
        failed = result.returncode != 0 or any(
            item["ruleId"].startswith("AD") or item["ruleId"] in {"CS8032", "CS8033", "CS8034"}
            for item in diagnostics)
        return (2 if failed else int(bool(diagnostics))), diagnostics


def select_units(root, selected):
    root = root.resolve()
    selected = {path.resolve() for path in selected}
    units = []
    covered = set()
    for unit in json.loads((CONFIG / "units.json").read_text()):
        primary = {path.resolve() for pattern in unit["sources"] for path in root.glob(pattern)
                   if path.is_file() and not path.is_symlink()}
        if not primary.intersection(selected):
            continue
        covered.update(primary)
        support = {root / path for path in unit.get("support", [])}
        missing = [str(path) for path in support if not path.is_file()]
        if missing:
            raise ValueError(f"Missing dependencies for {unit['name']}: {missing}")
        units.append({**unit, "files": sorted(primary | support)})
    if selected - covered:
        raise ValueError("C# sources have no analysis unit; update tools/quality/roslyn/units.json: "
                         + ", ".join(str(path.relative_to(root)) for path in sorted(selected - covered)))
    return units


def managed_directory(explicit=None):
    value = explicit or os.environ.get("QUD_MANAGED")
    if not value and SETTINGS.is_file():
        value = json.loads(SETTINGS.read_text())["managed"]
    if not value:
        raise ValueError("Set QUD_MANAGED or run just quality-setup-csharp /absolute/path/to/Managed")
    managed = Path(value).expanduser().resolve()
    required = ("Assembly-CSharp.dll", "mscorlib.dll", "Newtonsoft.Json.dll")
    if not all((managed / name).is_file() for name in required):
        raise ValueError(f"Managed directory must contain the fixed game's {', '.join(required)}: {managed}")
    return managed


def run(selected, managed=None):
    units = select_units(ROOT, selected)
    sdk = sdk_paths()
    if any(unit["framework"] == "game" or unit.get("newtonsoft") for unit in units):
        managed = managed_directory(managed)
    exit_code = 0
    for unit in units:
        print(f"roslyn: {unit['name']} ({len(unit['files'])} files, {unit['framework']})", flush=True)
        references = sorted(managed.glob("*.dll")) if unit["framework"] == "game" else framework_references(sdk)
        if unit.get("newtonsoft"):
            references.append(managed / "Newtonsoft.Json.dll")
        code, diagnostics = compile_sources(
            unit["files"], references, target="library" if unit["framework"] == "game" else "exe",
            implicit_usings=unit.get("implicit_usings", False), defines=unit.get("defines", ()))
        for item in diagnostics:
            location = next(iter(item.get("locations", [])), {}).get("physicalLocation", {})
            uri = location.get("artifactLocation", {}).get("uri", "")
            path = unquote(urlparse(uri).path) if uri.startswith("file:") else uri
            region = location.get("region", {})
            print(f"{path}:{region.get('startLine', 1)}:{region.get('startColumn', 1)}: "
                  f"{item['level']} {item['ruleId']}: {item['message']['text']}")
        print(f"roslyn: {unit['name']}: {len(diagnostics)} diagnostics; exit {code}", flush=True)
        exit_code = max(exit_code, code)
    return exit_code


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--managed", type=Path)
    parser.add_argument("--configure", type=Path, help="Save the fixed-game Managed path locally")
    parser.add_argument("paths", nargs="*", type=Path)
    args = parser.parse_args()
    try:
        if args.configure:
            managed = managed_directory(args.configure)
            sdk = sdk_paths()
            SETTINGS.parent.mkdir(parents=True, exist_ok=True)
            SETTINGS.write_text(json.dumps({"managed": str(managed)}, indent=2) + "\n")
            print(f"Roslyn SDK: {sdk.name}; settings: {SETTINGS}")
            return 0
        if not args.paths:
            parser.error("Provide source files, or use just anti-slop-csharp for default source selection")
        return run(args.paths, args.managed)
    except (OSError, ValueError, KeyError, subprocess.CalledProcessError) as error:
        print(f"roslyn: {error}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
