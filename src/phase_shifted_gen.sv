/*
 * Copyright (c) 2024 Matt Venn
 * SPDX-License-Identifier: Apache-2.0
 *
 * Channel 1: phase-shifted replica of ch0, sharing the same free-running
 * phase counter (see phase_counter.sv).
 *
 * total_delay = spi_offset + floor(enc_phase_fp/256) + sigma_delta_carry
 *
 * spi_offset: signed 16-bit static offset set via SPI (registers 4-5).
 *
 * enc_phase_fp: Q8 signed 16-bit fixed-point, range +/-127 cycles.
 *   Updated by enc_up/enc_dn in steps of enc_step/256 cycles per click.
 *
 * sigma_delta_carry: 0 or 1, averages to enc_frac/256 per period.
 *
 * actual_delay = total_delay mod period, in [0, period). ch1's phase is
 * the shared counter shifted back by actual_delay:
 *   ch1_phase = (count - actual_delay) mod period
 *   out       = (ch1_phase < on_count)
 * No clamping is needed: any actual_delay in [0, period) is valid.
 */

`default_nettype none

module phase_shifted_gen (
    input  wire               clk,
    input  wire               rst_n,
    input  wire        [15:0] on_count,
    input  wire        [15:0] off_count,
    input  wire signed [15:0] spi_offset, // static phase offset (clock cycles)
    input  wire        [7:0]  enc_step,   // Q8 step per encoder click (1/256 cycle per unit)
    input  wire               enc_up,
    input  wire               enc_dn,
    input  wire        [15:0] count,        // shared phase counter (0..period-1)
    input  wire               period_start, // one cycle per period, when count==0
    output reg                out
);

    wire [15:0] period = on_count + off_count;

    // Encoder: Q8 signed 16-bit fixed-point, range +/-127 cycles
    localparam signed [15:0] ENC_MAX =  16'sd32512;  // +127 * 256
    localparam signed [15:0] ENC_MIN = -16'sd32512;

    reg  signed [15:0] enc_phase_fp;
    wire signed [15:0] enc_step_s  = {8'b0, enc_step};
    wire signed [15:0] enc_next_up = enc_phase_fp + enc_step_s;
    wire signed [15:0] enc_next_dn = enc_phase_fp - enc_step_s;

    wire signed  [7:0] enc_int  = enc_phase_fp[15:8];
    wire         [7:0] enc_frac = enc_phase_fp[7:0];

    // Sigma-delta: carry averages to enc_frac/256 per period
    reg [7:0] sd_acc;
    reg       sd_carry;

    // Total signed phase -> actual delay in [0, period)
    wire signed [16:0] total_phase   = {spi_offset[15], spi_offset}
                                     + {{9{enc_int[7]}}, enc_int}
                                     + {16'b0, sd_carry};

    wire        [15:0] actual_delay_raw = total_phase[16] ?
        (period + total_phase[15:0]) :
        total_phase[15:0];
    wire        [15:0] actual_delay = (actual_delay_raw >= period) ? 16'd0 : actual_delay_raw;

    // ch1_phase = (count - actual_delay) mod period
    wire [15:0] ch1_phase = (count >= actual_delay) ?
        (count - actual_delay) :
        (count - actual_delay + period);

    always_ff @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            enc_phase_fp <= 16'sd0;
            sd_acc       <= 8'd0;
            sd_carry     <= 1'b0;
            out          <= 1'b0;
        end else begin
            if (enc_up) begin
                enc_phase_fp <= (enc_next_up > ENC_MAX) ? ENC_MAX : enc_next_up;
            end else if (enc_dn) begin
                enc_phase_fp <= (enc_next_dn < ENC_MIN) ? ENC_MIN : enc_next_dn;
            end

            if (period_start) begin
                {sd_carry, sd_acc} <= {1'b0, sd_acc} + enc_frac;
            end

            out <= (ch1_phase < on_count);
        end
    end

endmodule
