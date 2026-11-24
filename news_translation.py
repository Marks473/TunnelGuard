from functools import lru_cache
from pathlib import Path
import re


CYRILLIC = re.compile(r"[А-Яа-яЁё]")
LATIN = re.compile(r"[A-Za-z]")


@lru_cache(maxsize=1)
def load_translator():
    from ctranslate2 import Translator
    from sentencepiece import SentencePieceProcessor

    directory = Path(__file__).with_name("translation_model")
    encoder = SentencePieceProcessor(model_file=str(directory / "source.spm"))
    decoder = SentencePieceProcessor(model_file=str(directory / "target.spm"))
    engine = Translator(str(directory / "model"), device="cpu", inter_threads=1, intra_threads=2)
    return encoder, decoder, engine


def translate_titles(titles):
    translations = {}
    pending = []
    for title in dict.fromkeys(titles):
        cyrillic = len(CYRILLIC.findall(title))
        latin = len(LATIN.findall(title))
        if cyrillic >= latin:
            translations[title] = title
        else:
            pending.append(title)
    if not pending:
        return translations

    encoder, decoder, engine = load_translator()
    tokens = encoder.encode(pending, out_type=str)
    results = engine.translate_batch(tokens, max_batch_size=12, beam_size=3,
                                     max_decoding_length=200, replace_unknowns=True)
    for original, result in zip(pending, results, strict=True):
        translated = decoder.decode(result.hypotheses[0]).strip()
        if CYRILLIC.search(translated):
            translations[original] = translated
    return translations
