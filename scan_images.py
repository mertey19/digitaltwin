import os
import shutil
import json

source_folder = r"C:\Users\SAMET\Downloads\images2"
dest_folder = r"C:\Users\SAMET\.gemini\antigravity\scratch\images2"

os.makedirs(dest_folder, exist_ok=True)

image_extensions = {'.jpg', '.jpeg', '.png', '.bmp', '.gif', '.webp', '.tiff', '.tif'}
files_info = []

if os.path.exists(source_folder):
    for f in os.listdir(source_folder):
        ext = os.path.splitext(f)[1].lower()
        if ext in image_extensions:
            src = os.path.join(source_folder, f)
            dst = os.path.join(dest_folder, f)
            shutil.copy2(src, dst)
            size = os.path.getsize(src)
            files_info.append({"name": f, "size": size, "ext": ext})
            print(f"Copied: {f} ({size} bytes)")
else:
    print(f"Folder not found: {source_folder}")
    files_info = []

with open(r"C:\Users\SAMET\.gemini\antigravity\scratch\images_list.json", "w") as fp:
    json.dump(files_info, fp, indent=2)

print(f"\nTotal images found: {len(files_info)}")
print("Done. images_list.json written.")
