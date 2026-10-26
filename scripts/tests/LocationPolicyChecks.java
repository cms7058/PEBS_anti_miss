import cn.familyguard.elder.LocationPolicy;

public final class LocationPolicyChecks {
    private static void check(boolean value, String message) { if (!value) throw new AssertionError(message); }
    public static void main(String[] args) {
        check(!LocationPolicy.readyToUpload(30, true, 0, false, true), "precise-looking network estimate must not cancel GPS");
        check(!LocationPolicy.readyToUpload(30, false, 9999, false, true), "automatic guard also allows GPS to arrive");
        check(LocationPolicy.readyToUpload(30, true, 0, true, true), "usable fresh GPS answers immediately");
        check(LocationPolicy.readyToUpload(30, true, 0, false, false), "GPS disabled: do not unnecessarily delay usable network fix");
        check(!LocationPolicy.readyToUpload(500, true, 9999, false, true), "coarse estimate waits for GPS grace");
        check(LocationPolicy.readyToUpload(500, true, 10000, false, true), "indoor query falls back after bounded grace");
        check(LocationPolicy.readyToUpload(30, false, 10000, false, true), "precise network fallback remains available for automatic guard");
        check(!LocationPolicy.readyToUpload(500, false, 10000, false, true), "query fallback does not relax automatic guard accuracy");
        check(!LocationPolicy.readyToUpload(10001, true, 10000, true, true), "reject accuracy beyond server limit");
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
        check(LocationPolicy.pendingRequest("r2", "r1", 200, 100), "new unexpired request is pending");
        check(!LocationPolicy.pendingRequest("r1", "r1", 200, 100) && !LocationPolicy.pendingRequest("r2", "r1", 100, 100), "completed and expired requests do not trigger fixes");
        check(LocationPolicy.sampleInterval(true, false) == 60000 && LocationPolicy.sampleInterval(true, true) == 1000, "guardian request must accelerate automatic sampling");
        check(LocationPolicy.restartFix(true, true, true, false, true, "", "r1"), "request during automatic capture starts a fresh capture window");
        check(!LocationPolicy.restartFix(true, true, true, true, true, "r1", "r1"), "duplicate push must not reset GPS progress");
        check(LocationPolicy.restartFix(true, true, true, true, false, "r1", ""), "completion restores low-frequency automatic sampling");
        check(LocationPolicy.restartFix(true, false, false, true, true, "r1", "r2"), "a later request receives its own full capture window");
        check(LocationPolicy.retryFix(1, 200, 100) && !LocationPolicy.retryFix(2, 200, 100) && !LocationPolicy.retryFix(1, 110, 100), "only one retry and only within the current request window");
        check(LocationPolicy.fixWindow(200, 100) == 90000 && LocationPolicy.fixWindow(120, 100) == 20000, "capture timeout respects request expiry");
        System.out.println("PASS: moving fixes, timestamp skew, provider cache, newest moving sample and bounded network recovery");
    }
}
