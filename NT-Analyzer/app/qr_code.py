"""A small QR encoder, so a login QR needs no third-party dependency.

The backend is deliberately stdlib-only, and the one thing we need to draw is
a short ASCII deep link. That is byte mode at error-correction level M, which
fits comfortably in the low versions, so this module implements exactly that
slice of ISO/IEC 18004 rather than the whole standard:

* byte mode only (the payload is an ASCII https://t.me/... URL);
* error-correction level M;
* versions 1 through 10, chosen automatically by payload length;
* all eight data masks, selected by the standard penalty rules.

Output is an inline SVG string. Nothing here touches the network, and the
result is deterministic for a given payload, which is what makes it testable
against a reference encoder.
"""
from __future__ import annotations

from typing import List, Tuple

__all__ = ["encode", "svg", "QRError"]


class QRError(ValueError):
    """The payload does not fit the supported byte-mode / level-M range."""


# (ec codewords per block, group1 blocks, group1 data cw, group2 blocks, group2 data cw)
_ECC_M: dict = {
    1: (10, 1, 16, 0, 0),
    2: (16, 1, 28, 0, 0),
    3: (26, 1, 44, 0, 0),
    4: (18, 2, 32, 0, 0),
    5: (24, 2, 43, 0, 0),
    6: (16, 4, 27, 0, 0),
    7: (18, 4, 31, 0, 0),
    8: (22, 2, 38, 2, 39),
    9: (22, 3, 36, 2, 37),
    10: (26, 4, 43, 1, 44),
}

_ALIGN: dict = {
    1: [], 2: [6, 18], 3: [6, 22], 4: [6, 26], 5: [6, 30],
    6: [6, 34], 7: [6, 22, 38], 8: [6, 24, 42], 9: [6, 26, 46], 10: [6, 28, 50],
}

_FORMAT_ECC_M = 0b00

# --- GF(256) with the QR primitive polynomial 0x11D --------------------------
_EXP: List[int] = [0] * 512
_LOG: List[int] = [0] * 256


def _init_tables() -> None:
    x = 1
    for i in range(255):
        _EXP[i] = x
        _LOG[x] = i
        x <<= 1
        if x & 0x100:
            x ^= 0x11D
    for i in range(255, 512):
        _EXP[i] = _EXP[i - 255]


_init_tables()


def _gf_mul(a: int, b: int) -> int:
    if a == 0 or b == 0:
        return 0
    return _EXP[_LOG[a] + _LOG[b]]


def _generator(degree: int) -> List[int]:
    poly = [1]
    for i in range(degree):
        nxt = [0] * (len(poly) + 1)
        for j, coef in enumerate(poly):
            nxt[j] ^= coef
            nxt[j + 1] ^= _gf_mul(coef, _EXP[i])
        poly = nxt
    return poly


def _ec_codewords(data: List[int], count: int) -> List[int]:
    gen = _generator(count)
    rem = list(data) + [0] * count
    for i in range(len(data)):
        factor = rem[i]
        if factor == 0:
            continue
        for j, g in enumerate(gen):
            rem[i + j] ^= _gf_mul(g, factor)
    return rem[len(data):]


# --- data encoding -----------------------------------------------------------

def _pick_version(length: int) -> int:
    for version, (ec, g1, d1, g2, d2) in sorted(_ECC_M.items()):
        capacity = g1 * d1 + g2 * d2
        header = 4 + (8 if version < 10 else 16)
        if length * 8 + header <= capacity * 8:
            return version
    raise QRError(f"payload of {length} bytes exceeds supported QR range")


def _bitstream(payload: bytes, version: int) -> List[int]:
    ec, g1, d1, g2, d2 = _ECC_M[version]
    total_data = g1 * d1 + g2 * d2
    bits: List[int] = []

    def put(value: int, width: int) -> None:
        for i in range(width - 1, -1, -1):
            bits.append((value >> i) & 1)

    put(0b0100, 4)                                   # byte mode
    put(len(payload), 8 if version < 10 else 16)     # character count
    for byte in payload:
        put(byte, 8)

    capacity = total_data * 8
    put(0, min(4, capacity - len(bits)))             # terminator
    while len(bits) % 8:
        bits.append(0)
    pads = (0xEC, 0x11)
    i = 0
    while len(bits) < capacity:
        put(pads[i % 2], 8)
        i += 1
    return bits


def _codewords(payload: bytes, version: int) -> List[int]:
    bits = _bitstream(payload, version)
    data = [int("".join(str(b) for b in bits[i:i + 8]), 2) for i in range(0, len(bits), 8)]

    ec_count, g1, d1, g2, d2 = _ECC_M[version]
    blocks: List[List[int]] = []
    pos = 0
    for _ in range(g1):
        blocks.append(data[pos:pos + d1]); pos += d1
    for _ in range(g2):
        blocks.append(data[pos:pos + d2]); pos += d2
    ec_blocks = [_ec_codewords(block, ec_count) for block in blocks]

    out: List[int] = []
    for i in range(max(len(b) for b in blocks)):
        for block in blocks:
            if i < len(block):
                out.append(block[i])
    for i in range(ec_count):
        for block in ec_blocks:
            out.append(block[i])
    return out


# --- matrix ------------------------------------------------------------------

def _new_matrix(size: int):
    # None means "free"; True/False are set modules. Reserved function areas
    # are written directly so the data walk can simply skip anything set.
    return [[None] * size for _ in range(size)]


def _place_finder(m, row: int, col: int) -> None:
    size = len(m)
    for r in range(-1, 8):
        for c in range(-1, 8):
            rr, cc = row + r, col + c
            if not (0 <= rr < size and 0 <= cc < size):
                continue
            inside = 0 <= r < 7 and 0 <= c < 7
            if inside:
                ring = r in (0, 6) or c in (0, 6)
                core = 2 <= r <= 4 and 2 <= c <= 4
                m[rr][cc] = ring or core
            else:
                m[rr][cc] = False


def _place_alignment(m, version: int) -> None:
    centers = _ALIGN[version]
    size = len(m)
    for a in centers:
        for b in centers:
            # Alignment patterns never overlap the three finder patterns.
            if (a, b) in ((6, 6), (6, centers[-1]), (centers[-1], 6)):
                continue
            for r in range(-2, 3):
                for c in range(-2, 3):
                    rr, cc = a + r, b + c
                    if 0 <= rr < size and 0 <= cc < size:
                        m[rr][cc] = max(abs(r), abs(c)) != 1


def _reserve_format(m, version: int) -> None:
    size = len(m)
    for i in range(9):
        if m[8][i] is None:
            m[8][i] = False
        if m[i][8] is None:
            m[i][8] = False
    for i in range(8):
        if m[8][size - 1 - i] is None:
            m[8][size - 1 - i] = False
        if m[size - 1 - i][8] is None:
            m[size - 1 - i][8] = False
    if version >= 7:
        for i in range(6):
            for j in range(3):
                m[size - 11 + j][i] = False
                m[i][size - 11 + j] = False


def _skeleton(version: int):
    size = version * 4 + 17
    m = _new_matrix(size)
    _place_finder(m, 0, 0)
    _place_finder(m, 0, size - 7)
    _place_finder(m, size - 7, 0)
    _place_alignment(m, version)
    for i in range(8, size - 8):
        bit = i % 2 == 0
        if m[6][i] is None:
            m[6][i] = bit
        if m[i][6] is None:
            m[i][6] = bit
    m[size - 8][8] = True  # the always-dark module
    _reserve_format(m, version)
    return m


def _function_mask(version: int):
    """True where a module belongs to a function pattern (never data)."""
    m = _skeleton(version)
    return [[cell is not None for cell in row] for row in m]


def _place_data(m, reserved, codewords: List[int]) -> None:
    size = len(m)
    bits = []
    for cw in codewords:
        for i in range(7, -1, -1):
            bits.append((cw >> i) & 1)
    idx = 0
    col = size - 1
    upward = True
    while col > 0:
        if col == 6:  # the vertical timing column is skipped entirely
            col -= 1
        rows = range(size - 1, -1, -1) if upward else range(size)
        for row in rows:
            for c in (col, col - 1):
                if reserved[row][c]:
                    continue
                m[row][c] = bool(bits[idx]) if idx < len(bits) else False
                idx += 1
        upward = not upward
        col -= 2


def _mask_condition(mask: int, row: int, col: int) -> bool:
    if mask == 0:
        return (row + col) % 2 == 0
    if mask == 1:
        return row % 2 == 0
    if mask == 2:
        return col % 3 == 0
    if mask == 3:
        return (row + col) % 3 == 0
    if mask == 4:
        return (row // 2 + col // 3) % 2 == 0
    if mask == 5:
        return (row * col) % 2 + (row * col) % 3 == 0
    if mask == 6:
        return ((row * col) % 2 + (row * col) % 3) % 2 == 0
    return ((row + col) % 2 + (row * col) % 3) % 2 == 0


def _format_bits(mask: int) -> int:
    """The 15-bit BCH(15,5) format string for level M and ``mask``."""
    value = (_FORMAT_ECC_M << 3) | mask
    rem = value << 10
    for i in range(4, -1, -1):
        if rem & (1 << (i + 10)):
            rem ^= 0b101_0011_0111 << i
    return ((value << 10) | rem) ^ 0b101_0100_0001_0010


def _place_format(m, mask: int) -> None:
    size = len(m)
    bits = _format_bits(mask)
    for i in range(15):
        # The layout is described most-significant bit first, so position i
        # carries bit number b = 14 - i of the format string.
        b = 14 - i
        bit = bool((bits >> b) & 1)
        # Copy 1, wrapped around the top-left finder.
        if i < 6:
            m[8][i] = bit
        elif i == 6:
            m[8][7] = bit
        elif i == 7:
            m[8][8] = bit
        elif i == 8:
            m[7][8] = bit
        else:
            m[14 - i][8] = bit
        # Copy 2 is split 7/8, not 8/7: the eighth module below the top-left
        # finder is the permanently dark module, which must not be written.
        if i <= 6:
            m[size - 1 - i][8] = bit
        else:
            m[8][size - 15 + i] = bit


def _place_version(m, version: int) -> None:
    if version < 7:
        return
    rem = version << 12
    for i in range(5, -1, -1):
        if rem & (1 << (i + 12)):
            rem ^= 0b1_1111_0010_0101 << i
    bits = (version << 12) | rem
    size = len(m)
    for i in range(18):
        bit = bool((bits >> i) & 1)
        a, b = i // 3, i % 3
        m[size - 11 + b][a] = bit
        m[a][size - 11 + b] = bit


def _penalty(m) -> int:
    size = len(m)
    score = 0
    # Rule 1: runs of five or more same-coloured modules in a line.
    for line in list(m) + [list(col) for col in zip(*m)]:
        run, prev = 1, line[0]
        for cell in line[1:]:
            if cell == prev:
                run += 1
            else:
                if run >= 5:
                    score += 3 + (run - 5)
                run, prev = 1, cell
        if run >= 5:
            score += 3 + (run - 5)
    # Rule 2: 2x2 blocks of one colour.
    for r in range(size - 1):
        for c in range(size - 1):
            if m[r][c] == m[r][c + 1] == m[r + 1][c] == m[r + 1][c + 1]:
                score += 3
    # Rule 3: the finder-like 1:1:3:1:1 pattern with four light modules.
    target_a = [True, False, True, True, True, False, True, False, False, False, False]
    target_b = list(reversed(target_a))
    for line in list(m) + [list(col) for col in zip(*m)]:
        for i in range(size - 10):
            window = line[i:i + 11]
            if window == target_a or window == target_b:
                score += 40
    # Rule 4: overall dark/light balance.
    dark = sum(1 for row in m for cell in row if cell)
    ratio = dark * 100 // (size * size)
    score += 10 * (abs(ratio - 50) // 5)
    return score


def encode(payload: str) -> List[List[bool]]:
    """Return the finished module matrix (True = dark) for ``payload``."""
    raw = payload.encode("utf-8")
    version = _pick_version(len(raw))
    codewords = _codewords(raw, version)
    reserved = _function_mask(version)

    best = None
    for mask in range(8):
        m = _skeleton(version)
        _place_data(m, reserved, codewords)
        for r in range(len(m)):
            for c in range(len(m)):
                if not reserved[r][c] and _mask_condition(mask, r, c):
                    m[r][c] = not m[r][c]
        _place_format(m, mask)
        _place_version(m, version)
        grid = [[bool(cell) for cell in row] for row in m]
        score = _penalty(grid)
        if best is None or score < best[0]:
            best = (score, grid)
    return best[1]


def svg(payload: str, *, quiet_zone: int = 4, size_px: int = 240,
        title: str = "") -> str:
    """Render ``payload`` as a self-contained, theme-aware inline SVG."""
    matrix = encode(payload)
    modules = len(matrix)
    total = modules + quiet_zone * 2
    parts = [
        f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {total} {total}" '
        f'width="{size_px}" height="{size_px}" shape-rendering="crispEdges" '
        f'role="img" aria-label="{title or "QR"}">',
        # The quiet zone must be light for a scanner, so it is painted rather
        # than left transparent over an unknown page background.
        f'<rect width="{total}" height="{total}" fill="#ffffff"/>',
    ]
    for r, row in enumerate(matrix):
        c = 0
        while c < modules:
            if not row[c]:
                c += 1
                continue
            run = 1
            while c + run < modules and row[c + run]:
                run += 1
            parts.append(
                f'<rect x="{c + quiet_zone}" y="{r + quiet_zone}" '
                f'width="{run}" height="1" fill="#000000"/>'
            )
            c += run
    parts.append("</svg>")
    return "".join(parts)
