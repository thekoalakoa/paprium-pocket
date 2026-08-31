"""Cycle model of rtl/PAPRIUM/paprium_ima_decode.sv, checked against golden data.

    python scripts/verify_ima_decode.py <golden_in.bin> <golden_out.bin>

WHY THIS EXISTS. Neither Questa edition shipped with Quartus Lite 21.1 will start
without a licence, so the decoder cannot be simulated here. This mirrors the RTL's
states and registers exactly - S_HDR_L0..S_EMIT, the same nib shift-right, the
same registered pred/idx update - and runs the same golden frames through it.

It verifies framing, nibble order and arithmetic, which are the failure modes that
matter: a mismatch there does not sound like mild ADPCM, it decodes at full
amplitude and drifts, measuring as noise. It does NOT verify that the Verilog
elaborates or meets timing; synthesis covers the first and the fit gate the second.

Golden data is produced by encoding a track with build_cdda_adpcm.py and decoding
it back with a straight reference decoder - see docs/CDDA_DESIGN.md.
"""
import struct
from ima_reference import STEP, INDEX, cl   # same tables the packer uses

S_HDR_L0,S_HDR_L1,S_HDR_L2,S_HDR_L3,S_HDR_R0,S_HDR_R1,S_HDR_R2,S_HDR_R3, \
S_SEED,S_FETCH,S_DEC,S_EMIT = range(12)

def s16(v): return v-0x10000 if v & 0x8000 else v

def run(data):
    st=S_HDR_L0; pred=[0,0]; idx=[0,0]; tmp=0
    grp=0; bidx=0; half=0; nib=[0,0]; emit_i=0; dec_ch=0; dec_code=0
    pcm=[0,0]; sample_valid=False
    out=[]; i=0
    for _ in range(10_000_000):
        byte_ready = st <= S_HDR_R3 or st == S_FETCH
        byte_valid = byte_ready and i < len(data)
        b = data[i] if byte_valid else 0
        sample_ack = sample_valid          # drain immediately

        # combinational decode step, exactly as the wires compute it
        dstep = STEP[idx[dec_ch]]; dpred = pred[dec_ch]; didx = idx[dec_ch]
        delta = (dstep>>3) + (dstep if dec_code&4 else 0) \
              + ((dstep>>1) if dec_code&2 else 0) + ((dstep>>2) if dec_code&1 else 0)
        sm = dpred - delta if dec_code&8 else dpred + delta
        pred_next = cl(sm, -32768, 32767)
        adj = (2,4,6,8)[(dec_code&7)-4] if (dec_code&7)>=4 else -1
        idx_next = cl(didx+adj, 0, 88)

        nxt=st
        if st==S_HDR_L0:
            if byte_valid: tmp=b; nxt=S_HDR_L1; i+=1
        elif st==S_HDR_L1:
            if byte_valid: pred[0]=s16((b<<8)|tmp); nxt=S_HDR_L2; i+=1
        elif st==S_HDR_L2:
            if byte_valid: idx[0]=b&0x7F; nxt=S_HDR_L3; i+=1
        elif st==S_HDR_L3:
            if byte_valid: nxt=S_HDR_R0; i+=1
        elif st==S_HDR_R0:
            if byte_valid: tmp=b; nxt=S_HDR_R1; i+=1
        elif st==S_HDR_R1:
            if byte_valid: pred[1]=s16((b<<8)|tmp); nxt=S_HDR_R2; i+=1
        elif st==S_HDR_R2:
            if byte_valid: idx[1]=b&0x7F; nxt=S_HDR_R3; i+=1
        elif st==S_HDR_R3:
            if byte_valid: nxt=S_SEED; i+=1
        elif st==S_SEED:
            if sample_valid and sample_ack:
                out.append((pcm[0],pcm[1])); sample_valid=False
                nxt=S_FETCH; bidx=0; half=0
            else:
                pcm=[pred[0],pred[1]]; sample_valid=True
        elif st==S_FETCH:
            if byte_valid:
                nib[half] = ((b<<24) | (nib[half]>>8)) & 0xFFFFFFFF
                i+=1
                if bidx==3:
                    bidx=0
                    if half: half=0; emit_i=0; dec_ch=0; nxt=S_DEC
                    else:    half=1
                else: bidx+=1
        elif st==S_DEC:
            dec_code = nib[dec_ch] & 0xF
            nxt=S_EMIT
        elif st==S_EMIT:
            if dec_ch==0:
                pred[0]=pred_next; idx[0]=idx_next; pcm[0]=pred_next
                nib[0]>>=4; dec_ch=1; nxt=S_DEC
            elif not sample_valid:
                pred[1]=pred_next; idx[1]=idx_next; pcm[1]=pred_next
                nib[1]>>=4; sample_valid=True
            elif sample_ack:
                out.append((pcm[0],pcm[1])); sample_valid=False; dec_ch=0
                if emit_i==7:
                    emit_i=0
                    if grp==62: grp=0; nxt=S_HDR_L0
                    else: grp+=1; nxt=S_FETCH
                else:
                    emit_i+=1; nxt=S_DEC
        st=nxt
        if i>=len(data) and st==S_HDR_L0 and not sample_valid: break
    return out

if __name__=='__main__':
    data=open('imatest/golden_in.bin','rb').read()
    got=run(data)
    g=open('imatest/golden_out.bin','rb').read()
    exp=[struct.unpack_from('<hh',g,k*4) for k in range(len(g)//4)]
    print("python decoder %d samples, rtl model %d samples" % (len(exp),len(got)))
    n=min(len(exp),len(got))
    bad=[k for k in range(n) if exp[k]!=got[k]]
    if not bad and len(exp)==len(got):
        print("MATCH over %d stereo samples" % n)
    else:
        print("MISMATCH: %d of %d differ" % (len(bad),n))
        for k in bad[:8]:
            print("   %4d  expected %6d %6d   got %6d %6d" % (k,*exp[k],*got[k]))
