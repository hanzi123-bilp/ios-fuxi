/* fuxi GMU cold-start adapter — wires UniXNU's ShengGmu/HFI code to fuxi.
 * SPDX-License-Identifier: BSD-2-Clause-Patent
 *
 * Windows (from the pinned fuxi/sheng device tree):
 *   Core    0x03d6a000   (gmu@3d68000 region, GMU core registers)
 *   Rscc    0x03d50000   (RSC seq / PDC handshake)
 *   CxMisc  0x03d9e000   (gpu "cx_mem")
 *   Gpu     0x03d90000   (GPUCC)              -- TODO confirm from fuxi.dtb
 *   Pdc     0x03d40000   (PDC)                -- TODO confirm from fuxi.dtb
 *
 * The five context payloads must be Normal non-cacheable memory mapped at the
 * fixed IOVAs the firmware expects: icache 0x4000, dummy 0x60000000,
 * debug 0x60400000, log and hfi elsewhere in the GMU window.
 */
#include <stdint.h>
#include <stddef.h>
#include "ShengGmu.h"

/* ---- windows ------------------------------------------------------------ */
enum { W_CORE, W_RSCC, W_PDC, W_GPU, W_CXMISC, W_COUNT };

static const uint64_t fuxi_win[W_COUNT] = {
    0x03d6a000ULL,  /* Core   */
    0x03d50000ULL,  /* Rscc   */
    0x03d40000ULL,  /* Pdc    (TODO: verify) */
    0x03d90000ULL,  /* Gpu/CC (TODO: verify) */
    0x03d9e000ULL,  /* CxMisc */
};

static const size_t fuxi_win_bytes[W_COUNT] = {
    0x35000, 0x10000, 0x10000, 0x10000, 0x10000,
};

static inline volatile uint32_t *win_ptr(unsigned w, size_t off)
{
    return (volatile uint32_t *)(uintptr_t)(fuxi_win[w] + off);
}

static int fuxi_read32(void *cookie, unsigned w, size_t off, uint32_t *out)
{
    (void)cookie;
    if (w >= W_COUNT || off + 4 > fuxi_win_bytes[w] || (off & 3)) return -1;
    *out = *win_ptr(w, off);
    return 0;
}

static int fuxi_write32(void *cookie, unsigned w, size_t off, uint32_t val)
{
    (void)cookie;
    if (w >= W_COUNT || off + 4 > fuxi_win_bytes[w] || (off & 3)) return -1;
    *win_ptr(w, off) = val;
    return 0;
}

static int fuxi_barrier(void *cookie)
{
    (void)cookie;
    __asm__ volatile("dsb sy" ::: "memory");
    return 0;
}

/* ---- SHA-256 (compact, no tables beyond K) ------------------------------ */
static const uint32_t K256[64] = {
 0x428a2f98,0x71374491,0xb5c0fbcf,0xe9b5dba5,0x3956c25b,0x59f111f1,0x923f82a4,0xab1c5ed5,
 0xd807aa98,0x12835b01,0x243185be,0x550c7dc3,0x72be5d74,0x80deb1fe,0x9bdc06a7,0xc19bf174,
 0xe49b69c1,0xefbe4786,0x0fc19dc6,0x240ca1cc,0x2de92c6f,0x4a7484aa,0x5cb0a9dc,0x76f988da,
 0x983e5152,0xa831c66d,0xb00327c8,0xbf597fc7,0xc6e00bf3,0xd5a79147,0x06ca6351,0x14292967,
 0x27b70a85,0x2e1b2138,0x4d2c6dfc,0x53380d13,0x650a7354,0x766a0abb,0x81c2c92e,0x92722c85,
 0xa2bfe8a1,0xa81a664b,0xc24b8b70,0xc76c51a3,0xd192e819,0xd6990624,0xf40e3585,0x106aa070,
 0x19a4c116,0x1e376c08,0x2748774c,0x34b0bcb5,0x391c0cb3,0x4ed8aa4a,0x5b9cca4f,0x682e6ff3,
 0x748f82ee,0x78a5636f,0x84c87814,0x8cc70208,0x90befffa,0xa4506ceb,0xbef9a3f7,0xc67178f2
};

#define ROR32(x,n) (((x) >> (n)) | ((x) << (32 - (n))))

static int fuxi_sha256(void *cookie, const void *data, size_t len, uint8_t out[32])
{
    (void)cookie;
    uint32_t h[8] = {0x6a09e667,0xbb67ae85,0x3c6ef372,0xa54ff53a,
                     0x510e527f,0x9b05688c,0x1f83d9ab,0x5be0cd19};
    const uint8_t *p = (const uint8_t *)data;
    size_t total = len, i;
    uint8_t block[64];

    for (i = 0; i + 63 < len || (i <= len); i += 64) {
        size_t n = (len - i >= 64) ? 64 : len - i;
        if (i >= len && n == 0) break;
        for (size_t k = 0; k < 64; k++) block[k] = (k < n) ? p[i + k] : 0;
        if (n < 64) {
            block[n] = 0x80;
            for (size_t k = n + 1; k < 64; k++) block[k] = 0;
            if (n >= 56) {
                uint32_t w[64], a,b,c,d,e,f,g,hh;
                for (int t = 0; t < 16; t++)
                    w[t] = (uint32_t)block[t*4]<<24 | (uint32_t)block[t*4+1]<<16 |
                           (uint32_t)block[t*4+2]<<8 | block[t*4+3];
                for (int t = 16; t < 64; t++) {
                    uint32_t s0 = ROR32(w[t-15],7)^ROR32(w[t-15],18)^(w[t-15]>>3);
                    uint32_t s1 = ROR32(w[t-2],17)^ROR32(w[t-2],19)^(w[t-2]>>10);
                    w[t] = w[t-16] + s0 + w[t-7] + s1;
                }
                a=h[0];b=h[1];c=h[2];d=h[3];e=h[4];f=h[5];g=h[6];hh=h[7];
                for (int t = 0; t < 64; t++) {
                    uint32_t S1 = ROR32(e,6)^ROR32(e,11)^ROR32(e,25);
                    uint32_t ch = (e & f) ^ (~e & g);
                    uint32_t t1 = hh + S1 + ch + K256[t] + w[t];
                    uint32_t S0 = ROR32(a,2)^ROR32(a,13)^ROR32(a,22);
                    uint32_t mj = (a & b) ^ (a & c) ^ (b & c);
                    uint32_t t2 = S0 + mj;
                    hh=g; g=f; f=e; e=d+t1; d=c; c=b; b=a; a=t1+t2;
                }
                h[0]+=a;h[1]+=b;h[2]+=c;h[3]+=d;h[4]+=e;h[5]+=f;h[6]+=g;h[7]+=hh;
                for (size_t k = 0; k < 56; k++) block[k] = 0;
            }
            /* length in bits, big endian, in the last 8 bytes */
            uint64_t bits = (uint64_t)total * 8;
            for (int k = 0; k < 8; k++) block[63 - k] = (uint8_t)(bits >> (8 * k));
            for (size_t k = 56; k < 64; k++) if (k < 56) block[k] = 0;
        }
        /* compress one block */
        uint32_t w[64], a,b,c,d,e,f,g,hh;
        for (int t = 0; t < 16; t++)
            w[t] = (uint32_t)block[t*4]<<24 | (uint32_t)block[t*4+1]<<16 |
                   (uint32_t)block[t*4+2]<<8 | block[t*4+3];
        for (int t = 16; t < 64; t++) {
            uint32_t s0 = ROR32(w[t-15],7)^ROR32(w[t-15],18)^(w[t-15]>>3);
            uint32_t s1 = ROR32(w[t-2],17)^ROR32(w[t-2],19)^(w[t-2]>>10);
            w[t] = w[t-16] + s0 + w[t-7] + s1;
        }
        a=h[0];b=h[1];c=h[2];d=h[3];e=h[4];f=h[5];g=h[6];hh=h[7];
        for (int t = 0; t < 64; t++) {
            uint32_t S1 = ROR32(e,6)^ROR32(e,11)^ROR32(e,25);
            uint32_t ch = (e & f) ^ (~e & g);
            uint32_t t1 = hh + S1 + ch + K256[t] + w[t];
            uint32_t S0 = ROR32(a,2)^ROR32(a,13)^ROR32(a,22);
            uint32_t mj = (a & b) ^ (a & c) ^ (b & c);
            uint32_t t2 = S0 + mj;
            hh=g; g=f; f=e; e=d+t1; d=c; c=b; b=a; a=t1+t2;
        }
        h[0]+=a;h[1]+=b;h[2]+=c;h[3]+=d;h[4]+=e;h[5]+=f;h[6]+=g;h[7]+=hh;
        if (n < 64) break;
    }
    for (int k = 0; k < 8; k++) {
        out[k*4]   = (uint8_t)(h[k] >> 24);
        out[k*4+1] = (uint8_t)(h[k] >> 16);
        out[k*4+2] = (uint8_t)(h[k] >> 8);
        out[k*4+3] = (uint8_t)(h[k]);
    }
    return 0;
}

/* ---- time services ------------------------------------------------------ */
static inline uint64_t cntpct(void)
{
    uint64_t v;
    __asm__ volatile("mrs %0, cntpct_el0" : "=r"(v));
    return v;
}

static int fuxi_now_us(void *cookie, uint64_t *us)
{
    (void)cookie;
    *us = cntpct() / 50;   /* 50 MHz counter on SM8550 */
    return 0;
}

static int fuxi_wait_us(void *cookie, unsigned us)
{
    (void)cookie;
    uint64_t until = cntpct() + (uint64_t)us * 50;
    while (cntpct() < until) __asm__ volatile("yield");
    return 0;
}

/* ---- entry point (called from the loader probe) ------------------------- */
extern const uint8_t *fuxi_gmu_firmware;   /* gmu_gen70200.bin staged in memory */
extern size_t fuxi_gmu_firmware_bytes;

int fuxi_gmu_cold_start(uint32_t chip_id, ShengGmuResult *result)
{
    ShengGmuDevice dev;
    ShengGmuConfig cfg;
    ShengGmuIo io;
    ShengGmuServices svc;

    io.cookie  = 0;
    io.read32  = fuxi_read32;
    io.write32 = fuxi_write32;
    io.barrier = fuxi_barrier;
    for (unsigned w = 0; w < ShengGmuWindows && w < W_COUNT; w++)
        io.bytes[w] = fuxi_win_bytes[w];

    svc.cookie  = 0;
    svc.sha256  = fuxi_sha256;
    svc.now_us  = fuxi_now_us;
    svc.wait_us = fuxi_wait_us;

    cfg.chip_id        = chip_id;
    cfg.firmware       = fuxi_gmu_firmware;
    cfg.firmware_bytes = fuxi_gmu_firmware_bytes;
    cfg.poll_budget    = 10000;
    /* icache / dummy / debug / log / hfi must be filled by the caller with
     * Normal non-cacheable memory at the firmware's fixed IOVAs. */

    dev.io = io;
    dev.services = svc;
    return ShengGmuLoadAndStartHfi(&dev, &cfg, result) == ShengGmuSuccess;
}
