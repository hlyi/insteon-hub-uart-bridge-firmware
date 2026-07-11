# Firmware Binaries

Prebuilt firmware images for the Insteon Hub 2245-222 (PIC32MX695F512H).

| File | Use Case |
|------|----------|
| `firmware_full.hex` | First-time flash via ICSP programmer (Pickit, ICD, Snap, or Pico probe) |
| `firmware_upgrade.hex` | Upgrade image uploaded through the command port using `tools/brg-service.py <ip> firmware_upgrade -f fw/firmware_upgrade.hex` |

## Version

Current firmware version is embedded in the hex files. After flashing, run:

```bash
echo "version" | nc <ip> 1984
```

Expected: `v1.x.x (<git_hash>)`
