/* fuxi_gmu_adapter.h — loader-side entry point for the vendored ShengGmu.
 * SPDX-License-Identifier: BSD-2-Clause-Patent
 */
#ifndef FUXI_GMU_ADAPTER_H
#define FUXI_GMU_ADAPTER_H

#include "ShengGmu.h"

#ifdef __cplusplus
extern "C" {
#endif

/* Board GMU identity, defined once from ShengGmuSource.h's SHENG_GMU_CHIP_ID.
 * ShengGmu compares it against ShengGmuConfig.chip_id, so the caller fills the
 * config from this instead of repeating the constant. */
extern const uint32_t fuxi_gmu_chip_id;

/* Run the pinned-firmware cold start (RSCC setup, ICACHE/ITCM/DTCM load and
 * readback, CM3 release, FW_INIT and HFI ready) on the five caller-owned
 * Normal non-cacheable payloads in cfg->icache/dummy/debug/log/hfi.
 *
 * The caller fills cfg->chip_id and all five ShengGmuMemory entries and must
 * already have programmed an SMMU context that translates those IOVAs for the
 * GMU stream. Firmware bytes, firmware length and poll_budget are filled in
 * here. One attempt per boot: a second call returns ShengGmuBusy, and any
 * failure poisons the device, exactly as ShengGmu documents. */
ShengGmuStatus fuxi_gmu_cold_start(ShengGmuConfig *cfg, ShengGmuResult *result);

#ifdef __cplusplus
}
#endif
#endif /* FUXI_GMU_ADAPTER_H */
