"""仅记录本次模拟会话的宿主单调时钟，不影响客体协议。"""
import json
import time
from contextlib import contextmanager


@contextmanager
def stage(timings, name):
    start = time.perf_counter()
    try:
        yield
    finally:
        timings[name] = round((time.perf_counter() - start) * 1000, 3)


def record(directory, value):
    with (directory / 'latency.jsonl').open('a') as stream:
        stream.write(json.dumps(value, ensure_ascii=False) + '\n')
