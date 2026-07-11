# Custom Firmware for Insteon Hub v2

This firmware replaces the Insteon Hub 2245-222 stock firmware with a custom firmware designed for Home Assistant.

**What you gain:**

- Completely reliable local control with instant status updates
- Direct PLM access over TCP (port 9761) — compatible with any Home Assistant Insteon integration
- Full bridge status monitoring via command port (1984)

**What you lose:**

- Insteon app and cloud service support
- Remote access via Insteon's servers
- Hub security features

## Background

The Insteon Hub v2 (model 2245-222) is built around a PIC32MX695F512H microcontroller with an LAN8720 Ethernet PHY. The MCU runs the Insteon application stack that integrates the PLM with the Insteon app and cloud service. The stock firmware relies on Insteon's cloud service for control and status updates, which introduces latency, single points of failure, and dependency on a defunct service.

Home Assistant's built-in Insteon integration can communicate with the stock v2 hub over local HTTP using polling, but this approach is unreliable — status updates are delayed, commands are slow, and the hub's HTTP API frequently has incomplete PLM messages.

This custom firmware replaces the entire stock firmware while keeping the same hardware. It presents a raw PLM TCP tunnel on port 9761, similar to the Insteon Hub v1, giving Home Assistant direct and instant access to the Insteon powerline network without cloud intermediaries.

## Install and Update custom firmware

### First Time Installation

See the detailed guide at `docs/first_flash/README.md` for step-by-step instructions covering:

- **Prerequisites:** Microchip programmer (Pickit/ICD/Snap) or DIY RP2040-based programmer
- **Backup** the Hub's original firmware
- **Power options:** mains power or external 3.3V supply
- **ICSP connector location** and pinout
- **Flashing** `fw/firmware_full.hex`
- **Verification** and troubleshooting

### Update firmware

After the bootloader is installed, copy `fw/firmware_upgrade.hex` to the host machine and use the bridge's command port (1984) to upload:

```
tools/brg-service.py <ip> firmware_upgrade -f fw/firmware_upgrade.hex
```

## HomeAssistant Integration

The custom firmware works with the Home Assistant Insteon integration. Select **Insteon Hub v1** when configuring the Insteon Integration, and connect to the Hub's IP address on TCP port 9761.

When the TCP connection drops unexpectedly — for example after a Hub reboot or network cable disconnect/reconnect — pyinsteon does not detect the disconnection. This results in lost status updates from Insteon devices until the integration is re-connected. While sending a new command from Home Assistant can trigger a reconnect, this can take a very long time.

A companion custom component (`insteon_uart_bridge_monitor`) is available for monitoring the bridge's status — reachability, PLM client connection state, firmware version, and auto-reload on disconnect. See [github.com/hlyi/insteon-hub-uart-bridge-monitor](https://github.com/hlyi/insteon-hub-uart-bridge-monitor) for details.

## Repository Structure

```
repo/
├── docs/
│   └── first_flash/        — First-time flashing guide images
├── fw/
│   ├── firmware_full.hex   — Full firmware (for first flash via ICSP)
│   └── firmware_upgrade.hex — Upgrade image (for bootloader update)
└── tools/
    └── pic32prog_tools/     — PIC32 programmer (Raspberry Pi Pico probe)
        ├── pic32probe.uf2   — Pico firmware for the programmer
        └── pic32prog        — CLI programming tool
```

## License

GPL-2.0 — see `LICENSE`.
