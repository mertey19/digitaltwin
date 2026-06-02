# Dijital İkiz — Buradan Başlayın

`ERR_CONNECTION_REFUSED` hatası, bilgisayarınızda **hiçbir programın 8000 veya 8765 portunda dinlemediği** anlamına gelir. Tarayıcı doğru; sunucu **sizin makinenizde çalışmıyor**.

Cursor veya başka bir ortamda arka planda başlatılan sunucular **sizin Windows oturumunuza ve tarayıcınıza ulaşmayabilir**. Sunucuyu **kendi bilgisayarınızda** başlatmanız gerekir.

---

## 3 adımda çalıştırma

### 1) Proje klasörünü açın

Bu dosyanın bulunduğu klasör proje köküdür. Aynı klasörde şunlar olmalı: `serve.py`, `twin.html`, `start.bat`.

Örnek yol (sizde farklı olabilir):

`C:\Users\mert\Downloads\digital-twin-main\digital-twin-main`

### 2) Sunucuyu başlatın (bir yöntem seçin)

**A — Çift tık (en kolay)**  
`start.bat` dosyasına çift tıklayın.

**B — PowerShell**

```powershell
cd "BU_KLASORUN_TAM_YOLU"
.\start.ps1
```

**C — Komut satırı**

```powershell
cd "BU_KLASORUN_TAM_YOLU"
python -m pip install -r requirements.txt
python serve.py
```

### 3) Tarayıcıda açın

Terminalde şuna benzer satırlar görünene kadar bekleyin:

```
Open:    http://localhost:8000/twin.html
```

Sonra tarayıcıda açın: **http://localhost:8000/twin.html**

(Veya **http://localhost:8000/** — otomatik olarak `twin.html` sayfasına yönlendirir.)

---

## Önemli kurallar

| Kural | Açıklama |
|--------|----------|
| **Terminal açık kalmalı** | `serve.py` çalışırken siyah/PowerShell penceresini **kapatmayın**. Kapatırsanız sunucu durur ve tarayıcıda yine `ERR_CONNECTION_REFUSED` görürsünüz. |
| **Varsayılan port 8000** | `serve.py` varsayılan olarak **8000** portunu kullanır. |
| **8765 portu** | Yalnızca `python run_twin.py --serve --port 8765` gibi **özel** komutlarla kullanılır. `start.bat` **8000** kullanır. |
| **Firewall** | Yerel `localhost` için genelde izin gerekmez; nadiren Windows Güvenlik Duvarı uyarısı çıkarsa **Python** için özel ağda izin verin. |

---

## Hata: ERR_CONNECTION_REFUSED

1. `start.bat` veya `python serve.py` çalışıyor mu? Terminal penceresi açık mı?
2. Terminalde `Serving ...` ve `Open: http://localhost:8000/...` yazıyor mu?
3. Adreste port **8000** mi? (`start.bat` ile 8765 kullanılmaz.)
4. Başka bir program 8000 portunu kullanıyorsa: `python serve.py --port 8080` deneyin, sonra `http://localhost:8080/twin.html` açın.

---

## start.bat ne yapar?

1. Kendi klasörüne geçer (`cd` script ile aynı dizin).
2. `python -m pip install -r requirements.txt` ile bağımlılıkları kurar (zaten kuruluysa sessizce tamamlanır).
3. `python serve.py --no-browser` ile HTTP sunucusunu başlatır.
4. Hata olursa pencere kapanmadan önce **pause** ile hatayı görmenizi sağlar.

`start.ps1` aynı işi PowerShell ile yapar.

---

## İsteğe bağlı: veri hattı + sunucu

Drone görselleri işlemek için (daha uzun sürer):

```powershell
python run_twin.py --serve
```

Bu komut ingest sonrası yine **8000** portunda `serve.py` başlatır (8765 yalnızca `--port 8765` verirseniz).

---

## Yardım

- Python yoksa: https://www.python.org/downloads/ — kurulumda **“Add python.exe to PATH”** işaretleyin.
- `pip install` hata verirse terminaldeki kırmızı metni kopyalayın.
- API uçları: `http://localhost:8000/api/telemetry` (sunucu çalışırken)
