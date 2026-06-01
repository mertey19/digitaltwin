using System.Collections.Generic;
using UnityEngine;

public class GridPathfinder : MonoBehaviour
{
    public GridManager grid;

    public List<Vector2Int> FindPath(Vector2Int start, Vector2Int goal)
    {
        var open = new List<Vector2Int>();
        var cameFrom = new Dictionary<Vector2Int, Vector2Int>();
        var gScore = new Dictionary<Vector2Int, int>();
        var fScore = new Dictionary<Vector2Int, int>();

        open.Add(start);
        gScore[start] = 0;
        fScore[start] = Heuristic(start, goal);

        while (open.Count > 0)
        {
            Vector2Int current = GetLowestF(open, fScore);

            if (current == goal)
                return Reconstruct(cameFrom, current);

            open.Remove(current);

            foreach (var n in Neighbors(current))
            {
                if (!InBounds(n)) continue;
                if (IsBlocked(n)) continue;

                int tentativeG = gScore[current] + 1;

                if (!gScore.ContainsKey(n) || tentativeG < gScore[n])
                {
                    cameFrom[n] = current;
                    gScore[n] = tentativeG;
                    fScore[n] = tentativeG + Heuristic(n, goal);
                    if (!open.Contains(n)) open.Add(n);
                }
            }
        }

        return new List<Vector2Int>(); // yol yok
    }

    int Heuristic(Vector2Int a, Vector2Int b) => Mathf.Abs(a.x - b.x) + Mathf.Abs(a.y - b.y);

    Vector2Int GetLowestF(List<Vector2Int> open, Dictionary<Vector2Int, int> fScore)
    {
        Vector2Int best = open[0];
        int bestScore = fScore.ContainsKey(best) ? fScore[best] : int.MaxValue;

        for (int i = 1; i < open.Count; i++)
        {
            var v = open[i];
            int s = fScore.ContainsKey(v) ? fScore[v] : int.MaxValue;
            if (s < bestScore) { best = v; bestScore = s; }
        }
        return best;
    }

    IEnumerable<Vector2Int> Neighbors(Vector2Int c)
    {
        yield return new Vector2Int(c.x + 1, c.y);
        yield return new Vector2Int(c.x - 1, c.y);
        yield return new Vector2Int(c.x, c.y + 1);
        yield return new Vector2Int(c.x, c.y - 1);
    }

    bool InBounds(Vector2Int c) => c.x >= 0 && c.y >= 0 && c.x < grid.width && c.y < grid.height;

    bool IsBlocked(Vector2Int cell)
    {
        Vector3 center = grid.CellToWorldCenter(cell) + Vector3.up * grid.obstacleCheckHeight;
        return Physics.CheckBox(
            center,
            new Vector3(grid.cellSize * 0.45f, 0.5f, grid.cellSize * 0.45f),
            Quaternion.identity,
            grid.obstacleLayer
        );
    }

    List<Vector2Int> Reconstruct(Dictionary<Vector2Int, Vector2Int> cameFrom, Vector2Int current)
    {
        var path = new List<Vector2Int> { current };
        while (cameFrom.ContainsKey(current))
        {
            current = cameFrom[current];
            path.Add(current);
        }
        path.Reverse();
        return path;
    }
}
