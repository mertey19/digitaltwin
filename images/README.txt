Ham DJI drone karelerini bu klasore koyun.

Ornek dosya adlari (scene_data.json ile uyumlu):
  DJI_0018.JPG … DJI_0035.JPG  (18 kare)

Sonra proje kokunde:
  python stitch_mosaic.py --input images --output mosaic.jpg
  python ingest_real_dataset.py

Not: Repodaki test kareleri eski 6x3 montajdan uretilmistir.
Gercek yarismada ham DJI ciktisini kullanin — EXIF GPS varsa otomatik
en hizli yontem (exif_gps) devreye girer.
