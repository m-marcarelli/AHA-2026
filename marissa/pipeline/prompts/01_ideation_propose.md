You are a hardware security researcher for the IEEE HOST 2026 AHA Challenge.

Given the following Ethernet MAC (ethmac) RTL, propose ONE high-CVSS, stealthy hardware Trojan concept.

ethmac RTL (ethmac.v excerpt):
```verilog
{rtl_context}
```

Key signals available in ethmac.v:
- Wishbone bus: wb_dat_i[31:0], wb_adr_i[11:2], wb_we_i, wb_cyc_i, wb_stb_i, wb_clk_i, wb_rst_i
- WB output: wb_dat_o[31:0] (driven via temp_wb_dat_o_reg with ETH_REGISTERED_OUTPUTS)
- TX PHY: mtxd_pad_o[3:0], mtxen_pad_o
- RX PHY: mrxd_pad_i[3:0], mrxdv_pad_i
- The existing always @(posedge wb_clk_i or posedge wb_rst_i) block is ideal for a trigger latch.
- The assign wb_dat_o[31:0] = temp_wb_dat_o_reg; line is a good payload target.

Provide:
1. Trojan name
2. Target file (ethmac.v is preferred for simplicity)
3. Trigger condition
4. Payload (what does it do?)
5. CVSS estimate and justification
6. Why it would be hard to detect
