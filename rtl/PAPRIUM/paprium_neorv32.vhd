-- Copyright (C) 2026 Marsupial Solutions LLC
-- SPDX-License-Identifier: GPL-3.0-or-later
-- pocket: 0.3.0 new core (the firmware's docs/MCU_INTERFACE.md v1.0 section 2) - the cart MCU's NEORV32 configuration.
--
-- mcu_core.sv instantiates this entity rather than neorv32_top_stdlogic. Every processor generic is set here, in
-- VHDL, and only two naturals cross the SystemVerilog / VHDL boundary (0.2.6 already passed one, the clock):
-- boolean and std_logic_vector generics set from SystemVerilog would rest on the tool's mixed-language mapping.
--
--   CLOCK_FREQUENCY  core_top's CLK_HZ. SYSINFO_CLK (0xFFFF_FFE0) reports it; the firmware compares it with its
--                    build-time clock at boot.
--   USER_CODE        the MCU interface version, 0x5049_MMmm ('P', 'I', major, minor); v1.0 = 0x5049_0100, v1.1 = 0x5049_0101.
--                    SYSINFO USER_CODE (0xFFFF_FFE4) reports it (0.2.6: 0). A natural, so it stays below 2^31,
--                    which 'P' = 0x50 in the top byte guarantees.
--
-- Against 0.2.6 (neorv32_top_stdlogic with its defaults and CLOCK_FREQUENCY only):
--   IO_MTIME_USE false  replaced by the FPGAIO timer; mtime_irq_i is the timer's level (the input is used only
--                       when MTIME is off); the time / timeh CSRs read 0
--   IO_UART_USE  false  no printf on the Pocket (its TX pin was unconnected)
--   IO_WDT_USE   false  the chip's watchdog is firmware on the timer
-- Everything else as before: RV32IM + Zicsr, fast multiply and shift (3 DSP), Wishbone external bus, no internal
-- IMEM / DMEM, no bootloader, GPIO kept (F-D1: the option word is GPIO input).
-- Removed units leave holes, not quiet addresses: a load or store to the WDT (0xFFFF_FF8C), MTIME
-- (0xFFFF_FF90-9C) or UART (0xFFFF_FFA0-A4) gets no acknowledge and ends in the CPU's bus-timeout access fault.
--
-- pocket: test build 4 (the 0.3.0 hardware test build of the MCU fast path) - the IROM (region 0x00) and the WRAM
-- (region 0x80) are tightly
-- coupled: they sit on the processor-internal bus (the tcm_* ports, mcu_core.sv's mcu_tcm_irom / mcu_tcm_wram) with
-- neorv32_imem / neorv32_dmem's one-clock registered ack, instead of behind the Wishbone gateway and mcu_wram's state
-- machine. The windows are the whole 16 MB regions (MEM_TCM_IMEM_SIZE / MEM_TCM_DMEM_SIZE below), so every address the
-- 0.2.x / v1.1 map decodes as IROM or WRAM still goes there, aliases included; nothing else reaches the processor bus.
-- MEM_INT_IMEM_USE / MEM_INT_DMEM_USE stay false, so SYSINFO (FEATURES, IMEM / DMEM size) reads as before.
-- The CPU is unchanged; only the time an access takes changes (fetch 1 + ack, no gateway round trip).
--
-- This entity wraps neorv32_top directly and does its own std_logic / std_ulogic conversion, because the vendored
-- neorv32_top_stdlogic (1.4.8.1) never drives its internal mtime_irq_i_int from the mtime_irq_i port: through it,
-- the external timer interrupt would be dead (measured in GHDL: the request reaches the port and stops there).
-- 0.2.6 did not notice, because the internal MTIME supplied the timer interrupt.

library ieee;
use ieee.std_logic_1164.all;
use ieee.numeric_std.all;

entity paprium_neorv32 is
  generic (
    CLOCK_FREQUENCY : natural := 0;   -- Hz; 0 = not set (refused below)
    USER_CODE       : natural := 0    -- MCU interface version
  );
  port (
    clk_i       : in  std_logic;
    rstn_i      : in  std_logic;
    wb_adr_o    : out std_logic_vector(31 downto 0);
    wb_dat_i    : in  std_logic_vector(31 downto 0);
    wb_dat_o    : out std_logic_vector(31 downto 0);
    wb_we_o     : out std_logic;
    wb_sel_o    : out std_logic_vector(3 downto 0);
    wb_stb_o    : out std_logic;
    wb_cyc_o    : out std_logic;
    wb_ack_i    : in  std_logic;
    wb_err_i    : in  std_logic;
    wb_src_o    : out std_logic;      -- pocket: test build 4 - 1 = the access is an instruction fetch (Wishbone tag bit 2)
    gpio_o      : out std_logic_vector(31 downto 0);
    gpio_i      : in  std_logic_vector(31 downto 0);
    mtime_irq_i : in  std_logic;      -- machine timer interrupt (FPGAIO timer level)
    msw_irq_i   : in  std_logic;      -- machine software interrupt (FPGAIO MSIP)
    mext_irq_i  : in  std_logic;      -- machine external interrupt (FPGAIO cause OR)
    -- pocket: test build 4 - the processor-internal bus to the tightly coupled IROM and WRAM (mcu_core.sv)
    tcm_re_o      : out std_logic;                     -- read enable, one clock
    tcm_we_o      : out std_logic;                     -- write enable, one clock
    tcm_ben_o     : out std_logic_vector(3 downto 0);  -- byte enables (by size, loads too)
    tcm_addr_o    : out std_logic_vector(31 downto 0);
    tcm_wdata_o   : out std_logic_vector(31 downto 0);
    tcm_i_rdata_i : in  std_logic_vector(31 downto 0); -- IROM read data, 0 when not reading
    tcm_i_ack_i   : in  std_logic;
    tcm_d_rdata_i : in  std_logic_vector(31 downto 0); -- WRAM read data, 0 when not reading
    tcm_d_ack_i   : in  std_logic
  );
end entity;

architecture rtl of paprium_neorv32 is

  component neorv32_top is
    generic (
      CLOCK_FREQUENCY              : natural := 0;
      BOOTLOADER_USE               : boolean := true;
      USER_CODE                    : std_ulogic_vector(31 downto 0) := x"00000000";
      HW_THREAD_ID                 : std_ulogic_vector(31 downto 0) := (others => '0');
      CPU_EXTENSION_RISCV_A        : boolean := false;
      CPU_EXTENSION_RISCV_C        : boolean := false;
      CPU_EXTENSION_RISCV_E        : boolean := false;
      CPU_EXTENSION_RISCV_M        : boolean := false;
      CPU_EXTENSION_RISCV_U        : boolean := false;
      CPU_EXTENSION_RISCV_Zicsr    : boolean := true;
      CPU_EXTENSION_RISCV_Zifencei : boolean := false;
      FAST_MUL_EN                  : boolean := false;
      FAST_SHIFT_EN                : boolean := false;
      PMP_USE                      : boolean := false;
      PMP_NUM_REGIONS              : natural := 4;
      PMP_GRANULARITY              : natural := 14;
      MEM_INT_IMEM_USE             : boolean := true;
      MEM_INT_IMEM_SIZE            : natural := 16*1024;
      MEM_INT_IMEM_ROM             : boolean := false;
      MEM_INT_DMEM_USE             : boolean := true;
      MEM_INT_DMEM_SIZE            : natural := 8*1024;
      MEM_EXT_USE                  : boolean := false;
      MEM_TCM_IMEM_SIZE            : natural := 0;      -- pocket: test build 4
      MEM_TCM_DMEM_SIZE            : natural := 0;      -- pocket: test build 4
      IO_GPIO_USE                  : boolean := true;
      IO_MTIME_USE                 : boolean := true;
      IO_UART_USE                  : boolean := true;
      IO_SPI_USE                   : boolean := true;
      IO_TWI_USE                   : boolean := true;
      IO_PWM_USE                   : boolean := true;
      IO_WDT_USE                   : boolean := true;
      IO_TRNG_USE                  : boolean := false;
      IO_CFU0_USE                  : boolean := false;
      IO_CFU1_USE                  : boolean := false
    );
    port (
      clk_i       : in  std_ulogic := '0';
      rstn_i      : in  std_ulogic := '0';
      wb_tag_o    : out std_ulogic_vector(02 downto 0);
      wb_adr_o    : out std_ulogic_vector(31 downto 0);
      wb_dat_i    : in  std_ulogic_vector(31 downto 0) := (others => '0');
      wb_dat_o    : out std_ulogic_vector(31 downto 0);
      wb_we_o     : out std_ulogic;
      wb_sel_o    : out std_ulogic_vector(03 downto 0);
      wb_stb_o    : out std_ulogic;
      wb_cyc_o    : out std_ulogic;
      wb_lock_o   : out std_ulogic;
      wb_ack_i    : in  std_ulogic := '0';
      wb_err_i    : in  std_ulogic := '0';
      fence_o     : out std_ulogic;
      fencei_o    : out std_ulogic;
      gpio_o      : out std_ulogic_vector(31 downto 0);
      gpio_i      : in  std_ulogic_vector(31 downto 0) := (others => '0');
      uart_txd_o  : out std_ulogic;
      uart_rxd_i  : in  std_ulogic := '0';
      spi_sck_o   : out std_ulogic;
      spi_sdo_o   : out std_ulogic;
      spi_sdi_i   : in  std_ulogic := '0';
      spi_csn_o   : out std_ulogic_vector(07 downto 0);
      twi_sda_io  : inout std_logic;
      twi_scl_io  : inout std_logic;
      pwm_o       : out std_ulogic_vector(03 downto 0);
      mtime_irq_i : in  std_ulogic := '0';
      msw_irq_i   : in  std_ulogic := '0';
      mext_irq_i  : in  std_ulogic := '0';
      tcm_re_o      : out std_ulogic;                    -- pocket: test build 4
      tcm_we_o      : out std_ulogic;
      tcm_ben_o     : out std_ulogic_vector(03 downto 0);
      tcm_addr_o    : out std_ulogic_vector(31 downto 0);
      tcm_wdata_o   : out std_ulogic_vector(31 downto 0);
      tcm_i_rdata_i : in  std_ulogic_vector(31 downto 0) := (others => '0');
      tcm_i_ack_i   : in  std_ulogic := '0';
      tcm_d_rdata_i : in  std_ulogic_vector(31 downto 0) := (others => '0');
      tcm_d_ack_i   : in  std_ulogic := '0'
    );
  end component;

  constant USER_CODE_V : std_ulogic_vector(31 downto 0) := std_ulogic_vector(to_unsigned(USER_CODE, 32));

  signal wb_adr_u, wb_dat_i_u, wb_dat_o_u, gpio_o_u, gpio_i_u : std_ulogic_vector(31 downto 0);
  signal wb_sel_u : std_ulogic_vector(3 downto 0);
  signal wb_tag_u : std_ulogic_vector(2 downto 0);           -- pocket: test build 4
  signal wb_we_u, wb_stb_u, wb_cyc_u : std_ulogic;
  signal tcm_re_u, tcm_we_u : std_ulogic;                    -- pocket: test build 4
  signal tcm_ben_u : std_ulogic_vector(3 downto 0);
  signal tcm_addr_u, tcm_wdata_u : std_ulogic_vector(31 downto 0);

begin

  assert CLOCK_FREQUENCY > 0
    report "paprium_neorv32: CLOCK_FREQUENCY is not set (core_top CLK_HZ)" severity failure;

  neorv32_inst: neorv32_top
    generic map (
      CLOCK_FREQUENCY              => CLOCK_FREQUENCY,
      BOOTLOADER_USE               => false,
      USER_CODE                    => USER_CODE_V,
      HW_THREAD_ID                 => (others => '0'),
      CPU_EXTENSION_RISCV_A        => false,
      CPU_EXTENSION_RISCV_C        => false,
      CPU_EXTENSION_RISCV_E        => false,
      CPU_EXTENSION_RISCV_M        => true,
      CPU_EXTENSION_RISCV_U        => false,
      CPU_EXTENSION_RISCV_Zicsr    => true,
      CPU_EXTENSION_RISCV_Zifencei => false,
      FAST_MUL_EN                  => true,
      FAST_SHIFT_EN                => true,
      PMP_USE                      => false,
      PMP_NUM_REGIONS              => 4,
      PMP_GRANULARITY              => 14,
      MEM_INT_IMEM_USE             => false,
      MEM_INT_IMEM_SIZE            => 16*1024,
      MEM_INT_IMEM_ROM             => false,
      MEM_INT_DMEM_USE             => false,
      MEM_INT_DMEM_SIZE            => 8*1024,
      MEM_EXT_USE                  => true,
      MEM_TCM_IMEM_SIZE            => 16*1024*1024,   -- pocket: test build 4 - region 0x00 (IROM, aliases every 128 KB)
      MEM_TCM_DMEM_SIZE            => 16*1024*1024,   -- pocket: test build 4 - region 0x80 (WRAM, aliases every 64 KB)
      IO_GPIO_USE                  => true,
      IO_MTIME_USE                 => false,
      IO_UART_USE                  => false,
      IO_SPI_USE                   => false,
      IO_TWI_USE                   => false,
      IO_PWM_USE                   => false,
      IO_WDT_USE                   => false,
      IO_TRNG_USE                  => false,
      IO_CFU0_USE                  => false,
      IO_CFU1_USE                  => false
    )
    port map (
      clk_i       => clk_i,
      rstn_i      => rstn_i,
      wb_tag_o    => wb_tag_u,                             -- pocket: test build 4 (bit 2 = instruction fetch)
      wb_adr_o    => wb_adr_u,
      wb_dat_i    => wb_dat_i_u,
      wb_dat_o    => wb_dat_o_u,
      wb_we_o     => wb_we_u,
      wb_sel_o    => wb_sel_u,
      wb_stb_o    => wb_stb_u,
      wb_cyc_o    => wb_cyc_u,
      wb_lock_o   => open,
      wb_ack_i    => wb_ack_i,
      wb_err_i    => wb_err_i,
      fence_o     => open,
      fencei_o    => open,
      gpio_o      => gpio_o_u,
      gpio_i      => gpio_i_u,
      uart_txd_o  => open,
      uart_rxd_i  => '1',
      spi_sck_o   => open,
      spi_sdo_o   => open,
      spi_sdi_i   => '0',
      spi_csn_o   => open,
      twi_sda_io  => open,
      twi_scl_io  => open,
      pwm_o       => open,
      mtime_irq_i => mtime_irq_i,
      msw_irq_i   => msw_irq_i,
      mext_irq_i  => mext_irq_i,
      tcm_re_o      => tcm_re_u,                           -- pocket: test build 4
      tcm_we_o      => tcm_we_u,
      tcm_ben_o     => tcm_ben_u,
      tcm_addr_o    => tcm_addr_u,
      tcm_wdata_o   => tcm_wdata_u,
      tcm_i_rdata_i => std_ulogic_vector(tcm_i_rdata_i),
      tcm_i_ack_i   => std_ulogic(tcm_i_ack_i),
      tcm_d_rdata_i => std_ulogic_vector(tcm_d_rdata_i),
      tcm_d_ack_i   => std_ulogic(tcm_d_ack_i)
    );

  -- type conversion (as neorv32_top_stdlogic does it, timer interrupt included)
  wb_adr_o   <= std_logic_vector(wb_adr_u);
  wb_dat_i_u <= std_ulogic_vector(wb_dat_i);
  wb_dat_o   <= std_logic_vector(wb_dat_o_u);
  wb_we_o    <= std_logic(wb_we_u);
  wb_sel_o   <= std_logic_vector(wb_sel_u);
  wb_stb_o   <= std_logic(wb_stb_u);
  wb_cyc_o   <= std_logic(wb_cyc_u);
  wb_src_o   <= std_logic(wb_tag_u(2));                       -- pocket: test build 4
  gpio_o     <= std_logic_vector(gpio_o_u);
  gpio_i_u   <= std_ulogic_vector(gpio_i);
  tcm_re_o    <= std_logic(tcm_re_u);                         -- pocket: test build 4
  tcm_we_o    <= std_logic(tcm_we_u);
  tcm_ben_o   <= std_logic_vector(tcm_ben_u);
  tcm_addr_o  <= std_logic_vector(tcm_addr_u);
  tcm_wdata_o <= std_logic_vector(tcm_wdata_u);

end architecture;
