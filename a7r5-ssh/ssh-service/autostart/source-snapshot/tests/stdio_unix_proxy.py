"""仅本机QEMU的OpenSSH ProxyCommand；Unix socket双向转发。"""
import os
import select
import socket
import sys

connection=socket.socket(socket.AF_UNIX,socket.SOCK_STREAM)
connection.connect(sys.argv[1]);stdin_open=True
while True:
    ready,_,_=select.select([connection]+([0] if stdin_open else []),[],[],30)
    if not ready:raise SystemExit(80)
    if connection in ready:
        raw=connection.recv(16384)
        if not raw:break
        while raw:
            used=os.write(1,raw);raw=raw[used:]
    if 0 in ready:
        raw=os.read(0,4096)
        if not raw:connection.shutdown(socket.SHUT_WR);stdin_open=False
        else:connection.sendall(raw)
connection.close()
