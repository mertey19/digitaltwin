# GroundStation (Unity) Entegrasyonu

Bu repo'daki fotogrametri çıktısını (orthophoto + DSM + **bina** + **ağaç**),
Unity tabanlı **GroundStation** Digital Twin projesine bağlamak için köprü.

## Mimari

```
digital-twin (Python)                 GroundStation (Unity / Built-in RP)
─────────────────────                 ───────────────────────────────────
data_real/ (aukerman) ── kopya ──►    Assets/StreamingAssets/SimurghTwin/
groundstation_bridge.py ─UDP:19090►   DigitalTwinUdpIngress → JsonPoseBridge
   imagery bloğu (orthophoto)            └─ DigitalTwinImageryService  (RawImage overlay)
   pose (saha merkezi / georef)          └─ harita / drone pozu
buildings.json + trees.json     ──►   SimurghSiteImporter.cs (Mapbox GeoToWorld → 3B)
```

İki bağımsız katman:

| Katman | Ne yapar | Dosya |
|--------|----------|-------|
| **Imagery** | Net orthophoto'yu Twin viewport'a overlay (mevcut altyapı) | `groundstation_bridge.py` |
| **3B Saha** | Bina + ağaçları Mapbox'ta gerçek GPS'e yerleştirir | `SimurghSiteImporter.cs` |

---

## 1) Veriyi StreamingAssets'e kopyala (bir kez)

```powershell
python groundstation_bridge.py --copy-to "C:/Users/mert/Downloads/groundstation-main/groundstation-main/Assets/StreamingAssets"
```

Bu, `data_real/` içindeki `orthomosaic.jpg, buildings.json, trees.json, site_meta.json,
heightmap.png, normalmap.png` dosyalarını `StreamingAssets/SimurghTwin/` altına kopyalar.

## 2) Imagery köprüsü (canlı)

GroundStation'ı Unity'de **Play** moduna al, sonra:

```powershell
python groundstation_bridge.py            # sürekli (her 2 sn)
python groundstation_bridge.py --once     # tek mesaj
```

`DigitalTwinUdpIngress` (port **19090**) mesajı alır → `DigitalTwinImageryService`
`SimurghTwin/orthomosaic.jpg`'yi Twin viewport'ta gösterir. `authToken` README ile aynıdır (`simurgh-2026`).

## 3) 3B bina + ağaç (SimurghSiteImporter.cs)

`Assets/Scripts/DigitalTwin/SimurghSiteImporter.cs` projene kopyalandı.

1. Sahnede boş bir GameObject oluştur → `SimurghSiteImporter` bileşenini ekle.
2. **Map** alanına sahnedeki `AbstractMap`'i sürükle (boşsa otomatik bulunur).
3. Haritayı aukerman konumuna (Cleveland: `41.5012, -81.6945`) getir.
4. **Play** → ~2.5 sn sonra `site_meta.json` georef'ine göre bina + ağaçlar
   gerçek GPS koordinatlarında belirir. (`Spawn Site` context-menu ile elle de tetiklenir.)

Yükseklik/boyut `AbstractMap.WorldRelativeScale` (Unity birimi / metre) ile ölçeklenir.

---

## Notlar

- **Built-in RP**: materyaller `Standard` shader ile otomatik oluşturulur (alanları boş bırak).
- Aukerman'da DSM yok → arazi düz; 3B zenginlik bina + ağaç nesnelerinden gelir.
- Mapbox access token'ı güvenli tut (GroundStation README uyarısı).
- Telemetri: GroundStation'ın kendi pose/UDP sistemi (ROS bridge vb.) korunur;
  bu köprü sadece **saha rekonstrüksiyonu** (imagery + 3B varlık) ekler. İstenirse
  `twin_api.py` bina telemetrisi (doluluk/enerji) ayrı bir panele bağlanabilir.
- Farklı dataset: `--data data` (sentetik) veya kendi `data_real/`'ın ile çalışır.
