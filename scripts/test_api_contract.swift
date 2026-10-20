import Foundation

@main struct ContractChecks {
    static func main() throws {
        let data = try Data(contentsOf: URL(fileURLWithPath: CommandLine.arguments[1]))
        let list = try JSONDecoder().decode(ElderList.self, from: data)
        precondition(list.elders.count == 1)
        let elder = list.elders[0]
        precondition(elder.paired && elder.is_owner && elder.can_edit)
        precondition(elder.location != nil && elder.settings.fence != nil)
        precondition(elder.events.contains { $0.kind == "offline" && $0.active == 1 })
        precondition(elder.members.count == 1 && elder.members[0].can_edit == 0)
        print("Swift decoded actual backend response: location, settings, authorization, event and push state")
    }
}
