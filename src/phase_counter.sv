/*
 * Copyright (c) 2024 Matt Venn
 * SPDX-License-Identifier: Apache-2.0
 *
 * Shared free-running phase counter.
 *
 * count cycles 0 .. period-1 .. 0 .. where period = on_count + off_count.
 * If period == 0 (on_count == off_count == 0), count stays at 0 (silence).
 */

`default_nettype none

module phase_counter (
    input  wire        clk,
    input  wire        rst_n,
    input  wire [15:0] on_count,
    input  wire [15:0] off_count,
    output reg  [15:0] count
);

    wire [15:0] period = on_count + off_count;

    always_ff @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            count <= 16'd0;
        end else if (period == 16'd0) begin
            count <= 16'd0;
        end else if (count + 16'd1 >= period) begin
            count <= 16'd0;
        end else begin
            count <= count + 16'd1;
        end
    end

endmodule
