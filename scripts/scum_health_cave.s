| Scum! Infinite Health, served at $0BF000 (zero padding before the $0C0000 animation
| container). Reached by the `jsr $0BF000.l` that replaces `move.w $88(a2),d0 ;
| cmp.w d0,d3` at the damage-vs-health decision ($2FAC4). Zeroes the hit (d3) when the
| object is a player - object slots 1 .. [$FF9903]-1, objects at $FF8610 + $100*slot,
| the game's own player test - then redoes the two instructions, so the `bcs.w` after
| the jsr sees the same flags. Enemies are untouched.

        .text
HEALTH: move.l  %a2,%d0
        andi.l  #0x00FFFFFF,%d0
        subi.l  #0x00FF8710,%d0         | offset from object slot 1
        bcs.s   go                      | below slot 1: not a player
        lsr.l   #8,%d0
        addq.l  #1,%d0                  | slot
        cmpi.l  #0xFF,%d0
        bhi.s   go
        cmp.b   0xFF9903,%d0            | slot < player count?
        bcc.s   go
        moveq   #0,%d3                  | player: no damage
go:     move.w  0x88(%a2),%d0
        cmp.w   %d0,%d3
        rts
