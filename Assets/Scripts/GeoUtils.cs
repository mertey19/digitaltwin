using UnityEngine;

public static class GeoUtils
{
    public static Vector3 LatLonToUnityXZ(
        double lat, double lon,
        double originLat, double originLon)
    {
        const double R = 6378137.0;

        double dLat = (lat - originLat) * Mathf.Deg2Rad;
        double dLon = (lon - originLon) * Mathf.Deg2Rad;

        double x = R * dLon * System.Math.Cos(originLat * Mathf.Deg2Rad);
        double z = R * dLat;

        return new Vector3((float)x, 0f, (float)z);
    }
}
