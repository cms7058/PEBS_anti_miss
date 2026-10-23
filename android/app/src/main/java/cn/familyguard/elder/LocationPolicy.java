package cn.familyguard.elder;

/** Pure policy, testable without a phone; never changes a capture's original timestamp. */
public final class LocationPolicy {
    private LocationPolicy() {}
    public static boolean pendingRequest(String id, String completed, double expires, double now) {
        return !id.isEmpty() && !id.equals(completed) && expires > now;
    }
    public static boolean retryFix(int attempts, double expires, double now) {
        return attempts < 2 && expires - now >= 15;
    }
    public static long fixWindow(double expires, double now) {
        return Math.max(1000L, Math.min(90000L, (long)((expires - now) * 1000)));
    }
    public static long sampleInterval(boolean automatic, boolean pending) {
        return automatic && !pending ? 60000L : 1000L;
    }
    public static boolean restartFix(boolean locating, boolean wasAutomatic, boolean automatic,
                                     boolean wasRequested, boolean pending, String previousID, String nextID) {
        return locating && (wasAutomatic != automatic || wasRequested != pending ||
            (pending && !previousID.equals(nextID)));
    }
    public static boolean fresh(long elapsed, long nowElapsed, long startedElapsed,
                                long wall, long nowWall, long lastUploaded, float accuracy) {
        return elapsed >= startedElapsed && nowElapsed >= elapsed && nowElapsed - elapsed <= 120000
            && wall > lastUploaded && wall >= nowWall - 120000 && wall <= nowWall + 30000
            && Float.isFinite(accuracy) && accuracy > 0;
    }
    public static boolean prefer(float accuracy, long elapsed, float bestAccuracy, long bestElapsed, boolean moving) {
        return (moving && elapsed - bestElapsed >= 10000) || accuracy < bestAccuracy;
    }
    public static boolean readyToUpload(float accuracy, boolean requested, long captureAge) {
        return Float.isFinite(accuracy) && accuracy > 0 && accuracy <= 10000 &&
            (accuracy <= 100 || (requested && captureAge >= 1500));
    }
    public static long retryDelay(int failures) {
        switch (failures) { case 1: return 5000; case 2: return 15000; case 3: return 30000; default: return -1; }
    }
    public static boolean uploadable(long captured, long now) {
        return now - captured <= 120000 && captured <= now + 30000;
    }
}
