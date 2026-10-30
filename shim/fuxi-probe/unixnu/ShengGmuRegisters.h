/* ShengGmuRegisters.h — A740 GMU register dword offsets for ShengGmu.c.
 * SPDX-License-Identifier: BSD-2-Clause-Patent
 *
 * The vendored ShengGmu.c addresses the GMU through core_offset(word):
 *
 *     core_offset(word) = word*4 - SHENG_GMU_CORE_GPU_DELTA   (0x6a000)
 *
 * so every REG_GMU_* value below is an A6XX whole-GPU dword offset, i.e. the
 * register's dword offset inside the kgsl_3d0_reg_memory window. The GMU core
 * block starts at byte 0x6a000 of that window (0x1a800 dwords), so a dword
 * offset D in the separate A6XX_GMU register file becomes D + 0x1a800 here.
 * Example: A6XX_GMU CM3_SYSRESET is 0x5000 there and 0x1f800 here, which is
 * byte 0x14000 inside the Core window - the value shim/fuxi-probe/gpu.c has
 * used since milestone 2.
 *
 * Cross-checks (each value is the dword the hardware-tested loader already
 * writes through gm_rd()/gm_wr(), which take block-relative dwords):
 *
 *   CM3_SYSRESET 0x1f800 <-> gm_rd(0x5000)        HFI_CTRL_STATUS 0x1f980 <-> 0x5180
 *   GENERAL_10   0x1f9cf <-> gm_wr(0x51cf)        HFI_CTRL_INIT   0x1f986 <-> 0x5186
 *   DTCM_START   0x1c400 <-> gm_rd(0x1c00)        ICACHE_CONFIG   0x1f400 <-> 0x4c00
 *   AHB_FENCE    0x23b11 <-> gm_wr(0x9311)        AO_HOST_INTR    0x23b05 <-> 0x9305
 *
 * RSCC_PDC_SLAVE_ID_DRV0 / RSCC_SEQ_BUSY_DRV0 are NOT here: ShengGmu.c reads
 * the RSC idle bit as REG_RSCC_SEQ_BUSY_DRV0*4 and the setup table carries
 * byte offsets, so both live in ShengGmuSource.h's RSCC numbering.
 *
 * REG_GBIF_QSB_SIDE0 is the only value not confirmed against gpu.c: no
 * pre-existing loader code writes it. 0x3c03 is the A6XX_GBIF_QSB_SIDE0 dword
 * published with the mainline Adreno register database; it places the four
 * side registers at byte 0xf00c..0xf018 of the Gpu window (0x3d00000/0x40000).
 * TODO: confirm against the pinned registers/adreno/a6xx.xml.
 */
#ifndef SHENG_GMU_REGISTERS_H
#define SHENG_GMU_REGISTERS_H

#include <stdint.h>

/* GMU core block (window 0), whole-GPU dword offsets. */
#define REG_GMU_CM3_ITCM_START                UINT32_C(0x0001b400)
#define REG_GMU_CM3_DTCM_START                UINT32_C(0x0001c400)
#define REG_GMU_CM3_SYSRESET                  UINT32_C(0x0001f800)
#define REG_GMU_CM3_BOOT_CONFIG               UINT32_C(0x0001f801)
#define REG_GMU_CM3_FW_INIT_RESULT            UINT32_C(0x0001f81c)
#define REG_GMU_CM3_CFG                       UINT32_C(0x0001f82d)
#define REG_GMU_SYS_BUS_CONFIG                UINT32_C(0x0001f40f)
#define REG_GMU_ICACHE_CONFIG                 UINT32_C(0x0001f400)
#define REG_GMU_DCACHE_CONFIG                 UINT32_C(0x0001f401)
#define REG_GMU_HFI_QTBL_ADDR                 UINT32_C(0x0001f985)
#define REG_GMU_HFI_QTBL_INFO                 UINT32_C(0x0001f984)
#define REG_GMU_HFI_CTRL_INIT                 UINT32_C(0x0001f986)
#define REG_GMU_HFI_CTRL_STATUS               UINT32_C(0x0001f980)
#define REG_GMU_HOST2GMU_INTR_SET             UINT32_C(0x0001f994)
#define REG_GMU_GMU2HOST_INTR_INFO            UINT32_C(0x0001f992)
#define REG_GMU_AO_HOST_INTERRUPT_STATUS      UINT32_C(0x00023b05)
#define REG_GMU_AHB_FENCE_RANGE_0             UINT32_C(0x00023b11)
#define REG_GMU_GENERAL_8                     UINT32_C(0x0001f9cd)
#define REG_GMU_GENERAL_9                     UINT32_C(0x0001f9ce)
#define REG_GMU_GENERAL_10                    UINT32_C(0x0001f9cf)
#define REG_GPU_GMU_CX_GMU_CX_FALNEXT_INTF    UINT32_C(0x0001f8f1)
#define REG_GPU_GMU_CX_GMU_CX_FAL_INTF        UINT32_C(0x0001f8f0)

/* GPU window (0x3d00000/0x40000), whole-GPU dword offsets. */
#define REG_GBIF_QSB_SIDE0                    UINT32_C(0x00003c03)

/* CX miscellaneous window (0x3d9e000/0x10000): ShengGmu.c multiplies by 4. */
#define REG_CX_MISC_TCM_RET_CNTL              UINT32_C(0x00000039)

#endif /* SHENG_GMU_REGISTERS_H */
