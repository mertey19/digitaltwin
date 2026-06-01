using UnityEngine;

public class GridManager : MonoBehaviour
{
    [Header("Obstacles")]
    public LayerMask obstacleLayer;
    public float obstacleCheckHeight = 1f; // ray baþlangýç yüksekliði
    public bool drawBlocked = true;

    [Header("Grid")]
    public int width = 20;      // X yönü hücre sayýsý
    public int height = 20;     // Z yönü hücre sayýsý
    public float cellSize = 1f; // 1 hücre = 1 metre
    public Vector3 origin = Vector3.zero;

    [Header("Debug")]
    public bool drawGrid = true;

    public Vector2Int WorldToCell(Vector3 worldPos)
    {
        Vector3 p = worldPos - origin;
        int x = Mathf.FloorToInt(p.x / cellSize);
        int z = Mathf.FloorToInt(p.z / cellSize);
        return new Vector2Int(x, z);
    }

    public Vector3 CellToWorldCenter(Vector2Int cell)
    {
        float x = (cell.x + 0.5f) * cellSize;
        float z = (cell.y + 0.5f) * cellSize;
        return origin + new Vector3(x, 0f, z);
    }

    void OnDrawGizmos()
    {
        if (!drawGrid) return;

        Gizmos.color = Color.gray;

        // Dikey çizgiler
        for (int x = 0; x <= width; x++)
        {
            Vector3 a = origin + new Vector3(x * cellSize, 0f, 0f);
            Vector3 b = origin + new Vector3(x * cellSize, 0f, height * cellSize);
            Gizmos.DrawLine(a, b);
        }

        // Yatay çizgiler
        for (int z = 0; z <= height; z++)
        {
            Vector3 a = origin + new Vector3(0f, 0f, z * cellSize);
            Vector3 b = origin + new Vector3(width * cellSize, 0f, z * cellSize);
            Gizmos.DrawLine(a, b);
        }
        if (drawBlocked && obstacleLayer.value != 0)
        {
            Gizmos.color = new Color(1f, 0f, 0f, 0.25f);

            for (int x = 0; x < width; x++)
                for (int z = 0; z < height; z++)
                {
                    Vector3 center = CellToWorldCenter(new Vector2Int(x, z)) + Vector3.up * obstacleCheckHeight;
                    bool blocked = Physics.CheckBox(
                        center,
                        new Vector3(cellSize * 0.45f, 0.5f, cellSize * 0.45f),
                        Quaternion.identity,
                        obstacleLayer
                    );

                    if (blocked)
                    {
                        Vector3 drawPos = CellToWorldCenter(new Vector2Int(x, z)) + Vector3.up * 0.01f;
                        Gizmos.DrawCube(drawPos, new Vector3(cellSize, 0.02f, cellSize));
                    }
                }
        }

    }
}
