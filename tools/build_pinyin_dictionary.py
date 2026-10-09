"""Build a host-encoded dictionary; inputs and their licenses belong to the host."""
import argparse
import json
import re
from pathlib import Path


def generate(charset, readings, frequency=None):
    if not isinstance(charset, dict) or not isinstance(readings, dict) or not readings:
        raise ValueError("Expected charset and nonempty readings objects")
    frequency = {} if frequency is None else frequency
    if not isinstance(frequency, dict) or any(type(v) is not int or v < 0 for v in frequency.values()):
        raise ValueError("Frequencies must be nonnegative integers")
    encoded = {}
    for char, code in charset.items():
        if not isinstance(char, str) or len(char) != 1:
            raise ValueError("Charset keys must be single Unicode characters")
        if isinstance(code, str) and re.fullmatch(r"(?:0[xX])?[0-9a-fA-F]{4}", code):
            code = int(code, 16)
        if type(code) is not int or not 256 <= code <= 65535 or code >> 8 == 255 or code & 255 == 255:
            raise ValueError("Expected a two-byte code without the FF terminator")
        encoded[char] = code
    if len(set(encoded.values())) != len(encoded):
        raise ValueError("Ambiguous character-to-code mapping")
    entries, codes = [], []
    for key, chars in sorted(readings.items()):
        if not isinstance(key, str) or not re.fullmatch(r"[a-z]{1,6}", key):
            raise ValueError("Use lowercase toneless pinyin, v for umlaut-u, maximum 6 letters")
        if not isinstance(chars, list) or not chars or any(not isinstance(c, str) or len(c) != 1 for c in chars):
            raise ValueError("Each syllable needs a nonempty list of characters")
        chars = list(dict.fromkeys(chars))
        if any(c not in encoded for c in chars):
            raise ValueError("Reading references a character missing from the host charset")
        # Stable ties preserve the host's curated reading order.
        chars.sort(key=lambda c: -frequency.get(c, 0))
        entries.append((key, len(codes), len(chars)))
        codes.extend(encoded[c] for c in chars)
    return ('#include "cki_pinyin.h"\n'
            'static const unsigned short codes[] = {\n' +
            ','.join('0x%04X' % c for c in codes) + '\n};\n'
            'static const CKIPinyinEntry entries[] = {\n' +
            ',\n'.join('{"%s",%du,%du}' % e for e in entries) + '\n};\n'
            'const CKIPinyinDictionary cki_pinyin_dictionary = {entries,%du,codes,%du};\n' % (len(entries), len(codes)))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--charset', type=Path, required=True)
    parser.add_argument('--readings', type=Path, required=True)
    parser.add_argument('--frequency', type=Path)
    parser.add_argument('-o', '--output', type=Path, required=True)
    args = parser.parse_args()
    try:
        read = lambda p: json.loads(p.read_text(encoding='utf-8'))
        result = generate(read(args.charset), read(args.readings), read(args.frequency) if args.frequency else None)
        # Never overwrite input data or an existing generated table implicitly.
        with args.output.open('x', encoding='utf-8', newline='\n') as stream:
            stream.write(result)
    except (ValueError, OSError) as exc:
        parser.error(str(exc))


if __name__ == '__main__':
    main()
