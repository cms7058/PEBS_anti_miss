import Foundation

@main struct ContractChecks {
    static func main() throws {
        let data = try Data(contentsOf: URL(fileURLWithPath: CommandLine.arguments[1]))
        let list = try JSONDecoder().decode(ElderList.self, from: data)
        precondition(list.elders.count == 1)
        let elder = list.elders[0]
        precondition(elder.paired && elder.is_owner && elder.can_edit)
        precondition(elder.location != nil && elder.settings.fence != nil)
        precondition(elder.location_freshness?.state == "historical")
        precondition(elder.locationIsHistorical(at: Date(timeIntervalSince1970: elder.location!.recorded_at)))
        let legacyPosition = try JSONDecoder().decode(Position.self, from: Data("{\"lat\":31,\"lon\":121,\"accuracy\":30,\"recorded_at\":1800000000,\"battery\":70}".utf8))
        precondition(legacyPosition.provider == nil)
        precondition(!legacyPosition.isHistorical(at: Date(timeIntervalSince1970: 1800000179.999)))
        precondition(legacyPosition.isHistorical(at: Date(timeIntervalSince1970: 1800000180)))
        let networkPosition = try JSONDecoder().decode(Position.self, from: Data("{\"lat\":31,\"lon\":121,\"accuracy\":30,\"recorded_at\":1800000000,\"battery\":70,\"provider\":\"network\"}".utf8))
        precondition(networkPosition.provider == "network" && networkPosition.sourceLabel.contains("估算"))
        precondition(elder.events.contains { $0.kind == "offline" && $0.active == 1 })
        precondition(elder.members.count == 1 && elder.members[0].can_edit == 0)
        print("Swift decoded actual backend response: location, settings, authorization, event and push state")
    }
}
