/*
 * Copyright (c) 2024 Matt Venn
 * SPDX-License-Identifier: Apache-2.0
 */

`default_nettype none

module sq_wave_gen (
    input  wire        clk,
    input  wire        rst_n,
    input  wire [15:0] on_count,
    input  wire [15:0] off_count,
    output reg         out
);

    typedef enum logic [1:0] {
        IDLE = 2'b00,
        HIGH = 2'b01,
        LOW  = 2'b10
    } state_t;

    state_t  state;
    reg [15:0] counter;

    always_ff @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            state   <= IDLE;
            counter <= 16'd0;
            out     <= 1'b0;
        end else begin
            case (state)

                IDLE: begin
                    if (on_count != 0) begin
                        state   <= HIGH;
                        counter <= on_count;
                        out     <= 1'b1;
                    end
                end

                HIGH: begin
                    if (counter <= 16'd1) begin
                        if (on_count == 0 && off_count == 0) begin
                            state <= IDLE;
                            out   <= 1'b0;
                        end else if (off_count != 0) begin
                            state   <= LOW;
                            counter <= off_count;
                            out     <= 1'b0;
                        end else begin
                            // off_count=0: stay HIGH, reload
                            counter <= on_count;
                        end
                    end else begin
                        counter <= counter - 16'd1;
                    end
                end

                LOW: begin
                    if (counter <= 16'd1) begin
                        if (on_count == 0 && off_count == 0) begin
                            state <= IDLE;
                            out   <= 1'b0;
                        end else if (on_count != 0) begin
                            state   <= HIGH;
                            counter <= on_count;
                            out     <= 1'b1;
                        end else begin
                            // on_count=0: stay LOW, reload
                            counter <= off_count;
                        end
                    end else begin
                        counter <= counter - 16'd1;
                    end
                end

                default: state <= IDLE;

            endcase
        end
    end

endmodule
