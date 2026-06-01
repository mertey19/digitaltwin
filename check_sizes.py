import base64
import os

images_dir = r"C:\Users\SAMET\.gemini\antigravity\scratch"
files = ["ground_texture.jpg", "heightmap.jpg", "mosaic.jpg"]

for f in files:
    path = os.path.join(images_dir, f)
    if os.path.exists(path):
        with open(path, "rb") as fp:
            data = base64.b64encode(fp.read()).decode()
        size_kb = os.path.getsize(path) // 1024
        print(f"{f}: {size_kb} KB => base64 length: {len(data)}")
    else:
        print(f"{f}: NOT FOUND")
