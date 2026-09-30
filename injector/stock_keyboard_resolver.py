"""Resolve the stock four-row printer by its complete window/text call shape.

No symbols or map files are consulted. Refuse unsupported and ambiguous hosts.
"""
import struct
from resolve_modern import calls

BASE = 0x08000000


def _word(rom, q):
    return struct.unpack_from('<I', rom, q)[0]


def _string_table(rom, p):
    if not 0 <= p <= len(rom) - 48:
        return False
    pointers = [_word(rom, p + 4*i) - BASE for i in range(12)]
    return len(set(pointers)) == 12 and all(
        0 <= q < len(rom) and rom[q:q+2] == b'\xFC\x11' and 0xFF in rom[q:q+256] for q in pointers)


def _balanced_return(rom, start, end):
    """Symbolically balance stack saves, scratch allocation, and BX's return.

    Track high-register MOVs to cover GCC's r8 save via LR and restore via r7.
    Normal arithmetic is irrelevant to the stack-save identities checked here.
    """
    registers = {i: i for i in range(16)}
    stack = []
    saved = set()
    for q in range(start, end, 2):
        ins = int.from_bytes(rom[q:q+2], 'little')
        if ins & 0xFE00 == 0xB400:
            regs = [i for i in range(8) if ins & (1 << i)]
            if ins & 0x100:
                regs.append(14)
            values = [registers[i] for i in regs]
            saved.update(v for v in values if v in range(4, 12))
            stack[:0] = values
        elif ins & 0xFE00 == 0xBC00:
            regs = [i for i in range(8) if ins & (1 << i)]
            if ins & 0x100:
                return False  # These known printer ABIs return with BX.
            if len(stack) < len(regs):
                return False
            for i in regs:
                registers[i] = stack.pop(0)
        elif ins & 0xFF00 == 0xB000:
            words = ins & 0x7F
            if ins & 0x80:
                stack[:0] = [None] * words
            else:
                if len(stack) < words or any(v is not None for v in stack[:words]):
                    return False
                del stack[:words]
        elif ins & 0xFF00 == 0x4600:
            dest = (ins & 7) | ((ins >> 4) & 8)
            source = (ins >> 3) & 15
            registers[dest] = registers[source]
        elif ins & 0xFF87 == 0x4700:
            source = (ins >> 3) & 15
            return (q == end-2 and not stack and registers[source] == 14
                    and all(registers[i] == i for i in saved))
    return False


def resolve_stock_keyboard(rom, r, ext):
    """Return a Thumb callable address, or raise when evidence is insufficient."""
    def number(v):
        return int(v, 0) if isinstance(v, str) else v
    expected = [number(ext[k]) & ~1 for k in (
        'FillWindowPixelBuffer', 'AddTextPrinterParameterized3', 'PutWindowTilemap')]
    center = number(r['ok'])
    found = []
    for start in range(max(0, center-0x2000) & ~1, min(len(rom)-2, center+0x2000), 2):
        h = int.from_bytes(rom[start:start+2], 'little')
        # Outer prologue must save callee-saved registers as well as LR. A nested
        # PUSH {LR} saves r8 on modern GCC and is not a callable entry.
        if h & 0xFF00 != 0xB500 or not h & 0xF0:
            continue
        end = None
        for q in range(start+2, min(len(rom)-2, start+0x100), 2):
            if rom[q:q+2] == b'\x00\x47' and int.from_bytes(rom[q-2:q], 'little') & 0xFF00 == 0xBC00:
                end = q+2
                break
        if end is None or not _balanced_return(rom, start, end) or [t for _, t in calls(rom, start, end-start)] != expected:
            continue
        literals = []
        loop = False
        for q in range(start, end, 2):
            ins = int.from_bytes(rom[q:q+2], 'little')
            if ins & 0xF800 == 0x4800:
                p = ((q+4) & ~3) + (ins & 255)*4
                if p+4 <= len(rom):
                    literals.append(_word(rom, p)-BASE)
            if ins & 0xF000 == 0xD000 and ins & 0xFF00 < 0xDE00 and ins & 0x80:
                target = q+4+((ins & 255)-256)*2
                loop |= start <= target < q
        # GCC merges nearby constants; agbcc has independent literal addresses.
        tables = {p+delta for p in literals for delta in range(0, 0x60, 4)
                  if _string_table(rom, p+delta)}
        fills = any(0 <= p < len(rom)-3 and b'\xEE\xDD\xFF' in rom[p:p+0x40]
                    for p in literals)
        if loop and len(tables) == 1 and fills:
            found.append(start)
    if len(found) != 1:
        raise RuntimeError('stock keyboard printer candidates=' + repr([hex(BASE+p+1) for p in found]))
    return BASE + found[0] + 1

