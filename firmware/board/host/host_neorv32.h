/* Copyright (C) 2026 Marsupial Solutions LLC
   SPDX-License-Identifier: GPL-3.0-or-later */
/* board/host/host_neorv32.h - the NEORV32 names the shared sources use, for the x86 host build.
 *
 * GPIO_INPUT    the core's option word (paprium_cart.sv packs Console / MegaWire into the MCU GPIO input); on the host
 *               it is a variable the harness sets ('O' request in ours_host.c; 0 = the default options).
 * CSR reads     the TEST build's trap record reads mcause / mscratch / mtval; the host has no traps, so they read 0.
 * RTE           the TEST build installs its trap recorder through the NEORV32 runtime environment: a no-op here.
 * Values follow board/pocket/neorv32/include (neorv32.h, neorv32_rte.h). */
#ifndef HOST_NEORV32_H
#define HOST_NEORV32_H
#include <stdint.h>

extern volatile uint32_t host_gpio_input;
#define GPIO_INPUT host_gpio_input

enum { CSR_MSTATUS = 0x300, CSR_MIE = 0x304, CSR_MTVEC = 0x305, CSR_MSCRATCH = 0x340, CSR_MEPC = 0x341,
       CSR_MCAUSE = 0x342, CSR_MTVAL = 0x343, CSR_MIP = 0x344 };
static inline uint32_t neorv32_cpu_csr_read(const int csr_id) { (void) csr_id; return 0; }
static inline void neorv32_cpu_csr_write(const int csr_id, uint32_t data) { (void) csr_id; (void) data; }
static inline int neorv32_rte_setup(void) { return 0; }
static inline int neorv32_rte_exception_install(uint8_t id, void (*handler)(void)) { (void) id; (void) handler; return 0; }
#endif
