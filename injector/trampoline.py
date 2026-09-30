#!/usr/bin/env python3
"""Thumb-1 codec for ARM7TDMI.

Encoders:
  `thumb_bl` - 4-byte BL hook, refusing out-of-range or unaligned targets.
  `jump`     - 8-byte absolute jump (`ldr r3,[pc,#0]` / `bx r3` / `.word addr|1`),
               no range limit, used where the payload is too far for a BL.
  `make_gateway` - displaced halfwords plus a BL back, for sites that cannot be
               relocated as-is.

Decoder:
  `decode_thumb_bl` - read a BL at a ROM offset and return its thumbnail-tagged
               target, or None if the two halfwords are not a BL. This is the
               primitive the naming-screen dataflow resolver is built on.
"""

import struct

ROM_BASE = 0x08000000


def thumb_bl(src_addr, dst_addr):
    """Encode a Thumb-1 BL. src/dst are even runtime addresses; Thumb BL PC is src+4."""
    off = dst_addr - (src_addr + 4)
    if off & 1:
        raise ValueError("unaligned Thumb target")
    if not -(1 << 22) <= off < (1 << 22):
        raise ValueError("Thumb-1 BL out of range")
    x = off >> 1
    hi = (x >> 11) & 0x7ff
    lo = x & 0x7ff
    return struct.pack("<HH", 0xF000 | hi, 0xF800 | lo)


def jump(dst_addr):
    """Encode an 8-byte absolute jump: `ldr r3,[pc,#0]` / `bx r3` / `.word dst|1`."""
    return struct.pack("<HHI", 0x4B00, 0x4718, dst_addr | 1)


def decode_thumb_bl(rom, off):
    """Return the Thumb-tagged BL target at ROM offset `off`, or None.

    `rom` is the raw image; `off` is a file offset, so the runtime address is
    ROM_BASE + off. Returns None when the two halfwords at `off` are not a BL, so
    callers can sweep a range in 2-byte steps and keep the hits.
    """
    h1, h2 = struct.unpack_from("<HH", rom, off)
    if (h1 & 0xF800) != 0xF000 or (h2 & 0xF800) != 0xF800:
        return None
    imm = ((h1 & 0x7FF) << 11) | (h2 & 0x7FF)
    if imm & (1 << 21):
        imm -= 1 << 22
    pc = ROM_BASE + off + 4
    return (pc + (imm << 1)) | 1


def unsafe_halfword(hw):
    """True for halfwords that cannot be relocated blindly.

    Conservative: conditional/unconditional branches, BL halves, literal LDR,
    ADR/add PC.
    """
    if hw & 0xF000 in (0xD000,):
        return True
    if hw & 0xF800 == 0xE000:
        return True
    if hw & 0xF800 in (0xF000, 0xF800):
        return True
    if hw & 0xF800 == 0x4800:
        return True
    if hw & 0xF800 == 0xA000:
        return True
    return False


def make_gateway(original4, hook_addr, gateway_addr):
    if len(original4) != 4:
        raise ValueError("gateway currently requires exactly 4 displaced bytes")
    h0, h1 = struct.unpack("<HH", original4)
    if unsafe_halfword(h0) or unsafe_halfword(h1):
        raise ValueError("displaced instruction is PC-relative/branching; refuse unsafe relocation")
    back = hook_addr + 4
    return original4 + thumb_bl(gateway_addr + 4, back)
