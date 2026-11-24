"""Download, verify and convert the OPUS-MT English → Russian release for Windows builds."""

import argparse
import hashlib
from pathlib import Path
import shutil
from tempfile import TemporaryDirectory
from urllib.request import urlopen
from zipfile import ZipFile


MODEL_URL = "https://object.pouta.csc.fi/OPUS-MT-models/en-ru/opus-2020-02-11.zip"
MODEL_SHA256 = "798027c7e4ae7ddf89fea13ce80de517b6726d7e710fa5a9b5a376316dbf1677"
MAX_ARCHIVE_BYTES = 300 * 1024 * 1024
FILES = (
    "LICENSE", "README.md", "decoder.yml", "source.spm", "target.spm",
    "opus.spm32k-spm32k.vocab.yml",
    "opus.spm32k-spm32k.transformer-align.model1.npz.best-perplexity.npz",
)
PROJECT = Path(__file__).resolve().parents[1]


def verify_archive(path):
    if path.stat().st_size > MAX_ARCHIVE_BYTES:
        raise ValueError("OPUS-MT archive is too large")
    with path.open("rb") as archive:
        if hashlib.file_digest(archive, "sha256").hexdigest() != MODEL_SHA256:
            raise ValueError("OPUS-MT archive does not match its pinned SHA-256")


def download(path):
    with urlopen(MODEL_URL, timeout=60) as response, path.open("wb") as file:
        remaining = MAX_ARCHIVE_BYTES
        while block := response.read(1024 * 1024):
            remaining -= len(block)
            if remaining < 0:
                raise ValueError("OPUS-MT archive is too large")
            file.write(block)
    verify_archive(path)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--archive", type=Path, help="Use a local copy of the pinned upstream ZIP.")
    args = parser.parse_args()
    output = PROJECT / "translation_model"
    if (output / "model/model.bin").is_file():
        print(f"Already prepared: {output}")
        return
    if output.exists():
        raise FileExistsError(f"Move the incomplete model directory before rebuilding: {output}")

    from ctranslate2.converters import OpusMTConverter

    with TemporaryDirectory(prefix=".opus-mt-", dir=PROJECT) as folder:
        temporary = Path(folder)
        archive_path = args.archive or temporary / "upstream.zip"
        if args.archive:
            verify_archive(archive_path)
        else:
            download(archive_path)
        with ZipFile(archive_path) as archive:
            for name in FILES:
                with archive.open(name) as input_file, (temporary / name).open("wb") as output_file:
                    shutil.copyfileobj(input_file, output_file)
        ready = temporary / "ready"
        ready.mkdir()
        OpusMTConverter(str(temporary)).convert(str(ready / "model"), quantization="int8")
        for name in ("source.spm", "target.spm", "LICENSE"):
            shutil.copy2(temporary / name, ready / name)
        shutil.copy2(temporary / "README.md", ready / "UPSTREAM.md")
        ready.rename(output)
    print(f"Prepared {output}")


if __name__ == "__main__":
    main()
