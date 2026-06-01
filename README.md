# Dijital İkiz — Sentetik & Gerçek Saha (Digital Twin Platform)

Gerçekçi görünümlü **dijital ikiz platformu**. Drone mozaiği + DSM ile 3B sahne,
canlı telemetri simülasyonu, alarm paneli, ölçüm araçları ve tam Türkçe arayüz.

**Ana deneyim:** [`twin.html`](twin.html) — Dijital İkiz Platformu  
**Klasik görüntüleyici:** [`viewer.html`](viewer.html) — hafif Three.js viewer

> Eski dosyalar (`digital_twin.html`, `digital_twin_eski.html`) değiştirilmemiştir.

---

## ⭐ TEK KOMUTLA BAŞLAT (önerilen)

```powershell
cd C:\Users\mert\Downloads\digital-twin-main\digital-twin-main

# Bağımlılıklar (bir kez)
python -m pip install -r requirements.txt

# Stitch (images/ doluysa) + ingest + sunucu
python run_twin.py --serve
```

Tarayıcıda: **http://localhost:8000/twin.html** (veya http://localhost:8000/ → otomatik yönlendirme)

| Komut | Açıklama |
|-------|----------|
| `python run_twin.py` | Stitch (gerekirse) + ingest |
| `python run_twin.py --serve` | Ingest + serve.py (8000) + twin_api (8001) |
| `python run_twin.py --no-stitch` | Mevcut mosaic.jpg ile yalnızca ingest |
| `python run_twin.py --serve --port 8765` | Özel port |

---

## twin.html — Platform Özellikleri

| Özellik | Açıklama |
|---------|----------|
| **Dashboard** | Saha boyutu, yükseklik, bina sayısı, su seviyesi, CANLI pulse |
| **Canlı telemetri** | Sıcaklık, nem, rüzgar, güneş; bina doluluk/enerji (API veya simülasyon) |
| **Tıkla-incele** | Bina: tip, kapasite, footprint, bakım; arazi: koordinat + yükseklik |
| **Hover vurgu** | Binalar üzerinde mavi highlight |
| **Gün saati / hava** | Sky shader; Güneşli / Bulutlu / Yağmurlu (sis, yağmur partikülleri) |
| **Ölçüm** | Mesafe (2 tık), alan poligonu, yükseklik profili (2D grafik) |
| **Pin/not** | sessionStorage ile oturum pinleri |
| **Mini harita** | Ortho thumbnail + viewport + tıkla-atla |
| **Kamera ön ayarları** | Kuş bakışı, Kuzey, Güney, Bina yakın |
| **Demo turu** | Otomatik kamera: kuş bakışı → binalar → su |
| **Zaman ekseni** | 2024 ↔ 2026 karşılaştırma tonu (data_real / sentetik) |
| **Alarmlar** | Su seviyesi, enerji anomalisi — yeşil/sarı/kırmızı rozetler |
| **IoT paneli** | MQTT/OPC-UA bağlantı stub (yol haritası) |
| **Performans** | Performans / Dengeli / Kalite (gölge, mesh, SSAO) |
| **Ekran görüntüsü** | PNG export |

### API uçları (`twin_api.py` / `serve.py`)

```
GET /api/telemetry   — ortam + bina telemetrisi
GET /api/assets      — varlık kaydı (buildings.json genişletilmiş)
GET /api/alarms      — eşik tabanlı alarmlar
```

Standalone API: `python twin_api.py --port 8001`

---

## GERÇEK VERİ İLE HIZLI BAŞLANGIÇ

```powershell
python -m pip install -r requirements.txt

# DJI karelerini images/ klasörüne koyun
python stitch_mosaic.py --input images --output mosaic.jpg
python ingest_real_dataset.py

python serve.py
# → http://localhost:8000/twin.html
```

### EXIF GPS otomatik seçimi

`stitch_mosaic.py` `--method auto` ile DJI JPG'lerde GPS EXIF varsa **exif_gps**
yöntemini seçer (~1–3 sn, özellik eşleştirme yok). Yeterli GPS yoksa phase
correlation (FFT) veya ORB partial affine fallback devreye girer.

```powershell
python stitch_mosaic.py --method auto    # varsayılan
python stitch_mosaic.py --method gps     # EXIF GPS zorla
```

### WebODM / GeoTIFF import

Gerçek orthophoto + DSM GeoTIFF dosyalarını doğrudan `data_real/` formatına dönüştürün:

```powershell
python import_geotiff.py --ortho orthophoto.tif --dsm dsm.tif
python import_geotiff.py --ortho ortho.tif --dsm dsm.tif --out data_real --gsd 0.12
```

`rasterio` yüklüyse gerçek CRS/bounds okunur; yoksa Pillow fallback (sınırlı georef).

---

## Yol Haritası (Roadmap)

| Aşama | Durum | Not |
|-------|-------|-----|
| Three.js dijital ikiz | ✅ | twin.html |
| Simüle telemetri + alarmlar | ✅ | twin_api.py |
| GeoTIFF import | ✅ | import_geotiff.py |
| IoT MQTT/OPC-UA | 🔜 | twin.html stub panel |
| Cesium geospatial | 🔜 | README hook |
| BIM (IFC/glTF) | 🔜 | buildings.json genişletilebilir |
| Fizik simülasyonu | 🔜 | — |

---


Gerçek drone karelerinden mozaik üretmek için önce **`stitch_mosaic.py`**
(hızlı geometrik birleştirme) çalıştırın; ardından ingest:

```powershell
# 1) Bağımlılıklar (numpy + Pillow + OpenCV)  — bir kez
python -m pip install -r requirements.txt

# 2) DJI karelerini images/ klasörüne koyun (DJI_0018.JPG … DJI_0035.JPG)
#    Ham kareler yoksa kendi drone çıktınızı images/ altına kopyalayın.

# 3) Hızlı mozaik birleştirme  ->  mosaic.jpg + mosaic_meta.json
python stitch_mosaic.py --input images --output mosaic.jpg

# 4) Gerçek veri kümesini sindir  ->  data_real/ klasörüne yazar
python ingest_real_dataset.py

# images/ doluysa ingest otomatik yeniden birleştirir ( --stitch gerekmez )
python ingest_real_dataset.py --stitch   # zorla yeniden birleştir

# 5) Yerel http sunucusunu başlat
python serve.py
```

Ardından tarayıcıda aç (varsayılan olarak **Dijital İkiz Platformu** açılır):

```
http://localhost:8000/twin.html
```

Klasik görüntüleyici: `http://localhost:8000/viewer.html`

### Mozaik birleştirme — hızlı yöntem (RANSAC yerine)

**Eski sorun:** `create_textures.py` dosya adı sırasına göre kareleri `sqrt(n)`
tabanlı bir **ızgara hücresine** yapıştırıyordu; örtüşen drone kareleri
**geometrik hizalanmıyordu** — sahne parçaları rastgele konmuş gibi görünüyordu.
Dikiş yumuşatma (Gaussian blur) yalnızca sınır çizgilerini gizliyordu.

**Yeni yöntem (`stitch_mosaic.py`):** Otomatik en hızlı yöntem seçilir:

| Öncelik | Yöntem | Süre (18 kare) | Ne zaman? |
|---------|--------|----------------|-----------|
| 1 | **EXIF GPS + gimbal yaw** | ~1–3 sn | DJI JPG'lerde GPS EXIF varsa (tercih) |
| 2 | **Phase correlation (FFT)** | ~0,1–2 sn | Nadir drone, ardışık kareler, çoğu senaryo |
| 3 | **ORB + partial affine** | ~5–15 sn | Düşük örtüşme / zor sahne (minimal RANSAC) |

**Neden RANSAC homography'den hızlı?**
- Tam homography RANSAC her çift için binlerce ORB özelliği + iterasyon döngüsü çalıştırır.
- EXIF GPS hiç eşleştirme yapmaz — koordinatları doğrudan tuval üzerine yerleştirir.
- Phase correlation FFT ile öteleme bulur; özellik çıkarma yok.
- Partial affine (4 DOF) homography'den (8 DOF) daha az parametre + max 500 RANSAC iterasyonu.

**Benchmark (bu repoda, 18 test karesi, `--output-scale 0.35`, laptop):**

| Yöntem | Süre |
|--------|------|
| `phase_correlation` (varsayılan, EXIF yok) | **~0,07 s** |
| `orb_partial_affine` (fallback) | **~0,23 s** |

Ham DJI karelerinde EXIF GPS varsa `exif_gps` ~1–3 sn; gerçek 4000×2250 karelerde
hedef **< 30 sn** (phase veya EXIF GPS).

Ham DJI kareleri repoda **bulunmaz** — `images/` klasörüne siz koymalısınız.
`ingest_real_dataset.py`, `images/` doluysa ingest öncesi otomatik birleştirir.

| `stitch_mosaic.py` argümanı | Varsayılan | Açıklama |
|-----------------------------|-----------|----------|
| `--input` / `--images` | `./images` | Kaynak JPG/PNG klasörü |
| `--output` | proje kökü | `mosaic.jpg` dosyası veya klasör |
| `--method` | `auto` | `auto`, `gps`, `phase`, `orb` |
| `--max-dim` | 640 | Eşleştirme uzun kenar limiti (px) |
| `--output-scale` | 0.35 | Çıktı mozaik ölçeği |
| `--nfeatures` | 500 | ORB fallback özellik sayısı |
| `--ransac` | 4.0 | ORB partial affine RANSAC eşiği (px) |

Çıktılar: `mosaic.jpg`, `heightmap.jpg`, `mosaic_meta.json` (yöntem, süre, sınırlar).

Projedeki gerçek drone çıktıları (`mosaic.jpg`, `heightmap.jpg`,
`ground_texture.jpg`, `scene_data.json`) ingest ile görüntüleyiciye hazırlanır.

Görüntüleyicide artık: gerçek orthomosaic ile kaplı arazi, **3B prizma binalar**,
**su yüzeyi**, normal-map + (isteğe bağlı) GPU yer değiştirme, pozlama ve güneş
kontrolleri vardır.

**Veri kümesini değiştirme:** sağ üstteki **“Veri kümesi”** açılır menüsünden
*Gerçek veri (data_real)* ↔ *Sentetik (data)* arasında geçiş yapabilir, ya da
URL ile seçebilirsiniz: `viewer.html?data=data_real` / `viewer.html?data=data`.

> `ingest_real_dataset.py` parametreleri (ölçek varsayımı):
> ```powershell
> python ingest_real_dataset.py --gsd 0.15 --min-elev 0 --max-elev 16
> ```
> | Argüman | Varsayılan | Açıklama |
> |---------|-----------|----------|
> | `--gsd` | 0.15 | Varsayılan yer örnekleme aralığı (m/piksel). Saha boyutunu belirler. |
> | `--min-elev` / `--max-elev` | 0 / 16 | Varsayılan yükseklik aralığı (m). |
> | `--height-res` | 1024 | İşlenen heightmap genişliği (px). |

### Ölçek varsayımı (önemli)

`mosaic.jpg` ham DJI karelerinden **hızlı geometrik birleştirme** ile üretilmiş
olmalıdır (`stitch_mosaic.py`). Repodaki eski dosya 6×3 legacy montaj olabilir;
`images/` doluysa ingest otomatik yeniden birleştirir.
`heightmap.jpg` mutlak ölçeği olmayan 8-bit bir JPEG'tir; gerçek saha ölçüsü
**bilinmiyor**. Makul bir drone GSD'si varsayıp saha genişliğini mosaic piksel
boyutundan türetiyoruz (varsayılan: `0.15 m/px`) ve makul bir yükseklik aralığı
(0–16 m) seçiyoruz. Tüm değerler `data_real/site_meta.json` içinde yazılır.

### Çıktılar (`data_real/`)

| Dosya | Açıklama |
|-------|----------|
| `orthomosaic.jpg` | Arazi albedo dokusu (mosaic.jpg'den) |
| `heightmap.png` | 16-bit DSM; orthomosaic en-boy oranına hizalanmış + JPEG gürültüsü temizlenmiş |
| `normalmap.png` | Heightmap'ten türetilmiş normal harita |
| `buildings.json` | Çıkarılan **3B bina ayak izleri** (UV + metre yükseklik) |
| `site_meta.json` | Saha sınırları, su seviyesi, ölçek varsayımları, georef stub |

**Bina çıkarımı:** orthomosaic'te düşük doygunluklu / orta-parlak / yeşil
olmayan (beton/çatı) pikseller sınıflandırılır; `scene_data.json`'daki kare
bazlı `concrete_ratio`, `green_ratio` ve `edge_density` ile 6×3 montaj ızgarasına
göre eşiklenir. Orman ağırlıklı karelerde eşik yükseltilir; düzgün gri
(asfalt/yol) bölgeleri yerel varyans ve yol-benzeri renk filtresiyle elenir.

**Montaj dikiş yumuşatma:** Geometrik mozaiklerde (EXIF/phase/ORB) gerekmez. Legacy 6×3 montajda
orthomosaic ve heightmap kare sınırlarında crossfade + Gaussian karışım uygulanır.

**Su:** orthomosaic'teki mavi/teal pikseller suyun **varlığını** belirler;
legacy montajda dikiş artefaktları filtrelenir.

**Performans:** görüntüleyicide **Kalite ön ayarı** (Performans / Dengeli /
Kalite) gölge haritası boyutu, mesh detayı ve piksel oranını tek tıkla ayarlar;
varsayılan ilk yükleme düşük gölge (1024) + 256 mesh segmenti ile başlar.

---

## Sentetik Veri İle Başlangıç (alternatif)

Windows / PowerShell üzerinde, proje klasöründe:

```powershell
# 1) Bağımlılıklar (numpy + Pillow)
python -m pip install -r requirements.txt

# 2) Sentetik sahayı üret  ->  data/ klasörüne yazar
python generate_synthetic_site.py

# 3) Yerel http sunucusunu başlat (fetch için file:// yerine http gerekir)
python serve.py
```

Ardından tarayıcıda aç:

```
http://localhost:8000/viewer.html?data=data
```

`serve.py` tarayıcıyı otomatik açar; durdurmak için `Ctrl+C`.

> `python` komutu yoksa `py` deneyin: `py ingest_real_dataset.py`.

---

## Ne Üretilir? (`data/` klasörü)

| Dosya | Açıklama |
|-------|----------|
| `data/heightmap.png` | 16-bit gri tonlamalı **DSM** (yükseklik, metre cinsine ölçeklenir) |
| `data/orthomosaic.jpg` | Yükseklik/eğime göre renklendirilmiş, AO/tepe gölgesi pişirilmiş RGB ortho doku |
| `data/normalmap.png` | DSM'den türetilmiş yüzey **normal haritası** (ince detay aydınlatması) |
| `data/site_meta.json` | **Tek doğruluk kaynağı**: gerçek dünya sınırları ve georef bilgisi |

`site_meta.json` alanları: `width_m`, `height_m`, `min_elev_m`, `max_elev_m`,
`resolution_px`, `ground_sample_distance_m`, dosya adları ve `georef`
(origin lat/lon stub). Görüntüleyici tüm ölçeklemeyi bu dosyadan okur.

### Üretici parametreleri

```powershell
python generate_synthetic_site.py --resolution 1024 --width-m 400 --max-elev 40 --seed 42
```

| Argüman | Varsayılan | Açıklama |
|---------|-----------|----------|
| `--resolution` | 1024 | Kare çıktıların piksel çözünürlüğü |
| `--width-m` | 400 | Sahanın gerçek dünya genişliği/uzunluğu (m) |
| `--max-elev` | 40 | Maksimum DSM yüksekliği (m) |
| `--seed` | 42 | Rastgelelik tohumu (tekrarlanabilirlik) |
| `--origin-lat/--origin-lon` | İstanbul | Georef stub başlangıç koordinatı |

---

## Görüntüleyici (`viewer.html`)

- **Three.js r0.160** (ES module + importmap, CDN), **OrbitControls**.
- `MeshStandardMaterial`: orthomosaic = albedo, normal map = yüzey detayı.
- **ACESFilmic** tone mapping, sRGB çıktı, yumuşak gölgeler (PCFSoft).
- `Sky` shader + `HemisphereLight` + yönlü **güneş** (Sky güneş konumunu da sürer)
  + hafif **sis** + sky'dan üretilen ortam (env) haritası ile su yansıması.
- **3B binalar:** `buildings.json`'dan `InstancedMesh` prizmalar, arazi
  yüksekliğine oturtulur (dikey abartı ile ölçeklenir).
- **Su yüzeyi:** düşük pürüzlülük + yarı saydam + yansıtmalı, hafif dalgalı.
- **GPU yer değiştirme** seçeneği: heightmap `displacementMap` olarak
  (CPU tepe yer değiştirme varsayılan — gölgeler doğru kalsın diye).
- **Veri kümesi seçici** (Gerçek ↔ Sentetik), `?data=` parametresi.
- Kontrol paneli: **performans ön ayarı**, veri kümesi, dikey abartı, mesh detayı, GPU disp., tel kafes,
  bina/su aç-kapa, güneş azimut/yükseklik, **pozlama**, sis, **SSAO**, sıfırla.
- HUD: saha boyutu, yükseklik aralığı, GSD, mesh yoğunluğu, bina sayısı, su
  seviyesi, FPS.
- Yükleme ekranı + performans için seçilebilir segment sayısı.

Kontroller: **sürükle** döndür · **sağ tık sürükle** kaydır · **tekerlek** yakınlaş.

---

## Dijital İkiz Platformu (`twin.html`) — önerilen

`viewer.html`'in üzerine inşa edilmiş **tam dijital ikiz deneyimi**. Aynı
Three.js sahnesini (ortho + DSM + binalar + su) kullanır; profesyonel dashboard
arayüzü, canlı telemetri ve etkileşim araçları ekler.

```powershell
python serve.py          # varsayılan: twin.html açılır
python serve.py --page viewer.html   # klasik görüntüleyici
```

### Dashboard arayüzü

| Bölüm | Özellik |
|-------|---------|
| **Sol üst** | Saha adı, Twin sürümü, **CANLI** nabız göstergesi |
| **Sağ panel** | Saha özeti (boyut, yükseklik, bina sayısı, su), canlı telemetri |
| **Sol panel** | Araçlar, kamera ön ayarları, ortam kontrolleri, kalite |
| **Mini harita** | Orthomosaic küçük resim + görüş alanı dikdörtgeni; tıkla → kamerayı taşı |
| **Alt durum çubuğu** | FPS, koordinatlar, aktif araç, telemetri kaynağı (API / simülasyon) |

### Canlı telemetri (simüle)

Her 2–3 saniyede güncellenir (API çevrimdışıysa istemci simülasyonu):

- Ortam: sıcaklık, nem, rüzgar, güneş ışınımı, su seviyesi (hafif dalgalanma)
- Bina başına: doluluk %, enerji kWh, durum (normal/uyarı), bakım
- Yeşil/sarı/kırmızı durum rozetleri

Telemetri API: `GET http://localhost:8000/api/telemetry` (`serve.py` ile aynı port).
Bağımsız sunucu: `python twin_api.py --port 8001`

### Etkileşim

- **İncele:** bina veya araziye tıkla → detay paneli (footprint, yükseklik, doluluk, lat/lon)
- **Mesafe:** iki nokta tıkla → metre cinsinden mesafe
- **Alan:** çokgen köşeleri tıkla, çift tıkla bitir → m² alan
- **Pin:** araziye işaret koy (sessionStorage'da saklanır)
- Bina üzerine gelince mavi vurgu (hover highlight)

### Ortam kontrolleri

- **Gün saati** kaydırıcısı → Sky + güneş + ambient otomatik
- **Hava:** Güneşli / Bulutlu / Yağmurlu (sis, turbidity, ışık; yağmur partikülleri)
- **Mevsim tonu:** ilkbahar/yaz/sonbahar/kış (hafif renk filtresi)

### Kamera ön ayarları

Kuş bakışı · Kuzey · Güney · Bina yakın

### Dışa aktarma

📷 **Ekran görüntüsü** → PNG indir (`canvas.toDataURL`)

### site_meta.json genişletmeleri

`ingest_real_dataset.py` artık şunları da yazar:

- `site_name`, `twin_version`, `last_updated`
- `asset_summary`: bina sayısı, su, alan, dataset türü

---

## Gerçek WebODM / ODM Verisini Takma

Sentetik veriyi gerçek fotogrametri çıktısıyla değiştirmek için:

1. WebODM/ODM çıktısından **orthophoto** (GeoTIFF) → JPG/PNG'ye çevirip
   `data/orthomosaic.jpg` olarak koyun.
2. **DSM** (GeoTIFF, metre) → 16-bit gri PNG'ye çevirip `data/heightmap.png`
   olarak koyun. (İsteğe bağlı: DSM'den normal map üretip `data/normalmap.png`.)
3. `data/site_meta.json` içindeki değerleri gerçek sınırlara göre güncelleyin:
   - `width_m`, `height_m` → orthophoto'nun kapladığı gerçek alan (m),
   - `min_elev_m`, `max_elev_m` → DSM'nin gerçek min/max yüksekliği (m),
   - `ground_sample_distance_m`, `georef.origin_lat/lon`.

Örnek GeoTIFF → PNG dönüşümü (GDAL ile):

```bash
gdal_translate -ot UInt16 -scale <dsm_min> <dsm_max> 0 65535 dsm.tif heightmap.png
gdal_translate -of JPEG orthophoto.tif orthomosaic.jpg
```

Görüntüleyicide hiçbir değişiklik gerekmez; meta dosyası tek doğruluk kaynağıdır.

---

## Dosya Listesi (yeni eklenenler)

```
run_twin.py                  # Tek komut: stitch → ingest → (--serve)
import_geotiff.py            # WebODM GeoTIFF → data_real/
stitch_mosaic.py             # Hizli mozaik (EXIF GPS / phase FFT / ORB partial) -> mosaic.jpg + meta
ingest_real_dataset.py       # GERÇEK veriyi sindirir -> data_real/ (ortho, DSM, normal, binalar, su, meta)
generate_synthetic_site.py   # sentetik DSM + ortho + normal map + meta üretir -> data/
twin.html                    # ★ Dijital İkiz Platformu (dashboard + telemetri + araçlar)
viewer.html                  # klasik Three.js görüntüleyici (binalar + su + GPU disp.)
twin_api.py                  # /api/telemetry, /api/assets, /api/alarms
serve.py                     # stdlib http sunucusu + API + / → twin.html
requirements.txt             # numpy, Pillow, opencv-python, rasterio
images/                      # ham DJI kareleri — stitch_mosaic girdisi
data_real/                   # gerçek veri çıktıları (ingest_real_dataset.py)
data/                        # sentetik çıktılar (generate_synthetic_site.py)
```

> Ham drone kareleri repoda **yoktur** — `images/` klasörüne DJI_0018.JPG …
> kopyalayın, sonra `python stitch_mosaic.py`. Gerçek girdi dosyaları
> (`mosaic.jpg`, `heightmap.jpg`, …) ve orijinal dosyalar **silinmez**; ingest
> yalnızca `data_real/` altına yazar.
