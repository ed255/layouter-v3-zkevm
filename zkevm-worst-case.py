#!/usr/bin/env python3

import math
import sys
from copy import deepcopy
from dataclasses import dataclass
import pygame
from pygame.locals import *

# Renamed state circuit to rw for consistency with table name

circuits_tables = [
    ("evm", None),
    ("bytecode", "bytecode"),
    ("copy", "copy"),
    ("exp", "exp"),
    ("keccak", "keccak"),
    ("mpt", "mpt"),
    ("rw", "rw"),
    ("tx", "tx"),
    ("sig", "sig"),
    ("ecc", None),
    ("pi", None),
    (None, "block"),
    (None, "u8"),
    (None, "u10"),
    (None, "u16"),
]

circuit_colors = {
    "evm": "turquoise",
    "bytecode": "hotpink",
    "copy": "indigo",
    "exp": "khaki3",
    "keccak": "green4",
    "mpt": "lightgoldenrod",
    "rw": "lightsalmon",
    "tx": "olive",
    "pi": "orangered",
    "ecc": "gray",
    "sig": "gray",
}

# Notes:
# MAX_CODESIZE = 0x6000

# Worst case rows per gas.  Numbers taken from
# https://github.com/privacy-scaling-explorations/zkevm-specs/issues/71#issuecomment-1125612886
# (could be a bit outdated)
rows_per_gas = {
    "evm": 4.5,  # Via PUSH0
    "bytecode": 9.47,  # Via EXTCODESIZE of contract with MAX_CODESIZE
    "copy": 21.3,  # Via CODECOPY of contract with MAX_CODESIZE
    "exp": 1.09,  # 7 rows per exponent bit
    "keccak": 90.5,  # Via EXTCODESIZE of contract with MAX_CODESIZE
    # via hot SLOAD (100 gas), assuming 11 levels for state and 8 for storage,
    "mpt": 0.95,
    "rw": 11.33,  # Via MLOAD (RETURNDATASIZE + repeating MLOAD)
    "tx": 8.73,  # From SignVerifyChip
    "ecc": None,  # TODO
    "pi": 0.33,  # 1 tx with call_data_len = 1_048_576
    "block": 0,
    # TODO 8192 rows per signature in current configuration, but circuit not
    # yet instantiated in zkEVM
    "sig": None,
    "u8": 0,
    "u10": 0,
    "u16": 0,
}

min_rows = {
    "tx": 295188,  # From range chip table in SignVerifyChip
    "block": 264,
    "u8": 2**8,
    "u10": 2**10,
    "u16": 2**16,
}

# Numbers from `cargo run --features="stats" --bin stats -- general`

fix_cols = {
    "tx_table": 1,
    "wd_table": 0,
    "rw_table": 0,
    "mpt_table": 0,
    "bytecode_table": 0,
    "block_table": 2,
    "copy_table": 1,
    "exp_table": 1,
    "keccak_table": 0,
    "sig_table": 1,
    "u8_table": 1,
    "u10_table": 1,
    "u16_table": 1,
    "keccak": 18,
    "pi": 3,
    "tx": 13,
    "bytecode": 5,
    "copy": 1,
    "rw": 3,
    "exp": 0,
    "evm": 5,
    "mpt": 8,
    "ecc": 0,  # TODO
    "sig": 0,  # TODO
}

adv_cols = {
    "tx_table": 4,
    "wd_table": 5,
    "rw_table": 14,
    "mpt_table": 12,
    "bytecode_table": 6,
    "block_table": 2,
    "copy_table": 12,
    "exp_table": 5,
    "keccak_table": 5,
    "sig_table": 9,
    "u8_table": 0,
    "u10_table": 0,
    "u16_table": 0,
    "keccak": 198,
    "pi": 10,
    "tx": 6,
    "bytecode": 6,
    "copy": 14,
    "rw": 49,
    "exp": 10,
    "evm": 131,
    "mpt": 144,
    "ecc": 0,  # TODO
    "sig": 0,  # TODO
}


def next_power_of_2(x):
    return 1 if x == 0 else 2**math.ceil(math.log2(x))


field_bytes = 32


def estimate_mem(degree, k, fixed, advice):
    """Estimate peak memory only considering fixed and advice columns"""
    c_f = fixed
    c_a = advice
    m_e = 4 + c_f + c_a
    e = next_power_of_2(degree - 1)
    return e * m_e * 2**k * field_bytes


def max_gas(k):
    """Figure out the maximum amount of gas we can prove in the worst case"""
    max_rows_per_gas = 0
    for _, value in rows_per_gas.items():
        if not value:
            continue
        if value > max_rows_per_gas:
            max_rows_per_gas = value
    return 2**k // max_rows_per_gas


@dataclass
class Region:
    name: str
    width: int
    height: int
    x: int = -1
    y: int = -1

    def overlap(self, other) -> bool:
        return (self.x <= other.x and self.x+self.width > other.x) and \
                (self.y <= other.y and self.y+self.height > other.y)


@dataclass
class Point:
    x: int
    y: int


def solve_v1(k, regions):
    """Find a solution to the region placing.  Halo2 algorithm"""
    width = 0
    for i in range(0, len(regions)):
        region = regions[i]
        region.y = 0
        region.x = width
        width += region.width

    if not check_valid(k, regions):
        print("Invalid solution")
    return regions


def solve_v3(k, regions):
    """
    Find a solution to the region placing.  Simple algorithm.
    This layouter treats columns as virtual, and can map multiple virutal
    columns into the same real column.  This means that regions that use
    independent columns can be stacked vertically
    """

    n = 2**k
    # Sort by height
    regions = sorted(regions, key=lambda r: -r.height)
    position = Point(0, 0)
    width = 0
    for i in range(0, len(regions)):
        region = regions[i]
        # If the region fits below the last one, add it, otherwise start at
        # offset 0 to the right (in new columns)
        if position.y + region.height < n:
            region.y = position.y
            region.x = position.x
            position.y += region.height
            if width < region.width:
                width = region.width
        else:
            position.x += width
            region.y = 0
            region.x = position.x
            position.y = region.height
            width = region.width

    if not check_valid(k, regions):
        print("Invalid solution")
    return regions


def check_valid(k, regions):
    n = 2**k
    # All regions within 0..2^k height
    for region in regions:
        if region.y + region.height > n:
            print(f"Region {region} over 2^k height")
            return False

    # No region overlap
    for i in range(0, len(regions)):
        for j in range(i+1, len(regions)):
            if regions[i].overlap(regions[j]):
                print(f"Overlapping regions {regions[i]} and {regions[j]}")
                return False

    return True


def draw1(regions, n, max_width):
    w, h = (1280, 720)
    window = pygame.display.set_mode((w, h))
    window.fill(pygame.Color("white"))

    for i in range(0, len(regions)):
        region = regions[i]
        name = region.name
        x = region.x / max_width * w
        y = region.y / n * h
        width = region.width / max_width * w
        height = region.height / n * h
        pygame.draw.rect(window, pygame.Color(circuit_colors[name]),
                         [x, y, width, height], 0)
    pygame.display.update()

    running = True
    while running:
        pygame.event.wait()
        for event in pygame.event.get():
            if event.type == pygame.QUIT:
                running = False


def draw2(regions1, regions2, n, max_width):
    w, h = (1024, 1024)
    window = pygame.display.set_mode((w, h))
    window.fill(pygame.Color("white"))

    def draw_regions(offset, w, h, regions):
        for i in range(0, len(regions)):
            region = regions[i]
            name = region.name
            x = region.x / max_width * w
            y = region.y / n * h
            width = region.width / max_width * w
            height = region.height / n * h
            pygame.draw.rect(window, pygame.Color(circuit_colors[name]),
                             [x, y + offset, width, height], 0)

    draw_regions(0, w, h//2, regions1)
    pygame.draw.line(window, pygame.Color("black"), (0, h//2-1), (w, h//2-1))
    draw_regions(h//2, w, h//2, regions2)
    pygame.display.update()

    running = True
    while running:
        pygame.event.wait()
        for event in pygame.event.get():
            if event.type == pygame.QUIT:
                running = False


def get_regions(gas):
    # Collect regions where width and height count advice cells.  We have one
    # region per subcircuit. We merge subcircuit and their table into the same
    # region.
    regions = []
    for (circuit, table) in circuits_tables:
        width = 0
        if circuit:
            width += adv_cols[circuit]
        if table:
            width += adv_cols[f"{table}_table"]
        name = circuit
        if not circuit:
            name = table
        rows_gas = rows_per_gas[name]
        if not rows_gas:
            continue
        rows = int(gas * rows_gas)
        try:
            rows = max(rows, min_rows[name])
        except KeyError:
            pass
        regions.append(Region(circuit, width, rows))

    return regions


def get_fixed():
    """Count the total number of fixed columns"""
    fixed = 0
    for (circuit, table) in circuits_tables:
        if circuit:
            fixed += fix_cols[circuit]
        if table:
            fixed += fix_cols[f"{table}_table"]
    return fixed


def get_advice(regions):
    """Count the total number of advice columns required for the layouter regions"""
    advice = 0
    for region in regions:
        max_col = region.x + region.width
        if max_col > advice:
            advice = max_col
    return advice


def cell_usage(k, regions):
    width = get_advice(regions)
    height = 2**k
    area = width * height
    used_cells = 0
    for region in regions:
        used_cells += region.width * region.height

    return area, used_cells


def to_gb(x):
    return x//1024//1024//1024


def main():
    pygame.init()

    k = 26
    degree = 10
    gas = max_gas(k)
    print(f"k = {k}, max_gas = {gas}")

    # TODO: For now we don't touch fixed columns.  They can be stacked only if
    # they're not used as selectors

    regions = get_regions(gas)

    regions_v1 = solve_v1(k, deepcopy(regions))
    print(regions_v1)
    advice_v1 = get_advice(regions_v1)
    fixed_v1 = get_fixed()

    print("= Current =")
    print(f"advice = {advice_v1}, fixed = {fixed_v1}")
    mem_v1 = estimate_mem(degree, k, fixed_v1, advice_v1)
    print(f"Mem estimation: {to_gb(mem_v1)} GiB")
    area_v1, used_cells_v1 = cell_usage(k, regions_v1)
    print(f"Area usage: {used_cells_v1/area_v1 * 100}%")

    print("")
    regions_v3 = solve_v3(k, deepcopy(regions))
    print(regions_v3)
    advice_v3 = get_advice(regions_v3)
    fixed_v3 = get_fixed()

    print("= V3 =")
    print(f"advice = {advice_v3}, fixed = {fixed_v3}")
    mem_v3 = estimate_mem(degree, k, fixed_v3, advice_v3)
    print(f"Mem estimation: {to_gb(mem_v3)} GiB")
    area_v3, used_cells_v3 = cell_usage(k, regions_v3)
    print(f"Area usage: {used_cells_v3/area_v3 * 100}%")

    draw2(regions_v1, regions_v3, 2**k, advice_v1)


if __name__ == '__main__':
    sys.exit(main())
