"""
create_textures.py (legacy wrapper)
===================================

Eski surum dosya adi sirasina gore sqrt-tabanli bir izgaraya resim yerlestiriyordu;
bu geometrik hizalama yapmiyordu (Ebrar'in bildirdigi "rastgele" mozaik sorunu).

Yeni akis: stitch_mosaic.py  (EXIF GPS / phase FFT / ORB partial affine)
    python stitch_mosaic.py --input ./images --output mosaic.jpg

Bu dosya geriye uyumluluk icin stitch_mosaic'e yonlendirir.
"""

import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
DEFAULT_IMAGES = os.path.join(HERE, "images")

if __name__ == "__main__":
    from stitch_mosaic import stitch_folder

    images_dir = os.environ.get("DT_IMAGES_DIR", DEFAULT_IMAGES)
    output_dir = os.environ.get("DT_OUTPUT_DIR", HERE)
    if not os.path.isdir(images_dir):
        print(f"HATA: Resim klasoru yok: {images_dir}")
        print("DJI karelerini 'images/' klasorune koyun veya DT_IMAGES_DIR ayarlayin.")
        sys.exit(1)
    stitch_folder(images_dir, output_dir)
