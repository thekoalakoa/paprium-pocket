import sys, subprocess, collections, numpy as np, wave as W
sys.path.insert(0,"C:/Users/Profe/Downloads/PAPRIUM project/paprium-pocket/scripts")
import mwmm, voice_notes
from scipy.signal import butter, sosfiltfilt
from scipy.stats import mannwhitneyu
SP="C:/Users/Profe/AppData/Local/Temp/claude/C--Users-Profe-Downloads-PAPRIUM-project/1349de78-c90b-4590-8613-9987278e24b0/scratchpad"
CAP="C:/Users/Profe/Downloads/captures master/captures/og hardware music tests/3A Tough Guy.mkv"
SR=32000
hw=np.frombuffer(subprocess.run(["ffmpeg","-v","error","-t","165","-i",CAP,"-ac","1","-ar",str(SR),"-f","f32le","-"],
    capture_output=True).stdout,dtype=np.float32).astype(float)
w=W.open(SP+"/renders/v7/ToughGuy.wav")
rn=np.frombuffer(w.readframes(w.getnframes()),dtype="<i2").reshape(-1,w.getnchannels()).mean(1).astype(float)/32768.0
m={x.n:x for x in mwmm.load_all(SP+"/music-modules")}[58]
tl,_=voice_notes.timeline(m,list(range(26)),2)
notes=[(t,v,pg,12*b1+b0+11) for (t,v,pg,b0,b1) in tl if b0 and b0!=0x0E and t<150]
# calibrate the module->capture lag on a loud in-bank voice (v13, prog 0x02, 960 notes)
cal=[t for t,v,pg,mi in notes if v==13][:500]
sos=butter(4,[150/(SR/2),3000/(SR/2)],btype='band',output='sos'); e=np.abs(sosfiltfilt(sos,hw))
def med(L):
    d=[]
    for t in cal:
        c=int((t+L)*SR)
        if c-1600<0 or c+1600>=len(e): continue
        d.append(20*np.log10((e[c:c+1600].mean()+1e-12)/(e[c-1600:c].mean()+1e-12)))
    return np.median(d) if d else -99
LAG=float(max(np.arange(0.6,3.0,0.02),key=med))
print(f"module->capture lag {LAG:.2f} s (median onset rise {med(LAG):+.2f} dB on v13)\n")
# per 0.25 s frame: is 0x0F sounding?
H=0.25
f0=[(t,mi) for t,v,pg,mi in notes if pg==0x0F]
nF=int(150/H)
on=np.zeros(nF,bool)
for t,mi in f0:
    i=int(t/H)
    for k in range(i,min(i+2,nF)): on[k]=True
dens=np.zeros(nF)
for t,v,pg,mi in notes:
    i=int(t/H)
    if i<nF: dens[i]+=1
def share(x,lag,lo,hi):
    s=butter(4,[lo/(SR/2),hi/(SR/2)],btype='band',output='sos')
    bnd=np.abs(sosfiltfilt(s,x))
    s2=butter(4,[60/(SR/2),14000/(SR/2)],btype='band',output='sos')
    tot=np.abs(sosfiltfilt(s2,x))
    out=np.full(nF,np.nan)
    for i in range(nF):
        a,b=int((i*H+lag)*SR),int(((i+1)*H+lag)*SR)
        if a<0 or b>=len(bnd): continue
        out[i]=bnd[a:b].mean()/(tot[a:b].mean()+1e-12)
    return out
print(f"{'band':>12} {'source':>10} {'0x0F ON':>9} {'0x0F OFF':>10} {'diff':>8} {'p':>10}")
for lo,hi,nm in ((100,1000,"100Hz-1k"),(250,1000,"250Hz-1k"),(1000,3000,"1-3kHz")):
    for tag,x,lag in (("HARDWARE",hw,LAG),("our render",rn,0.0)):
        sh=share(x,lag,lo,hi)
        ok=~np.isnan(sh)
        # control for how busy the music is: keep frames of comparable note density
        band=ok&(dens>=np.percentile(dens[ok],25))&(dens<=np.percentile(dens[ok],75))
        A,B=sh[band&on],sh[band&~on]
        if len(A)<30 or len(B)<30:
            print(f"{nm:>12} {tag:>10}  too few frames ({len(A)}/{len(B)})"); continue
        p=mannwhitneyu(A,B,alternative='greater')[1]
        print(f"{nm:>12} {tag:>10} {np.median(A):9.3f} {np.median(B):10.3f} {np.median(A)-np.median(B):+8.3f} {p:10.2e}")
    print()
