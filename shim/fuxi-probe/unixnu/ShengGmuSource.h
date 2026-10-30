/* ShengGmuSource.h — fuxi (SM8550 / Adreno 740) board data for ShengGmu.
 * SPDX-License-Identifier: BSD-2-Clause-Patent
 *
 * Sources
 *   windows            fuxi.dtb  /soc/qcom,kgsl-3d0@3d00000  reg / reg-names
 *   firmware size/hash local fuxi-port/fw/gmu_gen70200.bin
 *   chip ids           Adreno catalog entry 0x43050a01 (A740) and the
 *                      firmware-reported id gpu.c stage 9 already wrote
 *   RSCC write order   upstream linux a6xx_gmu.c  a6xx_gmu_rpmh_init()
 *   RSCC offsets       A6XX dword offsets rebased onto the 0x10000 window
 *
 * RSCC numbering. The fuxi DT maps "rscc" at 0x3d50000 for 0x10000 bytes.
 * A6XX whole-GPU dword offsets put the RSC block at 0x8c00, so a register at
 * dword D is written at byte 4*(D-0x8c00) inside that window: SEQ_BUSY_DRV0
 * (0x8d01) is byte 0x404, which is the index shim/fuxi-probe/gpu.c has used
 * since milestone 2. Offsets below are BYTE offsets in that mapping.
 */
#ifndef SHENG_GMU_SOURCE_H
#define SHENG_GMU_SOURCE_H

#include <stdint.h>
#include "ShengGmuRegisters.h"

/* ---- firmware --------------------------------------------------------- */
#define SHENG_GMU_FIRMWARE_BYTES 66844u

static const uint8_t sheng_gmu_firmware_sha256[32] = {
    0x1a,0x2a,0x41,0x9c,0x39,0x04,0x6d,0x31,0x41,0xfc,0x5f,0xed,0x5a,0xa7,0xf9,0x71,
    0xde,0x2d,0xb4,0x0c,0xc7,0xa1,0xd8,0x96,0x93,0xc3,0xe2,0x6f,0xad,0x64,0xdd,0x98,
};

/* ---- windows ---------------------------------------------------------- *
 * Order matches enum {Core, Rscc, Pdc, Gpu, CxMisc} in ShengGmu.h.
 * Core is the GMU register block inside kgsl_3d0_reg_memory.
 */
static const uint64_t sheng_gmu_window_physical[5] = {
    0x03d6a000ull,   /* Core   (0x03d00000 + 0x6a000) */
    0x03d50000ull,   /* Rscc   (DT "rscc",         0x10000) */
    0x03d8b000ull,   /* Pdc    (DT "isense_cntl",  0x2000)  */
    0x03d00000ull,   /* Gpu    (DT kgsl_3d0_reg_memory, 0x40000) */
    0x03d9e000ull,   /* CxMisc (DT "cx_misc",      0x10000) */
};

static const uint32_t sheng_gmu_window_bytes[5] = {
    0x35000u,   /* Core  */
    0x10000u,   /* Rscc  */
    0x2000u,    /* Pdc   */
    0x40000u,   /* Gpu   */
    0x10000u,   /* CxMisc */
};

/* GMU core dword -> GPU window byte offset: dword*4 - CORE_GPU_DELTA. */
#define SHENG_GMU_CORE_GPU_DELTA 0x6a000u

/* ---- chip ids --------------------------------------------------------- */
#define SHENG_GMU_CHIP_ID    0x43050a01u   /* A740 (Adreno catalog entry)   */
#define SHENG_GMU_FW_CHIP_ID 0x07020100u   /* REG_GMU_GENERAL_10, gen70200  */

/* Fault masks (a6xx_gmu.xml.h). */
#define SHENG_GMU_AO_FATAL_MASK  0x00000010u
#define SHENG_GMU_CM3_FATAL_MASK 0x00000010u

/* ---- RSCC ------------------------------------------------------------- */
/* RSC idle poll: ShengGmu.c reads REG_RSCC_SEQ_BUSY_DRV0*4 (= byte 0x404). */
#define REG_RSCC_SEQ_BUSY_DRV0 0x00000101u

/* ---- RSCC/PDC setup sequence ------------------------------------------ *
 * Write order from a6xx_gmu_rpmh_init() with the A740/A722 variant selected
 * for HIDDEN_TCS_CMD0_DATA+4 and the A740 SEQ_MEM_0 register. PDC itself is
 * AOP-owned on a7xx (pdc_in_aop), so no PDC window write is included.
 * `byte_offset` is a byte offset into the RSCC window; entry 0 is the
 * "disable SDE clock gating" store, kept in Linux order.
 */
typedef struct { uint32_t window, byte_offset, value; } ShengGmuSetupWrite;

#define SHENG_GMU_RSC_SETUP_COUNT 17

static const ShengGmuSetupWrite sheng_gmu_rsc_setup[SHENG_GMU_RSC_SETUP_COUNT] = {
    { 1, 0x010u, 0x01000000u },  /* RSCC_RSC_STATUS0_DRV0  = BIT(24)      */
    { 1, 0x02cu, 1u },           /* RSCC_PDC_SLAVE_ID_DRV0 = 1            */
    { 1, 0x038u, 0u },           /* RSCC_HIDDEN_TCS_CMD0_DATA      = 0    */
    { 1, 0x034u, 0u },           /* RSCC_HIDDEN_TCS_CMD0_ADDR      = 0    */
    { 1, 0x040u, 0u },           /* RSCC_HIDDEN_TCS_CMD0_DATA + 2  = 0    */
    { 1, 0x03cu, 0u },           /* RSCC_HIDDEN_TCS_CMD0_ADDR + 2  = 0    */
    { 1, 0x048u, 0x80000021u },  /* RSCC_HIDDEN_TCS_CMD0_DATA + 4  (A740) */
    { 1, 0x044u, 0u },           /* RSCC_HIDDEN_TCS_CMD0_ADDR + 4  = 0    */
    { 1, 0x400u, 0u },           /* RSCC_OVERRIDE_START_ADDR       = 0    */
    { 1, 0x020u, 0x4520u },      /* RSCC_PDC_SEQ_START_ADDR        = 0x4520 */
    { 1, 0x024u, 0x4510u },      /* RSCC_PDC_MATCH_VALUE_LO        = 0x4510 */
    { 1, 0x028u, 0x4514u },      /* RSCC_PDC_MATCH_VALUE_HI        = 0x4514 */
    { 1, 0x550u, 0xeaaae5a0u },  /* RSCC_SEQ_MEM_0_DRV0_A740 (a7xx)       */
    { 1, 0x554u, 0xe1a1ebabu },
    { 1, 0x558u, 0xa2e0a581u },
    { 1, 0x55cu, 0xecac82e2u },
    { 1, 0x560u, 0x0020edadu },
};

#endif /* SHENG_GMU_SOURCE_H */
