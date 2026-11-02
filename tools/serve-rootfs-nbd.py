#!/usr/bin/env python3
"""Serve a raw ext4 image through the old-style NBD protocol.

The default is read-only. The target initramfs mounts the exported image
read-only and supplies a tmpfs overlay, so this process never changes the
NixOS image during a test.
"""

from __future__ import annotations

import argparse
import errno
import os
import socket
import struct
import sys
import time
from pathlib import Path

NBD_MAGIC = b"NBDMAGIC"
NBD_OLD_MAGIC = b"\x00\x00\x42\x02\x81\x86\x12\x53"
NBD_REQUEST_MAGIC = 0x25609513
NBD_REPLY_MAGIC = 0x67446698
NBD_FLAG_READ_ONLY = 2
NBD_CMD_MASK = 0xFFFF
NBD_CMD_READ = 0
NBD_CMD_WRITE = 1
NBD_CMD_DISC = 2
NBD_CMD_FLUSH = 3
NBD_CMD_TRIM = 4
NBD_CMD_WRITE_ZEROES = 6
REQUEST_SIZE = 28
MAX_REQUEST = 16 * 1024 * 1024


def recv_exact(conn: socket.socket, size: int) -> bytes:
    chunks = bytearray()
    while len(chunks) < size:
        data = conn.recv(size - len(chunks))
        if not data:
            raise ConnectionError("client disconnected")
        chunks.extend(data)
    return bytes(chunks)


def send_reply(conn: socket.socket, handle: bytes, error: int = 0, data: bytes = b"") -> None:
    conn.sendall(struct.pack(">II8s", NBD_REPLY_MAGIC, error, handle))
    if data:
        conn.sendall(data)


def serve_connection(
    conn: socket.socket,
    image: Path,
    size: int,
    read_only: bool,
) -> None:
    try:
        conn.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
    except OSError:
        # A socketpair is useful for the offline protocol self-test and has no
        # TCP layer. Real TCP connections still get the low-latency setting.
        pass
    flags = NBD_FLAG_READ_ONLY if read_only else 0
    handshake = (
        NBD_MAGIC
        + NBD_OLD_MAGIC
        + struct.pack(">Q", size)
        + struct.pack(">I", flags)
        + bytes(124)
    )
    conn.sendall(handshake)
    reads = 0
    read_bytes = 0
    last_report = time.monotonic()
    with image.open("r+b" if not read_only else "rb", buffering=0) as stream:
        while True:
            request = recv_exact(conn, REQUEST_SIZE)
            magic, request_type, handle, offset, length = struct.unpack(
                ">II8sQI", request
            )
            if magic != NBD_REQUEST_MAGIC:
                raise ValueError(f"bad request magic 0x{magic:08x}")
            command = request_type & NBD_CMD_MASK
            if length > MAX_REQUEST:
                send_reply(conn, handle, errno.EINVAL)
                continue
            if offset > size or length > size - offset:
                send_reply(conn, handle, errno.EINVAL)
                continue
            if command == NBD_CMD_READ:
                stream.seek(offset)
                data = stream.read(length)
                if len(data) != length:
                    send_reply(conn, handle, errno.EIO)
                    continue
                send_reply(conn, handle, data=data)
                reads += 1
                read_bytes += length
                now = time.monotonic()
                if reads == 1 or now - last_report >= 10:
                    print(
                        f"NBD reads={reads} bytes={read_bytes} last_offset={offset}",
                        flush=True,
                    )
                    last_report = now
            elif command == NBD_CMD_WRITE:
                payload = recv_exact(conn, length)
                if read_only:
                    send_reply(conn, handle, errno.EROFS)
                    continue
                stream.seek(offset)
                stream.write(payload)
                stream.flush()
                send_reply(conn, handle)
            elif command in (NBD_CMD_FLUSH, NBD_CMD_TRIM, NBD_CMD_WRITE_ZEROES):
                if command == NBD_CMD_WRITE_ZEROES and read_only:
                    send_reply(conn, handle, errno.EROFS)
                else:
                    if command == NBD_CMD_WRITE_ZEROES:
                        stream.seek(offset)
                        remaining = length
                        zeroes = bytes(min(1024 * 1024, remaining))
                        while remaining:
                            chunk = min(len(zeroes), remaining)
                            stream.write(zeroes[:chunk])
                            remaining -= chunk
                    stream.flush()
                    send_reply(conn, handle)
            elif command == NBD_CMD_DISC:
                print(f"NBD disconnect: reads={reads} bytes={read_bytes}", flush=True)
                return
            else:
                send_reply(conn, handle, errno.EOPNOTSUPP)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--image", required=True, type=Path)
    parser.add_argument("--bind", default="0.0.0.0")
    parser.add_argument("--port", default=10809, type=int)
    parser.add_argument(
        "--allow-client",
        help="accept connections only from this IPv4 address during a USB test",
    )
    parser.add_argument(
        "--allow-write",
        action="store_true",
        help="allow writes to the image; unsafe for the canonical test artifact",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    image = args.image.resolve()
    if not image.is_file():
        print(f"image does not exist: {image}", file=sys.stderr)
        return 2
    size = image.stat().st_size
    if size == 0:
        print("refusing to export an empty image", file=sys.stderr)
        return 2
    if args.port < 1 or args.port > 65535:
        print("port must be between 1 and 65535", file=sys.stderr)
        return 2

    read_only = not args.allow_write
    mode = "read-only" if read_only else "read-write"
    print(
        f"Serving {image} ({size} bytes, {mode}) on {args.bind}:{args.port}",
        flush=True,
    )
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as server:
        server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        server.bind((args.bind, args.port))
        server.listen(1)
        while True:
            conn, address = server.accept()
            if args.allow_client and address[0] != args.allow_client:
                conn.close()
                print(f"Rejected non-target NBD client {address[0]}", flush=True)
                continue
            print(f"NBD client connected from {address[0]}:{address[1]}", flush=True)
            try:
                with conn:
                    serve_connection(conn, image, size, read_only)
            except (ConnectionError, OSError) as error:
                print(f"NBD client disconnected: {error}", file=sys.stderr, flush=True)
            except Exception as error:
                print(f"NBD protocol error: {error}", file=sys.stderr, flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
