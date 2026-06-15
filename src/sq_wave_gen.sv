/*
 * Copyright (c) 2024 Matt Venn
 * SPDX-License-Identifier: Apache-2.0
 *
 * Channel 0: square wave generator.
 *
 * out is high while the shared phase counter is in [0, on_count).
 */

`default_nettype none

module sq_wave_gen (
    input  wire        clk,
    input  wire        rst_n,
    input  wire [15:0] on_count,
    input  wire [15:0] count,
    output reg         out
);

    always_ff @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            out <= 1'b0;
        end else begin
            out <= (count < on_count);
        end
    end

endmodule
