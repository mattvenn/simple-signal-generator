`default_nettype none

module sq_wave_gen (
    input  wire        clk,
    input  wire        rst_n,
    input  wire [23:0] on_count,
    input  wire [23:0] off_count,
    output reg         out
);
    always_ff @(posedge clk or negedge rst_n) begin
        if (!rst_n) out <= 1'b0;
        else        out <= 1'b0;  // stub: always low
    end
    wire _unused = &{on_count, off_count, 1'b0};
endmodule
