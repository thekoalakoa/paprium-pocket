#!/usr/bin/env python3
# Copyright (C) 2026 Marsupial Solutions LLC
# SPDX-License-Identifier: GPL-3.0-or-later
"""check_fwstack_exact.py - the stack check's address-taken rule and indirect-jump reading on small programs.

    python -I -B tests/check_fwstack_exact.py

tools/fwstack.py counts a function's address as taken only where the code builds it as an address (the linker's
relocation records, main.rel.elf) and then stores it, passes it or a data word holds it; and it reads an indirect jump's
target only from its own register tracking, not from objdump's "# <address>" note. This test builds one small RV32
program with the firmware's own compiler and options, linked three times with its code at the three places the
firmware links code (the IROM at 0x0, the SRAM at 0x08000000, the WRAM code window at 0x80000000), and runs fwstack.py
on each. The program puts a function (coin_fn) exactly at base + 0x4000 and uses that number as plain integers: passed
as an argument, stored to a variable, held in a data word (the kind of value that used to be read as its address). It
also takes three other functions' addresses for real: one stored in a pointer variable and called through it, one
passed to a function that calls it, one in a table of pointers. And a switch jump through a4 follows a function whose
last instruction loads a4 with 0x04800000 (objdump's note then names 0x04800000 as the jump's target).
Each build must:
  1. pass with the config that covers the three real pointers' calls (exit 0);
  2. list ptr_fn, arg_fn, tab_fn as address-taken, and not coin_fn;
  3. list coin_fn among the values equal to a function's start that are not addresses (the argument, the store and
     the data word);
  4. fail naming each of ptr_fn, arg_fn, tab_fn when that one is treated as covered by nothing (--uncover);
  5. resolve the switch from its table (sw_fn's two cases reached, no target 0x04800000), and fail when sw_fn's switch
     entry is removed from the config.
The compiler is the firmware's (paths.local.json "riscv_bin"); without it the test prints SKIP and exits 0."""
import json, os, shutil, subprocess, sys, tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
T = os.path.join(ROOT, 'tools')

SRC = r'''
#include <stdint.h>
#define COIN (BASE + 0x4000u)               /* coin_fn's start: the linker script puts it there */
typedef void (*fnp)(void);
void sink(uint32_t v);
void call_through(fnp f);
void ptr_fn(void);
void arg_fn(void);
void tab_fn(void);
void sw_fn(uint32_t k);
void prev_fn(void);
volatile uint32_t gword;
volatile uint32_t gsel;
fnp volatile fp;
const uint32_t len_tab[2] = { COIN, 7u };   /* a data word equal to coin_fn's start: an integer */
fnp const tab[2] = { tab_fn, tab_fn };     /* data words that are addresses */
__attribute__((noinline, section(".text.sink"))) void sink(uint32_t v) { gword = v ^ 1u; }
__attribute__((noinline, section(".text.call_through"))) void call_through(fnp f) { f(); gword = 9u; }   /* (no tail jump) */
__attribute__((noinline, section(".text.coin_fn"))) void coin_fn(void) { gword = 3u; }
__attribute__((noinline, section(".text.ptr_fn"))) void ptr_fn(void) { gword = 4u; }
__attribute__((noinline, section(".text.arg_fn"))) void arg_fn(void) { gword = 5u; }
__attribute__((noinline, section(".text.tab_fn"))) void tab_fn(void) { gword = 6u; }
__attribute__((noinline, section(".text.main_fn"))) void main_fn(void)
{
    sink(COIN);                             /* an integer argument equal to coin_fn's start */
    gword = COIN;                           /* an integer stored */
    sink(len_tab[gsel & 1u]);               /* the data word read */
    fp = ptr_fn;                            /* a pointer stored ... */
    fp();                                   /* ... and called through */
    call_through(arg_fn);                   /* a pointer passed */
    tab[gsel & 1u]();                       /* a pointer from a table */
    prev_fn();
    sw_fn(gsel & 1u);
    coin_fn();
}
__attribute__((naked, section(".text.prev_fn"))) void prev_fn(void)
{
    __asm__ volatile("lui a4, 0x4800\n\tret\n");
}
__attribute__((naked, section(".text.sw_fn"))) void sw_fn(uint32_t k)
{
    __asm__ volatile(
        "lui t1, %hi(sw_tab)\n\taddi t1, t1, %lo(sw_tab)\n\tslli t0, a0, 2\n\tadd t0, t1, t0\n\tlw a4, 0(t0)\n"
        "\tjr a4\n"
        "1:\tret\n"
        "2:\tret\n"
        "\t.pushsection .rodata.sw_tab, \"a\"\n\t.balign 4\nsw_tab:\t.word 1b, 2b\n\t.popsection\n");
}
__attribute__((naked, section(".text._start"))) void _start(void)
{
    __asm__ volatile("lui sp, %hi(stack_top)\n\taddi sp, sp, %lo(stack_top)\n\tcall main_fn\n1:\tj 1b\n");
}
'''

LD = '''ENTRY(_start)
SECTIONS
{
  . = %(base)#x;
  .text : { KEEP(*(.text._start)) *(.text.main_fn) *(.text.sink) *(.text.call_through) *(.text.prev_fn) *(.text.sw_fn) }
  .tgt %(coin)#x : { *(.text.coin_fn) *(.text.ptr_fn) *(.text.arg_fn) *(.text.tab_fn) }
  .rodata : { *(.rodata*) *(.srodata*) }
  .data : { *(.data*) *(.sdata*) }
  .bss : { *(.bss*) *(.sbss*) *(COMMON) }
  . = ALIGN(16) + 0x400;
  stack_top = .;
}
'''

CFG = {
    'indirect': {
        'main_fn': {'targets': ['ptr_fn', 'tab_fn'], 'basis': 'fp() and tab[]()'},
        'call_through': {'targets': ['arg_fn'], 'basis': 'f()'},
        'sw_fn': {'targets': [], 'switch': True, 'basis': 'the jump table sw_tab'},
    },
    'sp_init': ['_start'],
    'schemes': {'t': {'gate': True, 'what': 'one thread level', 'levels': [{'name': 'thread', 'entries': ['_start']}]}},
}

BASES = ((0x00000000, 'IROM'), (0x08000000, 'SRAM'), (0x80000000, 'WRAM code window'))


def main():
    loc = {}
    try:
        loc = json.load(open(os.path.join(ROOT, 'paths.local.json')))
    except OSError:
        pass
    bindir = loc.get('riscv_bin')
    man = json.load(open(os.path.join(ROOT, 'fwbuild.json')))
    pc = man['pocket']
    gcc = os.path.join(bindir or '', pc['prefix'] + 'gcc' + ('.exe' if os.name == 'nt' else ''))
    if not bindir or not os.path.exists(gcc):
        print('SKIP: no RV32 compiler (paths.local.json riscv_bin)')
        return 0
    objdump = os.path.join(bindir, pc['prefix'] + 'objdump' + ('.exe' if os.name == 'nt' else ''))
    opts = [o for o in pc['cc_opts'] if o.startswith(('-march', '-mabi', '-O', '-f'))]
    tmp = tempfile.mkdtemp(prefix='fwsx_')
    ok = True

    def res(name, good, info=''):
        nonlocal ok
        ok &= bool(good)
        print('%-4s %s%s' % ('PASS' if good else 'FAIL', name, ('  | ' + info) if info and not good else ''))

    try:
        for base, where in BASES:
            d = os.path.join(tmp, '%08x' % base)
            os.makedirs(d)
            src = os.path.join(d, 'p.c')
            open(src, 'w').write(SRC)
            ld = os.path.join(d, 'p.ld')
            open(ld, 'w').write(LD % dict(base=base, coin=base + 0x4000))
            obj = os.path.join(d, 'p.o')
            r = subprocess.run([gcc, '-c'] + opts + ['-DBASE=%#xu' % base, src, '-o', obj], capture_output=True, text=True)
            if r.returncode:
                res('%s: compile' % where, False, r.stderr[-300:])
                continue
            link = [gcc] + opts + ['-nostdlib', '-nostartfiles', '-Wl,--no-warn-rwx-segments', '-T', ld, obj]
            r1 = subprocess.run(link + ['-o', os.path.join(d, 'main.elf')], capture_output=True, text=True)
            r2 = subprocess.run(link + ['-o', os.path.join(d, 'main.rel.elf'), '-Wl,--emit-relocs'], capture_output=True,
                                text=True)
            if r1.returncode or r2.returncode:
                res('%s: link' % where, False, (r1.stderr + r2.stderr)[-300:])
                continue
            dis = subprocess.run([objdump, '-d', os.path.join(d, 'main.elf')], capture_output=True, text=True).stdout
            open(os.path.join(d, 'main.dis'), 'w', newline='\n').write(dis)
            note = any('jr\ta4 # 4800000' in ln for ln in dis.splitlines())
            res('%s (%#x): objdump notes the switch jump as 0x04800000 (the case this test exists for)' % (where, base), note)
            lay = os.path.join(d, 'lay.json')
            json.dump({'regions': [{'name': 'stack', 'lo': '%#x' % (base + 0x8000), 'hi': '%#x' % (base + 0x9000),
                                    'kind': 'stack'}]}, open(lay, 'w'))

            def fws(cfg, extra=()):
                cp = os.path.join(d, 'cfg.json')
                json.dump(cfg, open(cp, 'w'))
                jp = os.path.join(d, 'out.json')
                r = subprocess.run([sys.executable, '-I', '-B', os.path.join(T, 'fwstack.py'), d, '--config', cp,
                                    '--layout', lay, '--json', jp] + list(extra), capture_output=True, text=True)
                return r.returncode, r.stdout, json.load(open(jp))

            rc, out, o = fws(CFG)
            res('%s: the program passes with its calls covered' % where, rc == 0, (o['errors'] or [''])[0])
            at, eq = o['address_taken'], o['equal_not_address']
            res('%s: ptr_fn, arg_fn, tab_fn are address-taken' % where, all(n in at for n in ('ptr_fn', 'arg_fn', 'tab_fn')),
                str(sorted(at)))
            res('%s: coin_fn (its start used only as integers) is not address-taken' % where, 'coin_fn' not in at, str(at.get('coin_fn')))
            w = eq.get('coin_fn', [])
            res('%s: coin_fn listed as equal, not an address, at the argument, the store and the data word' % where,
                len([x for x in w if x.startswith('main_fn ')]) >= 2 and any(x.startswith('data .rodata') for x in w), str(w))
            for n in ('ptr_fn', 'arg_fn', 'tab_fn'):
                rc, out, o2 = fws(CFG, ['--uncover', n])
                res('%s: %s treated as covered by nothing fails naming it' % (where, n), rc != 0 and any(
                    ('address taken but not covered by any indirect-call target set: %s ' % n) in e for e in o2['errors']),
                    str(o2['errors'][:2]))
            reached = set(o['frames'])
            unknown = [e for e in o['errors'] if '0x4800000' in e]
            res('%s: the switch read from its table (sw_fn reached, nothing at 0x04800000)' % where,
                'sw_fn' in reached and not unknown, str(o['errors'][:2]))
            c2 = json.loads(json.dumps(CFG))
            c2['indirect']['sw_fn'].pop('switch')
            rc, out, o3 = fws(c2)
            res('%s: the switch entry removed from the config fails' % where, rc != 0 and any(
                'indirect jump not resolved' in e for e in o3['errors']), str(o3['errors'][:2]))
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    print('ALL PASS' if ok else 'SOME FAIL')
    return 0 if ok else 1


if __name__ == '__main__':
    sys.exit(main())
