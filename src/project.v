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
    assign uo_out[7:3] = 6'b0;

    // Status registers unused
    assign status_regs = {(NUM_STATUS*REG_WIDTH){1'b0}};

    // Synchronise SPI inputs and mode bits (2-stage)
    localparam SYNC_STAGES = 2;
    wire spi_cs_n_sync, spi_clk_sync, spi_mosi_sync, cpol_sync, cpha_sync;
    wire enc_a_sync, enc_b_sync, enc_btn_sync, enc_up, enc_dn;
    assign uo_out[2] = enc_btn_sync;

    synchronizer #(.STAGES(SYNC_STAGES), .WIDTH(1)) sync_cs_n  (.rstb(rst_n), .clk(clk), .ena(ena), .data_in(uio_in[4]), .data_out(spi_cs_n_sync));
    synchronizer #(.STAGES(SYNC_STAGES), .WIDTH(1)) sync_clk   (.rstb(rst_n), .clk(clk), .ena(ena), .data_in(uio_in[5]), .data_out(spi_clk_sync));
    synchronizer #(.STAGES(SYNC_STAGES), .WIDTH(1)) sync_mosi  (.rstb(rst_n), .clk(clk), .ena(ena), .data_in(uio_in[6]), .data_out(spi_mosi_sync));
    synchronizer #(.STAGES(SYNC_STAGES), .WIDTH(1)) sync_cpol  (.rstb(rst_n), .clk(clk), .ena(ena), .data_in(ui_in[0]),  .data_out(cpol_sync));
    synchronizer #(.STAGES(SYNC_STAGES), .WIDTH(1)) sync_cpha  (.rstb(rst_n), .clk(clk), .ena(ena), .data_in(ui_in[1]),  .data_out(cpha_sync));
    synchronizer #(.STAGES(SYNC_STAGES), .WIDTH(1)) sync_enc_a (.rstb(rst_n), .clk(clk), .ena(ena), .data_in(ui_in[4]),  .data_out(enc_a_sync));
    synchronizer #(.STAGES(SYNC_STAGES), .WIDTH(1)) sync_enc_b (.rstb(rst_n), .clk(clk), .ena(ena), .data_in(ui_in[5]),  .data_out(enc_b_sync));
    synchronizer #(.STAGES(SYNC_STAGES), .WIDTH(1)) sync_enc_btn (.rstb(rst_n), .clk(clk), .ena(ena), .data_in(ui_in[6]), .data_out(enc_btn_sync));

    // Default register values on reset:
    //   regs 0-3: on_count=1000 (0x03E8), off_count=10000 (0x2710)
    //   regs 4-5: spi_offset=0
    //   reg  6:   enc_step=1
    localparam [NUM_CFG*REG_WIDTH-1:0] CFG_RESET_VAL = {
        8'h00,   // reg 7: unused
        8'h01,   // reg 6: enc_step = 1
        8'h00,   // reg 5: spi_offset low  = 0
        8'h00,   // reg 4: spi_offset high = 0
        8'h10,   // reg 3: off_count low   = 0x10 (10000 & 0xFF)
        8'h27,   // reg 2: off_count high  = 0x27 (10000 >> 8)
        8'hE8,   // reg 1: on_count low    = 0xE8 (1000 & 0xFF)
        8'h03    // reg 0: on_count high   = 0x03 (1000 >> 8)
    };

    spi_wrapper #(
        .NUM_CFG   (NUM_CFG),
        .NUM_STATUS(NUM_STATUS),
        .REG_WIDTH (REG_WIDTH),
        .RESET_VAL (CFG_RESET_VAL)
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

    // Encoder decoder: ui_in[4]=A, ui_in[5]=B
    enc_decoder enc_dec_i (
        .clk   (clk),
        .rst_n (rst_n),
        .a     (enc_a_sync),
        .b     (enc_b_sync),
        .up    (enc_up),
        .dn    (enc_dn)
    );

    // Shared free-running phase counter (drives both channels)
    // config regs 0-3: on_count[15:8], on_count[7:0], off_count[15:8], off_count[7:0]
    wire [15:0] on_count  = {config_regs[7  -: 8], config_regs[15 -: 8]};
    wire [15:0] off_count = {config_regs[23 -: 8], config_regs[31 -: 8]};
    wire [15:0] phase_count;

    phase_counter phase_counter_i (
        .clk         (clk),
        .rst_n       (rst_n),
        .on_count    (on_count),
        .off_count   (off_count),
        .count       (phase_count)
    );

    // Channel 0: square wave generator
    sq_wave_gen ch0_inst (
        .clk     (clk),
        .rst_n   (rst_n),
        .on_count(on_count),
        .count   (phase_count),
        .out     (uo_out[0])
    );

    // Channel 1: phase-shifted replica of ch0
    // config regs 4-5:  spi_offset[15:0] (signed; static phase offset in clock cycles)
    // config reg  6:    enc_step[7:0]    (Q8 encoder step per click: 1/256 cycle per unit)
    wire [15:0] ch1_spi_offset = {config_regs[39 -: 8], config_regs[47 -: 8]};
    wire  [7:0] ch1_enc_step   = config_regs[55 -: 8];

    phase_shifted_gen ch1_inst (
        .clk         (clk),
        .rst_n       (rst_n),
        .on_count    (on_count),
        .off_count   (off_count),
        .spi_offset  (ch1_spi_offset),
        .enc_step    (ch1_enc_step),
        .enc_up      (enc_up),
        .enc_dn      (enc_dn),
        .enc_btn     (enc_btn_sync),
        .count       (phase_count),
        .out         (uo_out[1])
    );

endmodule
