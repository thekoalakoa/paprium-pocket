
typedef struct{
	
	bit [15:0]dati;
	bit [23:0]addr;
	bit [1:0]we;
	bit oe;
	
}MemBus;


typedef struct{
	
	bit [31:0]dato;
	bit [31:0]addr;
	bit [3:0]we;
	bit oe;
	bit ce;
	bit clk;
	McuMap map;
	
}McuBus;

typedef struct{//mcu memory map
	
	bit wrom;
	bit wram;
	bit fpgio;
	bit ramdp;
	bit sdram;
	bit flash;
	bit bram;
	bit sfx;
	bit mdp;
	
	bit fpgio_ctrl;//var control flags
	bit fpgio_time;//timer
	bit fpgio_sptr;//sdram ptr 
	bit fpgio_vols;//sfx vol
	bit fpgio_volb;//bgm vol
	bit fpgio_wcnt;//delivered-word counter latch (diagnostic)
	
	bit mdp_ctrl;//md+ core control
	bit mdp_fifo;//link to everdrive mcu
	
}McuMap;


typedef struct{
	
	bit [15:0]dato;
	bit [23:0]addr;
	bit as;
	bit oe;
	bit we_hi;
	bit we_lo;
	bit ce_hi;
	bit ce_lo;
	bit tim;
	bit vclk;
	
	CpuMap map;
	
}CpuBus;


typedef struct{
	
	bit ramdp;
	bit sdram;
	bit flash;
	
}CpuMap;


typedef struct{

	bit clk;
	bit next_sample;
	bit [8:0]phase;
	
}SndCk;


typedef struct{

	bit [1:0]status;
	bit [7:0]pan[2];
	bit [10:0]vol;
	bit signed[15:0]pcm;
	
	// paprium: per-voice effect flags, from the 16-bit flags word the game writes
	// to 0x1E16. Our 8-bit `flags` is its HIGH byte, so 0x4000 -> bit 6 and
	// 0x0100 -> bit 0. GPGX applies both; this port previously applied neither.
	bit echo;   // 0x4000 - 166 ms delay at 33%, one side per voice
	bit amp;    // 0x0100 - x1.25 on the running mix
	
}SfxOut;

typedef struct{
	SfxOut sfx[8];
}SfxBank;