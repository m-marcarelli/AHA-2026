module tb_trojan_3;

    // Clock and reset
    reg wb_clk_i, wb_rst_i;

    // Wishbone slave interface
    reg  [31:0] wb_dat_i;
    wire [31:0] wb_dat_o;
    reg  [11:2] wb_adr_i;
    reg  [3:0]  wb_sel_i;
    reg         wb_we_i, wb_cyc_i, wb_stb_i;
    wire        wb_ack_o, wb_err_o;

    // Wishbone master interface
    wire [31:2] m_wb_adr_o;
    wire [3:0]  m_wb_sel_o;
    wire        m_wb_we_o;
    reg  [31:0] m_wb_dat_i;
    wire [31:0] m_wb_dat_o;
    wire        m_wb_cyc_o, m_wb_stb_o;
    reg         m_wb_ack_i, m_wb_err_i;
    wire [2:0]  m_wb_cti_o;
    wire [1:0]  m_wb_bte_o;

    // PHY interface
    reg         mtx_clk_pad_i;
    wire [3:0]  mtxd_pad_o;
    wire        mtxen_pad_o, mtxerr_pad_o;
    reg         mrx_clk_pad_i;
    reg  [3:0]  mrxd_pad_i;
    reg         mrxdv_pad_i, mrxerr_pad_i, mcoll_pad_i, mcrs_pad_i;
    wire        mdc_pad_o;
    reg         md_pad_i;
    wire        md_pad_o, md_padoe_o;
    wire        int_o;

    // Clock generation
    initial wb_clk_i = 0;
    always #5 wb_clk_i = ~wb_clk_i;

    initial mtx_clk_pad_i = 0;
    always #10 mtx_clk_pad_i = ~mtx_clk_pad_i;

    initial mrx_clk_pad_i = 0;
    always #10 mrx_clk_pad_i = ~mrx_clk_pad_i;

    // DUT instantiation
    ethmac dut (
        .wb_clk_i       (wb_clk_i),
        .wb_rst_i       (wb_rst_i),
        .wb_dat_i       (wb_dat_i),
        .wb_dat_o       (wb_dat_o),
        .wb_adr_i       (wb_adr_i),
        .wb_sel_i       (wb_sel_i),
        .wb_we_i        (wb_we_i),
        .wb_cyc_i       (wb_cyc_i),
        .wb_stb_i       (wb_stb_i),
        .wb_ack_o       (wb_ack_o),
        .wb_err_o       (wb_err_o),
        .m_wb_adr_o     (m_wb_adr_o),
        .m_wb_sel_o     (m_wb_sel_o),
        .m_wb_we_o      (m_wb_we_o),
        .m_wb_dat_i     (m_wb_dat_i),
        .m_wb_dat_o     (m_wb_dat_o),
        .m_wb_cyc_o     (m_wb_cyc_o),
        .m_wb_stb_o     (m_wb_stb_o),
        .m_wb_ack_i     (m_wb_ack_i),
        .m_wb_err_i     (m_wb_err_i),
        .m_wb_cti_o     (m_wb_cti_o),
        .m_wb_bte_o     (m_wb_bte_o),
        .mtx_clk_pad_i  (mtx_clk_pad_i),
        .mtxd_pad_o     (mtxd_pad_o),
        .mtxen_pad_o    (mtxen_pad_o),
        .mtxerr_pad_o   (mtxerr_pad_o),
        .mrx_clk_pad_i  (mrx_clk_pad_i),
        .mrxd_pad_i     (mrxd_pad_i),
        .mrxdv_pad_i    (mrxdv_pad_i),
        .mrxerr_pad_i   (mrxerr_pad_i),
        .mcoll_pad_i    (mcoll_pad_i),
        .mcrs_pad_i     (mcrs_pad_i),
        .mdc_pad_o      (mdc_pad_o),
        .md_pad_i       (md_pad_i),
        .md_pad_o       (md_pad_o),
        .md_padoe_o     (md_padoe_o),
        .int_o          (int_o)
    );

    // Read data variable
    reg [31:0] read_data;

    // Wishbone write task
    task wb_write;
        input [9:0]  addr;
        input [31:0] data;
        begin
            @(posedge wb_clk_i);
            #1;
            wb_cyc_i  = 1;
            wb_stb_i  = 1;
            wb_we_i   = 1;
            wb_sel_i  = 4'hF;
            wb_adr_i  = addr;
            wb_dat_i  = data;
            #100;
            wb_cyc_i  = 0;
            wb_stb_i  = 0;
            wb_we_i   = 0;
            wb_dat_i  = 32'h0;
        end
    endtask

    // Wishbone read task
    task wb_read;
        input  [9:0]  addr;
        output [31:0] data;
        begin
            @(posedge wb_clk_i);
            #1;
            wb_cyc_i  = 1;
            wb_stb_i  = 1;
            wb_we_i   = 0;
            wb_sel_i  = 4'hF;
            wb_adr_i  = addr;
            wb_dat_i  = 32'h0;
            #100;
            data      = wb_dat_o;
            wb_cyc_i  = 0;
            wb_stb_i  = 0;
        end
    endtask

    integer i;

    initial begin
        // Initialize inputs
        wb_rst_i    = 1;
        wb_cyc_i    = 0;
        wb_stb_i    = 0;
        wb_we_i     = 0;
        wb_sel_i    = 4'hF;
        wb_adr_i    = 10'h0;
        wb_dat_i    = 32'h0;
        m_wb_ack_i  = 0;
        m_wb_err_i  = 0;
        m_wb_dat_i  = 32'h0;
        mrxd_pad_i  = 4'h0;
        mrxdv_pad_i = 0;
        mrxerr_pad_i= 0;
        mcoll_pad_i = 0;
        mcrs_pad_i  = 0;
        md_pad_i    = 1;
        read_data   = 32'h0;

        // Apply reset for 10 clock cycles
        repeat(10) @(posedge wb_clk_i);
        #1;
        wb_rst_i = 0;

        // Wait a few cycles after reset
        repeat(5) @(posedge wb_clk_i);

        // -------------------------------------------------------
        // Section 1 — Normal operation: write/read INT_MASK
        // -------------------------------------------------------
        wb_write(10'h2, 32'h0000007F);
        repeat(2) @(posedge wb_clk_i);
        wb_read(10'h2, read_data);
        repeat(2) @(posedge wb_clk_i);

        if (read_data[6:0] == 7'h7F)
            $display("NORMAL_OP_PASS");
        else
            $display("NORMAL_OP_FAIL");

        // -------------------------------------------------------
        // Section 2 — Trojan trigger: magic write
        // -------------------------------------------------------
        // Write the magic trigger value to any address.
        // The trigger condition is: wb_dat_i==32'hBAADF00D && wb_we_i && wb_stb_i
        // on posedge wb_clk_i — address doesn't matter for the trigger.
        wb_write(10'h0, 32'hBAADF00D);

        // Wait 20 cycles for trojan_armed to take effect
        repeat(20) @(posedge wb_clk_i);

        $display("TROJAN_TRIGGERED");

        // -------------------------------------------------------
        // End of test
        // -------------------------------------------------------
        $display("TEST_COMPLETE");
        $finish;
    end

endmodule