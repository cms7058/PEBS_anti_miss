import Foundation

/// All API values are WGS-84. Mainland map display/search is adapted at the UI boundary.
/// Approximate GCJ-02 math; real location/search alignment must be verified on the target device.
enum Coordinates {
    static func mainland(_ lat: Double, _ lon: Double) -> Bool {
        // Initial deployment targets mainland China. Rectangular coverage is not a border dataset.
        guard (0.8293...55.8271).contains(lat), (72.004...137.8347).contains(lon) else { return false }
        if (21.8...25.4).contains(lat) && (119.3...122.3).contains(lon) { return false } // Taiwan
        if (22.1...22.6).contains(lat) && (113.8...114.5).contains(lon) { return false } // Hong Kong
        if (22.0...22.25).contains(lat) && (113.5...113.62).contains(lon) { return false } // Macao
        return true
    }
    static func display(lat: Double, lon: Double) -> (lat: Double, lon: Double) {
        guard mainland(lat, lon) else { return (lat, lon) }
        let x = lon - 105, y = lat - 35
        var dlat = -100 + 2 * x + 3 * y + 0.2 * y * y + 0.1 * x * y + 0.2 * sqrt(abs(x))
        dlat += (20 * sin(6 * x * .pi) + 20 * sin(2 * x * .pi)) * 2 / 3
        dlat += (20 * sin(y * .pi) + 40 * sin(y * .pi / 3)) * 2 / 3
        dlat += (160 * sin(y * .pi / 12) + 320 * sin(y * .pi / 30)) * 2 / 3
        var dlon = 300 + x + 2 * y + 0.1 * x * x + 0.1 * x * y + 0.1 * sqrt(abs(x))
        dlon += (20 * sin(6 * x * .pi) + 20 * sin(2 * x * .pi)) * 2 / 3
        dlon += (20 * sin(x * .pi) + 40 * sin(x * .pi / 3)) * 2 / 3
        dlon += (150 * sin(x * .pi / 12) + 300 * sin(x * .pi / 30)) * 2 / 3
        let rad = lat / 180 * .pi
        let magic = 1 - 0.006693421622965943 * pow(sin(rad), 2)
        let root = sqrt(magic)
        let latitudeDelta = dlat * 180 / ((6378245 * (1 - 0.006693421622965943)) / (magic * root) * .pi)
        let longitudeDelta = dlon * 180 / (6378245 / root * cos(rad) * .pi)
        return (lat + latitudeDelta, lon + longitudeDelta)
    }
    static func canonical(lat: Double, lon: Double, country: String?) -> (lat: Double, lon: Double) {
        guard country == "CN", mainland(lat, lon) else { return (lat, lon) }
        var result = (lat: lat, lon: lon)
        for _ in 0..<8 {
            let point = display(lat: result.lat, lon: result.lon)
            result.lat -= point.lat - lat
            result.lon -= point.lon - lon
        }
        return result
    }
}
