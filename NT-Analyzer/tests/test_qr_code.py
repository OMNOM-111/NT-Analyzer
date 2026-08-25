"""QR encoder checks.

The strongest available check without a third-party dependency is a real
round trip: read the mask back out of the finished matrix's format strip,
undo it, walk the data modules in the same order the encoder wrote them,
de-interleave the blocks and recover the original payload. That exercises
data encoding, block splitting, interleaving, module placement, masking and
format placement together, rather than asserting on a golden image.
"""
from __future__ import annotations

import pytest

from app import qr_code


def _read_mask(matrix) -> int:
    bits = 0
    for i in range(15):
        if i < 6:
            value = matrix[8][i]
        elif i == 6:
            value = matrix[8][7]
        elif i == 7:
            value = matrix[8][8]
        elif i == 8:
            value = matrix[7][8]
        else:
            value = matrix[14 - i][8]
        bits |= (1 if value else 0) << (14 - i)
    for mask in range(8):
        if qr_code._format_bits(mask) == bits:
            return mask
    raise AssertionError("format strip does not decode to a level-M mask")


def _decode_payload(matrix) -> bytes:
    """Recover the payload bytes from a finished matrix."""
    size = len(matrix)
    version = (size - 17) // 4
    mask = _read_mask(matrix)
    reserved = qr_code._function_mask(version)

    grid = [list(row) for row in matrix]
    for r in range(size):
        for c in range(size):
            if not reserved[r][c] and qr_code._mask_condition(mask, r, c):
                grid[r][c] = not grid[r][c]

    bits = []
    col, upward = size - 1, True
    while col > 0:
        if col == 6:
            col -= 1
        rows = range(size - 1, -1, -1) if upward else range(size)
        for row in rows:
            for c in (col, col - 1):
                if not reserved[row][c]:
                    bits.append(1 if grid[row][c] else 0)
        upward = not upward
        col -= 2
    codewords = [
        int("".join(str(b) for b in bits[i:i + 8]), 2)
        for i in range(0, len(bits) - len(bits) % 8, 8)
    ]

    ec_count, g1, d1, g2, d2 = qr_code._ECC_M[version]
    sizes = [d1] * g1 + [d2] * g2
    blocks = [[] for _ in sizes]
    idx = 0
    for i in range(max(sizes)):
        for b, length in enumerate(sizes):
            if i < length:
                blocks[b].append(codewords[idx])
                idx += 1
    data = [cw for block in blocks for cw in block]

    stream = "".join(format(cw, "08b") for cw in data)
    assert stream[:4] == "0100", "expected byte mode"
    count_bits = 8 if version < 10 else 16
    length = int(stream[4:4 + count_bits], 2)
    start = 4 + count_bits
    out = bytearray()
    for i in range(length):
        out.append(int(stream[start + i * 8:start + (i + 1) * 8], 2))
    return bytes(out)


PAYLOADS = [
    "https://t.me/StratForgeAI_bot?start=login_86133E37",
    "https://t.me/StratForgeAI_bot?start=canary_login_A8E6848F",
    "A",
    "hello world",
    "x" * 16,
    "y" * 44,
    "z" * 80,
    "q" * 154,
    "w" * 213,
]


@pytest.mark.parametrize("payload", PAYLOADS)
def test_encoded_matrix_round_trips_back_to_the_payload(payload: str) -> None:
    matrix = qr_code.encode(payload)
    assert _decode_payload(matrix) == payload.encode("utf-8")


@pytest.mark.parametrize("payload", PAYLOADS)
def test_structure_is_a_valid_qr_symbol(payload: str) -> None:
    matrix = qr_code.encode(payload)
    size = len(matrix)
    assert all(len(row) == size for row in matrix)
    assert (size - 17) % 4 == 0
    version = (size - 17) // 4
    assert 1 <= version <= 10

    # Three finder patterns, each a dark 7x7 ring with a 3x3 core.
    for row, col in ((0, 0), (0, size - 7), (size - 7, 0)):
        assert matrix[row][col] and matrix[row + 6][col + 6]
        assert matrix[row + 3][col + 3]
        assert not matrix[row + 1][col + 1]
    # Timing patterns alternate, starting dark.
    for i in range(8, size - 8):
        assert matrix[6][i] == (i % 2 == 0)
        assert matrix[i][6] == (i % 2 == 0)
    # The dark module is always set.
    assert matrix[size - 8][8] is True


def test_version_grows_with_payload_and_refuses_beyond_the_supported_range() -> None:
    assert len(qr_code.encode("a" * 10)) == 21      # version 1
    assert len(qr_code.encode("a" * 40)) == 29      # version 4
    assert len(qr_code.encode("a" * 213)) == 57     # version 10
    with pytest.raises(qr_code.QRError):
        qr_code.encode("a" * 400)


def test_svg_is_self_contained_and_scannable_sized() -> None:
    svg = qr_code.svg("https://t.me/StratForgeAI_bot?start=login_DEADBEEF")
    assert svg.startswith("<svg") and svg.endswith("</svg>")
    # No external references: a strict CSP must not have anything to block.
    # The SVG namespace URI is an identifier, not a fetch, so it is excluded.
    body = svg.replace('xmlns="http://www.w3.org/2000/svg"', "")
    for forbidden in ("http://", "https://", "<script", "<image", "xlink:href", "url("):
        assert forbidden not in body
    # A light quiet zone is painted rather than inherited from the page.
    assert 'fill="#ffffff"' in svg
    assert 'shape-rendering="crispEdges"' in svg


def test_same_payload_encodes_deterministically() -> None:
    payload = "https://t.me/StratForgeAI_bot?start=login_0BADC0DE"
    assert qr_code.encode(payload) == qr_code.encode(payload)
