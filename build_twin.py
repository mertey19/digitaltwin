import os, json, base64, math
import numpy as np

scratch = r"C:\Users\SAMET\.gemini\antigravity\scratch"

# ─── Scene istatistikleri ─────────────────────────────────────────────────────
with open(os.path.join(scratch, "scene_data.json")) as f:
    scene_data = json.load(f)

avg_green    = round(sum(d["green_ratio"]    for d in scene_data) / len(scene_data) * 100, 1)
avg_concrete = round(sum(d["concrete_ratio"] for d in scene_data) / len(scene_data) * 100, 1)
avg_soil     = round(sum(d["soil_ratio"]     for d in scene_data) / len(scene_data) * 100, 1)
avg_edges    = round(sum(d["edge_density"]   for d in scene_data) / len(scene_data) * 100, 1)
n_images     = len(scene_data)

with open(os.path.join(scratch, "mosaic_meta.json")) as f:
    meta = json.load(f)

# ─── Görselleri Base64'e dönüştür (CORS sorunu olmadan çalışır) ───────────────
def to_b64(path):
    with open(path, "rb") as f:
        return base64.b64encode(f.read()).decode("ascii")

print("Orthomosaic Base64 donusturuluyor...")
ortho_b64 = to_b64(os.path.join(scratch, "orthomosaic.jpg"))
print(f"  Boyut: {len(ortho_b64)//1024} KB")

print("Heightmap Base64 donusturuluyor...")
hm_b64 = to_b64(os.path.join(scratch, "heightmap.jpg"))
print(f"  Boyut: {len(hm_b64)//1024} KB")

# ─── HTML ─────────────────────────────────────────────────────────────────────
html = f"""<!DOCTYPE html>
<html lang="tr">
<head>
<meta charset="UTF-8"/>
<meta name="viewport" content="width=device-width,initial-scale=1.0"/>
<title>3D Digital Twin — Drone Orthomosaic Survey</title>
<style>
*{{margin:0;padding:0;box-sizing:border-box;}}
body{{background:#070b14;font-family:'Segoe UI',sans-serif;overflow:hidden;}}
#wrap{{width:100vw;height:100vh;position:absolute;top:0;left:0;}}
canvas{{display:block;width:100vw;height:100vh;}}
#hud{{position:absolute;top:0;left:0;width:100%;height:100%;pointer-events:none;z-index:10;}}

#titlebar{{position:absolute;top:18px;left:50%;transform:translateX(-50%);
  background:rgba(5,10,25,0.88);border:1px solid rgba(0,210,255,0.35);
  border-radius:14px;padding:12px 32px;backdrop-filter:blur(14px);text-align:center;}}
#titlebar h1{{font-size:17px;font-weight:800;letter-spacing:2.5px;
  background:linear-gradient(90deg,#00d2ff,#7c63ff,#00ffa3);
  -webkit-background-clip:text;-webkit-text-fill-color:transparent;}}
#titlebar p{{font-size:10px;color:rgba(255,255,255,0.4);margin-top:3px;letter-spacing:1.2px;}}

#stats{{position:absolute;top:18px;right:18px;
  background:rgba(5,10,25,0.92);border:1px solid rgba(0,210,255,0.25);
  border-radius:13px;padding:16px 18px;backdrop-filter:blur(14px);min-width:220px;}}
#stats h3{{font-size:10px;color:#00d2ff;letter-spacing:2px;text-transform:uppercase;margin-bottom:12px;}}
.sr{{display:flex;justify-content:space-between;margin-bottom:3px;}}
.sl{{font-size:11px;color:rgba(255,255,255,0.5);}}
.sv{{font-size:12px;font-weight:700;color:#fff;}}
.sb{{width:100%;height:4px;background:rgba(255,255,255,0.08);border-radius:2px;margin-bottom:8px;overflow:hidden;}}
.sf{{height:100%;border-radius:2px;}}

#legend{{position:absolute;bottom:60px;left:18px;
  background:rgba(5,10,25,0.92);border:1px solid rgba(0,210,255,0.25);
  border-radius:13px;padding:14px 16px;backdrop-filter:blur(14px);}}
#legend h3{{font-size:10px;color:#00d2ff;letter-spacing:2px;text-transform:uppercase;margin-bottom:9px;}}
.li{{display:flex;align-items:center;gap:8px;margin:5px 0;}}
.ld{{width:11px;height:11px;border-radius:3px;}}
.lt{{font-size:11px;color:rgba(255,255,255,0.65);}}

#btns{{position:absolute;top:18px;left:18px;display:flex;flex-direction:column;gap:8px;}}
.vb{{background:rgba(5,10,25,0.9);border:1px solid rgba(0,210,255,0.28);
  border-radius:9px;padding:9px 16px;color:rgba(255,255,255,0.75);
  font-size:11px;cursor:pointer;transition:all .2s;letter-spacing:.5px;pointer-events:auto;}}
.vb:hover{{background:rgba(0,210,255,0.12);border-color:#00d2ff;color:#fff;}}
.vb.active{{background:rgba(0,210,255,0.18);border-color:#00d2ff;color:#00d2ff;}}

#ctrl{{position:absolute;bottom:18px;left:50%;transform:translateX(-50%);
  background:rgba(5,10,25,0.88);border:1px solid rgba(0,210,255,0.2);
  border-radius:10px;padding:9px 22px;font-size:10px;color:rgba(255,255,255,0.4);text-align:center;}}

#loading{{position:fixed;top:0;left:0;width:100%;height:100%;background:#070b14;
  display:flex;flex-direction:column;align-items:center;justify-content:center;z-index:999;}}
#loading h2{{color:#00d2ff;font-size:18px;letter-spacing:3px;margin-bottom:20px;}}
#pbar{{width:280px;height:4px;background:rgba(255,255,255,0.1);border-radius:2px;overflow:hidden;}}
#pfill{{width:0%;height:100%;background:linear-gradient(90deg,#00d2ff,#7c63ff);border-radius:2px;
  transition:width 0.4s;}}
#ptext{{color:rgba(255,255,255,0.4);font-size:11px;margin-top:10px;letter-spacing:1px;}}
</style>
</head>
<body>
<div id="loading">
  <h2>SAHNE YUKLENIYOR</h2>
  <div id="pbar"><div id="pfill"></div></div>
  <div id="ptext">Dokular hazirlaniyor...</div>
</div>

<div id="wrap"></div>

<div id="hud">
  <div id="titlebar">
    <h1>&#128248; 3D DIJITAL IKIZ</h1>
    <p>DRONE ORTHOMOSAIC &nbsp;&middot;&nbsp; {n_images} KARE &nbsp;&middot;&nbsp; {meta['cols']}x{meta['rows']} GRID</p>
  </div>
  <div id="btns">
    <button class="vb active" id="btn-top"   onclick="setView('top')">&#11014; Kus Bakisi</button>
    <button class="vb"        id="btn-iso"   onclick="setView('iso')">&#9672; Izometrik</button>
    <button class="vb"        id="btn-side"  onclick="setView('side')">&#9671; Yan Gorunum</button>
    <button class="vb"        id="btn-drone" onclick="setView('drone')">&#128248; Drone Yolu</button>
    <button class="vb"        id="btn-wire"  onclick="toggleWire()">&#9634; Tel Kafes</button>
  </div>
  <div id="stats">
    <h3>&#128202; Saha Analizi</h3>
    <div class="sr"><span class="sl">Yesil Alan</span><span class="sv">{avg_green} %</span></div>
    <div class="sb"><div class="sf" style="width:{min(avg_green,100)}%;background:linear-gradient(90deg,#16a34a,#4ade80)"></div></div>
    <div class="sr"><span class="sl">Beton / Yapi</span><span class="sv">{avg_concrete} %</span></div>
    <div class="sb"><div class="sf" style="width:{min(avg_concrete,100)}%;background:linear-gradient(90deg,#64748b,#cbd5e1)"></div></div>
    <div class="sr"><span class="sl">Toprak / Zemin</span><span class="sv">{avg_soil} %</span></div>
    <div class="sb"><div class="sf" style="width:{min(avg_soil,100)}%;background:linear-gradient(90deg,#92400e,#d97706)"></div></div>
    <div class="sr"><span class="sl">Kenar Yogunlugu</span><span class="sv">{avg_edges} %</span></div>
    <div class="sb"><div class="sf" style="width:{min(avg_edges,100)}%;background:linear-gradient(90deg,#6d28d9,#a78bfa)"></div></div>
    <div style="border-top:1px solid rgba(255,255,255,0.07);margin-top:4px;padding-top:10px;">
      <div class="sr"><span class="sl">Toplam Kare</span><span class="sv">{n_images}</span></div>
      <div class="sr"><span class="sl">Grid</span><span class="sv">{meta['cols']}x{meta['rows']}</span></div>
      <div class="sr"><span class="sl">Mozaik</span><span class="sv">{meta['mosaic_w']}x{meta['mosaic_h']}px</span></div>
    </div>
  </div>
  <div id="legend">
    <h3>&#128506; Gosterim</h3>
    <div class="li"><div class="ld" style="background:linear-gradient(135deg,#22c55e,#16a34a)"></div><span class="lt">Gercek Fotograf Dokusu</span></div>
    <div class="li"><div class="ld" style="background:linear-gradient(135deg,#94a3b8,#64748b)"></div><span class="lt">Yuksek Bolgeler (Heightmap)</span></div>
    <div class="li"><div class="ld" style="background:rgba(0,210,255,1);border-radius:50%"></div><span class="lt">Drone Yolu</span></div>
  </div>
  <div id="ctrl">Sol Tik Surukle = Dondur &nbsp;|&nbsp; Scroll = Zoom &nbsp;|&nbsp; Sag Tik = Kaydir</div>
</div>

<script src="https://cdnjs.cloudflare.com/ajax/libs/three.js/r128/three.min.js"></script>
<script>
const ORTHO_B64  = "data:image/jpeg;base64,{ortho_b64}";
const HM_B64     = "data:image/jpeg;base64,{hm_b64}";

const pfill  = document.getElementById('pfill');
const ptext  = document.getElementById('ptext');
function setProgress(pct, txt) {{
  pfill.style.width = pct + '%';
  if(txt) ptext.textContent = txt;
}}

window.addEventListener('DOMContentLoaded', () => {{
  const wrap = document.getElementById('wrap');
  const W = window.innerWidth, H = window.innerHeight;

  const renderer = new THREE.WebGLRenderer({{antialias:true}});
  renderer.setPixelRatio(window.devicePixelRatio||1);
  renderer.setSize(W, H);
  renderer.shadowMap.enabled = true;
  renderer.shadowMap.type = THREE.PCFSoftShadowMap;
  renderer.toneMapping = THREE.ACESFilmicToneMapping;
  renderer.toneMappingExposure = 1.3;
  wrap.appendChild(renderer.domElement);

  const scene = new THREE.Scene();
  scene.background = new THREE.Color(0x060c1a);
  scene.fog = new THREE.FogExp2(0x0a1020, 0.004);

  const camera = new THREE.PerspectiveCamera(52, W/H, 0.1, 3000);
  let sph = {{r:260, theta:0.55, phi:0.55}}, tgt = {{x:0, y:0, z:0}};
  let drag=false, rclick=false, pmx=0, pmy=0;

  function updateCam(){{
    camera.position.set(
      tgt.x + sph.r * Math.sin(sph.phi) * Math.sin(sph.theta),
      tgt.y + sph.r * Math.cos(sph.phi),
      tgt.z + sph.r * Math.sin(sph.phi) * Math.cos(sph.theta)
    );
    camera.lookAt(tgt.x, tgt.y, tgt.z);
  }}

  renderer.domElement.addEventListener('mousedown', e => {{ drag=true; rclick=(e.button===2); pmx=e.clientX; pmy=e.clientY; }});
  window.addEventListener('mouseup', () => drag=false);
  renderer.domElement.addEventListener('mousemove', e => {{
    if(!drag) return;
    const dx=e.clientX-pmx, dy=e.clientY-pmy;
    pmx=e.clientX; pmy=e.clientY;
    if(rclick){{ tgt.x-=dx*0.1; tgt.z-=dy*0.1; }}
    else {{ sph.theta-=dx*0.005; sph.phi=Math.max(0.04,Math.min(1.52,sph.phi+dy*0.005)); }}
    updateCam();
  }});
  renderer.domElement.addEventListener('wheel', e => {{
    sph.r=Math.max(20,Math.min(800,sph.r+e.deltaY*0.15));
    updateCam();
  }});
  renderer.domElement.addEventListener('contextmenu', e => e.preventDefault());
  updateCam();

  // Işıklar
  scene.add(new THREE.AmbientLight(0x8899bb, 1.2));
  const sun = new THREE.DirectionalLight(0xffe8c0, 3.2);
  sun.position.set(120, 200, 80);
  sun.castShadow = true;
  sun.shadow.mapSize.set(4096, 4096);
  sun.shadow.camera.left = -300; sun.shadow.camera.right = 300;
  sun.shadow.camera.top  =  300; sun.shadow.camera.bottom= -300;
  sun.shadow.camera.far  = 1000;
  scene.add(sun);
  scene.add(new THREE.DirectionalLight(0x4466aa, 0.8).position.set(-100, 80, -60));
  scene.add(new THREE.HemisphereLight(0x4488cc, 0x224411, 0.7));

  // Izgara (zemin referans)
  const grid = new THREE.GridHelper(600, 60, 0x112233, 0x0a1525);
  grid.position.y = -0.5;
  scene.add(grid);

  // Yıldızlar
  const sv = new Float32Array(3000);
  for(let i=0;i<3000;i+=3){{ sv[i]=(Math.random()-0.5)*2000; sv[i+1]=Math.random()*600+100; sv[i+2]=(Math.random()-0.5)*2000; }}
  const sg = new THREE.BufferGeometry();
  sg.setAttribute('position', new THREE.Float32BufferAttribute(sv,3));
  scene.add(new THREE.Points(sg, new THREE.PointsMaterial({{color:0xffffff,size:0.6,transparent:true,opacity:0.5}})));

  setProgress(30, 'Orthomosaic dokusu yukleniyor...');

  const loader = new THREE.TextureLoader();

  // Orthomosaic dokusu yükle
  loader.load(ORTHO_B64, (orthoTex) => {{
    setProgress(60, 'Heightmap yukleniyor...');
    orthoTex.wrapS = orthoTex.wrapT = THREE.ClampToEdgeWrapping;

    // Heightmap yükle
    loader.load(HM_B64, (hmTex) => {{
      setProgress(85, '3D arazi olusturuluyor...');
      hmTex.wrapS = hmTex.wrapT = THREE.ClampToEdgeWrapping;

      // ── Arazi geometrisi ────────────────────────────────────────────────
      const GW = 400, GH = 280;   // Arazi genişlik x derinlik (Three.js birimi)
      const SEG = 128;             // Segment sayısı (yüksek = daha pürüzlü arazi)

      const geo = new THREE.PlaneGeometry(GW, GH, SEG, SEG);
      geo.rotateX(-Math.PI / 2);

      // Heightmap verisi CPU'da okuyarak vertex Y koordinatlarını ayarla
      // (displacementMap WebGL'de daha iyi ama file:// protokolünde sorun çıkabilir)
      // Daha güvenli: Canvas ile heightmap pixel değerlerini oku
      const hmImg = new Image();
      hmImg.onload = function() {{
        const hmCanvas = document.createElement('canvas');
        hmCanvas.width  = hmImg.width;
        hmCanvas.height = hmImg.height;
        const ctx = hmCanvas.getContext('2d');
        ctx.drawImage(hmImg, 0, 0);
        const imgData = ctx.getImageData(0, 0, hmCanvas.width, hmCanvas.height);
        const pixels  = imgData.data;

        const positions = geo.attributes.position.array;
        const maxH = 25; // Maksimum yükseklik (Three.js birimi)

        for(let i=0; i < positions.length; i+=3) {{
          const px3d = positions[i];     // x
          const pz3d = positions[i+2];   // z

          // Geometry koordinatlarını ([-GW/2..GW/2], [-GH/2..GH/2]) → (0..1) UV aralığına çevir
          const u = (px3d / GW) + 0.5;
          const v = (pz3d / GH) + 0.5;

          // Heightmap piksel koordinatı
          const hx = Math.floor(Math.min(u,0.999) * hmCanvas.width);
          const hy = Math.floor(Math.min(v,0.999) * hmCanvas.height);
          const idx4 = (hy * hmCanvas.width + hx) * 4;
          const gray = pixels[idx4] / 255.0;

          positions[i+1] = gray * maxH; // Y = yükseklik
        }}
        geo.attributes.position.needsUpdate = true;
        geo.computeVertexNormals();

        // Material
        const mat = new THREE.MeshStandardMaterial({{
          map:          orthoTex,
          roughness:    0.85,
          metalness:    0.02,
          envMapIntensity: 0.5,
        }});

        const terrain = new THREE.Mesh(geo, mat);
        terrain.receiveShadow = true;
        terrain.castShadow    = false;
        scene.add(terrain);
        window._terrain = terrain; // tel kafes için

        // ── Drone yolu ─────────────────────────────────────────────────────
        const pathPts = [];
        const rows_n = {meta['rows']}, cols_n = {meta['cols']};
        for(let r=0; r<rows_n; r++) {{
          for(let c=0; c<cols_n; c++) {{
            const px = (c / (cols_n-1) - 0.5) * GW;
            const pz = (r / (rows_n-1) - 0.5) * GH;
            // Heightmap'ten bu noktanın yüksekliğini al
            const u2 = c / (cols_n-1);
            const v2 = r / (rows_n-1);
            const hx2 = Math.floor(u2 * (hmCanvas.width-1));
            const hy2 = Math.floor(v2 * (hmCanvas.height-1));
            const g2  = pixels[(hy2*hmCanvas.width+hx2)*4] / 255.0;
            pathPts.push(new THREE.Vector3(px, g2*maxH + 30, pz));
          }}
        }}

        const curve = new THREE.CatmullRomCurve3(pathPts, false, 'catmullrom', 0.4);
        scene.add(new THREE.Mesh(
          new THREE.TubeGeometry(curve, 200, 0.4, 7, false),
          new THREE.MeshStandardMaterial({{color:0x00d2ff,emissive:0x003366,emissiveIntensity:0.9,
            roughness:0.1,metalness:0.9,transparent:true,opacity:0.8}})
        ));

        pathPts.forEach(p => {{
          const m = new THREE.Mesh(
            new THREE.SphereGeometry(0.8, 8, 8),
            new THREE.MeshStandardMaterial({{color:0x00ffa3,emissive:0x00cc66,emissiveIntensity:2}})
          );
          m.position.copy(p);
          scene.add(m);
        }});

        // ── Drone modeli ───────────────────────────────────────────────────
        const droneBody = new THREE.Mesh(
          new THREE.BoxGeometry(3, 0.5, 3),
          new THREE.MeshStandardMaterial({{color:0xe0e0e0,emissive:0x224488,emissiveIntensity:0.5,metalness:0.9,roughness:0.2}})
        );
        scene.add(droneBody);

        const droneLed = new THREE.Mesh(
          new THREE.SphereGeometry(0.35, 8, 8),
          new THREE.MeshStandardMaterial({{color:0xff2222,emissive:0xff0000,emissiveIntensity:3}})
        );
        scene.add(droneLed);

        let t = 0;
        function animate(){{
          requestAnimationFrame(animate);
          t += 0.003;
          const u3 = (t*0.05) % 1;
          const p  = curve.getPointAt(u3);
          const p2 = curve.getPointAt(Math.min(u3+0.005,1));

          droneBody.position.set(p.x, p.y + Math.sin(t*3)*0.5, p.z);
          droneBody.lookAt(p2.x, p2.y, p2.z);
          droneBody.rotation.x = 0;

          droneLed.position.set(p.x, p.y + 0.6 + Math.sin(t*3)*0.5, p.z);
          droneLed.visible = Math.sin(t*8) > 0;

          renderer.render(scene, camera);
        }}
        animate();

        setProgress(100, 'Hazir!');
        setTimeout(() => {{
          document.getElementById('loading').style.display = 'none';
        }}, 600);
      }};
      hmImg.src = HM_B64;
    }});
  }});

  // Kamera açıları
  window.setView = function(v){{
    document.querySelectorAll('.vb').forEach(b => b.classList.remove('active'));
    document.getElementById('btn-'+v).classList.add('active');
    if     (v==='top')  {{ sph={{r:320,theta:0.55,phi:0.1}};  tgt={{x:0,y:0,z:0}}; }}
    else if(v==='iso')  {{ sph={{r:280,theta:0.65,phi:0.65}}; tgt={{x:0,y:0,z:0}}; }}
    else if(v==='side') {{ sph={{r:250,theta:0,  phi:1.45}}; tgt={{x:0,y:5,z:0}}; }}
    else if(v==='drone'){{ sph={{r:100,theta:1.2,phi:0.5}};  tgt={{x:0,y:8,z:0}}; }}
    updateCam();
  }};

  let wireOn = false;
  window.toggleWire = function(){{
    if(!window._terrain) return;
    wireOn = !wireOn;
    window._terrain.material.wireframe = wireOn;
    document.getElementById('btn-wire').classList.toggle('active', wireOn);
  }};

  window.addEventListener('resize', () => {{
    const nw=window.innerWidth, nh=window.innerHeight;
    camera.aspect = nw/nh;
    camera.updateProjectionMatrix();
    renderer.setSize(nw, nh);
  }});
}});
</script>
</body>
</html>"""

out = r"C:\Users\SAMET\.gemini\antigravity\scratch\digital_twin.html"
with open(out, "w", encoding="utf-8") as f:
    f.write(html)

total_kb = len(html) // 1024
print(f"Done! {total_kb} KB => {out}")
