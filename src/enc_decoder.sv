/*
 * Copyright (c) 2024 Matt Venn
 * SPDX-License-Identifier: Apache-2.0
 *
 * Quadrature encoder decoder.
 * Takes synchronized A/B inputs, outputs single-cycle up/dn pulses.
 *
 * ab = {a, b}. CW transitions: 00→01→11→10→00 produce up pulses.
 * CCW transitions: 00→10→11→01→00 produce dn pulses.
 */

`default_nettype none

module enc_decoder (
    input  wire clk,
    input  wire rst_n,
    input  wire a,      // encoder A (pre-synchronized)
    input  wire b,      // encoder B (pre-synchronized)
    output reg  up,
    output reg  dn
);
    reg [1:0] ab_prev;
    wire [1:0] ab = {a, b};

    always_ff @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            ab_prev <= 2'b00;
            up      <= 1'b0;
            dn      <= 1'b0;
        end else begin
            ab_prev <= ab;
            up <= 1'b0;
            dn <= 1'b0;
            case ({ab_prev, ab})
                4'b00_01, 4'b01_11, 4'b11_10, 4'b10_00: up <= 1'b1;
                4'b00_10, 4'b10_11, 4'b11_01, 4'b01_00: dn <= 1'b1;
                default: ;
            endcase
        end
    end
endmodule
