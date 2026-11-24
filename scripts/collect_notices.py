import argparse
from importlib.metadata import distribution
from pathlib import Path
import shutil
import sys


BUNDLED_RUNTIME_FILES = {
    "cudnn64_9.dll", "mfc140u.dll", "msvcp140.dll", "msvcp140_1.dll", "msvcp140_2.dll",
    "vcruntime140.dll", "vcruntime140_1.dll",
}
DEPENDENCIES = (
    "Pillow", "pywin32", "ctranslate2", "sentencepiece", "numpy", "PyYAML", "pyinstaller",
)


def copy_license_file(path, destination):
    if path.is_file():
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(path, destination)


def main():
    parser = argparse.ArgumentParser(description="Collect distribution licenses for the installer.")
    parser.add_argument("destination", type=Path)
    args = parser.parse_args()
    project = Path(__file__).resolve().parents[1]
    payload = (project / ".build/installer-payload/TunnelGuard").resolve()
    if args.destination.resolve() != payload / "licenses" or not (payload / "TunnelGuard.exe").is_file():
        parser.error("Expected the generated TunnelGuard installer payload.")
    vendored = project / "third_party" / "licenses"
    shutil.copytree(vendored, args.destination, dirs_exist_ok=True)
    # Leave the Microsoft runtime to the documented system prerequisite.
    # The CPU translation backend can omit the CUDA stub.
    for library in payload.rglob("*.dll"):
        if library.name.casefold() in BUNDLED_RUNTIME_FILES and library.resolve().is_relative_to(payload):
            library.unlink()

    for dependency in DEPENDENCIES:
        installed = distribution(dependency)
        for member in installed.files or ():
            name = member.name.casefold()
            if name.startswith(("license", "copying", "notice")) and any(
                part.endswith(".dist-info") for part in member.parts
            ):
                copy_license_file(Path(installed.locate_file(member)), args.destination / dependency / member.name)
    base = Path(sys.base_prefix)
    copy_license_file(base / "LICENSE.txt", args.destination / "python" / "LICENSE.txt")
    for folder in ("tcl8.6", "tk8.6"):
        copy_license_file(base / "tcl" / folder / "license.terms", args.destination / folder / "license.terms")


if __name__ == "__main__":
    main()
