using System.Collections.Generic;
using System.Globalization;
using System.IO;
using UnityEngine;

public class GPSPathPlayer : MonoBehaviour
{
    public Transform drone;
    public float speed = 5f;

    List<Vector3> path = new();
    int index = 0;

    void Start()
    {
        string filePath =
            Path.Combine(Application.streamingAssetsPath, "gps.csv");

        var lines = File.ReadAllLines(filePath);

        double oLat = 0, oLon = 0;

        for (int i = 1; i < lines.Length; i++)
        {
            var p = lines[i].Split(',');
            double lat = double.Parse(p[0], CultureInfo.InvariantCulture);
            double lon = double.Parse(p[1], CultureInfo.InvariantCulture);

            if (i == 1) { oLat = lat; oLon = lon; }

            path.Add(
                GeoUtils.LatLonToUnityXZ(lat, lon, oLat, oLon)
                + Vector3.up
            );
        }

        drone.position = path[0];
    }

    void Update()
    {
        if (path.Count == 0) return;

        drone.position = Vector3.MoveTowards(
            drone.position,
            path[index],
            speed * Time.deltaTime
        );

        if (Vector3.Distance(drone.position, path[index]) < 0.1f)
            index = (index + 1) % path.Count;
    }
}
