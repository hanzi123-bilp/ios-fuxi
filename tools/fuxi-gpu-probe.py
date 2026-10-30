#!/usr/bin/env python3
"""Decode/run the Fuxi A740 staged GPU probe (request 0x56, value 0x4753).

--stage 8a snapshots all GPU SMMU streams/banks after stages1..7.
8 maps SID5 and loads externally embedded firmware; 9 starts GMU/HFI;
10 requests GX; 11 maps GPU SIDs0/1; 12 starts SQE/CP; 13 writes a fence; 14 clears/copies scratch pixels; 15 blits to scanout; 16 loads PAS zap before the stage-14 clear/copy (never scanout). Run each on a fresh loader boot first.
--read-reports retrieves pages without replaying hardware setup.
See docs-lanes/gpu.md for memory reservations, risks and report words.
"""
import argparse
import struct
import sys

from pathlib import Path


def bit_names(value, names):
    return '|'.join(name for bit, name in names.items() if value & (1 << bit)) or 'none'


CP_BITS = {0: 'BR_OPCODE', 1: 'BR_UCODE', 2: 'BR_HW_FAULT', 4: 'BR_PROTECT',
           5: 'AHB', 6: 'VSD_PARITY', 7: 'BR_ILLEGAL_INSTR', 8: 'LPAC_OPCODE',
           9: 'LPAC_UCODE', 10: 'LPAC_HW_FAULT', 11: 'LPAC_PROTECT',
           12: 'LPAC_ILLEGAL_INSTR', 13: 'BV_OPCODE', 14: 'BV_UCODE',
           15: 'BV_HW_FAULT', 16: 'BV_PROTECT', 17: 'BV_ILLEGAL_INSTR'}
RBBM_BITS = {i: name for i, name in enumerate([
    'AHB_CX', 'AHB_CP', 'CP', 'GFX_DBGC', 'VBIF', 'TSE', 'RAS', 'RB', 'CCU',
    'A2D', 'LRZ', 'COM_DCOM', 'PC_DCALL', 'PC_VSD', 'TESS', 'VFD', 'VPC',
    'UCHE', 'SP', 'TPL1', 'VSC', 'HLSQ', 'GPU_IGN_AHB_CP', 'GPU_IGN_AHB'])}


SHENG_STATUS = {0: 'Success', 1: 'Argument', 2: 'Firmware', 3: 'Busy', 4: 'IoError',
                5: 'StateMismatch', 6: 'Timeout', 7: 'ClockError', 8: 'Poisoned',
                9: 'Fault', 10: 'ProtocolError'}
SHENG_PHASE = {0: 'not started', 1: 'preconditions', 2: 'RSCC/reset+state', 3: 'payload load',
               4: 'register config', 5: 'FW_INIT poll', 6: 'HFI init', 7: 'HFI ready'}


def fault_client(fsynr1, uche):
    """Linux a6xx_fault_block / a6xx_uche_fault_block, A7xx paths."""
    mid = fsynr1 & 0xff
    if mid in (0, 4, 5, 6, 7):
        return {0: 'CP', 4: 'CCU', 5: 'Flag cache', 6: 'CDP Prefetch', 7: 'GMU'}[mid]
    client = uche & 0x7f
    blocks = ['VFD', 'SP', 'VSC', 'VPC', 'HLSQ', 'PC', 'LRZ', 'TP']
    if mid == 3 and client < 16:
        return ('BR_' if client < 8 else 'BV_') + blocks[client % 8]
    if mid == 8 and client in (1, 4, 7):
        return 'LPAC_' + blocks[client]
    return {1: 'UCHE', 2: 'UCHE_LPAC', 3: 'UCHE', 8: 'UCHE_LPAC'}.get(mid, 'UNKNOWN')


def decode(r, pages=None):
    """r: list of 128 uint32. Prints a human-readable stage-by-stage report."""
    def on(cbcr):
        return 'EN' if cbcr & 1 else '--', 'OFF' if cbcr & (1 << 31) else 'on'
    out = []
    out.append(f'magic={r[0]:#x} stage_limit={r[1]:#x} furthest={r[2]:#x} gmu_started={r[3]}')
    # Stage 1 / 4 snapshot
    out.append('-- stage 1 read-only snapshot --')
    out.append(f'  gcc cfg_ahb={r[4]:#010x} memnoc={r[5]:#010x} dvm={r[6]:#010x} gpll0_vote={r[7]:#010x}')
    out.append(f'  gpucc_read={r[13]}  cx_gdscr={r[8]:#010x} gx_gdscr={r[9]:#010x}')
    out.append(f'          ahb_clk={r[10]:#010x} smmu_vote={r[11]:#010x} cx_gmu={r[12]:#010x}')
    out.append(f'  smmu_read={r[15]} scr0={r[16]:#010x} id0={r[17]:#010x} id1={r[18]:#010x} id2={r[19]:#010x} gfsr={r[20]:#010x}')
    if r[15]:
        out.append(f'          smr_valid={r[21] & 0xffff} first={r[21] >> 16} smr={r[22]:#010x} s2cr={r[23]:#010x}')
    out.append(f'  gpu_read={r[14]} rbbm_status={r[24]:#010x}')
    # Stage 2
    out.append('-- stage 2 gcc_gpu_cfg_ahb enable --')
    out.append(f'  wrote_enable={r[26]} cfg_ahb_after={r[27]:#010x}')
    # Stage 3
    out.append('-- stage 3 CX GDSC + ahb/smmu clocks --')
    out.append(f'  cx_gdscr before={r[28]:#010x} hw_ctrl={r[29]:#010x} after={r[30]:#010x} (on={bool(r[30] & (1 << 31))})')
    out.append(f'  ahb_clk={r[31]:#010x} smmu_vote={r[32]:#010x} smmu_on={r[33]}')
    # Stage 4
    out.append('-- stage 4 powered adreno SMMU GR0 + CB0/CB1 --')
    out.append(f'  done={r[35]} scr0={r[36]:#010x} id0={r[37]:#010x} id1={r[38]:#010x} id2={r[39]:#010x}')
    if r[35]:
        out.append(f'  CB0 cbar={r[40]:#010x} sctlr={r[41]:#010x} fsr={r[42]:#010x} tcr={r[43]:#010x}')
        out.append(f'  CB1 cbar={r[44]:#010x} sctlr={r[45]:#010x} fsr={r[46]:#010x} tcr={r[47]:#010x}')
    # Stage 5
    out.append('-- stage 5 GMU clock snapshot --')
    out.append(f'  pll1 mode={r[48]:#010x} opmode={r[49]:#x} L={r[50]:#x}')
    out.append(f'  gmu_rcg cmd={r[51]:#010x} cfg={r[52]:#010x}  hub_rcg cmd={r[53]:#010x} cfg={r[54]:#010x}')
    out.append(f'  cx_gmu={r[55]:#010x} cxo={r[56]:#010x} hub_cx_int={r[57]:#010x} demet={r[58]:#010x} axi={r[59]:#010x} gpll0_vote={r[60]:#010x}')
    out.append(f'  gmu_regs_read={r[79]}')
    out.append(f'  (stage5 gmu state) sysreset={r[61]:#x} tcm_ret={r[62]:#x} rsc_busy={r[63]:#x} hfi_status={r[64]:#x}')
    # Stage 6
    STEP = {0: 'not-run', 7: 'ALL-PASS', 3: 'PLL1 lock timeout', 4: 'hub RCG timeout', 5: 'gmu RCG timeout', 6: 'cx_gmu CLK_OFF timeout'}
    out.append('-- stage 6 GMU clock bring-up --')
    out.append(f'  result={r[65]} ({STEP.get(r[65], "?")}) gpll0_voted={r[66]} pll1_lock_polls={r[67]} cx_gmu={r[68]:#010x} cx_gmu_polls={r[69]}')
    out.append(f'  pll1 mode={r[70]:#010x} opmode={r[71]:#x} gmu_cfg={r[72]:#05x} hub_cfg={r[73]:#05x}')
    out.append(f'  gmu cold-start preconds: sysreset={r[74]:#x}(want 1) tcm_ret={r[75]:#x}(want 0) rsc_busy={r[76]:#x}(want 0) hfi_status={r[77]:#x}(want bit0=0)')
    # Stage 7
    NAMES = ['gfx.lvl', 'mx.lvl', 'cx.lvl', 'gmxc.lvl', 'SH0', 'MC0', 'ACV', 'CN0']
    out.append('-- stage 7 cmd-db parse --')
    out.append(f'  version={r[80]:#x} magic={r[81]:#010x} (want 0x0c0330db) slaves={r[82]}')
    for i, nm in enumerate(NAMES):
        out.append(f'  {nm:<9} addr={r[83 + i]:#x}')
    if pages and pages[0][0] in (0xa7400002, 0xa7400003, 0xa7400004, 0xa7400005, 0xa7400006, 0xa7400007, 0xa7400008, 0xa7400009):
        e = pages[0]
        errors = {
            0: 'not-run', 1: 'PASS',
            0x801: 'unsupported SMMU geometry/state', 0x802: 'no embedded firmware',
            0x803: 'bad/truncated/unmapped firmware block', 0x804: 'SID5 already matched',
            0x805: 'no unused disabled context/slot/ASID', 0x806: 'not a cold GMU',
            0x807: 'scratch overlaps image/FDT', 0x808: 'TLB sync timeout',
            0x809: 'SMMU readback mismatch', 0x80a: 'firmware readback mismatch',
            0x80b: 'page-table capacity/overlap', 0x80c: 'context fault after load',
            0x80d: 'ShengGmu cold start failed (page1[66]=status, [67]=phase)', 0x901: 'FW init timeout/fault',
            0x902: 'HFI init timeout/fault', 0x903: 'HFI ACK timeout',
            0x904: 'bad queue indices/packet size/space', 0x905: 'GMU firmware error/fault',
            0x906: 'unexpected ACK/header/sequence', 0x907: 'ACK error',
            0x908: 'missing cmd-db aux/ARC/BW resource', 0x909: 'cold precondition lost',
            0x90b: 'stage 9 without HFI-ready from stage 8',
            0xa01: 'GPU_SET timeout/fault', 0xa02: 'GX power/clock timeout/fault',
            0xa03: 'GX GDSC off', 0xa04: 'context fault before GX',
        }
        errors.update({
            0xb01: 'SMMU MMIO fault/unreadable stream ownership', 0xb02: 'ownership changed/live bank',
            0xb03: 'SID0/1 already matched', 0xb04: 'no free GPU bank/two slots/ASID',
            0xb05: 'GPU page-table pool/overlap', 0xb06: 'GPU TLB sync timeout',
            0xb07: 'GPU context/stream readback mismatch', 0xb08: 'SMMU fault at stage11',
            0xc01: 'no embedded SQE', 0xc02: 'invalid SQE size', 0xc03: 'SQE readback mismatch',
            0xc04: 'GPU_SET/GX timeout or MMIO fault', 0xc05: 'hw_init/CP MMIO fault',
            0xc06: 'CP/RBBM/SMMU fault', 0xc07: 'CP init rptr/idle timeout',
            0xc08: 'CP ring not in reset state', 0xc09: 'SECVID access fault',
            0xc0a: 'SECVID_TRUST_CNTL did not clear',
            0xc0b: 'critical CP pointer/control readback mismatch (before SQE start)',
            0xc0c: 'SQE not dormant before cold hw_init',
            0xd01: 'fence MMIO fault', 0xd02: 'fence CP/RBBM/SMMU fault',
            0xd03: 'fence/rptr/idle timeout', 0xd04: 'ring/fence precondition lost',
            0xd05: 'fence guard overwritten',
            0xe01: 'blit safe-access fault', 0xe02: 'blit CP/RBBM/SMMU fault',
            0xe03: 'blit TLB sync timeout', 0xe04: 'blit idle/ring/OOB precondition',
            0xe05: 'blit event-fence/rptr/idle timeout', 0xe06: 'pixel/source mismatch',
            0xe07: 'scratch guard or panel border overwritten',
            0xe08: 'live framebuffer geometry mismatch', 0xe09: 'blit mapping failure',
            0xe0a: 'CPU comparison copy/readback mismatch',
            0xe0b: 'source-free solid clear pixel mismatch',
            0xf01: 'zap idle/ring/OOB/guard precondition lost',
            0xf02: 'no embedded zap MBN', 0xf03: 'invalid zap ELF32 header',
            0xf04: 'zap metadata/LOAD bounds or relocation invalid',
            0xf05: 'PAS availability query transport error' if e[0] == 0xa7400009 else 'PAS support-call unavailable or SCM error',
            0xf06: 'PAS support query transport error' if e[0] == 0xa7400009 else 'PAS13 unsupported or SCM error', 0xf07: 'PAS init_image SCM error',
            0xf08: 'PAS mem_setup SCM error', 0xf09: 'zap metadata/LOAD copy fault or mismatch',
            0xf0a: 'PAS auth_and_reset SCM error', 0xf0b: 'zap/secure packet safe-access fault',
            0xf0c: 'zap/secure packet CP/RBBM/SMMU fault', 0xf0d: 'secure packet idle timeout',
            0xf0e: 'TRUST still nonzero after secure packet',
            0xf0f: 'zap refused after 2D already attempted', 0xf10: 'owned zap resume SCM error',
        })
        result = lambda v: f'{v:#x} ({errors.get(v, "unknown")})'
        out.append('-- stage 8a SMMU snapshot (frozen before stage8 writes) --')
        out.append(f'  snapshot={result(e[1])} SMRs={e[5]} CBs={e[6]} stride={e[7]:#x} CBbase={e[8]:#x} GFSR={e[9]:#x}')
        if len(pages) >= 5 and e[1] == 1:
            snap = pages[1]
            out.append(f'  safe snapshot faults={snap[48]} ESR={snap[49]:#x} offset={snap[50]:#x} SMRmask={snap[51]:#x} CBmask={snap[52]:#x}')
            for i in range(min(e[5], 32)):
                smr, s2cr = pages[1][i*2:i*2+2]
                out.append(f'  SMR{i:02}: {smr:#010x} S2CR={s2cr:#010x} valid={smr>>31} SID={smr&0x7fff:#x} mask={(smr>>16)&0x7fff:#x} type={(s2cr>>16)&3} CB={s2cr&255}')
            for b in range(min(e[6], 24)):
                d = pages[2+b//8][b%8*16:b%8*16+16]
                out.append(f'  CB{b:02}: ACTLR={pages[1][64+b]:#x} CONTEXTIDR={pages[1][88+b]:#x} CBAR={d[0]:#x} CBA2R={d[1]:#x} SCTLR={d[2]:#x} TCR2={d[3]:#x} TCR={d[8]:#x} MAIR={d[9]:#x}/{d[10]:#x}')
                out.append(f'        TTBR0={d[5]:08x}{d[4]:08x} TTBR1={d[7]:08x}{d[6]:08x} FSR={d[11]:#x} FAR={d[13]:08x}{d[12]:08x} FSYNR={d[14]:#x}/{d[15]:#x}')
        out.append('-- stage 8 SID5 translation + firmware --')
        out.append(f'  result={result(e[2])} slot={e[10]} CB={e[11]} ASID={e[12]} table_PA={(e[14]<<32)|e[13]:#x} tables={e[33]} programmed={e[15]} TLBstatus={e[16]:#x}')
        out.append(f'  fw bytes={e[17]} data_blocks={e[18]} prealloc_headers={e[19]} data_bytes={e[20]} bad_addr={e[21]:#x} bad_size={e[22]:#x}')
        out.append(f'  CBAR={e[23]:#x} CBA2R={e[24]:#x} TCR2={e[25]:#x} TCR={e[26]:#x} TTBR0={e[28]:08x}{e[27]:08x} MAIR0={e[29]:#x} SCTLR={e[30]:#x} SMR={e[31]:#x} S2CR={e[32]:#x}')
        if e[82] == 5:
            # Loader build only: stage 8 loaded the firmware and released CM3
            # through the vendored UniXNU ShengGmu, not the in-tree sequence.
            st = e[66]
            out.append('  ShengGmu cold start (vendored UniXNU transport): '
                       f'status={st} ({SHENG_STATUS.get(st, "unknown")}) '
                       f'phase={e[67]} ({SHENG_PHASE.get(e[67], "?")}) ok={e[81]}')
            out.append(f'    hash_verified={e[70]} memory_zeroed={e[71]} reset_verified={e[72]} resources_retain={e[73]}')
            out.append(f'    FW_INIT={e[68]:#x} HFI_STATUS={e[69]:#x} fw_ready={e[79]} hfi_ready={e[80]} payloads={e[82]} arena={e[83]:#x}')
            out.append(f'    AO_faults={e[74]:#x} CM3_faults={e[75]:#x} io writes/reads/polls={e[76]}/{e[77]}/{e[78]}')
            if not e[81]:
                out.append('    stopped at that phase: nothing from stage 9 onward may run')
        out.append('-- stage 9 GMU firmware + HFI startup --')
        out.append(f'  result={result(e[3])} handoff_locked={e[4]} DTCM_version={e[34]:#x} expected={e[35]:#x} init={e[36]:#x} HFIstatus={e[37]:#x} HFIversion={e[38]:#x}')
        for i, name in enumerate(['PERF_TABLE', 'BW_TABLE', 'CORE_FW_START', 'START', 'GX_BW_PERF_VOTE']):
            d = e[40+i*4:44+i*4]
            out.append(f'  {name:<16} sent={d[0]:#010x} response={d[1]:#010x} returned={d[2]:#010x} error={d[3]:#x}')
        out.append('  GPU ARC votes (OFF,220,295,348,401,475,550,615,680,719 MHz): ' + ' '.join(f'{x:#x}' for x in e[100:110]))
        out.append('  GMU ARC votes (OFF,200,500 MHz): ' + ' '.join(f'{x:#x}' for x in e[110:113]))
        out.append('-- stage 10 GPU_SET / GX --')
        out.append(f'  result={result(e[60])} OOB_intr={e[61]:#x} SPTPRAC={e[62]:#x} GX_GDSCR={e[63]:#x} RBBM_read={e[65]} RBBM_STATUS={e[64]:#x}')
        out.append(f'  live: intr={e[84]:#x} AOirq={e[85]:#x} fence={e[86]:#x} GFSR={e[87]:#x} CB_FSR={e[88]:#x} FAR={e[90]:08x}{e[89]:08x} FSYNR={e[91]:#x}/{e[92]:#x}')
        out.append(f'  queues: command r/w={e[93]}/{e[94]} response r/w={e[95]}/{e[96]}')
        if len(pages) >= 7 and e[0] in (0xa7400003, 0xa7400004, 0xa7400005, 0xa7400006, 0xa7400007, 0xa7400008, 0xa7400009):
            m = pages[5]
            out.append('-- stage 11 GPU SID0/1 context --')
            out.append(f'  result={result(m[2])} slots={m[10]}/{m[34]} CB={m[11]} ASID={m[12]} GMU_CB/ASID={m[8]}/{m[9]} tables={m[33]} PT={(m[14]<<32)|m[13]:#x}')
            out.append(f'  CBAR={m[23]:#x} CBA2R={m[24]:#x} TCR2={m[25]:#x} TCR={m[26]:#x} TTBR0={m[28]:08x}{m[27]:08x} MAIR={m[29]:#x} SCTLR={m[30]:#x}')
            out.append(f'  SMR/S2CR SID0={m[31]:#x}/{m[32]:#x} SID1={m[35]:#x}/{m[36]:#x}; GMU FSR before/after={m[74]:#x}/{m[75]:#x} GPU FSR={m[76]:#x}/{m[77]:#x}')
            for i, name in enumerate(['SQE', 'ring', 'memptrs', 'fence']):
                out.append(f'  {name} VA={m[37+i]:#x} PA={m[65+2*i]:08x}{m[64+2*i]:08x}')
            out.append('-- stage 12 SQE / a7xx CP init / SECVID report --')
            out.append(f'  result={result(m[3])} step={m[60]} OOB_held={m[7]} SQE_started={m[59]} GX={m[63]:#x}')
            out.append(f'  SQE file/copy={m[17]}/{m[18]} header={m[19]:#x} first_payload={m[20]:#x} readback_dwords={m[21]} bad_offset={m[22]:#x}')
            out.append(f'  CP rptr before/after={m[48]}/{m[49]} wptr={m[50]} polls={m[51]} trust before/after={m[44]:#x}/{m[45]:#x} write_ok={m[43]} TSBstatus={m[47]:08x}{m[46]:08x}')
            out.append('-- stage 13 CP_MEM_WRITE fence --')
            out.append(f'  result={result(m[4])} fence before/after={m[52]:#x}/{m[53]:#x} expected={m[54]:#x} CP rptr before/after={m[55]}/{m[56]} wptr={m[57]} polls={m[58]}')
            out.append(f'  safe MMIO faults={m[116]} first_PA={m[118]:08x}{m[117]:08x} last_PA={m[111]:08x}{m[110]:08x} op={m[115]} ESR={m[112]:#x} FAR={m[114]:08x}{m[113]:08x}')
            if e[0] in (0xa7400004, 0xa7400005, 0xa7400006, 0xa7400007, 0xa7400008, 0xa7400009):
                out.append(f'  halt-clear readbacks: GBIF={m[95]:#x} RBBM_GBIF={m[96]:#x}')
            init_words = 7 if e[0] in (0xa7400004, 0xa7400005, 0xa7400006, 0xa7400007, 0xa7400008, 0xa7400009) else 10
            if e[0] in (0xa7400005, 0xa7400006, 0xa7400007, 0xa7400008, 0xa7400009):
                out.append('  raw SQE payload prefix: ' + ' '.join(f'{v:08x}' for v in m[97:97+min(m[109], 12)]))
                out.append(f'  checkpoint mask={m[119]:#x} (bit0=OOB,bit1=configured,bit2=RUN)')
            out.append('  init packet: ' + ' '.join(f'{v:08x}' for v in m[80:80+init_words]))
            out.append('  fence packet: ' + ' '.join(f'{v:08x}' for v in m[90:94]))
            for start in (0, 64):
                d = pages[6][start:start+64]
                if not d[0]:
                    continue
                out.append(f'  stage{d[0]} frozen diagnostics: rptr/wptr={d[1]}/{d[2]} shadows={d[3]}/{d[4]} fence={d[5]:#x} RBBM={d[6]:#x} SQE_CNTL={d[7]:#x} SQE_STAT[1]={d[8]:#x}')
                out.append(f'    CP_HW_FAULT={d[9]:#x} CP_INT={d[10]:#x} PROTECT={d[11]:#x} RBBM_INT={d[12]:#x} TRUST={d[13]:#x} TSB={d[15]:08x}{d[14]:08x} GFSR={d[16]:#x}')
                out.append(f'    CP_INT bits: {bit_names(d[10], CP_BITS)}; RBBM busy bits (Linux XML): {bit_names(d[6], RBBM_BITS)}')
                for at, name in ((17, 'GPU'), (23, 'GMU')):
                    out.append(f'    {name} CB{d[at]} FSR={d[at+1]:#x} FAR={d[at+3]:08x}{d[at+2]:08x} FSYNR={d[at+4]:#x}/{d[at+5]:#x}')
                    if d[at+1] & 0xc00001fe:
                        syn = d[at+4]
                        out.append(f'      fault attributes: {"write" if syn & 16 else "read"} level={syn & 3} IND={bool(syn & 64)} PNU={bool(syn & 32)} PTWF={bool(syn & 1024)} MID={d[at+5] & 255} ({fault_client(d[at+5], 0x7f)})')
                out.append(f'    fence guards={d[32]:#x}/{d[33]:#x} MMIO_faults={d[31]}')
                if e[0] in (0xa7400004, 0xa7400005, 0xa7400006, 0xa7400007, 0xa7400008, 0xa7400009) and len(pages) >= 9:
                    x = pages[8 if start else 7]
                    out.append(f'    extended: stage={x[1]} step={x[2]} phase={x[3]} (1=verify,2=SQE/wptr0,3=doorbell,4=cold-entry) bad_pointer_index={m[94]}')
                    out.append(f'      before doorbell: polls={x[4]} CP_INT={x[5]:#x} GPU_FSR={x[6]:#x} RBBM={x[7]:#x}')
                    names = ['SQElo', 'SQEhi', 'RBlo', 'RBhi', 'RB_CNTL', 'RPTRlo', 'RPTRhi',
                             'BV_RPTRlo', 'BV_RPTRhi', 'BR_APRIV', 'BV_APRIV', 'LPAC_APRIV',
                             'APERTURE_HOST', 'LPAC_SQE_CNTL', 'LPAC_SQElo', 'LPAC_SQEhi']
                    for i, name in enumerate(names):
                        out.append(f'      {name}: before_RUN={x[8+i]:#x} frozen={x[24+i]:#x}')
                    for at, word, name in ((17, 40, 'GPU'), (23, 41, 'GMU')):
                        valid = bool(d[at+1] & 0xc00001fe)
                        out.append(f'      {name} CBFRSYNRA={x[word]:#x} SID={x[word] & 0xffff} valid_fault={valid}' +
                                   (f' client={fault_client(d[at+5], x[42])}' if valid else ''))
                    out.append(f'      UCHE_CLIENT_PF={x[42]:#x} RBBM_STATUS1/2/3={x[43]:#x}/{x[44]:#x}/{x[45]:#x} SMMU_stalled={bool(x[45] & (1 << 24))}')
                    out.append(f'      CP_STATUS1={x[46]:#x} CP2GMU={x[47]:#x} IB1={x[49]:08x}{x[48]:08x}/{x[50]} IB2={x[52]:08x}{x[51]:08x}/{x[53]}')
                    out.append(f'      ROQ_RB/MRB={x[54]:#x}/{x[55]:#x} MRB={x[57]:08x}{x[56]:08x}/{x[58]} BV_HW/PROTECT={x[59]:#x}/{x[60]:#x} MMIO_faults={x[61]}')
                    out.append(f'      SQE PC/header: BR={x[64]:#x}/{x[65]:08x} BV={x[115]:#x}/{x[116]:08x} LPAC={x[117]:#x}/{x[118]:08x}')
                    out.append(f'      BR SQE_STAT count={x[63]} [0..50]: ' + ' '.join(f'{v:08x}' for v in x[64:115]))
                    out.append('      raw UCODE_DBG[0..3]: ' + ' '.join(f'{v:08x}' for v in x[120:124]))
                    out.append('      CPU SQE[0..3]:       ' + ' '.join(f'{v:08x}' for v in x[124:128]))
                if e[0] in (0xa7400005, 0xa7400006, 0xa7400007, 0xa7400008, 0xa7400009):
                    if not start:
                        for i, name in enumerate(('OOB/pre-setup', 'configured/pre-RUN', 'immediate/post-RUN')):
                            if not (m[119] & (1 << i)):
                                continue
                            c = d[34+i*10:44+i*10]
                            out.append(f'    {name}: SQE_CNTL={c[0]:#x} SQEbase={c[2]:08x}{c[1]:08x} CP_INT={c[3]:#x} RBBM={c[4]:#x} HW_FAULT={c[5]:#x} SW_RESET={c[6]:#x} MISC/CHICKEN={c[7]:#x}/{c[8]:#x} GPU_FSR={c[9]:#x}')
                    if len(pages) >= 11:
                        y = pages[10 if start else 9]
                        out.append(f'    pipe diagnostics: stage={y[1]} MMIO_faults={y[4]}')
                        for j, name in enumerate(('BV', 'LPAC')):
                            out.append(f'      {name} SQE_STAT count={y[2+j]} [0..50]: ' + ' '.join(f'{v:08x}' for v in y[16+j*51:16+j*51+min(y[2+j], 51)]))
                            out.append(f'      {name} raw UCODE_DBG[0..3]: ' + ' '.join(f'{v:08x}' for v in y[5+j*4:9+j*4]))
                        out.append(f'      raw AQE bases={y[119]:08x}{y[118]:08x}/{y[121]:08x}{y[120]:08x} MISC/BR_CHICKEN/BV_CHICKEN={y[122]:#x}/{y[123]:#x}/{y[124]:#x} APERTURE_CD={y[125]:#x} SMMU_INFO={y[127]:08x}{y[126]:08x}')
    if pages and len(pages) >= 13 and pages[0][0] in (0xa7400006, 0xa7400007, 0xa7400008, 0xa7400009):
        for d in pages[11:13]:
            if not d[1]:
                continue
            out.append(f'-- stage {d[1]} A7xx 2D blit --')
            out.append(f'  result={result(d[2])} step={d[3]} size={d[4]}x{d[5]} bytes={d[8]} src/dst_pitch={d[6]}/{d[7]} dst_xy={d[15]}/{d[16]}')
            out.append(f'  src VA/PA={d[9]:#x}/{d[12]:08x}{d[11]:08x} dst VA/PA={d[10]:#x}/{d[14]:08x}{d[13]:08x}')
            out.append(f'  checksum expected/actual={d[19]:08x}/{d[20]:08x} mismatch={d[21]} first_xy={d[22]}/{d[23]} expected/actual={d[24]:08x}/{d[25]:08x} source_bad={d[46]}')
            out.append(f'  guard_bad={d[26]} scratch_guard_bad={d[45]} fence_guards={d[27]:08x}/{d[48]:08x} CPU_mismatch={d[47]} CPU_border_bad={d[49]}')
            out.append(f'  ring start/end/count={d[31]}/{d[32]}/{d[33]} rptr/wptr={d[35]}/{d[36]} polls={d[34]} fence VA={d[17]:#x} expected/actual={d[18]:08x}/{d[37]:08x}')
            gpu_ticks = d[38] | d[39] << 32
            cpu_ticks = d[40] | d[41] << 32
            v7 = d[0] in (0xa7400007, 0xa7400008, 0xa7400009)
            cpu_valid = bool(d[43] & 1) if v7 else d[3] >= 7 and bool(cpu_ticks)
            gpu_valid = bool(d[43] & 8) if v7 else d[3] >= 5
            cpu_text = str(cpu_ticks) if cpu_valid else 'N/A (not run)'
            gpu_text = str(gpu_ticks) if gpu_valid else 'N/A (not submitted)'
            out.append(f'  cntpct GPU_submit_to_idle={gpu_text} CPU_volatile_byte_memcpy={cpu_text} cntfrq={d[42]} Hz (polling, uncached loader)')
            if d[42] and gpu_valid:
                cpu_us = f'{cpu_ticks*1e6/d[42]:.3f} us' if cpu_valid else 'N/A (not run)'
                out.append(f'  GPU={gpu_ticks*1e6/d[42]:.3f} us CPU={cpu_us}')
            if v7:
                out.append(f'  validity={d[43]:#x} solid_clear={result(d[44])} end={d[54]} fence={d[55]:08x} mismatch={d[56]} first_actual={d[57]:08x} expected=ff336699 untouched_deadbeef={d[58]} guard_bad={d[61]} source_bad={d[62]} polls={d[63]}')
                if d[43] & 2:
                    out.append(f'  clear after 100us RBBM={d[59]:#x} ({bit_names(d[59], RBBM_BITS)}) CP_INT={d[60]:#x} ({bit_names(d[60], CP_BITS)})')
                if d[43] & 32:
                    out.append(f'  copy after 100us RBBM={d[112]:#x} ({bit_names(d[112], RBBM_BITS)}) CP_INT={d[113]:#x} ({bit_names(d[113], CP_BITS)})')
                    names = ('CCU_CNTL', 'CCU_CNTL2', 'RB_BLIT', 'GRAS_BLIT', 'SP_FORMAT', 'SRC_INFO', 'SRC_SIZE', 'SRC_PITCH', 'DST_INFO', 'DST_PITCH', 'TPL1_BLIT', 'RB_CMP_DBG', 'RB_DBG', 'APERTURE_HOST')
                    out.append('  raw state (host aperture): ' + ' '.join(f'{name}={v:08x}' for name, v in zip(names, d[114:128])))
            out.append(f'  tables={d[28]} TLBstatus={d[29]:#x} TLBpolls={d[30]} display PA/pitch/size/format=' + '/'.join(f'{v:#x}' for v in d[50:54]))
            out.append(f'  frozen CP r/w={d[64]}/{d[65]} RBBM={d[66]:#x} CP_INT={d[67]:#x} HW_FAULT={d[68]:#x} PROTECT={d[69]:#x} RBBM_INT={d[70]:#x} GFSR={d[71]:#x} TRUST={d[88]:#x}')
            out.append(f'  CP_INT bits: {bit_names(d[67], CP_BITS)}; RBBM busy bits: {bit_names(d[66], RBBM_BITS)}')
            for at, name in ((72, 'GPU'), (80, 'GMU')):
                out.append(f'  {name} CB{d[at]} FSR={d[at+1]:#x} FAR={d[at+3]:08x}{d[at+2]:08x} FSYNR={d[at+4]:#x}/{d[at+5]:#x} SID={d[at+6]:#x} SCTLR={d[at+7]:#x}')
            out.append(f'  RBBM_STATUS1/2/3={d[89]:#x}/{d[90]:#x}/{d[91]:#x} safe_faults={d[92]} last_PA={d[94]:08x}{d[93]:08x} ESR={d[95]:#x}')
            out.append(f'  first {16 if v7 else 32} copy command words: ' + ' '.join(f'{v:08x}' for v in d[96:112 if v7 else 128]))
    if len(pages) >= 14 and pages[0][0] in (0xa7400008, 0xa7400009) and pages[13][1] == 16:
        d = pages[13]
        out.append('-- stage 16 PAS13 zap + stage-14 clear/copy --')
        out.append(f'  result={result(d[2])} step={d[3]} authenticated={d[4]} path={d[38]} (1=cold,2=owned-resume) calls={d[5]} failed_call={d[44]} clear_copy={result(d[37])}')
        out.append(f'  MBN={d[6]} metadata={d[7]}@{d[9]:08x}{d[8]:08x} reserved={d[10]:#x}+{d[11]:#x} min/max={d[12]:#x}/{d[13]:#x} relocate={d[14]} loads={d[15]} span={d[16]:#x} copied/zeroed={d[17]}/{d[18]}')
        out.append(f'  TRUST before/after={d[19]:#x}/{d[20]:#x} TSB before/after={d[22]:08x}{d[21]:08x}/{d[24]:08x}{d[23]:08x} (after valid at step>=11)')
        out.append(f'  secure packet={d[39]:08x} {d[40]:08x} submitted={d[43]} ring before={d[25]}/{d[26]} target={d[27]} after={d[28]}/{d[29]} polls={d[30]} RBBM={d[31]:#x} CP_INT={d[32]:#x} HW_FAULT={d[46]:#x} PROTECT={d[45]:#x} RBBM_INT={d[47]:#x}')
        out.append(f'  guards={d[41]:08x}/{d[42]:08x} safe_faults={d[33]} last_PA={d[35]:08x}{d[34]:08x} ESR={d[36]:#x}')
        slots = [d[48+i*16:64+i*16] for i in range(5)]
        v9 = pages[0][0] == 0xa7400009
        if v9 and len(pages) >= 15 and pages[14][:2] == [0xa7400009, 16]:
            slots += [pages[14][16+i*16:32+i*16] for i in range(3)]
        if d[5] > len(slots):
            out.append(f'  SCM records missing: captured={len(slots)} issued={d[5]}')
        for i, slot in enumerate(slots[:d[5]]):
            args = [slot[j] | slot[j+1] << 32 for j in (4, 6)]
            returns = [slot[j] | slot[j+1] << 32 for j in (8, 10, 12, 14)]
            out.append(f'  SCM[{i+1}] step={slot[0]} fn={slot[1]:#010x} arginfo={slot[2]:#x} returned={slot[3]} args0/1={args[0]:#x}/{args[1]:#x}' + (f' arg2(span)={d[16]:#x}' if slot[1] == 0x42000202 else ''))
            if v9 and slot[1] in (0x42000601, 0x42000207):
                out.append('    advisory query boolean; nonzero x0 still stops')
            if slot[3]:
                out.append('    ' + ' '.join(f'x{j}={value:#018x}' for j, value in enumerate(returns)))
            else:
                out.append('    in flight (no returned registers)')
    return '\n'.join(out)


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--stage', default='1', choices=[str(i) for i in range(1, 17)] + ['8a'],
                    help='last stage (default 1); 8a is the powered SMMU snapshot')
    ap.add_argument('--timeout', type=int, default=15000, help='control-transfer timeout ms')
    ap.add_argument('--raw', action='store_true', help='also dump every raw report page')
    ap.add_argument('--read-reports', action='store_true', help='read all pages without running a stage')
    ap.add_argument('--save', type=Path, help='save raw concatenated little-endian report pages')
    ap.add_argument('--decode', type=Path, help='decode a saved report offline (no USB access)')
    args = ap.parse_args()
    if args.decode:
        blob = args.decode.read_bytes()
        if len(blob) not in (512, 3072, 4096, 5120, 6144, 7168, 7680, 8192):
            ap.error('report must be 512 (legacy), 3072 (v2), 4096 (v3), 5120 (v4), 6144 (v5), 7168 (v6/v7), 7680 (v8), or 8192 (v9) bytes')
    else:
        import usb.core
        import usb.util
        devs = list(usb.core.find(find_all=True, idVendor=0x1209, idProduct=0x0001))
        devs = [d for d in devs if usb.util.get_string(d, d.iProduct) == 'Fuxi hardware probe']
        if len(devs) != 1:
            ap.error('expected exactly one Fuxi native probe (1209:0001)')
        dev = devs[0]

        def read(index):
            data = bytes(dev.ctrl_transfer(0xc0, 0x56, 0x4753, index, 512, timeout=args.timeout))
            if len(data) != 512:
                raise SystemExit(f'short USB response: {len(data)} bytes at index {index:#x}')
            return data

        stage = 0x8a if args.stage == '8a' else int(args.stage)
        blob = read(0x100 if args.read_reports else stage)
        if args.read_reports or stage >= 8:
            extra = read(0x101)
            version = struct.unpack_from('<I', extra)[0]
            page_count = {0xa7400002: 6, 0xa7400003: 8, 0xa7400004: 10, 0xa7400005: 12, 0xa7400006: 14, 0xa7400007: 14, 0xa7400008: 15, 0xa7400009: 16}.get(version)
            if page_count is None:
                ap.error(f'unsupported report version {version:#x}')
            blob += extra + b''.join(read(0x100 + i) for i in range(2, page_count))
    pages = [list(struct.unpack('<128I', blob[i:i+512])) for i in range(0, len(blob), 512)]
    if pages[0][0] != 0xa740:
        raise SystemExit(f'bad report magic {pages[0][0]:#x} (probe may not have the 0x56 handler)')
    print(decode(pages[0], pages[1:]))
    if args.save:
        args.save.write_bytes(blob)
    if args.raw:
        for p, r in enumerate(pages):
            print(f'page {p}:')
            for i in range(0, 128, 8):
                print('  w%3d:' % i, ' '.join('%08x' % x for x in r[i:i + 8]))
    return 0


if __name__ == '__main__':
    sys.exit(main())
