/*
 * Copyright (c) 2024 Matt Venn
 * SPDX-License-Identifier: Apache-2.0
 */

`default_nettype none

module tt_um_mattvenn_signal_generator (
    input  wire [7:0] ui_in,
    output wire [7:0] uo_out,
    input  wire [7:0] uio_in,
    output wire [7:0] uio_out,
    output wire [7:0] uio_oe,
    input  wire       ena,
    input  wire       clk,
    input  wire       rst_n
);

    localparam NUM_CFG    = 8;
    localparam NUM_STATUS = 8;
    localparam REG_WIDTH  = 8;

    wire [NUM_CFG*REG_WIDTH-1:0]    config_regs;
    wire [NUM_STATUS*REG_WIDTH-1:0] status_regs;
    wire spi_miso;

    // SPI pins: CS_N=uio[4], CLK=uio[5], MOSI=uio[6], MISO=uio[3]
    assign uio_oe  = 8'b0000_1000;   // uio[3]=MISO output, rest inputs
    assign uio_out = {4'b0, spi_miso, 3'b0};

    // CPOL=ui[0], CPHA=ui[1]; unused uo_out bits
    assign uo_out[7:2] = 6'b0;

    // Status registers unused
    assign status_regs = {(NUM_STATUS*REG_WIDTH){1'b0}};

    // Synchronise SPI inputs and mode bits (2-stage)
    localparam SYNC_STAGES = 2;
    wire spi_cs_n_sync, spi_clk_sync, spi_mosi_sync, cpol_sync, cpha_sync;

    synchronizer #(.STAGES(SYNC_STAGES), .WIDTH(1)) sync_cs_n  (.rstb(rst_n), .clk(clk), .ena(ena), .data_in(uio_in[4]), .data_out(spi_cs_n_sync));
    synchronizer #(.STAGES(SYNC_STAGES), .WIDTH(1)) sync_clk   (.rstb(rst_n), .clk(clk), .ena(ena), .data_in(uio_in[5]), .data_out(spi_clk_sync));
    synchronizer #(.STAGES(SYNC_STAGES), .WIDTH(1)) sync_mosi  (.rstb(rst_n), .clk(clk), .ena(ena), .data_in(uio_in[6]), .data_out(spi_mosi_sync));
    synchronizer #(.STAGES(SYNC_STAGES), .WIDTH(1)) sync_cpol  (.rstb(rst_n), .clk(clk), .ena(ena), .data_in(ui_in[0]),  .data_out(cpol_sync));
    synchronizer #(.STAGES(SYNC_STAGES), .WIDTH(1)) sync_cpha  (.rstb(rst_n), .clk(clk), .ena(ena), .data_in(ui_in[1]),  .data_out(cpha_sync));

    spi_wrapper #(
        .NUM_CFG   (NUM_CFG),
        .NUM_STATUS(NUM_STATUS),
        .REG_WIDTH (REG_WIDTH)
    ) spi_wrapper_i (
        .rstb      (rst_n),
        .clk       (clk),
        .ena       (ena),
        .mode      ({cpol_sync, cpha_sync}),
        .spi_cs_n  (spi_cs_n_sync),
        .spi_clk   (spi_clk_sync),
        .spi_mosi  (spi_mosi_sync),
        .spi_miso  (spi_miso),
        .config_regs(config_regs),
        .status_regs(status_regs)
    );

    // 4 square wave generators; channel i uses config regs [i*4 .. i*4+3]
    // config_regs layout: reg N occupies bits [N*8+7 : N*8]
    // on_count  = {reg[i*4], reg[i*4+1]} = MSB..LSB (16-bit)
    // off_count = {reg[i*4+2], reg[i*4+3]}
    genvar i;
    generate
        for (i = 0; i < 2; i = i + 1) begin : gen_ch
            sq_wave_gen ch_inst (
                .clk      (clk),
                .rst_n    (rst_n),
                .on_count ({config_regs[i*32 +  7 -: 8],
                            config_regs[i*32 + 15 -: 8]}),
                .off_count({config_regs[i*32 + 23 -: 8],
                            config_regs[i*32 + 31 -: 8]}),
                .out      (uo_out[i])
            );
        end
    endgenerate

endmodule
