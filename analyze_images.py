import cv2
import numpy as np
import json
import os
from pathlib import Path

images_dir = r"C:\Users\SAMET\.gemini\antigravity\scratch\images2"
output_dir = r"C:\Users\SAMET\.gemini\antigravity\scratch"

image_files = sorted([f for f in os.listdir(images_dir) if f.endswith('.JPG')])
print(f"Analyzing {len(image_files)} images...")

# We'll extract color palette and basic scene info from each image
scene_data = []
all_colors = []

for i, fname in enumerate(image_files):
    path = os.path.join(images_dir, fname)
    img = cv2.imread(path)
    if img is None:
        continue
    
    h, w = img.shape[:2]
    
    # Downsample for analysis
    small = cv2.resize(img, (320, 240))
    
    # Convert to RGB
    small_rgb = cv2.cvtColor(small, cv2.COLOR_BGR2RGB)
    
    # Get dominant colors via k-means
    pixels = small_rgb.reshape(-1, 3).astype(np.float32)
    k = 5
    criteria = (cv2.TERM_CRITERIA_EPS + cv2.TERM_CRITERIA_MAX_ITER, 20, 1.0)
    _, labels, centers = cv2.kmeans(pixels, k, None, criteria, 3, cv2.KMEANS_RANDOM_CENTERS)
    centers = centers.astype(int)
    
    # Count label frequencies
    unique, counts = np.unique(labels, return_counts=True)
    color_freq = sorted(zip(counts, centers.tolist()), reverse=True)
    dominant_colors = [{"r": c[0], "g": c[1], "b": c[2], "freq": int(cnt)} 
                       for cnt, c in color_freq]
    
    # Compute brightness/contrast stats
    gray = cv2.cvtColor(small, cv2.COLOR_BGR2GRAY)
    brightness = float(np.mean(gray))
    contrast = float(np.std(gray))
    
    # Edge density (to estimate scene complexity)
    edges = cv2.Canny(gray, 50, 150)
    edge_density = float(np.sum(edges > 0) / edges.size)
    
    # Detect green regions (vegetation)
    hsv = cv2.cvtColor(small, cv2.COLOR_BGR2HSV)
    green_mask = cv2.inRange(hsv, (35, 40, 40), (85, 255, 255))
    green_ratio = float(np.sum(green_mask > 0) / green_mask.size)
    
    # Detect gray/concrete regions (roads/buildings)
    gray_mask = cv2.inRange(small_rgb, (80, 80, 80), (200, 200, 200))
    concrete_ratio = float(np.sum(gray_mask > 0) / gray_mask.size)
    
    # Detect brown/soil
    brown_mask = cv2.inRange(small_rgb, (80, 50, 20), (200, 150, 100))
    soil_ratio = float(np.sum(brown_mask > 0) / brown_mask.size)
    
    record = {
        "file": fname,
        "index": i,
        "width": w,
        "height": h,
        "brightness": round(brightness, 2),
        "contrast": round(contrast, 2),
        "edge_density": round(edge_density, 4),
        "green_ratio": round(green_ratio, 4),
        "concrete_ratio": round(concrete_ratio, 4),
        "soil_ratio": round(soil_ratio, 4),
        "dominant_colors": dominant_colors[:3]
    }
    scene_data.append(record)
    print(f"  {fname}: green={green_ratio:.2%}, concrete={concrete_ratio:.2%}, soil={soil_ratio:.2%}, edges={edge_density:.2%}")

# Save scene data
with open(os.path.join(output_dir, "scene_data.json"), "w") as f:
    json.dump(scene_data, f, indent=2)

print(f"\nScene data saved to scene_data.json")

# Compute aggregate stats
avg_green = np.mean([d["green_ratio"] for d in scene_data])
avg_concrete = np.mean([d["concrete_ratio"] for d in scene_data])
avg_soil = np.mean([d["soil_ratio"] for d in scene_data])
avg_edges = np.mean([d["edge_density"] for d in scene_data])

print(f"\n=== SCENE SUMMARY ===")
print(f"Average green coverage:    {avg_green:.1%}")
print(f"Average concrete coverage: {avg_concrete:.1%}")
print(f"Average soil coverage:     {avg_soil:.1%}")
print(f"Average edge density:      {avg_edges:.2%}")
print(f"Image resolution: {scene_data[0]['width']}x{scene_data[0]['height']}")
