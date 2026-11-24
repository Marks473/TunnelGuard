# Third-party components

The MIT license covers the TunnelGuard project. Packaged third-party components retain their own terms. License files from the build dependencies are included in the installed `licenses` directory.

## Offline translation model

TunnelGuard's public installer uses the English-to-Russian **OPUS-MT** model from Helsinki-NLP, release `opus-2020-02-11`. The [original archive](https://object.pouta.csc.fi/OPUS-MT-models/en-ru/opus-2020-02-11.zip) contains a **Creative Commons Attribution 4.0 International** license. TunnelGuard converts the original Marian weights to CTranslate2 format and applies int8 quantization. The upstream README and license are included in the installed `translation_model` directory. [OPUS-MT](https://github.com/Helsinki-NLP/Opus-MT) · [CC BY 4.0](https://creativecommons.org/licenses/by/4.0/)

## Windows distribution

- [Python](https://www.python.org/psf/license/) and [Tcl/Tk](https://www.tcl-lang.org/software/tcltk/license.html) provide the runtime and interface.
- [Pillow](https://github.com/python-pillow/Pillow), [pywin32](https://github.com/mhammond/pywin32), [CTranslate2](https://github.com/OpenNMT/CTranslate2), [SentencePiece](https://github.com/google/sentencepiece), [NumPy](https://github.com/numpy/numpy) and [PyYAML](https://github.com/yaml/pyyaml) ship under their respective terms.
- [PyInstaller](https://pyinstaller.org/en/stable/license.html) packages the app. The bootloader exception permits distribution of packaged applications under their own license.
- Intel OpenMP runtime, from the CTranslate2 wheel and verified against `intelopenmp.redist.win 2025.3.0.640`, is distributed with Intel’s license and third-party notices. [Intel OpenMP Runtime NuGet package](https://www.nuget.org/packages/intelopenmp.redist.win/2025.3.0.640)
- [Inno Setup](https://jrsoftware.org/isinfo.php) builds the Windows installer.
- Microsoft Visual C++ Redistributable x64 is a system prerequisite. [Microsoft Visual C++ Redistributable](https://learn.microsoft.com/en-us/cpp/windows/latest-supported-vc-redist)

Protected applications, AmneziaVPN and Google News RSS are external products or services. Their names identify supported integrations.
