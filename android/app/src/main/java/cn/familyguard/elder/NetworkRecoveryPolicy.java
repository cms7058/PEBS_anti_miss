package cn.familyguard.elder;

/** Edge-triggered recovery, confined to the service's main thread. No timer polling. */
public final class NetworkRecoveryPolicy {
    private Object current;
    private boolean validated;
    private boolean blocked;

    public boolean isCurrent(Object network) { return network.equals(current); }

    public boolean available(Object network) {
        if (isCurrent(network)) return false;
        current = network;
        validated = false;
        blocked = false;
        return true;
    }

    public boolean capabilities(Object network, boolean ready) {
        if (!isCurrent(network)) return false;
        boolean recover = ready && !validated && !blocked;
        validated = ready;
        return recover;
    }

    public boolean blocked(Object network, boolean value) {
        if (!isCurrent(network)) return false;
        boolean recover = blocked && !value;
        blocked = value;
        return recover;
    }

    public boolean lost(Object network) {
        if (!isCurrent(network)) return false;
        current = null;
        validated = false;
        blocked = false;
        return true;
    }
}
