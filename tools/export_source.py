"""Export a standalone freestanding source integration bundle without editing a host."""
import argparse
import json
import re
import shutil
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

def _characters(charset_path):
    if charset_path is None:
        source = (ROOT / 'payload' / 'adapter_v10.c').read_text(encoding='utf-8')
        match = re.search(r'static\s+const\s+u16\s+chars\[(\d+)\]\s*=\s*\{([^}]+)\}', source, re.S)
        if not match:
            raise ValueError('Cannot locate the payload character table')
        body = re.sub(r'/\*.*?\*/|//[^\n]*', '', match[2], flags=re.S)
        values = [int(token.strip(), 0) for token in body.split(',') if token.strip()]
        if len(values) != int(match[1]):
            raise ValueError('Payload character table size mismatch')
    else:
        values = json.loads(Path(charset_path).read_text(encoding='utf-8'))
        if not isinstance(values, list) or not values:
            raise ValueError('Charset must be a nonempty JSON array')
        parsed = []
        for value in values:
            if isinstance(value, str):
                if not re.fullmatch(r'0[xX][0-9a-fA-F]{1,4}', value):
                    raise ValueError('Charset strings must be u16 hexadecimal values')
                value = int(value, 16)
            if type(value) is not int:
                raise ValueError('Charset entries must be integers or hex strings')
            parsed.append(value)
        values = parsed
    for value in values:
        if not 0 <= value <= 65535 or value and (value < 256 or value >> 8 == 255 or value & 255 == 255):
            raise ValueError('Charset entries must be two-byte codes without EOS (0xFF); zero is an empty cell')
    if not any(values):
        raise ValueError('Charset has no characters')
    if len(values) > 65535 * 32:
        raise ValueError('Charset exceeds page capacity')
    return values

def export_source(output_dir, charset_path=None):
    """Create bundle in a new/empty directory; return output_dir/files/character_count."""
    values = _characters(charset_path)
    out = Path(output_dir).resolve()
    if out.exists() and (not out.is_dir() or any(out.iterdir())):
        raise ValueError('Source output must be a new or empty directory; refusing overwrite')
    core = (ROOT / 'payload' / 'cki_text.h').read_text(encoding='utf-8')
    templates = {p.name: p.read_text(encoding='utf-8') for p in (ROOT / 'sdk').iterdir() if p.is_file()}
    table = '\n'.join(','.join('0x%04X' % v for v in values[i:i+16]) + ',' for i in range(0, len(values), 16))
    templates['cki_keyboard.c'] = templates['cki_keyboard.c'].replace('@CHARACTERS@', table).replace('@COUNT@', str(len(values)))
    templates['cki_text.h'] = core
    out.mkdir(parents=True, exist_ok=True)
    for name, content in templates.items():
        (out / name).write_text(content, encoding='utf-8', newline='\n')
    return {'output_dir': str(out), 'files': sorted(templates), 'character_count': len(values)}

def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('output_dir')
    parser.add_argument('--charset', dest='charset_path')
    args = parser.parse_args(argv)
    try:
        print(json.dumps(export_source(args.output_dir, args.charset_path), indent=2))
    except (ValueError, OSError) as exc:
        parser.error(str(exc))

if __name__ == '__main__':
    main()
