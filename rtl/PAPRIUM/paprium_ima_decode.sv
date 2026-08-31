// ---------------------------------------------------------------------------
// IMA ADPCM decoder for the CDDA path.
//
// Takes 512-byte MS-IMA frames and emits 505 stereo PCM samples. The blob format
// and the reasoning behind it are in docs/CDDA_DESIGN.md; the short version is
// that the raw music blob is 2.09 GB and this makes it about 535 MB.
//
// FRAME LAYOUT - stated here in the same words as scripts/build_cdda_adpcm.py,
// because a mismatch between encoder and decoder does NOT sound like mild ADPCM.
// It decodes at full amplitude and drifts, which measures as noise:
//
//     L header : s16 predictor, u8 step index, u8 reserved   (4 bytes)
//     R header : s16 predictor, u8 step index, u8 reserved   (4 bytes)
//     then 63 groups of: L 4 bytes (8 nibbles), R 4 bytes (8 nibbles)
//
// The first sample of each channel is the header predictor and is NOT encoded,
// which is why block_samples - 1 must be a multiple of 8. 505 = 1 + 8*63.
// Nibble order within a byte is LOW first, then high.
//
// WHY IT DECODES ON THE READ SIDE. Decoding into the ring instead would need the
// ring to hold PCM: a 4096-byte fetch becomes 16,160 bytes decoded, so four
// chunks is ~50 M10K against 14 spare. Holding compressed frames keeps the same
// 16 KB and raises buffering from 0.085 s to 0.337 s.
//
// EVERYTHING IS REGISTERED. The nibble arithmetic must not reach the 48 kHz
// sample path - that is the mistake the srate+1 adder made in front of the aclk
// mux, costing 0.4 ns of setup and four fitter seeds. There is no throughput
// pressure: 48 kHz x 2 channels is 96k updates/second against a ~53 MHz clock,
// roughly 550 cycles per sample.
// ---------------------------------------------------------------------------

module paprium_ima_decode (
	input  wire        clk,
	input  wire        reset,

	// Compressed byte stream in, one byte per byte_valid. The producer presents
	// bytes in frame order; frame_start resyncs to a frame boundary after a seek
	// or a track change.
	input  wire        frame_start,
	input  wire [7:0]  byte_data,
	input  wire        byte_valid,
	output wire        byte_ready,

	// Decoded stereo samples out, held until sample_ack.
	output reg  [15:0] pcm_l,
	output reg  [15:0] pcm_r,
	output reg         sample_valid,
	input  wire        sample_ack
);

	// ---- IMA tables -------------------------------------------------------
	function [15:0] step_of(input [6:0] i);
		case(i)
			7'd0:  step_of=16'd7;     7'd1:  step_of=16'd8;     7'd2:  step_of=16'd9;
			7'd3:  step_of=16'd10;    7'd4:  step_of=16'd11;    7'd5:  step_of=16'd12;
			7'd6:  step_of=16'd13;    7'd7:  step_of=16'd14;    7'd8:  step_of=16'd16;
			7'd9:  step_of=16'd17;    7'd10: step_of=16'd19;    7'd11: step_of=16'd21;
			7'd12: step_of=16'd23;    7'd13: step_of=16'd25;    7'd14: step_of=16'd28;
			7'd15: step_of=16'd31;    7'd16: step_of=16'd34;    7'd17: step_of=16'd37;
			7'd18: step_of=16'd41;    7'd19: step_of=16'd45;    7'd20: step_of=16'd50;
			7'd21: step_of=16'd55;    7'd22: step_of=16'd60;    7'd23: step_of=16'd66;
			7'd24: step_of=16'd73;    7'd25: step_of=16'd80;    7'd26: step_of=16'd88;
			7'd27: step_of=16'd97;    7'd28: step_of=16'd107;   7'd29: step_of=16'd118;
			7'd30: step_of=16'd130;   7'd31: step_of=16'd143;   7'd32: step_of=16'd157;
			7'd33: step_of=16'd173;   7'd34: step_of=16'd190;   7'd35: step_of=16'd209;
			7'd36: step_of=16'd230;   7'd37: step_of=16'd253;   7'd38: step_of=16'd279;
			7'd39: step_of=16'd307;   7'd40: step_of=16'd337;   7'd41: step_of=16'd371;
			7'd42: step_of=16'd408;   7'd43: step_of=16'd449;   7'd44: step_of=16'd494;
			7'd45: step_of=16'd544;   7'd46: step_of=16'd598;   7'd47: step_of=16'd658;
			7'd48: step_of=16'd724;   7'd49: step_of=16'd796;   7'd50: step_of=16'd876;
			7'd51: step_of=16'd963;   7'd52: step_of=16'd1060;  7'd53: step_of=16'd1166;
			7'd54: step_of=16'd1282;  7'd55: step_of=16'd1411;  7'd56: step_of=16'd1552;
			7'd57: step_of=16'd1707;  7'd58: step_of=16'd1878;  7'd59: step_of=16'd2066;
			7'd60: step_of=16'd2272;  7'd61: step_of=16'd2499;  7'd62: step_of=16'd2749;
			7'd63: step_of=16'd3024;  7'd64: step_of=16'd3327;  7'd65: step_of=16'd3660;
			7'd66: step_of=16'd4026;  7'd67: step_of=16'd4428;  7'd68: step_of=16'd4871;
			7'd69: step_of=16'd5358;  7'd70: step_of=16'd5894;  7'd71: step_of=16'd6484;
			7'd72: step_of=16'd7132;  7'd73: step_of=16'd7845;  7'd74: step_of=16'd8630;
			7'd75: step_of=16'd9493;  7'd76: step_of=16'd10442; 7'd77: step_of=16'd11487;
			7'd78: step_of=16'd12635; 7'd79: step_of=16'd13899; 7'd80: step_of=16'd15289;
			7'd81: step_of=16'd16818; 7'd82: step_of=16'd18500; 7'd83: step_of=16'd20350;
			7'd84: step_of=16'd22385; 7'd85: step_of=16'd24623; 7'd86: step_of=16'd27086;
			7'd87: step_of=16'd29794; default: step_of=16'd32767;
		endcase
	endfunction

	// index adjust: -1 for codes 0..3 and 8..B, then +2/+4/+6/+8
	function signed [5:0] idx_adj(input [3:0] c);
		case(c[2:0])
			3'd4: idx_adj =  6'sd2;
			3'd5: idx_adj =  6'sd4;
			3'd6: idx_adj =  6'sd6;
			3'd7: idx_adj =  6'sd8;
			default: idx_adj = -6'sd1;
		endcase
	endfunction

	localparam signed [7:0] IDX_MAX = 8'sd88;

	localparam S_HDR_L0 = 4'd0, S_HDR_L1 = 4'd1, S_HDR_L2 = 4'd2, S_HDR_L3 = 4'd3,
	           S_HDR_R0 = 4'd4, S_HDR_R1 = 4'd5, S_HDR_R2 = 4'd6, S_HDR_R3 = 4'd7,
	           S_SEED   = 4'd8, S_FETCH  = 4'd9, S_DEC    = 4'd10, S_EMIT = 4'd11;

	reg [3:0]  st;
	reg [15:0] pred_l, pred_r;
	reg [6:0]  idx_l,  idx_r;
	reg [7:0]  tmp;

	reg [5:0]  grp;          // 0..62, the 63 nibble groups in a frame
	reg [1:0]  bidx;         // byte within the current 4-byte half
	reg        half;         // 0 = left half, 1 = right half
	reg [31:0] nib_l, nib_r; // 8 codes each, 4 bits per code, low nibble first
	reg [2:0]  emit_i;
	reg        dec_ch;       // 0 = left, 1 = right
	reg [3:0]  dec_code;

	// The decode step, shared by both channels. Its result is registered into
	// pred_*/idx_* on the next edge and never reaches an output combinationally.
	wire [15:0] dstep = step_of(dec_ch ? idx_r : idx_l);
	wire [15:0] dpred = dec_ch ? pred_r : pred_l;
	wire [6:0]  didx  = dec_ch ? idx_r  : idx_l;

	wire [17:0] delta = {5'b0, dstep[15:3]}
	                  + (dec_code[2] ? {2'b0, dstep}       : 18'd0)
	                  + (dec_code[1] ? {3'b0, dstep[15:1]} : 18'd0)
	                  + (dec_code[0] ? {4'b0, dstep[15:2]} : 18'd0);

	wire signed [19:0] sum = dec_code[3]
	        ? ($signed({{4{dpred[15]}}, dpred}) - $signed({2'b0, delta}))
	        : ($signed({{4{dpred[15]}}, dpred}) + $signed({2'b0, delta}));

	wire [15:0] pred_next = (sum >  20'sd32767) ? 16'h7FFF
	                      : (sum < -20'sd32768) ? 16'h8000
	                                            : sum[15:0];

	wire signed [7:0] idx_sum  = $signed({1'b0, didx}) + $signed({{2{idx_adj(dec_code)[5]}}, idx_adj(dec_code)});
	wire       [6:0]  idx_next = (idx_sum < 8'sd0) ? 7'd0
	                           : (idx_sum > IDX_MAX) ? 7'd88 : idx_sum[6:0];

	assign byte_ready = (st <= S_HDR_R3) | (st == S_FETCH);

	always @(posedge clk) begin
		if(reset | frame_start) begin
			st <= S_HDR_L0; grp <= 6'd0; bidx <= 2'd0; half <= 1'b0;
			emit_i <= 3'd0; dec_ch <= 1'b0; sample_valid <= 1'b0;
		end
		else begin
			case(st)
				// ---- 8-byte header: L predictor/index, then R ---------------
				S_HDR_L0: if(byte_valid) begin tmp <= byte_data; st <= S_HDR_L1; end
				S_HDR_L1: if(byte_valid) begin pred_l <= {byte_data, tmp}; st <= S_HDR_L2; end
				S_HDR_L2: if(byte_valid) begin idx_l  <= byte_data[6:0];   st <= S_HDR_L3; end
				S_HDR_L3: if(byte_valid) st <= S_HDR_R0;                 // reserved
				S_HDR_R0: if(byte_valid) begin tmp <= byte_data; st <= S_HDR_R1; end
				S_HDR_R1: if(byte_valid) begin pred_r <= {byte_data, tmp}; st <= S_HDR_R2; end
				S_HDR_R2: if(byte_valid) begin idx_r  <= byte_data[6:0];   st <= S_HDR_R3; end
				S_HDR_R3: if(byte_valid) st <= S_SEED;                   // reserved

				// ---- sample 0 IS the header predictor, not an encoded code ---
				S_SEED: begin
					pcm_l <= pred_l;
					pcm_r <= pred_r;
					sample_valid <= 1'b1;
					if(sample_valid & sample_ack) begin
						sample_valid <= 1'b0;
						st <= S_FETCH; bidx <= 2'd0; half <= 1'b0;
					end
				end

				// ---- pull 4 bytes into the current half's code register ------
				S_FETCH: if(byte_valid) begin
					if(half) nib_r <= {byte_data, nib_r[31:8]};
					else     nib_l <= {byte_data, nib_l[31:8]};
					if(bidx == 2'd3) begin
						bidx <= 2'd0;
						if(half) begin
							half   <= 1'b0;
							emit_i <= 3'd0;
							dec_ch <= 1'b0;
							st     <= S_DEC;
						end
						else half <= 1'b1;
					end
					else bidx <= bidx + 2'd1;
				end

				// ---- one nibble per channel, then emit the stereo pair -------
				S_DEC: begin
					dec_code <= dec_ch ? nib_r[3:0] : nib_l[3:0];
					st <= S_EMIT;
				end

				S_EMIT: begin
					if(!dec_ch) begin
						pred_l <= pred_next; idx_l <= idx_next; pcm_l <= pred_next;
						nib_l  <= {4'b0, nib_l[31:4]};
						dec_ch <= 1'b1;
						st     <= S_DEC;
					end
					else if(!sample_valid) begin
						pred_r <= pred_next; idx_r <= idx_next; pcm_r <= pred_next;
						nib_r  <= {4'b0, nib_r[31:4]};
						sample_valid <= 1'b1;
					end
					else if(sample_ack) begin
						sample_valid <= 1'b0;
						dec_ch <= 1'b0;
						if(emit_i == 3'd7) begin
							emit_i <= 3'd0;
							if(grp == 6'd62) begin grp <= 6'd0; st <= S_HDR_L0; end
							else begin grp <= grp + 6'd1; st <= S_FETCH; end
						end
						else begin
							emit_i <= emit_i + 3'd1;
							st <= S_DEC;
						end
					end
				end

				default: st <= S_HDR_L0;
			endcase
		end
	end

endmodule
