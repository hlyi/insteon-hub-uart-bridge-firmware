#!/usr/bin/env python3
import socket
import sys
import struct

CMDS = ["enter_bootloader", "reboot_hub", "version", "reset_plm", "reset_lan", "test_error", "bridge_status", "firmware_load_img", "firmware_trig_upgrade", "firmware_upgrade"]

SPIFLASH_SECTOR_SIZE = 4096
SPIFLASH_CAPACITY = 2 * 1024 * 1024

def crc16(data):
    crc = 0x0000
    for byte in data:
        crc ^= byte << 8
        for _ in range(8):
            if crc & 0x8000:
                crc = (crc << 1) ^ 0x1021
            else:
                crc <<= 1
    return crc & 0xFFFF

def _recv_all(sock, size):
    data = b""
    while len(data) < size:
        try:
            chunk = sock.recv(size - len(data))
        except socket.timeout:
            return None
        if not chunk:
            return None
        data += chunk
    return data

def parse_hex(s):
    if s.startswith("0x") or s.startswith("0X"):
        return int(s, 16)
    return int(s)

def build_spi_rdsr(chip):
    buf = b"spi rdsr "
    buf += bytes([chip])
    return buf

def handle_spi_rdsr(sock, chip):
    req = build_spi_rdsr(chip)
    sock.sendall(req)
    resp = _recv_all(sock, 12)
    if resp is None:
        print("Connection closed")
        return
    if not resp.startswith(b"spi rdsr "):
        print(f"Unexpected response: {resp!r}")
        return
    status = resp[9]
    if status != 0:
        print(f"Error {status}")
        return
    sr = resp[10]
    print(f"Chip {chip}: Status Register = 0x{sr:02X}")
    print(f"  WIP (busy):  {(sr >> 0) & 1}")
    print(f"  WEL:         {(sr >> 1) & 1}")
    print(f"  BP0:         {(sr >> 2) & 1}")
    print(f"  BP1:         {(sr >> 3) & 1}")
    print(f"  BP2:         {(sr >> 4) & 1}")
    print(f"  BP3:         {(sr >> 5) & 1}")
    print(f"  SRWD:        {(sr >> 7) & 1}")

def build_spi_wrsr(chip, value):
    buf = b"spi wrsr "
    buf += bytes([chip, value])
    return buf

def handle_spi_wrsr(sock, chip, value):
    req = build_spi_wrsr(chip, value)
    sock.sendall(req)
    resp = _recv_all(sock, 11)
    if resp is None:
        print("Connection closed")
        return
    if not resp.startswith(b"spi wrsr "):
        print(f"Unexpected response: {resp!r}")
        return
    status = resp[9]
    if status == 0:
        print(f"Chip {chip}: Status register written to 0x{value:02X}")
    else:
        print(f"Error {status}")

def build_spi_read(chip, addr, length):
    buf = b"spi read "
    buf += bytes([chip])
    buf += struct.pack(">I", addr)[1:]
    buf += struct.pack(">I", length)
    return buf

def build_spi_chipid(chip):
    buf = b"spi chipid "
    buf += bytes([chip])
    return buf

def build_spi_write(chip, addr, data):
    buf = b"spi write "
    buf += bytes([chip])
    buf += struct.pack(">I", addr)[1:]
    buf += struct.pack(">I", len(data))
    buf += data
    c = crc16(data)
    buf += struct.pack(">H", c)
    return buf

def build_spi_erase_chip(chip):
    buf = b"spi erase_chip "
    buf += bytes([chip])
    return buf

def build_spi_erase_sector(chip, addr):
    buf = b"spi erase_sector "
    buf += bytes([chip])
    buf += struct.pack(">I", addr)[1:]
    return buf

def _spi_read_chunk(sock, chip, addr, length):
    req = build_spi_read(chip, addr, length)
    sock.sendall(req)
    resp = _recv_all(sock, length + 12)
    if resp is None:
        return None, False, "connection closed"
    if not resp.startswith(b"spi read "):
        return None, False, "unexpected response"
    status = resp[9]
    if status != 0:
        return None, False, f"error {status}"
    data = resp[10:-2]
    crc_recv = struct.unpack(">H", resp[-2:])[0]
    crc_calc = crc16(data)
    return data, crc_recv == crc_calc, None

def handle_flash_read(sock, addr, length, outfile=None):
    chunk_size = 512
    all_data = bytearray()
    for offset in range(0, length, chunk_size):
        this_len = min(chunk_size, length - offset)
        req = b"flash_read "
        req += struct.pack(">I", addr + offset)[1:]
        req += struct.pack(">I", this_len)
        sock.sendall(req)
        resp = _recv_all(sock, 12 + this_len)
        if resp is None:
            print("Connection closed")
            return
        if not resp.startswith(b"flash_read "):
            print(f"Unexpected response: {resp!r}")
            return
        status = resp[11]
        if status != 0:
            errs = {1: "bad address", 2: "bad length"}
            print(f"Read failed at 0x{addr+offset:06X}: error {status} ({errs.get(status, 'unknown')})")
            return
        all_data.extend(resp[12:])

    if outfile:
        with open(outfile, "wb") as f:
            f.write(all_data)
        print(f"Wrote {len(all_data)} bytes to {outfile}")
    else:
        print(f"Read {len(all_data)} bytes from 0x{addr:06X}:")
        for i in range(0, len(all_data), 16):
            chunk = all_data[i:i+16]
            hex_str = " ".join(f"{b:02X}" for b in chunk)
            ascii_str = "".join(chr(b) if 32 <= b < 127 else "." for b in chunk)
            print(f"  {addr+i:06X}  {hex_str:<48s}  {ascii_str}")

def handle_spi_read(sock, chip, addr, length, outfile=None):
    chunk_size = 512
    all_data = bytearray()
    for offset in range(0, length, chunk_size):
        this_len = min(chunk_size, length - offset)
        data, crc_ok, err = _spi_read_chunk(sock, chip, addr + offset, this_len)
        if err:
            print(f"Read failed at 0x{addr+offset:06X}: {err}")
            return
        if not crc_ok:
            print(f"CRC mismatch at 0x{addr+offset:06X}")
            return
        all_data.extend(data)

    if outfile:
        with open(outfile, "wb") as f:
            f.write(all_data)
        print(f"Wrote {len(all_data)} bytes to {outfile}")
    else:
        print(f"Read {len(all_data)} bytes from 0x{addr:06X} chip {chip}:")
        for i in range(0, len(all_data), 16):
            chunk = all_data[i:i+16]
            hex_str = " ".join(f"{b:02X}" for b in chunk)
            ascii_str = "".join(chr(b) if 32 <= b < 127 else "." for b in chunk)
            print(f"  {addr+i:06X}  {hex_str:<48s}  {ascii_str}")

def handle_spi_read_full(sock, chip, outfile=None):
    total = 2 * 1024 * 1024
    chunk_size = 512
    all_data = bytearray()
    for offset in range(0, total, chunk_size):
        remaining = total - offset
        this_len = min(chunk_size, remaining)
        data, crc_ok, err = _spi_read_chunk(sock, chip, offset, this_len)
        if err:
            print(f"Read failed at 0x{offset:06X}: {err}")
            return
        if not crc_ok:
            print(f"CRC mismatch at 0x{offset:06X}")
            return
        all_data.extend(data)
        if len(all_data) % (64 * 1024) == 0:
            print(f"  ... {len(all_data)} / {total} bytes", flush=True)

    if outfile:
        with open(outfile, "wb") as f:
            f.write(all_data)
        print(f"Read complete: {len(all_data)} bytes written to {outfile}")
    else:
        print(f"Read complete: {len(all_data)} bytes, OK")


def handle_spi_chipid(sock, chip):
    req = build_spi_chipid(chip)
    sock.sendall(req)
    resp = _recv_all(sock, 12)
    if resp is None:
        print("Connection closed")
        return
    if not resp.startswith(b"spi chipid "):
        print(f"Unexpected response: {resp!r}")
        return
    status = resp[11]
    if status != 0:
        print(f"Error {status}")
        return
    more = _recv_all(sock, 5)
    if more is None:
        print("Connection closed")
        return
    resp += more
    jedec = resp[12:15]
    manuf = resp[15]
    device = resp[16]
    print(f"Chip {chip}:")
    print(f"  JEDEC ID:  {jedec[0]:02X} {jedec[1]:02X} {jedec[2]:02X}")
    print(f"  Manuf ID:  {manuf:02X}")
    print(f"  Device ID: {device:02X}")


def _erase_sectors(sock, chip, start_addr, end_addr):
    first = start_addr & ~(SPIFLASH_SECTOR_SIZE - 1)
    last_sector = (end_addr - 1) & ~(SPIFLASH_SECTOR_SIZE - 1)
    for sa in range(first, last_sector + SPIFLASH_SECTOR_SIZE, SPIFLASH_SECTOR_SIZE):
        req = build_spi_erase_sector(chip, sa)
        sock.sendall(req)
        resp = _recv_all(sock, 11)
        if resp is None:
            print(f"Connection closed at 0x{sa:06X}")
            return False
        if not resp.startswith(b"spi erase "):
            print(f"Unexpected erase response at 0x{sa:06X}: {resp!r}")
            return False
        status = resp[10]
        if status != 0:
            print(f"Erase failed at 0x{sa:06X}: error {status}")
            return False
    return True

def _write_chunk(sock, chip, addr, data_bytes):
    req = build_spi_write(chip, addr, data_bytes)
    sock.sendall(req)
    resp = _recv_all(sock, 11)
    if resp is None:
        return "connection closed"
    if not resp.startswith(b"spi write "):
        return f"unexpected response: {resp!r}"
    status = resp[10]
    if status != 0:
        errs = {1: "bad chip", 2: "bad address", 3: "bad length",
                4: "addr+len overflow", 5: "SPI failure", 6: "CRC mismatch"}
        return f"error {status} ({errs.get(status, 'unknown')})"
    return None

def _spi_write_with_erase(sock, chip, addr, data_bytes):
    if not _erase_sectors(sock, chip, addr, addr + len(data_bytes)):
        return False
    err = _write_chunk(sock, chip, addr, data_bytes)
    if err:
        print(f"Write failed at 0x{addr:06X}: {err}")
        return False
    return True

def handle_spi_write(sock, chip, addr, data_bytes):
    if _spi_write_with_erase(sock, chip, addr, data_bytes):
        print(f"Wrote {len(data_bytes)} bytes to 0x{addr:06X} chip {chip}: OK")


def _spi_write_data(sock, chip, addr, data, label=""):
    total = len(data)
    chunk_size = 512
    if not _erase_sectors(sock, chip, addr, addr + total):
        return
    for offset in range(0, total, chunk_size):
        chunk = data[offset:offset + chunk_size]
        err = _write_chunk(sock, chip, addr + offset, chunk)
        if err:
            print(f"Failed at 0x{addr+offset:06X}: {err}")
            return
        written = offset + len(chunk)
        if written % (64 * 1024) == 0 or written == total:
            print(f"  ... {written} / {total} bytes", flush=True)
    print(f"Write complete: {total} bytes{label} to chip {chip} at 0x{addr:06X}")

def handle_spi_write_file(sock, chip, addr, filepath):
    with open(filepath, "rb") as f:
        data = f.read()
    _spi_write_data(sock, chip, addr, data, f" from {filepath}")


def handle_spi_erase(sock, mode, addr, chip):
    if mode == "chip":
        req = build_spi_erase_chip(chip)
    else:
        req = build_spi_erase_sector(chip, addr)
    sock.sendall(req)
    resp = _recv_all(sock, 11)
    if resp is None:
        print("Connection closed")
        return

    if not resp.startswith(b"spi erase "):
        print(f"Unexpected response: {resp!r}")
        return

    status = resp[10]
    if status == 0:
        if mode == "chip":
            print("Chip erase: OK")
        else:
            print(f"Sector erase at 0x{addr:06X}: OK")
    else:
        errs = {1: "SPI failure", 2: "invalid sub-data"}
        print(f"Error {status}: {errs.get(status, 'unknown')}")


def send_text(sock, cmd):
    sock.sendall(cmd.encode() + b"\n")
    resp = b""
    try:
        resp = sock.recv(1024)
    except socket.timeout:
        if not resp:
            print("Error: no response received (timeout)", file=sys.stderr)
            return
    print(resp.decode(errors="replace"), end="")


def run_cmd(sock, args):
    if not args:
        return

    if args[0] == "spi":
        if len(args) < 2:
            print("spi: missing subcommand (rdsr, read, chipid, write, erase)")
            return
        sub = args[1]

        if sub == "rdsr":
            if len(args) < 3:
                print("Usage: spi rdsr <chip>")
                return
            chip = int(args[2])
            handle_spi_rdsr(sock, chip)

        elif sub == "wrsr":
            if len(args) < 4:
                print("Usage: spi wrsr <chip> <value_hex>")
                return
            chip = int(args[2])
            value = parse_hex(args[3])
            handle_spi_wrsr(sock, chip, value)

        elif sub == "read":
            pos_args = [a for a in args[2:] if a != "-r"]
            outfile = None
            if "-r" in args:
                idx = args.index("-r")
                if idx + 1 < len(args):
                    outfile = args[idx + 1]
                    pos_args = [a for a in args[2:] if a not in ("-r", outfile)]
            if len(pos_args) == 1:
                chip = int(pos_args[0])
                handle_spi_read_full(sock, chip, outfile)
            elif len(pos_args) == 3:
                chip = int(pos_args[0])
                addr = parse_hex(pos_args[1])
                length = int(pos_args[2])
                handle_spi_read(sock, chip, addr, length, outfile)
            else:
                print("Usage: spi read [-r <file>] <chip> [<addr_hex> <len>]")
                return

        elif sub == "chipid":
            if len(args) != 3:
                print("Usage: spi chipid <chip>")
                return
            chip = int(args[2])
            handle_spi_chipid(sock, chip)

        elif sub == "write":
            pos_args = [a for a in args[2:] if a != "-w"]
            srcfile = None
            if "-w" in args:
                idx = args.index("-w")
                if idx + 1 < len(args):
                    srcfile = args[idx + 1]
                    pos_args = [a for a in args[2:] if a not in ("-w", srcfile)]
            if srcfile:
                if len(pos_args) < 1 or len(pos_args) > 2:
                    print("Usage: spi write -w <file> <chip> [<addr_hex=0>]")
                    return
                chip = int(pos_args[0])
                addr = parse_hex(pos_args[1]) if len(pos_args) >= 2 else 0
                handle_spi_write_file(sock, chip, addr, srcfile)
            else:
                if len(pos_args) < 3:
                    print("Usage: spi write <chip> <addr_hex> <hex_bytes...>")
                    return
                chip = int(pos_args[0])
                addr = parse_hex(pos_args[1])
                hexdata = "".join(pos_args[2:]).replace(" ", "")
                data_bytes = bytes.fromhex(hexdata)
                handle_spi_write(sock, chip, addr, data_bytes)

        elif sub == "pgt":
            if len(args) < 5:
                print("Usage: spi pgt <chip> <addr_hex> <byte_hex>")
                return
            chip = int(args[2])
            addr = parse_hex(args[3])
            wdata = parse_hex(args[4])
            req = b"spi pgt " + bytes([chip]) + struct.pack(">I", addr)[1:] + bytes([wdata])
            sock.sendall(req)
            resp = _recv_all(sock, 16)
            if resp is None:
                print("Connection closed")
                return
            if not resp.startswith(b"spi pgt "):
                print(f"Unexpected response: {resp!r}")
                return
            chip_r = resp[8]
            status = resp[9]
            wdata_r = resp[10]
            rdata_r = resp[11]
            sr0 = resp[12]
            sr1 = resp[13]
            sr2 = resp[14]
            print(f"Chip {chip_r}: status={status} w=0x{wdata_r:02X} r=0x{rdata_r:02X} "
                  f"sr0=0x{sr0:02X} sr1=0x{sr1:02X} sr2=0x{sr2:02X}")
            if status == 0:
                print("  PASS: write+read verified")
            elif status == 1:
                print("  FAIL: WREN did not set WEL")
            elif status == 2:
                print("  FAIL: Byte-Program failed")
            elif status == 3:
                print("  FAIL: Read after write failed")
            elif status == 4:
                print("  FAIL: Verify mismatch")
            else:
                print(f"  FAIL: unknown status {status}")

        elif sub == "erase_chip":
            if len(args) < 3:
                print("Usage: spi erase_chip <chip>")
                return
            chip = int(args[2])
            handle_spi_erase(sock, "chip", None, chip)
        elif sub == "erase_sector":
            if len(args) < 4:
                print("Usage: spi erase_sector <chip> <addr_hex>")
                return
            chip = int(args[2])
            addr = parse_hex(args[3])
            handle_spi_erase(sock, "sector", addr, chip)

        else:
            print(f"Unknown spi subcommand: {sub}")

    elif args[0] == "flash":
        if len(args) < 2:
            print("flash: missing subcommand (read)")
            return
        sub = args[1]
        if sub == "read":
            pos_args = [a for a in args[2:] if a != "-r"]
            outfile = None
            if "-r" in args:
                idx = args.index("-r")
                if idx + 1 < len(args):
                    outfile = args[idx + 1]
                    pos_args = [a for a in args[2:] if a not in ("-r", outfile)]
            if len(pos_args) == 0:
                addr = 96 * 1024
                length = 512 * 1024 - 96 * 1024
            elif len(pos_args) == 2:
                addr = parse_hex(pos_args[0])
                length = int(pos_args[1])
            else:
                print("Usage: flash read [-r <file>] [<addr_hex> <len>]")
                return
            handle_flash_read(sock, addr, length, outfile)
        else:
            print(f"Unknown flash subcommand: {sub}")

    elif args[0] in ("firmware_load_img", "firmware_upgrade"):
        if "-f" not in args:
            print(f"Usage: {args[0]} -f <firmware_file>")
            return
        idx = args.index("-f")
        if idx + 1 >= len(args):
            print(f"Usage: {args[0]} -f <firmware_file>")
            return
        filepath = args[idx + 1]
        with open(filepath, "rb") as f:
            fw_data = f.read()
        payload = b"FWUP" + struct.pack("<I", len(fw_data)) + fw_data
        run_cmd(sock, ["spi", "wrsr", "2", "0x00"])
        _spi_write_data(sock, 2, 0, payload, " firmware update image")
        if args[0] == "firmware_upgrade":
            run_cmd(sock, ["firmware_trig_upgrade"])

    elif args[0] in CMDS:
        send_text(sock, args[0])

    else:
        print(f"Unknown command: {args[0]}")


def main():
    text_cmds = [c for c in CMDS if c not in ("firmware_load_img", "firmware_upgrade")]
    epilog = (
        "Commands:\n"
        f"  text: {', '.join(text_cmds)}\n"
        "  spi:  spi read [-r <file>] <chip> [<addr> <len>]\n"
        "        spi write [-w <file>] <chip> [<addr=0>] [<hex...>]\n"
        "        spi chipid|rdsr|wrsr|pgt|erase_chip|erase_sector <chip> [...]\n"
        "  flash: flash read [-r <file>] [<addr=0x18000> <len=0x68000>]\n"
        "  firmware_load_img: firmware_load_img -f <file>\n"
        "  firmware_upgrade: firmware_upgrade -f <file>\n"
    )
    ap = argparse.ArgumentParser(
        description="Send commands to Insteon Hub UART Bridge service port (1984).",
        epilog=epilog, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("ip", help="Target IP address")
    ap.add_argument("cmd", nargs="*", help="Command and arguments")
    args, unknown = ap.parse_known_args()
    args.cmd = args.cmd + unknown

    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.settimeout(5)
    try:
        sock.connect((args.ip, 1984))
    except Exception as e:
        print(f"Connection failed: {e}", file=sys.stderr)
        sys.exit(1)

    if args.cmd:
        run_cmd(sock, args.cmd)
    else:
        print("Interactive mode. Commands: " + ", ".join(CMDS) + " | spi ... | flash ... | quit")
        while True:
            try:
                line = input("> ").strip()
            except (EOFError, KeyboardInterrupt):
                break
            if not line:
                continue
            if line == "quit":
                break
            parts = line.split()
            if parts[0] not in CMDS and parts[0] not in ("spi", "flash"):
                print(f"Unknown command. Available: {', '.join(CMDS)} or spi/flash ...")
                continue
            run_cmd(sock, parts)

    sock.close()


if __name__ == "__main__":
    import argparse
    main()
