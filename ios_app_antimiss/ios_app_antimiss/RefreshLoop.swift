import Foundation

/// A temporary connection failure must not permanently stop foreground updates.
@MainActor enum RefreshLoop {
    static func run(attempt: () async throws -> Void, failure: (Error) -> Void,
                    pause: () async throws -> Void = { try await Task.sleep(for: .seconds(15)) }) async {
        while !Task.isCancelled {
            do { try await attempt() }
            catch {
                if Task.isCancelled || error is CancellationError { return }
                failure(error)
            }
            do { try await pause() } catch { return }
        }
    }
}
