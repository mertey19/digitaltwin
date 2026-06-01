using UnityEngine;

public class DroneCellTracker : MonoBehaviour
{
    public GridManager grid;
    public Transform drone;

    void Update()
    {
        if (grid == null || drone == null) return;

        Vector2Int cell = grid.WorldToCell(drone.position);
        Debug.Log($"Drone Cell: ({cell.x}, {cell.y})  World: {drone.position}");
    }
}
