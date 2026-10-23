import cn.familyguard.elder.NetworkRecoveryPolicy;

public final class NetworkRecoveryChecks {
    private static void check(boolean value, String message) {
        if (!value) throw new AssertionError(message);
    }
    public static void main(String[] args) {
        NetworkRecoveryPolicy p = new NetworkRecoveryPolicy();
        check(p.available("wifi"), "initial default route triggers recovery");
        check(!p.capabilities("wifi", false), "unvalidated event is not a second trigger");
        check(p.capabilities("wifi", true), "late internet validation must retry recovery");
        check(!p.capabilities("wifi", true), "repeated capabilities must not poll");
        check(p.available("cell"), "rapid Wi-Fi/cellular switch must not be lost to time debounce");
        check(!p.lost("wifi"), "old network loss must not cancel new route recovery");
        check(!p.capabilities("wifi", true), "old network callback ignored");
        check(p.capabilities("cell", true), "cellular ready triggers recovery");
        check(!p.blocked("cell", true), "blocked route does not trigger traffic");
        check(p.blocked("cell", false), "lifting OS data block triggers recovery");
        check(!p.blocked("cell", false), "unchanged block state must not poll");
        check(!p.capabilities("cell", false), "validation loss does not trigger traffic");
        check(p.capabilities("cell", true), "internet recovery on same route triggers recovery");
        check(p.lost("cell"), "default route loss cancels pending recovery");
        check(!p.capabilities("cell", true), "lost route cannot trigger traffic");
        check(p.available("cell"), "same route reconnect after disconnect is a new event");
        System.out.println("Network recovery checks passed");
    }
}
