/* fuxi GMU cold-start adapter — wires UniXNU's ShengGmu/HFI transport to fuxi.
 * SPDX-License-Identifier: BSD-2-Clause-Patent
 *
 * Split of ownership:
 *   shim/fuxi-probe/gpu.c   the five Normal non-cacheable payloads and their
 *                           fixed GMU IOVAs, plus the SMMU context that makes
 *                           those IOVAs translate for the GMU stream
 *   this file               the five MMIO windows (ShengGmuSource.h), the
 *                           pinned firmware bytes, and real SHA-256/time
 *                           services. Nothing here invents an ACK.
 *
 * The loader runs with the MMU and caches off (VA==PA, Device-nGnRnE), so a
 * physical address is directly a CPU pointer; the GMU sees the same bytes
 * through SMMU leaf descriptors with MAIR index 0 (Normal non-cacheable).
 */
#include <stdint.h>
#include <stddef.h>

#include "fuxi_gmu_adapter.h"
#include "ShengGmuSource.h"

#if !defined(FUXI_XNU_LOADER)
#error fuxi_gmu_adapter is a loader-only translation unit today
#endif

/* .gpu_fw is emitted by shim/fuxi-loader/build.sh from the pinned blobs. */
extern const uint8_t _gpu_fw_start[];
extern const uint8_t _gpu_fw_end[];

/* ShengGmu rejects a poll budget above 1024; each iteration also enforces a
 * 10 ms elapsed-time bound. 200 x 100 us leaves room for a slow first boot. */
#define FUXI_GMU_POLL_BUDGET 200u

/* ---- freestanding memory primitives ------------------------------------- *
 * The loader links with -nostdlib, and ShengGmu's aggregate initialisers plus
 * its payload copies reference memset/memcpy. Byte-wise on purpose: the GMU
 * payloads are Device memory under the loader's MMU-off identity mapping, so
 * no unaligned wide accesses are assumed. -fno-builtin is already in the
 * build flags, which keeps clang from turning these loops back into calls.
 */
__attribute__((used)) void *memset(void *dst, int value, size_t bytes)
{
    unsigned char *p = (unsigned char *)dst;
    while (bytes--) *p++ = (unsigned char)value;
    return dst;
}

__attribute__((used)) void *memcpy(void *dst, const void *src, size_t bytes)
{
    unsigned char *d = (unsigned char *)dst;
    const unsigned char *s = (const unsigned char *)src;
    while (bytes--) *d++ = *s++;
    return dst;
}

/* ---- MMIO windows ------------------------------------------------------- */
static int fuxi_read32(void *cookie, unsigned window, size_t at, uint32_t *out)
{
    (void)cookie;
    if (window >= ShengGmuWindows || (at & 3) || at > sheng_gmu_window_bytes[window] - 4u)
        return -1;
    *out = *(volatile uint32_t *)(uintptr_t)(sheng_gmu_window_physical[window] + at);
    return 0;
}

static int fuxi_write32(void *cookie, unsigned window, size_t at, uint32_t value)
{
    (void)cookie;
    if (window >= ShengGmuWindows || (at & 3) || at > sheng_gmu_window_bytes[window] - 4u)
        return -1;
    *(volatile uint32_t *)(uintptr_t)(sheng_gmu_window_physical[window] + at) = value;
    return 0;
}

static int fuxi_barrier(void *cookie)
{
    (void)cookie;
    __asm__ volatile("dsb sy" ::: "memory");
    return 0;
}

/* ---- SHA-256 ------------------------------------------------------------ */
static const uint32_t fuxi_sha256_k[64] = {
    0x428a2f98u,0x71374491u,0xb5c0fbcfu,0xe9b5dba5u,0x3956c25bu,0x59f111f1u,
    0x923f82a4u,0xab1c5ed5u,0xd807aa98u,0x12835b01u,0x243185beu,0x550c7dc3u,
    0x72be5d74u,0x80deb1feu,0x9bdc06a7u,0xc19bf174u,0xe49b69c1u,0xefbe4786u,
    0x0fc19dc6u,0x240ca1ccu,0x2de92c6fu,0x4a7484aau,0x5cb0a9dcu,0x76f988dau,
    0x983e5152u,0xa831c66du,0xb00327c8u,0xbf597fc7u,0xc6e00bf3u,0xd5a79147u,
    0x06ca6351u,0x14292967u,0x27b70a85u,0x2e1b2138u,0x4d2c6dfcu,0x53380d13u,
    0x650a7354u,0x766a0abbu,0x81c2c92eu,0x92722c85u,0xa2bfe8a1u,0xa81a664bu,
    0xc24b8b70u,0xc76c51a3u,0xd192e819u,0xd6990624u,0xf40e3585u,0x106aa070u,
    0x19a4c116u,0x1e376c08u,0x2748774cu,0x34b0bcb5u,0x391c0cb3u,0x4ed8aa4au,
    0x5b9cca4fu,0x682e6ff3u,0x748f82eeu,0x78a5636fu,0x84c87814u,0x8cc70208u,
    0x90befffau,0xa4506cebu,0xbef9a3f7u,0xc67178f2u,
};

#define FUXI_ROR(x, n) (((x) >> (n)) | ((x) << (32 - (n))))

static void fuxi_sha256_block(uint32_t h[8], const uint8_t block[64])
{
    uint32_t w[64], a, b, c, d, e, f, g, hh;
    for (unsigned i = 0; i < 16; i++)
        w[i] = (uint32_t)block[i*4] << 24 | (uint32_t)block[i*4+1] << 16 |
               (uint32_t)block[i*4+2] << 8 | (uint32_t)block[i*4+3];
    for (unsigned i = 16; i < 64; i++) {
        uint32_t s0 = FUXI_ROR(w[i-15], 7) ^ FUXI_ROR(w[i-15], 18) ^ (w[i-15] >> 3);
        uint32_t s1 = FUXI_ROR(w[i-2], 17) ^ FUXI_ROR(w[i-2], 19) ^ (w[i-2] >> 10);
        w[i] = w[i-16] + s0 + w[i-7] + s1;
    }
    a = h[0]; b = h[1]; c = h[2]; d = h[3];
    e = h[4]; f = h[5]; g = h[6]; hh = h[7];
    for (unsigned i = 0; i < 64; i++) {
        uint32_t s1 = FUXI_ROR(e, 6) ^ FUXI_ROR(e, 11) ^ FUXI_ROR(e, 25);
        uint32_t ch = (e & f) ^ (~e & g);
        uint32_t t1 = hh + s1 + ch + fuxi_sha256_k[i] + w[i];
        uint32_t s0 = FUXI_ROR(a, 2) ^ FUXI_ROR(a, 13) ^ FUXI_ROR(a, 22);
        uint32_t maj = (a & b) ^ (a & c) ^ (b & c);
        uint32_t t2 = s0 + maj;
        hh = g; g = f; f = e; e = d + t1;
        d = c; c = b; b = a; a = t1 + t2;
    }
    h[0] += a; h[1] += b; h[2] += c; h[3] += d;
    h[4] += e; h[5] += f; h[6] += g; h[7] += hh;
}

static int fuxi_sha256(void *cookie, const void *data, size_t bytes, uint8_t out[32])
{
    (void)cookie;
    uint32_t h[8] = {0x6a09e667u,0xbb67ae85u,0x3c6ef372u,0xa54ff53au,
                     0x510e527fu,0x9b05688cu,0x1f83d9abu,0x5be0cd19u};
    const uint8_t *p = (const uint8_t *)data;
    uint8_t tail[128];
    size_t whole = bytes & ~(size_t)63, rest = bytes - whole;

    if (!data || !out) return -1;
    for (size_t at = 0; at < whole; at += 64) fuxi_sha256_block(h, p + at);
    for (size_t i = 0; i < 128; i++) tail[i] = 0;
    for (size_t i = 0; i < rest; i++) tail[i] = p[whole + i];
    tail[rest] = 0x80;
    size_t tail_bytes = rest < 56 ? 64 : 128;
    uint64_t bits = (uint64_t)bytes * 8;
    for (unsigned i = 0; i < 8; i++)
        tail[tail_bytes - 1 - i] = (uint8_t)(bits >> (8 * i));
    for (size_t at = 0; at < tail_bytes; at += 64) fuxi_sha256_block(h, tail + at);
    for (unsigned i = 0; i < 8; i++) {
        out[i*4]     = (uint8_t)(h[i] >> 24);
        out[i*4 + 1] = (uint8_t)(h[i] >> 16);
        out[i*4 + 2] = (uint8_t)(h[i] >> 8);
        out[i*4 + 3] = (uint8_t)h[i];
    }
    return 0;
}

/* ---- time services ------------------------------------------------------ */
/* CNTFRQ_EL0 is the architectural counter frequency and is EL1-readable.
 * Never assume a fixed 19.2/50 MHz here: ShengGmu's poll bound is elapsed
 * time, so a wrong scale would cut the GMU boot short (or hide a timeout). */
static inline uint64_t fuxi_cntfrq(void)
{
    uint64_t v;
    __asm__ volatile("mrs %0, cntfrq_el0" : "=r"(v));
    return v ? v : 19200000u;
}

static inline uint64_t fuxi_cntpct(void)
{
    uint64_t v;
    __asm__ volatile("isb; mrs %0, cntpct_el0" : "=r"(v));
    return v;
}

static int fuxi_now_us(void *cookie, uint64_t *us)
{
    (void)cookie;
    if (!us || !fuxi_cntfrq()) return -1;
    *us = fuxi_cntpct() / (fuxi_cntfrq() / 1000000u);
    return 0;
}

static int fuxi_wait_us(void *cookie, unsigned us)
{
    (void)cookie;
    uint64_t freq = fuxi_cntfrq(), until = fuxi_cntpct() + (uint64_t)us * freq / 1000000u;
    while (fuxi_cntpct() < until) __asm__ volatile("yield");
    return 0;
}

/* ---- entry point -------------------------------------------------------- */
/* One device per boot: ShengGmu allows a single attempt and keeps the poisoned
 * state, so the object must outlive the call. */
static ShengGmuDevice fuxi_gmu_device;

const uint32_t fuxi_gmu_chip_id = SHENG_GMU_CHIP_ID;

ShengGmuStatus fuxi_gmu_cold_start(ShengGmuConfig *cfg, ShengGmuResult *result)
{
    if (!cfg || !result) return ShengGmuArgument;

    fuxi_gmu_device.io.cookie  = 0;
    fuxi_gmu_device.io.read32  = fuxi_read32;
    fuxi_gmu_device.io.write32 = fuxi_write32;
    fuxi_gmu_device.io.barrier = fuxi_barrier;
    for (unsigned w = 0; w < ShengGmuWindows; w++)
        fuxi_gmu_device.io.bytes[w] = sheng_gmu_window_bytes[w];

    fuxi_gmu_device.services.cookie  = 0;
    fuxi_gmu_device.services.sha256  = fuxi_sha256;
    fuxi_gmu_device.services.now_us  = fuxi_now_us;
    fuxi_gmu_device.services.wait_us = fuxi_wait_us;

    /* ShengGmu owns these three; the caller only supplies identity + payloads. */
    cfg->firmware       = _gpu_fw_start;
    cfg->firmware_bytes = (size_t)(_gpu_fw_end - _gpu_fw_start);
    cfg->poll_budget    = FUXI_GMU_POLL_BUDGET;

    return ShengGmuLoadAndStartHfi(&fuxi_gmu_device, cfg, result);
}
