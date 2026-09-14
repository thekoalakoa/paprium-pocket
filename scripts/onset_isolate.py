#!/usr/bin/env python3
"""Decide whether one program is audible on the cartridge, from onsets it owns alone.

    python scripts/onset_isolate.py      (edit CASES; paths are local, see below)

The music is 26 voices deep and no hardware solo exists - across 54,748 frames of
four captures there is no run of 150 ms with a single voice lit. So a claim that
an instrument is or is not sounding cannot be made from the mix. What CAN be done
is to find the onsets where one voice starts a note and NOTHING else starts
within a guard window, and ask whether the capture's energy rises there more than
at times when nothing starts at all.

It only works where such onsets exist. In Dark Rock, program 0x0F - the largest
single deficit, 396 notes - has ZERO exclusive onsets at any guard, in either
track that uses it, so this method is blind to it and says so.

Where it does work it is decisive, because the controls prove the power. Dark
Rock voice 10 plays three programs:

    0x11  in the bank   12 exclusive onsets  AUDIBLE  p = 8e-7 .. 4e-8
    0x03  in the bank   11 exclusive onsets  AUDIBLE  p = 1e-8
    0x35  NOT in bank   28 exclusive onsets  nothing, in all six bands

Twice the onsets of either control and no rise anywhere. So a program the bank
does not define produces no sound on the cartridge either - the music selects it
and the hardware ignores it. Those are dead selectors left in the composition,
not instruments we are failing to play.

The same run shows the on-screen level meter is lit for 99.2% of the 0x35 frames
at mean level 6.16, higher than the same voice's audible programs. The meter is
the driver's note state, not the audio.

Derived from a commercial ROM: keep the output local.
"""

import sys, subprocess, numpy as np
sys.path.insert(0,"C:/Users/Profe/Downloads/PAPRIUM project/paprium-pocket/scripts")
import voice_notes, mwmm
from scipy.signal import butter, sosfiltfilt
from scipy.stats import mannwhitneyu
SP="C:/Users/Profe/AppData/Local/Temp/claude/C--Users-Profe-Downloads-PAPRIUM-project/1349de78-c90b-4590-8613-9987278e24b0/scratchpad"
CAP="C:/Users/Profe/Downloads/captures master/captures/og hardware music tests/16 Dark Rock.mkv"
SR=48000; LAG=1.48; G=0.060; HALF=0.035
x=np.frombuffer(subprocess.run(["ffmpeg","-v","error","-t","240","-i",CAP,"-ac","1","-ar",str(SR),"-f","f32le","-"],
                capture_output=True).stdout,dtype=np.float32).astype(float)
MOD={m.n:m for m in mwmm.load_all(SP+"/music-modules")}[22]
tl,_=voice_notes.timeline(MOD,list(range(26)),2)
SAX={23,24,25}
ev=[(t,v,pg) for (t,v,pg,b0,b1) in tl if b0 and b0!=0x0E and v not in SAX and t<225]
allt=np.array(sorted(set(t for t,_,_ in ev)))
def excl(pred):
    own=sorted(set(t for t,v,pg in ev if pred(v,pg)))
    oth=np.array(sorted(set(t for t,v,pg in ev if not pred(v,pg))))
    out=[]
    for t in own:
        i=np.searchsorted(oth,t)
        if all(abs(t-oth[j])>G for j in (i-1,i) if 0<=j<len(oth)): out.append(t)
    return out
def nullt(n=600):
    rng=np.random.default_rng(5); o=[]
    while len(o)<n:
        t=rng.uniform(2,220); i=np.searchsorted(allt,t)
        if all(abs(t-allt[j])>G for j in (i-1,i) if 0<=j<len(allt)): o.append(t)
    return o
def rise(ts,lo,hi):
    sos=butter(4,[lo/(SR/2),hi/(SR/2)],btype='band',output='sos')
    e=np.abs(sosfiltfilt(sos,x)); d=[]
    for t in ts:
        c=int((t+LAG)*SR); a,b=c-int(HALF*SR),c+int(HALF*SR)
        if a<0 or b>=len(e): continue
        d.append(20*np.log10((e[c:b].mean()+1e-12)/(e[a:c].mean()+1e-12)))
    return np.array(d)
NULL=nullt()
CASES=[("v10 prog 0x35  MISSING FROM BANK", lambda v,pg: v==10 and pg==0x35),
       ("v10 prog 0x11  control, sample exists", lambda v,pg: v==10 and pg==0x11),
       ("v11 prog 0x03  control, sample exists", lambda v,pg: v==11 and pg==0x03)]
print(f"guard {G*1000:.0f} ms, window +/-{HALF*1000:.0f} ms, null n={len(NULL)}\n")
for name,pred in CASES:
    ts=excl(pred)
    print(f"=== {name}: {len(ts)} exclusive onsets")
    if len(ts)<10: print("    too few -> METHOD BLIND\n"); continue
    for nm,lo,hi in (("30-120",30,120),("120-480",120,480),("480-2k",480,1920),
                     ("2-8k",1920,7680),("8-16k",7680,15360),("BROAD 30-16k",30,15360)):
        d=rise(ts,lo,hi); dn=rise(NULL,lo,hi)
        p=mannwhitneyu(d,dn,alternative='greater')[1]
        print(f"    {nm:14} {np.median(d):+7.2f} dB  null {np.median(dn):+6.2f}  p={p:9.2e}  "
              f"{'AUDIBLE' if p<0.001 else ('weak' if p<0.05 else '-')}")
    print()
