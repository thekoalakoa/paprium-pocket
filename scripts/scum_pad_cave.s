| Scum! pad cave, served at $11C560 when Arcade Mode or 6-Button is on.
| Reached by the `jmp $11C560.l` that replaces `unlk a6 ; rts` at the end of the
| game's pad read ($B2392). Registers at REGS (served by the core at $11C600):
|   +0  flags      bit 0 = Arcade Mode, bit 1 = the one-pad CPU MATE join (always 0 in 0.2.6)
|   +4  P1 held    {Mode,X,Y,Z} in bits 11..8 (the game's own 6-button layout)
|   +6  P2 held
|   +8  P1 just pressed (cleared by this read)
|   +10 P2 just pressed
| Uses d0 only, like the instructions it replaces end with.
| $11C560-$11C75F is not free space: it is the Hall of Fame name-entry bar's tile data, which
| the game copies with a VDP DMA, and the core substitutes DMA reads too, so the bar shows
| these words while the cave is served (the 0.2.6 known issue, docs/SCUM.md).
| Assemble: vasm -m68000 -Fbin, after converting the | comments and %register prefixes
| to vasm's syntax. scripts/scum_table.py carries the assembled words (PAD_CAVE_CODE).

        .equ    REGS, 0x11C600

        .text
PAD:    unlk    %a6                     | what the hook replaced
        move.w  REGS+4,%d0              | P1 held -> or into the game's pad words
        or.w    %d0,0xFF7028
        move.w  REGS+8,%d0              | P1 just pressed
        or.w    %d0,0xFF702A
        move.w  REGS+6,%d0              | P2 held
        or.w    %d0,0xFF7038
        move.w  REGS+10,%d0             | P2 just pressed
        or.w    %d0,0xFF703A
        | Arcade Mode: a Mode press is a coin (adroxe), via the game's own credit routine
        btst    #0,REGS+1
        beq.s   nocoin
        move.w  0xFF702A,%d0
        andi.w  #0x0800,%d0
        beq.s   nocoin
        jsr     0x0B5960
nocoin:
        | Flags bit 1 (a one-pad CPU MATE join, used while the partner ran on the 68000 during
        | development): with no CPU partner in the game yet, a P1 Mode press is also player
        | 2's Start; once the partner exists (object slot 2 in use) it stops. 0.2.6 holds bit 1
        | at 0, so this never runs: the partner joins on controller 2's Start, as on the cart
        btst    #1,REGS+1
        beq.s   done
        move.w  0xFF702A,%d0
        andi.w  #0x0800,%d0
        beq.s   done
        tst.w   0xFF8810
        bne.s   done
        ori.w   #0x0080,0xFF7038        | P2 Start held
        ori.w   #0x0080,0xFF703A        | P2 Start just pressed
done:   rts
