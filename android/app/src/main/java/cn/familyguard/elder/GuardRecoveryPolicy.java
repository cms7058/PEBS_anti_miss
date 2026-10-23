package cn.familyguard.elder;

/** A bounded reaction to service/task loss, never an idle command polling timer. */
public final class GuardRecoveryPolicy {
    private GuardRecoveryPolicy() {}
    public static boolean eligible(boolean enabled, boolean consent, boolean paired, boolean fine,
                                   boolean background, boolean unrestricted) {
        return enabled && consent && paired && fine && background && unrestricted;
    }
    public static boolean newWindow(long now, long started) { return started <= 0 || now < started || now - started >= 600000; }
    public static boolean allowed(int attempts, long now, long last) { return attempts < 3 && (last <= 0 || now < last || now - last >= 10000); }
}
