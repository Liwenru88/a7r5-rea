"""冻结的批量加密器；解密校验使用另一密码库独立实现。"""
from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
from . import constants
BLOCK=1024
PAYLOAD=1020

class FdatStreamEncrypter:
    """Streaming FDAT encrypter: 750 MB cannot be held in memory.

    Reads plaintext in batches of payload chunks, packs each chunk into a
    1024-byte block (numpy-vectorised sum16), and pushes the packed blocks
    through the AES pipeline. The CBC chain is carried across batches by a
    single CBC encryptor instance, which is exactly equivalent to calling
    encrypt_block() per block because every batch is a whole number of blocks.
    """

    BATCH_BLOCKS = 4096

    def __init__(self, iv: bytes, batch_blocks: int | None = None):
        if len(iv) != 16:
            raise ValueError("IV must be 16 bytes")
        self.iv = iv
        self.batch_blocks = batch_blocks or self.BATCH_BLOCKS
        self.ecb = Cipher(algorithms.AES(constants.key_aes), modes.ECB()).encryptor()
        self.cbc = Cipher(
            algorithms.AES(constants.key_cxd90057_k8), modes.CBC(iv)
        ).encryptor()
        self.blocks_done = 0
        self.first_batch = True

    def encrypt_stream(self, src, dst, total_size: int) -> int:
        """Encrypt exactly total_size plaintext bytes. Returns bytes written."""
        np = _numpy()
        batch_payload = self.batch_blocks * PAYLOAD
        written = 0
        remaining = total_size
        while remaining > 0:
            take = min(batch_payload, remaining)
            chunk = src.read(take)
            if len(chunk) != take:
                raise IOError(
                    "short read: wanted %d got %d (plaintext truncated?)"
                    % (take, len(chunk))
                )
            remaining -= take
            # split into 1020-byte payloads; the final payload of the whole
            # stream is the only short one
            is_final_batch = remaining == 0
            if len(chunk) % PAYLOAD == 0 and is_final_batch:
                # exact multiple: last chunk is full-size and flagged last
                n = len(chunk) // PAYLOAD
                payloads = np.frombuffer(chunk, dtype=np.uint8).reshape(n, PAYLOAD)
                packed = self._pack_batch(n, payloads, last_index=n - 1)
            elif is_final_batch:
                n = len(chunk) // PAYLOAD + 1
                tail = len(chunk) % PAYLOAD
                arr = np.zeros((n, PAYLOAD), dtype=np.uint8)
                arr[:n - 1] = np.frombuffer(chunk[:len(chunk) - tail],
                                            dtype=np.uint8).reshape(n - 1, PAYLOAD)
                arr[n - 1, :tail] = np.frombuffer(chunk[len(chunk) - tail:],
                                                  dtype=np.uint8)
                packed = self._pack_batch(n, arr, last_index=n - 1,
                                          sizes=[PAYLOAD] * (n - 1) + [tail])
            else:
                n = len(chunk) // PAYLOAD
                payloads = np.frombuffer(chunk, dtype=np.uint8).reshape(n, PAYLOAD)
                packed = self._pack_batch(n, payloads, last_index=None)
            if self.first_batch:
                out = self.ecb.update(bytes(packed[:512])) + \
                      self.cbc.update(bytes(packed[512:]))
                self.first_batch = False
            else:
                out = self.cbc.update(bytes(packed))
            dst.write(out)
            written += len(out)
            self.blocks_done += n
        return written

    def _pack_batch(self, n, payloads, last_index, sizes=None):
        """Pack n payloads into n 1024-byte blocks as one contiguous buffer.

        Block layout: [0:2] sum16, [2:4] sizeAndEnd (little endian), [4:] payload,
        padded with 0xff. sum16 covers bytes [2:1024], which the reference
        pack_block computes with the sum field still zeroed.
        """
        np = _numpy()
        buf = np.full((n, BLOCK), 0xFF, dtype=np.uint8)
        buf[:, 4:] = payloads
        # a short final payload is padded with 0xff, not with the caller's zeros
        if sizes is not None:
            for i, sz in enumerate(sizes):
                if sz < PAYLOAD:
                    buf[i, 4 + sz:] = 0xFF
        # zero the header (both the sum field and the sizeAndEnd field)
        buf[:, 0:4] = 0
        sae = np.array(sizes, dtype=np.uint16) if sizes is not None \
            else np.full(n, PAYLOAD, dtype=np.uint16)
        if last_index is not None:
            sae[last_index] |= 0x8000
        # explicit little-endian split; avoids depending on host byte order
        buf[:, 2] = (sae & 0xFF).astype(np.uint8)
        buf[:, 3] = (sae >> 8).astype(np.uint8)
        words = buf.view("<u2").reshape(n, BLOCK // 2)
        sums = (words.sum(axis=1, dtype=np.uint64) & 0xFFFF).astype(np.uint16)
        buf[:, 0] = (sums & 0xFF).astype(np.uint8)
        buf[:, 1] = (sums >> 8).astype(np.uint8)
        return buf.reshape(-1)

def _numpy():
    import numpy as np
    return np
