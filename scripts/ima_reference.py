"""Reference IMA decoder - the spec the RTL is checked against.

Used by scripts/verify_ima_decode.py. Straight-line Python, no hardware
concerns, so a disagreement with the RTL model is the RTL model being wrong.
"""
"""Decode a PPAD blob - mirrors what the RTL must do, including per-block reseed."""
import struct, sys
STEP=[7,8,9,10,11,12,13,14,16,17,19,21,23,25,28,31,34,37,41,45,50,55,60,66,73,80,
 88,97,107,118,130,143,157,173,190,209,230,253,279,307,337,371,408,449,494,544,
 598,658,724,796,876,963,1060,1166,1282,1411,1552,1707,1878,2066,2272,2499,2749,
 3024,3327,3660,4026,4428,4871,5358,5894,6484,7132,7845,8630,9493,10442,11487,
 12635,13899,15289,16818,18500,20350,22385,24623,27086,29794,32767]
INDEX=[-1,-1,-1,-1,2,4,6,8,-1,-1,-1,-1,2,4,6,8]
cl=lambda v,a,b: a if v<a else (b if v>b else v)

def dec_nib(code, pred, idx):
    step=STEP[idx]
    delta=step>>3
    if code&4: delta+=step
    if code&2: delta+=step>>1
    if code&1: delta+=step>>2
    pred = cl(pred-delta if code&8 else pred+delta, -32768, 32767)
    return pred, cl(idx+INDEX[code],0,88)

def decode(path, track):
    d=open(path,'rb').read()
    assert d[:4]==b'PPAD', "not a PPAD blob"
    ver,hz,ch,blk,nt = struct.unpack_from('<IIIII', d, 4)
    off,ln,ns = struct.unpack_from('<QII', d, 0x18+track*16)
    out=bytearray(); p=off; end=off+ln
    while p < end:
        pred=[0,0]; idx=[0,0]
        for c in (0,1):
            pr,ix,_ = struct.unpack_from('<hBB', d, p); p+=4
            pred[c],idx[c]=pr,ix
        smp=[[pred[0]],[pred[1]]]
        n=1
        while n < blk and p < end:
            for c in (0,1):
                for k in range(4):
                    b=d[p]; p+=1
                    for code in (b&0xF, b>>4):
                        pred[c],idx[c]=dec_nib(code,pred[c],idx[c])
                        smp[c].append(pred[c])
            n+=8
        for i in range(min(len(smp[0]),len(smp[1]))):
            out += struct.pack('<hh', smp[0][i], smp[1][i])
    return out, hz, blk

if __name__=='__main__':
    pcm,hz,blk = decode(sys.argv[1], int(sys.argv[2]))
    open(sys.argv[3],'wb').write(pcm)
    print("decoded %d bytes, block=%d samples" % (len(pcm), blk))
