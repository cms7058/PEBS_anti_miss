import Foundation

enum TemporaryFailure: Error { case offline }
@main struct RefreshLoopTest {
    @MainActor static func main() async {
        var attempts = 0, failures = 0, pauses = 0
        await RefreshLoop.run(attempt: {
            attempts += 1
            if attempts == 1 { throw TemporaryFailure.offline }
        }, failure: { _ in failures += 1 }, pause: {
            pauses += 1
            if pauses == 2 { throw CancellationError() }
        })
        precondition(attempts == 2 && failures == 1 && pauses == 2, "Must recover after a transient failure")
        var cancellationFailures = 0
        await RefreshLoop.run(attempt: { throw CancellationError() }, failure: { _ in cancellationFailures += 1 },
                              pause: { fatalError("Cancellation must stop immediately") })
        precondition(cancellationFailures == 0)
        print("PASS: foreground refresh recovers after failure and stops on cancellation")
    }
}
