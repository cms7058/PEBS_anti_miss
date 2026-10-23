import cn.familyguard.elder.GuardRecoveryPolicy;
public final class GuardRecoveryChecks {
    private static void check(boolean value, String message) { if (!value) throw new AssertionError(message); }
    public static void main(String[] args) {
        check(GuardRecoveryPolicy.eligible(true,true,true,true,true,true), "consented background-ready guard can recover");
        check(!GuardRecoveryPolicy.eligible(false,true,true,true,true,true), "manual sharing stop must never revive");
        check(!GuardRecoveryPolicy.eligible(true,false,true,true,true,true), "no push consent means no recovery");
        check(!GuardRecoveryPolicy.eligible(true,true,false,true,true,true), "unbound device must not recover");
        check(!GuardRecoveryPolicy.eligible(true,true,true,false,true,true), "fine permission required");
        check(!GuardRecoveryPolicy.eligible(true,true,true,true,false,true), "background permission required");
        check(!GuardRecoveryPolicy.eligible(true,true,true,true,true,false), "battery restriction must be explicit");
        check(GuardRecoveryPolicy.allowed(0,100000,0), "initial task-loss event can schedule");
        check(!GuardRecoveryPolicy.allowed(1,101000,100000), "onTaskRemoved plus onDestroy coalesce");
        check(!GuardRecoveryPolicy.allowed(3,120000,100000), "crash recovery is bounded, not periodic polling");
        check(GuardRecoveryPolicy.newWindow(700000,100000), "budget renews after ten minutes");
        check(GuardRecoveryPolicy.newWindow(1000,100000), "reboot elapsed clock resets budget");
        System.out.println("PASS: task-loss recovery consent, permissions, stop, deduplication and retry budget");
    }
}
