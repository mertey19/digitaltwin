using System.Collections.Generic;
using UnityEngine;

public class GridDroneMover : MonoBehaviour
{
    public GridManager grid;
    public GridPathfinder pathfinder;
    public Transform drone;
    public float speed = 4f;

    List<Vector2Int> path = new();
    int index = 0;

    public void SetTargetCell(Vector2Int target)
    {
        Vector2Int start = grid.WorldToCell(drone.position);
        path = pathfinder.FindPath(start, target);
        index = 0;
    }

    void Update()
    {
        if (path == null || path.Count == 0 || index >= path.Count) return;

        Vector3 targetPos = grid.CellToWorldCenter(path[index]) + Vector3.up * 1f;
        drone.position = Vector3.MoveTowards(drone.position, targetPos, speed * Time.deltaTime);

        if (Vector3.Distance(drone.position, targetPos) < 0.05f)
            index++;
    }
}
