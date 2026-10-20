import Foundation

@main struct CoordinateChecks {
    static func main() {
        // Known Beijing reference pair; catches accidental identity/double conversion.
        let beijing = Coordinates.display(lat: 39.908823, lon: 116.397470)
        precondition(abs(beijing.lat - 39.910226498) < 0.000001)
        precondition(abs(beijing.lon - 116.403713582) < 0.000001)
        let original = Coordinates.canonical(lat: beijing.lat, lon: beijing.lon, country: "CN")
        precondition(abs(original.lat - 39.908823) < 0.0000001)
        precondition(abs(original.lon - 116.397470) < 0.0000001)
        let overseas = Coordinates.display(lat: 37.7749, lon: -122.4194)
        precondition(overseas.lat == 37.7749 && overseas.lon == -122.4194)
        let shanghai = Coordinates.display(lat: 31.2304, lon: 121.4737)
        let wgs = Coordinates.canonical(lat: shanghai.lat, lon: shanghai.lon, country: "CN")
        precondition(abs(wgs.lat - 31.2304) < 0.0000001 && abs(wgs.lon - 121.4737) < 0.0000001)
        print("Coordinate checks passed: known reference, round trip, overseas identity, Shanghai round trip")
    }
}
