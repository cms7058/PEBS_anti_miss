package cn.familyguard.elder

import android.content.Context
import java.net.HttpURLConnection

/** One server event connection owned by the foreground guard, no command/GPS polling. */
class CommandStream(private val context: Context, private val hint: () -> Unit, private val stateChanged: () -> Unit) {
    private val prefs = context.getSharedPreferences("guard", Context.MODE_PRIVATE)
    private val monitor = Object()
    @Volatile private var stopped = false
    @Volatile private var connection: HttpURLConnection? = null
    private var epoch = 0L
    private val thread = Thread({ run() }, "GuardCommandEvents").apply { isDaemon = true }
    fun start() { thread.start() }
    fun reconnect() {
        val old = synchronized(monitor) { epoch++; monitor.notifyAll(); connection }
        if (old != null) Thread({ old.disconnect() }, "GuardEventDisconnect").apply { isDaemon = true; start() }
    }
    fun close() {
        stopped = true
        reconnect()
        thread.interrupt()
        update(false, "closed")
    }
    private fun allowed() = !stopped && prefs.getBoolean("tracking_enabled", false) && prefs.getBoolean("push_consent", false) && !prefs.getString("token", "").isNullOrEmpty()
    private fun update(connected: Boolean, state: String) {
        val changed = prefs.getBoolean("command_stream_connected", false) != connected || prefs.getString("command_stream_state", "") != state
        prefs.edit().putBoolean("command_stream_connected", connected).putString("command_stream_state", state).apply()
        if (changed) stateChanged()
    }
    private fun run() {
        var failures = 0
        while (allowed()) {
            val attemptEpoch = synchronized(monitor) { epoch }
            var current: HttpURLConnection? = null
            try {
                update(false, "connecting")
                current = Api(context).openConnection("/device/events", readTimeout = 75000)
                connection = current
                current.setRequestProperty("Accept", "text/event-stream")
                current.setRequestProperty("Accept-Encoding", "identity")
                val status = current.responseCode
                if (status in listOf(401, 403, 404)) { update(false, if (status == 404) "unsupported" else "unauthorized"); return }
                if (status != 200 || current.contentType?.startsWith("text/event-stream") != true) throw IllegalStateException("event channel unavailable")
                update(true, "connected")
                failures = 0
                current.inputStream.bufferedReader().use { reader ->
                    while (allowed() && synchronized(monitor) { epoch == attemptEpoch }) {
                        val line = reader.readLine() ?: break
                        if (line == "data: sync_commands") hint()
                        // Keepalive comments never trigger a command fetch, GPS or wake lock.
                    }
                }
            } catch (_: Exception) { /* Never log auth headers, endpoint URLs or tokens. */ }
            finally {
                current?.disconnect()
                if (connection === current) connection = null
            }
            if (!allowed()) break
            update(false, "reconnecting")
            val delay = longArrayOf(5000, 15000, 30000, 60000, 120000)[failures.coerceAtMost(4)]
            failures++
            try { synchronized(monitor) { if (allowed() && epoch == attemptEpoch) monitor.wait(delay) } }
            catch (_: InterruptedException) { if (stopped) break }
        }
    }
}
