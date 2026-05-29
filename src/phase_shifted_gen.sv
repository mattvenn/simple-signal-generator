/*
 * Copyright (c) 2024 Matt Venn
 * SPDX-License-Identifier: Apache-2.0
 *
 * Phase-shifted square wave generator.
 *
 * total_delay = spi_offset + floor(enc_phase_fp/256) + sigma_delta_carry
 *
 * spi_offset: signed 16-bit static offset set via SPI (registers 4-5).
 *
 * enc_phase_fp: Q8 signed 16-bit fixed-point, range ±127 cycles.
 *   Updated by enc_up/enc_dn in steps of enc_step/256 cycles per click.
 *
 * sigma_delta_carry: 0 or 1, averages to enc_frac/256 per period.
 *
 * Constraint: |spi_offset + enc_int| < off_count
 */

`default_nettype none

module phase_shifted_gen (
    input  wire              clk,
    input  wire              rst_n,
    input  wire       [15:0] on_count,
    input  wire       [15:0] off_count,
    input  wire signed [15:0] spi_offset, // static phase offset (clock cycles)
    input  wire        [7:0] enc_step,    // Q8 step per encoder click (1/256 cycle per unit)
    input  wire              enc_up,
    input  wire              enc_dn,
    input  wire              ch0_out,
    output reg               out
);

    wire [15:0] period = on_count + off_count;

    // Encoder: Q8 signed 16-bit fixed-point, range ±127 cycles
    localparam signed [15:0] ENC_MAX =  16'sd32512;  // +127 * 256
    localparam signed [15:0] ENC_MIN = -16'sd32512;

    reg  signed [15:0] enc_phase_fp;
    wire signed [15:0] enc_step_s  = {8'b0, enc_step};
    wire signed [15:0] enc_next_up = enc_phase_fp + enc_step_s;
    wire signed [15:0] enc_next_dn = enc_phase_fp - enc_step_s;

    wire signed  [7:0] enc_int  = enc_phase_fp[15:8];
    wire         [7:0] enc_frac = enc_phase_fp[7:0];

    reg  ch0_prev;
    wire ch0_rising = ch0_out && !ch0_prev;

    // Sigma-delta: carry averages to enc_frac/256 per ch0 period
    reg [7:0] sd_acc;
    reg       sd_carry;

    // Total signed phase → actual delay in [0, period)
    wire signed [16:0] total_phase   = {spi_offset[15], spi_offset}
                                     + {{9{enc_int[7]}}, enc_int}
                                     + {16'b0, sd_carry};

    wire        [15:0] actual_delay_raw = total_phase[16] ?
        (period + total_phase[15:0]) :
        total_phase[15:0];
    wire        [15:0] actual_delay     = (actual_delay_raw >= period) ? 16'd0 : actual_delay_raw;

    typedef enum logic [1:0] {
        IDLE  = 2'b00,
        DELAY = 2'b01,
        ON    = 2'b10
    } state_t;

    state_t    state;
    reg [15:0] counter;

    always_ff @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            ch0_prev     <= 1'b0;
            enc_phase_fp <= 16'sd0;
            sd_acc       <= 8'd0;
            sd_carry     <= 1'b0;
            state        <= IDLE;
            counter      <= 16'd0;
            out          <= 1'b0;
        end else begin
            ch0_prev <= ch0_out;

            if (enc_up) begin
                enc_phase_fp <= (enc_next_up > ENC_MAX) ? ENC_MAX : enc_next_up;
            end else if (enc_dn) begin
                enc_phase_fp <= (enc_next_dn < ENC_MIN) ? ENC_MIN : enc_next_dn;
            end

            if (ch0_rising) begin
                {sd_carry, sd_acc} <= {1'b0, sd_acc} + enc_frac;
            end

            case (state)
                IDLE: begin
                    out <= 1'b0;
                    if (ch0_rising && on_count != 16'd0) begin
                        if (actual_delay == 16'd0) begin
                            state   <= ON;
                            counter <= on_count - 16'd1;
                            out     <= 1'b1;
                        end else begin
                            state   <= DELAY;
                            counter <= actual_delay - 16'd1;
                        end
                    end
                end
                DELAY: begin
                    if (counter == 16'd0) begin
                        state   <= ON;
                        counter <= on_count - 16'd1;
                        out     <= 1'b1;
                    end else begin
                        counter <= counter - 16'd1;
                    end
                end
                ON: begin
                    if (counter == 16'd0) begin
                        state <= IDLE;
                        out   <= 1'b0;
                    end else begin
                        counter <= counter - 16'd1;
                    end
                end
                default: state <= IDLE;
            endcase
        end
    end

endmodule
