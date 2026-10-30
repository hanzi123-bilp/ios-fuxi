/* ShengGmuSource.h — fuxi (SM8550 / Adreno 740) board data for ShengGmu.
 * Generated from verified sources; two constants still need confirmation
 * (marked TODO). Do not invent values for them.
 *
 * Sources
 *   windows            fuxi.dtb  /soc/qcom,kgsl-3d0@3d00000  reg / reg-names
 *   firmware size/hash local fuxi-port/fw/gmu_gen70200.bin
 *   RSCC write order   upstream linux a6xx_gmu.c  a6xx_gmu_rpmh_init()
 *   RSCC offsets       a6xx_gmu.xml.h (byte offsets; RSCC window is 0x10000)
 */
#ifndef SHENG_GMU_SOURCE_H
#define SHENG_GMU_SOURCE_H

#include <stdint.h>

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
    0x03d8b000ull,   /* Pdc    (DT "isense_cntl",  0x2000)  TODO confirm */
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
/* TODO: A740 GMU chip id and the firmware-reported chip id.  Both are
 * compared against the caller's chip_id and REG_GMU_GENERAL_10, so they must
 * come from the GPU id registers / vendor source, not from a guess. */
#define SHENG_GMU_CHIP_ID    0x00000740u   /* A740, provisional */
#define SHENG_GMU_FW_CHIP_ID 0x07040000u   /* provisional */

/* Fault masks (a6xx_gmu.xml.h). */
#define SHENG_GMU_AO_FATAL_MASK  0x00000010u
#define SHENG_GMU_CM3_FATAL_MASK 0x00000010u

/* ---- RSCC setup sequence ---------------------------------------------- *
 * Offsets are BYTE offsets into the RSCC window (it is only 0x10000 bytes).
 * Write order from a6xx_gmu_rpmh_init(); entry 0 is a read-modify-write of
 * BIT(24) and is issued separately by ShengGmu, so the table starts at
 * PDC_SLAVE_ID.
 */
typedef struct { uint32_t window, offset, value; } ShengGmuSetupWrite;

#define SHENG_GMU_RSC_SETUP_COUNT 7

static const ShengGmuSetupWrite sheng_gmu_rsc_setup[SHENG_GMU_RSC_SETUP_COUNT] = {
    { 1, 0x8c0bu, 1u },          /* RSCC_PDC_SLAVE_ID_DRV0      = 1      */
    { 1, 0x8c0eu, 0u },          /* RSCC_HIDDEN_TCS_CMD0_DATA   = 0      */
    { 1, 0x8c0du, 0u },          /* RSCC_HIDDEN_TCS_CMD0_ADDR   = 0      */
    { 1, 0x8d00u, 0u },          /* RSCC_OVERRIDE_START_ADDR    = 0      */
    { 1, 0x8c08u, 0x4520u },     /* RSCC_PDC_SEQ_START_ADDR     = 0x4520 */
    { 1, 0x8c09u, 0x4510u },     /* RSCC_PDC_MATCH_VALUE_LO     = 0x4510 */
    { 1, 0x8c0au, 0x4514u },     /* RSCC_PDC_MATCH_VALUE_HI     = 0x4514 */
};

#endif /* SHENG_GMU_SOURCE_H */
