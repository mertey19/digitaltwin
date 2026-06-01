using System.Collections;
using System.Collections.Generic;
using UnityEngine;
using UnityEngine.Networking;

public class MapTilesToPlane : MonoBehaviour
{
    [Header("Map Center (lat/lon)")]
    public double centerLat = 39.92077;
    public double centerLon = 32.85411;

    [Header("OSM Zoom (15-18 iyi)")]
    [Range(1, 19)]
    public int zoom = 16;

    [Header("Tiles radius: 1 => 3x3, 2 => 5x5")]
    [Range(0, 3)]
    public int tilesRadius = 1;

    [Header("Target plane")]
    public Renderer targetRenderer;  // Plane MeshRenderer

    [Header("Tile server")]
    public string tileUrlTemplate = "https://tile.openstreetmap.org/{z}/{x}/{y}.png";

    const int TILE_SIZE = 256;
    const double R = 6378137.0; // WebMercator radius

    void Start()
    {
        if (targetRenderer == null)
        {
            Debug.LogError("Target Renderer missing! Drag MapPlane's MeshRenderer here.");
            return;
        }
        StartCoroutine(LoadAndApply());
    }

    IEnumerator LoadAndApply()
    {
        // center tile index
        (int cx, int cy) = LatLonToTile(centerLat, centerLon, zoom);

        int size = tilesRadius * 2 + 1;
        int texSize = size * TILE_SIZE;

        Texture2D bigTex = new Texture2D(texSize, texSize, TextureFormat.RGB24, false);
        bigTex.wrapMode = TextureWrapMode.Clamp;

        // download tiles and stitch
        for (int dy = -tilesRadius; dy <= tilesRadius; dy++)
        {
            for (int dx = -tilesRadius; dx <= tilesRadius; dx++)
            {
                int x = cx + dx;
                int y = cy + dy;

                string url = tileUrlTemplate
                    .Replace("{z}", zoom.ToString())
                    .Replace("{x}", x.ToString())
                    .Replace("{y}", y.ToString());

                using var req = UnityWebRequestTexture.GetTexture(url);
                req.SetRequestHeader("User-Agent", "UnityDigitalTwinPrototype/1.0"); // nazikçe
                yield return req.SendWebRequest();

                if (req.result != UnityWebRequest.Result.Success)
                {
                    Debug.LogError($"Tile download failed: {url} :: {req.error}");
                    continue;
                }

                Texture2D tileTex = DownloadHandlerTexture.GetContent(req);

                int px = (dx + tilesRadius) * TILE_SIZE;
                int py = (tilesRadius - dy) * TILE_SIZE; // invert y for texture coords

                bigTex.SetPixels(px, py, TILE_SIZE, TILE_SIZE, tileTex.GetPixels());
            }
        }

        bigTex.Apply();

        // apply to material
        var mat = new Material(Shader.Find("Standard"));
        mat.mainTexture = bigTex;
        targetRenderer.material = mat;

        // scale plane to real meters
        // meters per pixel at center latitude:
        double mpp = Mathf.Cos((float)(centerLat * Mathf.Deg2Rad)) * 2.0 * Mathf.PI * R / (TILE_SIZE * (1 << zoom));
        float meters = (float)(texSize * mpp);

        // Unity Plane default is 10x10 units. We want meters x meters.
        // 1 Unity unit = 1 meter assumption.
        // plane scale: (meters/10)
        targetRenderer.transform.position = Vector3.zero;
        targetRenderer.transform.localScale = new Vector3(meters / 10f, 1f, meters / 10f);

        Debug.Log($"Map applied: {size}x{size} tiles, zoom={zoom}, approx size={meters:0}m");
    }

    static (int x, int y) LatLonToTile(double lat, double lon, int z)
    {
        double latRad = lat * Mathf.Deg2Rad;
        int n = 1 << z;
        int x = (int)((lon + 180.0) / 360.0 * n);
        int y = (int)((1.0 - System.Math.Log(System.Math.Tan(latRad) + 1.0 / System.Math.Cos(latRad)) / System.Math.PI) / 2.0 * n);
        return (x, y);
    }
}
