"""Compile mod sources against the fixed game's assemblies without launching it."""
import argparse
from pathlib import Path
import subprocess


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--managed", type=Path, required=True)
    parser.add_argument("--output", type=Path, default=Path(".runtime/compile"))
    args = parser.parse_args()
    references = sorted(args.managed.glob("*.dll"))
    if not references:
        parser.error("--managed must contain the fixed game's DLLs")
    version, location = subprocess.check_output(["dotnet", "--list-sdks"], text=True).splitlines()[-1].split(" ", 1)
    compiler = Path(location.strip("[]")) / version / "Roslyn/bincore/csc.dll"
    args.output.mkdir(parents=True, exist_ok=True)
    command = ["dotnet", str(compiler), "/nologo", "/target:library", "/nostdlib+",
               f"/out:{args.output / 'LlmOfQud.dll'}"]
    command += [f"/r:{path}" for path in references]
    command += [str(path) for path in sorted((Path(__file__).parent / "LlmOfQud").glob("*.cs"))]
    result = subprocess.run(command, capture_output=True, text=True)
    output = result.stdout + result.stderr
    (args.output / "compile.log").write_text(output)
    print(output if output else "Compilation succeeded")
    return result.returncode


if __name__ == "__main__":
    raise SystemExit(main())
