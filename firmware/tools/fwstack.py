#!/usr/bin/env python3
# Copyright (C) 2026 Marsupial Solutions LLC
# SPDX-License-Identifier: GPL-3.0-or-later
"""fwstack.py - static stack bound of a linked firmware, per interrupt level and per nesting chain.

    python -I -B tools/fwstack.py <build dir> [--config tools/stack.json] [--layout board/pocket/link/<l>.json]
                                  [--txt out.txt] [--json out.json]

<build dir> = build/pocket/<layout>/<variant> (needs main.elf and main.dis, which tools/fwbuild.py writes). Exit 1 when
the worst chain of the checked scheme (the one the config marks "gate": true) is over the stack region, or when the
analysis cannot bound something reachable.

How (all from the linked image, so library code, assembly and the brain glue are in it):
- Functions are the labels of `objdump -d`. Each one is walked as a control-flow graph (branches, jumps, switch
  tables) with three things tracked per instruction: the stack-pointer offset from entry, whether mstatus.MIE may
  be 1, and simple register constants (li/lui/auipc/addi/mv, so far calls, `add sp,sp,t0` frames and `csrs
  mstatus,a5` resolve). Where paths merge, the deeper offset and "MIE may be 1" win.
- frame(f) = the deepest offset inside f. D(f) = the deepest the stack gets while f runs: every call adds the callee's
  D at the call's own offset; tail jumps and fall-throughs continue at theirs.
- P(f) = the deepest point at which an interrupt can be TAKEN while f runs (MIE = 1 there), entered with MIE = 0:
  points with MIE = 1, plus calls made with MIE = 1 (the callee's whole D counts), plus P of calls made with MIE = 0.
  MIE windows are therefore found from the code, not listed by hand.
- Indirect calls must be resolved in the config (a list of targets, a regex over function names, or an opaque
  function with a measured depth, such as the brain); an unresolved one fails the check. Functions whose address is
  taken must be accounted for (an indirect target, a level entry, or listed with a reason), so a new handler table
  cannot slip past the bound. A function's address counts as taken only where the code builds it as an address and
  then stores it, passes it as an argument or writes it to a CSR (mtvec), or where a data word holds it: the linker's
  own relocation records say which instructions and words those are (main.rel.elf, the same link as main.elf with
  --emit-relocs, which tools/fwbuild.py writes beside it; its loaded bytes must equal main.elf's). A plain integer that
  happens to equal a function's start (a length, a count, a flag word) is not an address and does not count; the report
  lists such values apart ("equal_not_address"). Every call site's relocation must name the call's own target, or the
  check fails (the records do not belong to this code).
- Register values come from the code itself (the constant tracking above, and the linker's records for a value it
  formed): an indirect jump or call through a register whose value the walk does not know is unresolved, even where
  objdump's "# <address>" note beside it names a target (that note follows objdump's own last load of the register
  in address order, which may lie in another function).
- A level = a trap stub (its own frame, measured from its prologue) + the handlers it calls for that cause.
  D(level) = frame(stub) + max D(handler).
  P(level) = frame(stub) + max P(handler), or D when the config says the level runs with interrupts open ("open": true).
  The thread level has no stub; its entry is the reset entry.
- A nesting chain is thread -> L1 -> ... -> Lk, each level able to preempt the previous one (config "preempts").
  Its worst = P(thread) + P(L1) + ... + D(Lk). Every possible chain is listed; the worst is the bound.
- Levels that are not written yet use a proxy (today's functions that will run there, measured here, with
  exclusions) plus estimated bytes from the config; the report labels every number "MEASURED", "PROXY" or "MODELLED".
- Functions that exist but stand for code not written yet (the weak default hooks of the new firmware's skeleton,
  built with FW_S1) are listed in
  the config's "stand_in": a call to one counts at least the listed opaque depths (path shown as 'name~ -> @opaque').
- "stack_reset": functions that start again on a fresh stack (the reset entry, which crt0 points sp at the top): a
  call or jump to one adds nothing to its caller's path (a firmware restart is not a nested call).
- "constants_not_code": [{"in": function, "value": constant, "why": ...}]: a register constant that function builds
  is data (e.g. a job-slot halfword) even when it equals a function's start in this layout; not an address taken.

Caveats: the bound assumes every path in the graph is feasible (it is an upper bound, not a run); recursion fails the
check (none today); an `andi sp,sp,-N` alignment is taken as costing nothing (crt0's -4 on an aligned top)."""
import argparse, json, os, re, sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, HERE)
import fwelf   # noqa: E402

LAB = re.compile(r'^([0-9a-f]+) <(.+)>:$')
INS = re.compile(r'^\s*([0-9a-f]+):\t([0-9a-f]+)\s*\t(\S+)(?:\t(.*))?$')
TGT = re.compile(r'^([0-9a-f]+) <([^>]+)>$')
MEM = re.compile(r'^(-?\d+)\((\w+)\)$')
BR = {'beq', 'bne', 'blt', 'bge', 'bltu', 'bgeu', 'beqz', 'bnez', 'blez', 'bgez', 'bltz', 'bgtz', 'bgt', 'ble', 'bgtu', 'bleu'}
NOWRITE = BR | {'sb', 'sh', 'sw', 'j', 'jr', 'ret', 'csrw', 'csrs', 'csrc', 'csrwi', 'csrsi', 'csrci', 'fence', 'fence.i',
                'fence.tso', 'ecall', 'ebreak', 'mret', 'wfi', 'nop', 'unimp', 'pause'}
CALLER_SAVED = {'ra', 't0', 't1', 't2', 't3', 't4', 't5', 't6', 'a0', 'a1', 'a2', 'a3', 'a4', 'a5', 'a6', 'a7'}
MST_MIE = 8
NEG = -(1 << 60)
M32 = 0xFFFFFFFF
# RISC-V relocation types (the psABI numbers) the address-taken check reads from main.rel.elf
RT_32, RT_JAL, RT_CALL, RT_CALL_PLT = 1, 17, 18, 19
RT_PCREL_HI20, RT_PCREL_LO12_I, RT_HI20, RT_LO12_I = 23, 24, 26, 27
RT_GPREL_I = (47, 68)          # the low part of an address made relative to gp by the linker's relaxation (the old
                               # psABI number and the one GNU ld 2.45 writes)


def merge_regs(a, b):
    """the register values two paths agree on; a value one path built as an address stays one"""
    db = dict(b)
    out = []
    for k, v in a:
        w = db.get(k)
        if w is None:
            continue
        if v == w:
            out.append((k, v))
        elif v[0] == 'c' and w[0] == 'c' and v[1] == w[1]:
            out.append((k, ('c', v[1], bool(v[2] or w[2]))))
    return tuple(out)


def s32(v):
    v &= 0xFFFFFFFF
    return v - (1 << 32) if v & 0x80000000 else v


def parse_dis(path):
    blocks = []
    cur = None
    for ln in open(path, encoding='utf-8', errors='replace'):
        ln = ln.rstrip('\r\n')
        m = LAB.match(ln)
        if m:
            cur = dict(name=m.group(2), addr=int(m.group(1), 16), ins=[])
            blocks.append(cur)
            continue
        m = INS.match(ln)
        if not (m and cur is not None):
            continue
        ops, cmt = (m.group(4) or ''), None
        if ' # ' in ops:
            ops, c = ops.split(' # ', 1)
            mt = TGT.match(c.strip())
            cmt = int(mt.group(1), 16) if mt else None
        ops = ops.strip()
        cur['ins'].append(dict(addr=int(m.group(1), 16), mn=m.group(3), ops=[o for o in ops.split(',')] if ops else [],
                               cmt=cmt, size=len(m.group(2)) // 2))
    for b in blocks:
        b['end'] = b['ins'][-1]['addr'] + b['ins'][-1]['size'] if b['ins'] else b['addr']
    return blocks


def tgt_of(op):
    m = TGT.match(op.strip())
    return int(m.group(1), 16) if m else None


class Fn:
    def __init__(self, b):
        self.name, self.addr, self.end, self.ins = b['name'], b['addr'], b['end'], b['ins']
        self.idx = {i['addr']: k for k, i in enumerate(self.ins)}
        self.frame = 0
        self.mie_depth = NEG
        self.events = []          # (kind, addr, off, mie, target)  kind: call tail fall icall
        self.exit_mie = False
        self.errors = []
        self.notes = []
        self.taken = set()        # addresses of functions whose address this function materialises
        self.equal = set()        # (site, value): a stored / passed integer equal to a function's start, not an address
        self.static_calls = set()


class Analyzer:
    def __init__(self, elf, dis, cfg, rel_elf=None):
        self.cfg = cfg
        # functions that restart on a fresh stack (crt0 loads sp from its top): a call or jump to one adds no depth to
        # its caller's path (the firmware restart brd_full_reset -> _start); their own depth counts where they are an
        # entry (the thread level)
        self.resets = frozenset(cfg.get('stack_reset', []))
        self._elf = elf
        self.stack_guard = []
        self.blocks = parse_dis(dis)
        self.syms = fwelf.symbols(elf)
        self.secs = fwelf.sections(elf)
        self.dsec = [s for s in self.secs if s['alloc'] and not s['nobits'] and not s['exec']]
        self.skip = [(int(a, 0), int(b, 0), w) for a, b, w in cfg.get('skip_ranges', [])]
        self.fns = {}
        self.by_addr = {}
        for b in self.blocks:
            if any(lo <= b['addr'] < hi for lo, hi, _ in self.skip) or not b['ins']:
                continue
            f = Fn(b)
            self.fns[f.name] = f
            self.by_addr.setdefault(f.addr, f)
        self.order = sorted(self.fns.values(), key=lambda f: f.addr)
        self.next_of = {}
        for a, b in zip(self.order, self.order[1:]):
            if a.end == b.addr:
                self.next_of[a.name] = b
        # address-taken candidates: C functions and GLOBAL asm labels (local asm labels are internal: crt0's steps)
        cand = {s['name'] for s in self.syms if s['type'] == 'FUNC' or (s['type'] == 'NOTYPE' and s['bind'] == 'GLOBAL')}
        self.func_starts = {f.addr: f.name for f in self.order if f.name in cand}
        self.ind = cfg.get('indirect', {})
        self.opaque = cfg.get('opaque', {})
        self.stand_in = cfg.get('stand_in', {})
        self.analysed = set()
        self.memo_d, self.memo_p = {}, {}
        self.errors = []
        self.rel_elf = rel_elf or os.path.join(os.path.dirname(os.path.abspath(elf)), 'main.rel.elf')
        self.load_relocs(elf)

    def load_relocs(self, elf):
        """the linker's relocation records: self.form = {instruction address: the addresses it builds} (lui / auipc with
        the high part, addi with the low part, gp-relative or not), self.dptr = {data word address: the address it holds},
        self.calls = {call site: its targets}"""
        self.form, self.dptr, self.calls = {}, {}, {}
        if not os.path.exists(self.rel_elf):
            self.errors.append('no %s beside main.elf (tools/fwbuild.py writes it): the address-taken check needs the '
                               'linker\'s relocation records' % os.path.basename(self.rel_elf))
            return
        a = {s['name']: s for s in fwelf.sections(elf) if s['alloc'] and s['size']}     # (an empty section holds no byte)
        b = {s['name']: s for s in fwelf.sections(self.rel_elf) if s['alloc'] and s['size']}
        diff = sorted(n for n, s in a.items() if n not in b or (s['addr'], s['size'], s['nobits']) !=
                      (b[n]['addr'], b[n]['size'], b[n]['nobits']) or (not s['nobits'] and s['size'] and
                      fwelf.load_bytes(elf, s['addr'], s['size']) != fwelf.load_bytes(self.rel_elf, s['addr'], s['size'])))
        if diff or set(b) - set(a):
            self.errors.append('%s is not the same link as main.elf (sections differ: %s)' % (
                os.path.basename(self.rel_elf), ', '.join(diff + sorted(set(b) - set(a)))[:200]))
            return
        recs = fwelf.relocations(self.rel_elf)
        hi = {r['off']: (r['value'] + r['addend']) & M32 for r in recs if r['type'] == RT_PCREL_HI20}
        for r in recs:
            t, ty = (r['value'] + r['addend']) & M32, r['type']
            if ty == RT_PCREL_LO12_I:
                t = hi.get(t)                      # its symbol is the auipc: the address is that auipc's HI20 target
                if t is None:
                    continue
            if ty in (RT_HI20, RT_PCREL_HI20, RT_LO12_I, RT_PCREL_LO12_I) or ty in RT_GPREL_I:
                self.form.setdefault(r['off'], set()).add(t)
            elif ty == RT_32:
                self.dptr[r['off']] = t
            elif ty in (RT_JAL, RT_CALL, RT_CALL_PLT):
                self.calls.setdefault(r['off'], set()).add(t)
        # the records must describe this code: every direct call to another function carries its own target
        bad = []
        ncall = 0
        for f in self.order:
            for i in f.ins:
                if i['mn'] != 'jal' or not i['ops']:
                    continue
                t = tgt_of(i['ops'][-1])
                if t is None or f.addr <= t < f.end:
                    continue
                ncall += 1
                if t not in self.calls.get(i['addr'], ()):
                    bad.append('%#x' % i['addr'])
        self.n_calls_checked = ncall
        if bad:
            self.errors.append('the relocation records do not match the code at %d of %d calls (%s)' % (
                len(bad), ncall, ', '.join(bad[:6])))

    def formed(self, a, v=None):
        """the address instruction a builds (from its relocation): when v is given, only if it equals v"""
        t = self.form.get(a)
        if not t or len(t) != 1:
            return None
        t = next(iter(t))
        return t if v is None or t == (v & M32) else None

    def fn_at(self, a):
        """function containing address a (skip ranges -> None)"""
        f = self.by_addr.get(a)
        if f:
            return f
        for f in self.order:
            if f.addr <= a < f.end:
                return f
        return None

    def ind_targets(self, f, kind):
        """resolved targets of f's indirect calls: list of function names and/or '@opaque' names"""
        c = self.ind.get(f.name)
        if c is None:
            return None
        out = []
        for t in c.get('targets', []):
            if t.startswith('re:'):
                rx = re.compile(t[3:])
                out += sorted(n for n in self.fns if rx.search(n))
            else:
                out.append(t)
        return out

    # ---------------------------------------------------------------------------------------- per-function walk
    def walk(self, f):
        """fixpoint over f's instructions: state = (off, mie, regs)"""
        if f.name in self.analysed:
            return
        self.analysed.add(f.name)
        cfgf = self.ind.get(f.name, {})
        reset_ok = f.name in self.cfg.get('sp_init', [])
        restore_ok = f.name in self.cfg.get('sp_restore', {})
        # pre-pass: direct callees first (so their exit MIE is known)
        for i in f.ins:
            t = None
            if i['mn'] in ('jal', 'call') or (i['mn'] == 'jalr' and (len(i['ops']) == 1 or i['ops'][0] == 'ra')):
                t = i['cmt'] if i['cmt'] is not None else (tgt_of(i['ops'][-1]) if i['ops'] else None)
            if t is not None:
                g = self.fn_at(t)
                if g and g is not f:
                    f.static_calls.add(g.name)
        for n in sorted(f.static_calls):
            g = self.fns[n]
            if g.name not in self.analysed:
                self.stack_guard.append(g.name)
                if len(self.stack_guard) > 400:
                    f.errors.append('call graph too deep (recursion?)')
                    return
                self.walk(g)
                self.stack_guard.pop()
        for t in (self.ind_targets(f, 'icall') or []):
            if t in self.fns:
                self.walk(self.fns[t])
        st = {}
        cnt = {}
        work = [(f.ins[0]['addr'], (0, False, ()))]
        while work:
            a, s = work.pop()
            o = st.get(a)
            if o is not None:
                m = (min(o[0], s[0]), o[1] or s[1], merge_regs(o[2], s[2]))
                if m == o:
                    continue
                s = m
            cnt[a] = cnt.get(a, 0) + 1
            if cnt[a] > 64 or s[0] < -(1 << 20):
                f.errors.append('stack pointer does not settle at %#x (a frame that grows in a loop?)' % a)
                return
            st[a] = s
            s2, succ, _ = self.step(f, f.ins[f.idx[a]], s, reset_ok, restore_ok, cfgf, final=False)
            for b in succ:
                if b in f.idx:
                    work.append((b, s2))
        # final pass: events, frame, MIE points from the settled states
        for i in f.ins:
            s = st.get(i['addr'])
            if s is None:
                continue
            f.frame = max(f.frame, -s[0])
            if s[1]:
                f.mie_depth = max(f.mie_depth, -s[0])
            s2, _, ev = self.step(f, i, s, reset_ok, restore_ok, cfgf, final=True)
            f.frame = max(f.frame, -s2[0])
            f.events += ev
        if not st:
            f.errors.append('no reachable instruction')

    def step(self, f, i, s, reset_ok, restore_ok, cfgf, final):
        off, mie, regs = s
        R = dict(regs)
        mn, ops, a = i['mn'], i['ops'], i['addr']
        nxt = a + i['size']
        ev, succ = [], [nxt]

        def const(r):
            if r == 'zero':
                return 0                                  # x0 (e.g. a relaxed absolute call: jalr 1196(zero))
            v = R.get(r)
            return v[1] if v and v[0] == 'c' else None

        def err(msg):
            if final:
                f.errors.append('%#x %s %s: %s' % (a, mn, ','.join(ops), msg))

        def note_taken(r):
            """register r is stored / passed / written to a CSR: a function's address there is taken only when the
            code built it as an address (a relocation formed it); an equal plain integer is listed apart"""
            v = R.get(r)
            if not final or not v or v[0] != 'c' or (v[1] & M32) not in self.func_starts or (v[1] & M32) == 0:
                return
            if v[2]:
                f.taken.add(v[1] & M32)
            else:
                f.equal.add((a, v[1] & M32))

        # ---- control flow
        if mn in BR:
            t = tgt_of(ops[-1])
            succ = [nxt, t] if t is not None else [nxt]
            if t is not None and not (f.addr <= t < f.end):
                succ = [nxt]
                ev.append(('tail', a, off, mie, t))
            return (off, mie, regs), succ, ev
        if mn == 'j' or (mn == 'jal' and len(ops) == 2 and ops[0] == 'zero'):
            t = tgt_of(ops[-1])
            if f.addr <= t < f.end:
                return (off, mie, regs), [t], ev
            ev.append(('tail', a, off, mie, t))
            return (off, mie, regs), [], ev
        if mn in ('jal', 'call') or (mn == 'jalr' and (len(ops) == 1 or ops[0] != 'zero')):
            if mn in ('jal', 'call'):
                t = tgt_of(ops[-1])
            else:
                spec = ops[-1]
                mm = MEM.match(spec)              # the walk's own value of the register, not objdump's note
                base, imm = (mm.group(2), int(mm.group(1))) if mm else (spec, 0)
                c = const(base)
                t = (c + imm) & 0xFFFFFFFF if c is not None else None
            if t is None or (f.addr <= t < f.end and t != f.addr):
                if t is not None or (cfgf.get('self')):
                    pass                                   # an internal computed call (newlib memset's store table)
                else:
                    ev.append(('icall', a, off, mie, None))
            else:
                ev.append(('call', a, off, mie, t))
            # after a call: caller-saved registers are gone; MIE may come back set
            exit_mie = False
            if t is not None and not (f.addr <= t < f.end):
                g = self.fn_at(t)
                exit_mie = bool(g and g.exit_mie)
            elif t is None:
                tg = self.ind_targets(f, 'icall') or []
                exit_mie = any(self.fns[x].exit_mie for x in tg if x in self.fns)
            for r in ('a0', 'a1', 'a2', 'a3', 'a4', 'a5', 'a6', 'a7'):
                note_taken(r)                             # a function address passed as an argument
            R2 = tuple((k, v) for k, v in regs if k not in CALLER_SAVED)
            return (off, mie or exit_mie, R2), [nxt], ev
        if mn in ('jr', 'ret') or (mn == 'jalr' and ops and ops[0] == 'zero'):
            if mn == 'ret' or (ops and ops[-1] in ('ra', '0(ra)')):
                if final:
                    f.exit_mie = f.exit_mie or mie
                return (off, mie, regs), [], ev
            spec = ops[-1]
            mm = MEM.match(spec)                  # the walk's own value of the register, not objdump's note
            base, imm = (mm.group(2), int(mm.group(1))) if mm else (spec, 0)
            c = const(base)
            t = (c + imm) & 0xFFFFFFFF if c is not None else None
            if t is not None and not (f.addr <= t < f.end):
                ev.append(('tail', a, off, mie, t))
                return (off, mie, regs), [], ev
            if t is not None:
                return (off, mie, regs), [t], ev
            if cfgf.get('switch'):
                # a switch table: a register still holds the table's address (in a data section); its words that
                # point into this function are the cases
                cases = set()
                for _, v in regs:
                    if v[0] != 'c':
                        continue
                    for s in self.dsec:
                        if s['addr'] <= v[1] < s['addr'] + s['size']:
                            k = v[1]
                            while k + 4 <= s['addr'] + s['size']:
                                w = int.from_bytes(fwelf.load_bytes(self._elf, k, 4), 'little')
                                if not (f.addr <= w < f.end):
                                    break
                                cases.add(w)
                                k += 4
                if cases:
                    return (off, mie, regs), sorted(cases), ev
                err('switch table not found (no register holds a data address whose words point into %s)' % f.name)
                return (off, mie, regs), [], ev
            if cfgf.get('self'):
                return (off, mie, regs), [], ev
            err('indirect jump not resolved (add "switch": true or targets for %s in the stack config)' % f.name)
            return (off, mie, regs), [], ev
        if mn == 'mret':
            if final:
                f.exit_mie = True
            return (off, mie, regs), [], ev
        if mn in ('unimp',) or mn.startswith('.') or mn.startswith('0x'):
            err('not an instruction on a reachable path')
            return (off, mie, regs), [], ev

        # ---- function addresses used as pointers: stored, or written to a CSR (mtvec)
        if mn == 'sw':
            note_taken(ops[0])
        if mn in ('csrw', 'csrrw') and len(ops) >= 2:
            note_taken(ops[-1])
        # ---- CSR: mstatus.MIE
        if mn.startswith('csr'):
            csr = None
            val = None
            if mn in ('csrs', 'csrc', 'csrw'):
                csr, src = ops[0], ops[1]
                val = const(src)
            elif mn in ('csrsi', 'csrci', 'csrwi'):
                csr, val = ops[0], int(ops[1], 0)
            elif mn in ('csrrs', 'csrrc', 'csrrw'):
                csr, val = ops[1], const(ops[2])
            elif mn in ('csrrsi', 'csrrci', 'csrrwi'):
                csr, val = ops[1], int(ops[2], 0)
            if csr == 'mstatus':
                kind = mn.replace('csrr', 'csr').rstrip('i')
                if kind == 'csrs':
                    mie = mie or (val is None) or bool(val & MST_MIE)
                elif kind == 'csrc':
                    if val is not None and val & MST_MIE:
                        mie = False
                elif kind == 'csrw':
                    mie = True if val is None else bool(val & MST_MIE)

        # ---- writes to registers
        rd = ops[0] if ops and mn not in NOWRITE else None
        if mn.startswith('csr') and mn in ('csrs', 'csrc', 'csrw', 'csrsi', 'csrci', 'csrwi'):
            rd = None
        if rd == 'sp':
            if mn == 'addi' and ops[1] == 'sp':
                off += int(ops[2], 0)
            elif mn in ('add', 'sub') and 'sp' in ops[1:]:
                other = ops[2] if ops[1] == 'sp' else ops[1]
                c = const(other)
                if c is None:
                    err('stack pointer moved by an unknown amount (alloca / VLA?)')
                    off -= 1 << 16
                else:
                    off = off + s32(c) if mn == 'add' else off - s32(c)
            elif mn == 'andi' and ops[1] == 'sp':
                pass                                        # alignment of an aligned pointer: no bytes
            elif mn in ('mv', 'addi') and R.get(ops[1], ('?',))[0] == 's':
                off = R[ops[1]][1] + (int(ops[2], 0) if mn == 'addi' else 0)
            elif (mn in ('lui', 'li', 'auipc') or (mn == 'addi' and const(ops[1]) is not None)) and reset_ok:
                off = 0                                     # the stack pointer is initialised here (reset entry)
            elif restore_ok:
                off = 0                                     # unwinds to a frame saved earlier (config sp_restore)
            else:
                err('stack pointer written with an unknown value')
            R.pop('sp', None)
        elif rd:
            v = None
            if mn == 'li':
                t = self.formed(a)                # a relaxed %lo: the linker formed an address here
                v = ('c', t, True) if t is not None else ('c', int(ops[1], 0) & 0xFFFFFFFF, False)
            elif mn == 'lui':
                c = (int(ops[1], 0) << 12) & 0xFFFFFFFF
                v = ('c', c, self.formed(a, c) is not None)
            elif mn == 'auipc':
                c = (a + (int(ops[1], 0) << 12)) & 0xFFFFFFFF
                v = ('c', c, self.formed(a, c) is not None)
            elif mn == 'addi':
                src, imm = ops[1], int(ops[2], 0)
                t = self.formed(a)
                if src == 'sp':
                    v = ('s', off + imm)
                elif R.get(src, ('?',))[0] == 's':
                    v = ('s', R[src][1] + imm)
                elif t is not None:
                    v = ('c', t, True)            # %lo (or gp-relative) of an address: the linker's own value
                elif const(src) is not None:
                    v = ('c', (const(src) + imm) & 0xFFFFFFFF, False)
            elif mn == 'mv':
                t = self.formed(a)
                if ops[1] == 'sp':
                    v = ('s', off)
                elif t is not None:
                    v = ('c', t, True)
                else:
                    v = R.get(ops[1])
            if v is None:
                R.pop(rd, None)
            else:
                R[rd] = v
        return (off, mie, tuple(sorted(R.items()))), succ, ev

    # ------------------------------------------------------------------------------------------- depths
    def target_name(self, t):
        g = self.fn_at(t) if isinstance(t, int) else None
        return g.name if g else None

    def callee_list(self, f, e):
        kind, a, off, mie, t = e
        if kind == 'icall':
            tg = self.ind_targets(f, 'icall')
            if tg is None:
                return None
            return tg
        n = self.target_name(t)
        if n is None:
            for lo, hi, w in self.skip:
                if lo <= t < hi:
                    return ['@skip:' + w]
            return ['@unknown:%#x' % t]
        return [n]

    def D(self, name, excl=frozenset(), stack=()):
        key = (name, excl)
        if key in self.memo_d:
            return self.memo_d[key]
        if name.startswith('@'):
            o = self.opaque.get(name)
            if o is None:
                self.errors.append('no depth for %s' % name)
                return (0, [name + '(?)'])
            return (o['bytes'], [name])
        if name in stack:
            self.errors.append('recursion: ' + ' -> '.join(stack + (name,)))
            return (0, [name + '(rec)'])
        f = self.fns[name]
        self.walk(f)
        best = (f.frame, [name])
        for e in f.events:
            cl = self.callee_list(f, e)
            if cl is None:
                self.errors.append('%s: indirect call at %#x not resolved (add "%s" to the stack config "indirect")' % (name, e[1], name))
                continue
            for c in cl:
                if c in excl or c in self.resets:
                    continue
                d, p = self.D(c, excl, stack + (name,))
                tot = -e[2] + d
                if tot > best[0]:
                    best = (tot, [name + ('@%d' % -e[2] if e[2] else '')] + p)
        for o in self.stand_in.get(name, []):          # a body not written yet: at least its stand-in depth
            d, p = self.D(o, excl, stack + (name,))
            if d > best[0]:
                best = (d, [name + '~'] + p)
        self.memo_d[key] = best
        return best

    def P(self, name, excl=frozenset(), stack=()):
        key = (name, excl)
        if key in self.memo_p:
            return self.memo_p[key]
        if name.startswith('@'):
            o = self.opaque.get(name, {})
            return (o['bytes'], [name]) if o.get('mie_open') else (NEG, [])
        if name in stack:
            return (NEG, [])
        f = self.fns[name]
        self.walk(f)
        best = (f.mie_depth, [name + '[MIE]']) if f.mie_depth > NEG else (NEG, [])
        for o in self.stand_in.get(name, []):          # a stand-in that runs with interrupts open counts whole
            d, p = self.P(o, excl, stack + (name,))
            if d > best[0]:
                best = (d, [name + '~'] + p)
        for e in f.events:
            cl = self.callee_list(f, e) or []
            for c in cl:
                if c in excl or c in self.resets:
                    continue
                if e[3]:
                    d, p = self.D(c, excl, stack + (name,))
                    p = p[:1] + p[1:]
                    p = [p[0] + '[MIE]'] + p[1:]
                else:
                    d, p = self.P(c, excl, stack + (name,))
                if d <= NEG // 2:
                    continue
                tot = -e[2] + d
                if tot > best[0]:
                    best = (tot, [name + ('@%d' % -e[2] if e[2] else '')] + p)
        self.memo_p[key] = best
        return best

    def add_falls(self):
        """asm labels that run on into the next label (crt0, the trap stub's exits) get a fall edge"""
        for f in self.order:
            self.walk(f)
        for f in self.order:
            last = f.ins[-1]
            term = last['mn'] in ('j', 'jr', 'ret', 'mret') or (last['mn'] == 'jalr' and last['ops'] and last['ops'][0] == 'zero')
            if not term and f.name in self.next_of:
                g = self.next_of[f.name]
                f.events.append(('fall', last['addr'], 0, False, g.addr))
                f.notes.append('falls through into %s' % g.name)

    def taken_check(self, entries, uncover=()):
        taken = {}
        data_ok = {(d['in'], int(d['value'], 0)) for d in self.cfg.get('constants_not_code', [])}
        for f in self.order:
            for t in f.taken:
                if (f.name, t) in data_ok:
                    continue                                # a data constant that equals a function start
                taken.setdefault(self.func_starts[t], set()).add(f.name)
        # data words equal to a function start (tables in .rodata / .data / the code window)
        equal = {}
        for f in self.order:
            for site, v in f.equal:
                equal.setdefault(self.func_starts[v], set()).add('%s %#x' % (f.name, site))
        for s in self.dsec:
            blob = fwelf.load_bytes(self._elf, s['addr'], s['size']) or b''
            for k in range(0, len(blob) - 3, 4):
                w = int.from_bytes(blob[k:k + 4], 'little')
                if w in self.func_starts and w != 0:
                    if self.dptr.get(s['addr'] + k) == w:
                        taken.setdefault(self.func_starts[w], set()).add('data %s+%#x' % (s['name'], k))
                    else:
                        equal.setdefault(self.func_starts[w], set()).add('data %s+%#x' % (s['name'], k))
        self.equal_not_address = {n: sorted(w) for n, w in equal.items()}
        covered = set(entries)
        for n, c in self.ind.items():
            covered |= set(self.ind_targets(self.fns[n], 'icall') or []) if n in self.fns else set()
        ok = self.cfg.get('address_taken_ok', {})
        covered -= set(uncover)                    # negative tests (tests/check_tools.py): these count as not covered
        bad = {n: sorted(w) for n, w in taken.items() if n not in covered and (n not in ok or n in uncover)}
        return taken, bad


def level_numbers(an, lv, warn):
    """(D, P, label, detail) of one level"""
    label = 'MEASURED'
    stub = lv.get('stub')
    sf = 0
    if stub:
        if stub in an.fns:
            an.walk(an.fns[stub])
            sf = an.fns[stub].frame
        else:
            sf = lv.get('stub_bytes', 0)
            label = 'MODELLED'
    ents = [e for e in lv.get('entries', []) if e in an.fns]
    excl = frozenset(lv.get('exclude', []))
    detail = []
    D = P = None
    if ents:
        for e in ents:
            d, pd = an.D(e, excl)
            p, pp = an.P(e, excl)
            if lv.get('open'):
                p, pp = d, pd
            if D is None or d > D[0]:
                D = (d, pd)
            if P is None or p > P[0]:
                P = (p, pp)
    else:
        prox = lv.get('proxy', {})
        pents = [e for e in prox.get('entries', []) if e in an.fns]
        missing = [e for e in prox.get('entries', []) if e not in an.fns and not e.startswith('@')]
        if missing:
            warn.append('level %s: proxy entries not in this build: %s' % (lv['name'], ', '.join(missing)))
        pex = frozenset(prox.get('exclude', []))
        for e in pents + [e for e in prox.get('entries', []) if e.startswith('@')]:
            d, pd = an.D(e, pex)
            if D is None or d > D[0]:
                D = (d, pd)
        base = 0
        for b in prox.get('base_frames', []):
            if b in an.fns:
                an.walk(an.fns[b])
                base += an.fns[b].frame
        if D is None:
            D = (0, [])
        mod = lv.get('modelled_bytes', 0)
        D = (D[0] + base + mod, (['base %d' % base] if base else []) + D[1] + (['+%d MODELLED' % mod] if mod else []))
        P = D
        opq = [e for e in prox.get('entries', []) if e.startswith('@')]
        label = ('PROXY' + ('+MODELLED' if mod else '')) if (pents or base or opq) else ('MODELLED' if mod else 'none')
        detail.append(prox.get('basis', ''))
    return dict(name=lv['name'], stub=stub, stub_bytes=sf, D=sf + D[0], P=(sf + P[0]) if P and P[0] > NEG // 2 else None,
                Dpath=D[1], Ppath=(P[1] if P else []), label=label, basis=lv.get('basis', ''), detail=detail)


def chains(levels):
    """every thread -> ... chain where each level can preempt the previous one"""
    by = {l['name']: l for l in levels}
    out = []

    def ext(seq):
        out.append(list(seq))
        for l in levels:
            if l['name'] not in seq and seq[-1] in l.get('preempts', []):
                ext(seq + [l['name']])
    ext(['thread'])
    return out, by


def run_scheme(an, sname, sc, warn):
    lv = [l for l in sc['levels'] if not l.get('absent')]
    nums = {l['name']: level_numbers(an, l, warn) for l in lv}
    ch, by = chains(lv)
    rows = []
    for seq in ch:
        tot = 0
        parts = []
        ok = True
        for k, n in enumerate(seq):
            v = nums[n]
            x = v['D'] if k == len(seq) - 1 else v['P']
            if x is None:
                ok = False
                break
            tot += x
            parts.append('%s %s %d' % (n, 'D' if k == len(seq) - 1 else 'P', x))
        if ok:
            rows.append(dict(chain=seq, bytes=tot, parts=parts))
    rows.sort(key=lambda r: -r['bytes'])
    return dict(scheme=sname, what=sc.get('what', ''), gate=bool(sc.get('gate')), levels=nums,
                absent=[dict(name=l['name'], why=l['absent']) for l in sc['levels'] if l.get('absent')], chains=rows,
                worst=rows[0] if rows else None)


def stack_region(layout):
    for r in layout.get('regions', []):
        if r.get('kind') == 'stack':
            return int(r['hi'], 0) - int(r['lo'], 0), r
    return None, None


def report(build, cfg, layout, uncover=()):
    an = Analyzer(os.path.join(build, 'main.elf'), os.path.join(build, 'main.dis'), cfg)
    an.add_falls()
    warn = []
    out = dict(build=build, schemes=[])
    region, reg = stack_region(layout)
    for sname, sc in cfg['schemes'].items():
        out['schemes'].append(run_scheme(an, sname, sc, warn))
    entries = set()
    for sc in cfg['schemes'].values():
        for l in sc['levels']:
            entries |= set(l.get('entries', [])) | ({l['stub']} if l.get('stub') else set())
    entries |= set(cfg.get('entries_extra', []))
    taken, bad = an.taken_check(entries, uncover)
    # errors only matter in functions that some level reaches
    reach = set()

    def mark(n):
        if n in reach or n not in an.fns:
            return
        reach.add(n)
        f = an.fns[n]
        for e in f.events:
            for c in (an.callee_list(f, e) or []):
                mark(c)
    for sc in out['schemes']:
        for v in sc['levels'].values():
            for n in v['Dpath'] + v['Ppath']:
                pass
    for sc in cfg['schemes'].values():
        for l in sc['levels']:
            for e in l.get('entries', []) + ([l['stub']] if l.get('stub') else []) + l.get('proxy', {}).get('entries', []):
                mark(e)
    ferr = ['%s: %s' % (n, e) for n in sorted(reach) for e in an.fns[n].errors]
    errs = sorted(set(an.errors)) + ferr + ['address taken but not covered by any indirect-call target set: %s (taken in %s)' % (n, ', '.join(w[:4])) for n, w in sorted(bad.items())]
    out.update(region=region, region_name=reg['name'] if reg else None, errors=errs, warnings=warn,
               reached=len(reach), functions=len(an.fns), address_taken={n: sorted(w) for n, w in taken.items()},
               equal_not_address=an.equal_not_address, calls_checked=getattr(an, 'n_calls_checked', 0))
    gate = [s for s in out['schemes'] if s['gate']]
    out['gate_ok'] = all(s['worst'] and s['worst']['bytes'] <= region for s in gate) if region else False
    out['ok'] = out['gate_ok'] and not errs
    # per-function table (reached only)
    out['frames'] = {n: dict(frame=an.fns[n].frame, D=an.D(n)[0], P=(an.P(n)[0] if an.P(n)[0] > NEG // 2 else None))
                     for n in sorted(reach)}
    return out


def fmt(o):
    L = ['static stack bound (tools/fwstack.py): %s' % o['build'], '',
         'stack region: %s, %s B   functions analysed %d, reached from some level %d' % (o['region_name'], o['region'], o['functions'], o['reached']), '']
    for s in o['schemes']:
        L.append('== scheme %s%s: %s' % (s['scheme'], ' (GATE)' if s['gate'] else '', s['what']))
        L.append('  %-7s %-9s %6s %6s %6s  %s' % ('level', 'label', 'stub', 'D', 'P', 'deepest path (D)'))
        for n, v in s['levels'].items():
            L.append('  %-7s %-9s %6d %6d %6s  %s' % (n, v['label'], v['stub_bytes'], v['D'], v['P'] if v['P'] is not None else '-',
                                                     ' -> '.join(v['Dpath'][:14]) + (' ...' if len(v['Dpath']) > 14 else '')))
            if v['P'] is not None and v['Ppath'] and v['P'] != v['D']:
                L.append('  %-7s %-9s %6s %6s %6s  P: %s' % ('', '', '', '', '', ' -> '.join(v['Ppath'][:14])))
            for d in v['detail']:
                if d:
                    L.append('  %-7s   %s' % ('', d))
        for a in s['absent']:
            L.append('  %-7s absent: %s' % (a['name'], a['why']))
        L.append('  chains (P of every level but the last, D of the last):')
        for r in s['chains']:
            L.append('    %6d  %-28s %s' % (r['bytes'], ' > '.join(r['chain']), ' + '.join(r['parts'])))
        if s['worst']:
            w = s['worst']['bytes']
            L.append('  WORST %d B of %d: %s %d B' % (w, o['region'], 'margin' if w <= o['region'] else 'OVER by', abs(o['region'] - w)))
        L.append('')
    if o['warnings']:
        L += ['warnings:'] + ['  ' + w for w in o['warnings']] + ['']
    L += ['address-taken functions: %d (relocation records checked at %d calls); values equal to a function\'s start '
          'that are not addresses: %d%s' % (len(o['address_taken']), o['calls_checked'], len(o['equal_not_address']),
                                            (' (%s)' % ', '.join('%s at %s' % (n, w[0]) for n, w in
                                             sorted(o['equal_not_address'].items())[:6])) if o['equal_not_address'] else ''), '']
    L += ['errors (reachable code the analysis cannot bound, or uncovered address-taken functions): %d' % len(o['errors'])]
    L += ['  ' + e for e in o['errors']]
    L += ['', 'RESULT: %s' % ('PASS' if o['ok'] else 'FAIL')]
    return '\n'.join(L) + '\n'


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('build')
    ap.add_argument('--config', default=os.path.join(HERE, 'stack.json'))
    ap.add_argument('--layout')
    ap.add_argument('--txt')
    ap.add_argument('--json')
    ap.add_argument('--uncover', action='append', default=[], help='negative tests only: treat this function as covered '
                    'by nothing (an address-taken one must then fail the check)')
    a = ap.parse_args()
    cfg = json.load(open(a.config))
    lay_path = a.layout
    if not lay_path:
        man = json.load(open(os.path.join(ROOT, 'fwbuild.json')))
        lname = os.path.basename(os.path.dirname(os.path.abspath(a.build)))
        lay_path = os.path.join(ROOT, *man['layouts'][lname]['regions'].split('/'))
    layout = json.load(open(lay_path))
    o = report(a.build, cfg, layout, a.uncover)
    t = fmt(o)
    print(t, end='')
    if a.txt:
        open(a.txt, 'w', newline='\n').write(t)
    if a.json:
        json.dump(o, open(a.json, 'w', newline='\n'), indent=1, default=list)
    sys.exit(0 if o['ok'] else 1)


if __name__ == '__main__':
    main()
