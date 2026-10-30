#!/usr/bin/env python3
"""Check ShengGmuRegisters.h / ShengGmuSource.h against the pinned XML.

The hand-written board header had two classes of defect that no compiler can
see: register dwords copied from the wrong domain (A6XX_GMU block-relative
instead of A6XX whole-GPU) and fatal masks invented from a bit number rather
than read out of the bitfields. This script re-derives both from the pinned
register databases and fails on any drift.

    usage: check-sheng-gmu-source.py [--xml DIR]

--xml defaults to .cache/adreno-source/drivers/gpu/drm/msm/registers/adreno
(the prepare-sheng-gmu.py cache). No device or network access.
"""
import argparse
import re
import sys
import xml.etree.ElementTree as ET
from pathlib import Path

NS = {"r": "http://nouveau.freedesktop.org/"}
ROOT = Path(__file__).resolve().parent.parent
UNIXNU = ROOT / "shim" / "fuxi-probe" / "unixnu"

# Register dwords the vendored ShengGmu.c addresses, in A6XX whole-GPU dword
# numbering. GMU_GENERAL_8/9/10 and the FAL pair exist in several variants;
# an A740 selects the A7XX and A6XX ones respectively.
REGS = [
    "GMU_CM3_ITCM_START", "GMU_CM3_DTCM_START", "GMU_CM3_SYSRESET",
    "GMU_CM3_BOOT_CONFIG", "GMU_CM3_FW_INIT_RESULT", "GMU_CM3_CFG",
    "GMU_HFI_QTBL_ADDR", "GMU_HFI_QTBL_INFO", "GMU_HFI_CTRL_INIT",
    "GMU_HFI_CTRL_STATUS", "GMU_HOST2GMU_INTR_SET", "GMU_SYS_BUS_CONFIG",
    "GMU_ICACHE_CONFIG", "GMU_DCACHE_CONFIG", "GMU_AHB_FENCE_RANGE_0",
    "GMU_GMU2HOST_INTR_INFO", "GMU_AO_HOST_INTERRUPT_STATUS",
    "GMU_GENERAL_8", "GMU_GENERAL_9", "GMU_GENERAL_10",
    "GPU_GMU_CX_GMU_CX_FALNEXT_INTF", "GPU_GMU_CX_GMU_CX_FAL_INTF",
    "GBIF_QSB_SIDE0", "CX_MISC_TCM_RET_CNTL",
]
VARIANTS = {"GMU_GENERAL_8": "A7XX", "GMU_GENERAL_9": "A7XX", "GMU_GENERAL_10": "A7XX",
            "GPU_GMU_CX_GMU_CX_FALNEXT_INTF": "A6XX",
            "GPU_GMU_CX_GMU_CX_FAL_INTF": "A6XX"}
AO_FATAL = ["WDOG_BITE", "FENCE_ERR", "HOST_AHB_BUS_ERROR"]
CM3_FATAL = ["CM3_FAULT"]


def load(directory):
    roots = []
    for name in ("a6xx.xml", "a6xx_gmu.xml"):
        path = directory / name
        if not path.is_file():
            sys.exit(f"missing pinned register database: {path}")
        roots.append(ET.parse(path).getroot())
    return roots


def find_reg(roots, name, variant):
    hits = []
    for root in roots:
        for dom in root.findall("r:domain", NS):
            for reg in dom.findall("r:reg32", NS):
                if reg.attrib.get("name") != name:
                    continue
                if variant and reg.attrib.get("variants") != variant:
                    continue
                hits.append(reg)
    if len(hits) != 1:
        sys.exit(f"{name}: {len(hits)} matches in the pinned XML, expected 1")
    return hits[0]


def bitfield(reg, name):
    for f in reg.findall("r:bitfield", NS):
        if f.attrib["name"] == name:
            return 1 << int(f.attrib["pos"])
    sys.exit(f"{reg.attrib['name']}: missing bitfield {name}")


def header_defines(path):
    text = path.read_text()
    out = {}
    pattern = r"^#define\s+(SHENG_GMU_\w+|REG_\w+)\s+(?:UINT32_C\()?(0x[0-9a-fA-F]+|\d+)u?\)?"
    for m in re.finditer(pattern, text, re.M):
        out[m.group(1)] = int(m.group(2), 0)
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--xml", default=str(ROOT / ".cache/adreno-source/drivers/gpu/drm/msm/registers/adreno"))
    args = ap.parse_args()
    roots = load(Path(args.xml))

    regs = header_defines(UNIXNU / "ShengGmuRegisters.h")
    src = UNIXNU / "ShengGmuSource.h"
    src_defs = header_defines(src)
    src_text = src.read_text()
    failures = 0

    for name in REGS:
        reg = find_reg(roots, name, VARIANTS.get(name))
        want = int(reg.attrib["offset"], 0)
        got = regs.get("REG_" + name)
        ok = got == want
        failures += not ok
        print(f"{'ok  ' if ok else 'FAIL'} REG_{name:32s} header={got if got is None else hex(got)} xml={want:#x}")

    ao = 0
    for field in AO_FATAL:
        ao |= bitfield(find_reg(roots, "GMU_AO_HOST_INTERRUPT_STATUS", None), field)
    cm3 = 0
    for field in CM3_FATAL:
        cm3 |= bitfield(find_reg(roots, "GMU_GMU2HOST_INTR_INFO", None), field)
    for key, want in (("SHENG_GMU_AO_FATAL_MASK", ao), ("SHENG_GMU_CM3_FATAL_MASK", cm3)):
        got = src_defs.get(key)
        ok = got == want
        failures += not ok
        print(f"{'ok  ' if ok else 'FAIL'} {key:32s} header={got if got is None else hex(got)} xml={want:#x}")

    # RSCC table: byte offsets, 4-aligned, inside the Rscc window, and the
    # idle-poll dword rebases onto the same numbering.
    clean = re.sub(r"/\*.*?\*/", "", src_text, flags=re.S)
    m = re.search(r"sheng_gmu_window_bytes\[5\] = \{([^}]*)\}", clean)
    if not m:
        sys.exit("sheng_gmu_window_bytes not found")
    windows = [int(v.strip().rstrip("u"), 0) for v in m.group(1).split(",") if v.strip()]
    window_bytes = windows[1]
    entries = re.findall(r"\{\s*(\d+),\s*(0x[0-9a-fA-F]+)u,\s*(0x[0-9a-fA-F]+|\d+)u\s*\}", clean)
    count = src_defs.get("SHENG_GMU_RSC_SETUP_COUNT")
    ok = count == len(entries)
    failures += not ok
    print(f"{'ok  ' if ok else 'FAIL'} SHENG_GMU_RSC_SETUP_COUNT       header={count} table={len(entries)}")
    for win, off, val in entries:
        off, val, win = int(off, 16), int(val, 0), int(win)
        ok = win < len(windows) and (off & 3) == 0 and off + 4 <= windows[win]
        failures += not ok
        if not ok:
            print(f"FAIL rsc write window={win} offset={off:#x} outside the window")
    if not failures:
        print(f"ok   all {len(entries)} RSCC writes inside windows {[hex(w) for w in windows]}")

    busy = src_defs.get("REG_RSCC_SEQ_BUSY_DRV0")
    ok = busy is not None and (busy << 2) + 4 <= window_bytes
    failures += not ok
    print(f"{'ok  ' if ok else 'FAIL'} REG_RSCC_SEQ_BUSY_DRV0          header={busy if busy is None else hex(busy)} "
          f"byte={(busy << 2) if busy else 0:#x} window={window_bytes:#x}")

    if failures:
        print(f"\n{failures} mismatch(es)")
        return 1
    print("\nPASS: board header matches the pinned register databases")
    return 0


if __name__ == "__main__":
    sys.exit(main())
