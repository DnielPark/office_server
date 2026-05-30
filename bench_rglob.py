import time
from pathlib import Path

t0 = time.time()
path = Path("E:\\openshare\\sungsan1")
total = 0
for item in path.rglob("*"):
    if item.name == ".backup":
        continue
    if item.is_file():
        total += item.stat().st_size
t1 = time.time()
print(f"Size: {total} bytes ({total/1024**3:.2f} GB)")
print(f"Time: {t1-t0:.3f} sec")
