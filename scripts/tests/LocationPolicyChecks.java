import cn.familyguard.elder.LocationPolicy;

public final class LocationPolicyChecks {
    private static void check(boolean value, String message) { if (!value) throw new AssertionError(message); }
    public static void main(String[] args) {
        long now = 1800000000000L;
        check(LocationPolicy.fresh(5100, 5200, 5000, now, now, now - 1000, 30), "fresh moving fix must be accepted");
        check(LocationPolicy.fresh(5100, 5200, 5000, now + 5000, now, now - 1000, 30), "small GPS/wall-clock skew must not discard the capture");
        check(!LocationPolicy.fresh(4900, 5200, 5000, now, now, now - 1000, 30), "provider cache from before the request must not answer it");
        check(!LocationPolicy.fresh(5100, 130000, 5000, now, now, now - 1000, 30), "stale capture rejected using elapsed time");
        check(LocationPolicy.prefer(180, 25000, 120, 10000, true), "moving: prefer a newer fix to a much older precise point");
        check(!LocationPolicy.prefer(180, 25000, 120, 10000, false), "stationary: retain better accuracy");
        check(LocationPolicy.uploadable(now, now + 45000), "handover retry preserves a valid captured point");
        check(!LocationPolicy.uploadable(now, now + 120001), "expired buffered fix must not be replayed as current");
        check(LocationPolicy.retryDelay(1) == 5000 && LocationPolicy.retryDelay(2) == 15000 && LocationPolicy.retryDelay(3) == 30000, "bounded upload backoff");
        check(LocationPolicy.retryDelay(4) < 0, "no infinite upload retry");
        System.out.println("PASS: moving fixes, timestamp skew, provider cache, newest moving sample and bounded network recovery");
    }
}
