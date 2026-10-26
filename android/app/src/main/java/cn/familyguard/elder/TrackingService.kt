package cn.familyguard.elder

import android.Manifest
import android.app.*
import android.content.Intent
import android.content.pm.PackageManager
import android.location.Location
import android.location.LocationListener
import android.location.LocationManager
import android.os.*
import android.net.ConnectivityManager
import android.net.Network
import android.net.NetworkCapabilities
import org.json.JSONObject
import com.igexin.sdk.PushManager
import java.text.SimpleDateFormat
import java.util.Date
import java.util.Locale
import java.util.concurrent.Executors

/** Bounded on-demand fixes; OS location subscriptions while automatic guard rules are active. */
class TrackingService : Service(), LocationListener {
    private lateinit var manager: LocationManager
    private val worker = Executors.newSingleThreadExecutor()
    private val metadata = Executors.newSingleThreadExecutor()
    private var reporting = false
    private var commandStream: CommandStream? = null
    private var lastReport = 0L
    private var lastReportSignature = ""
    private val uploader = Executors.newSingleThreadExecutor()
    private var pendingUpload: JSONObject? = null
    private var uploadFailures = 0
    private val networkRecovery = NetworkRecoveryPolicy()
    private val recoverNetwork = Runnable {
        if (active()) {
            commandStream?.reconnect()
            // Re-enable the SDK on the new default route, without stopping its process.
            ElderPushRuntime.start(this)
            retryCount = 0
            lastReportSignature = ""
            sendPending()
            syncNow()
        }
    }
    private fun scheduleNetworkRecovery() {
        handler.removeCallbacks(recoverNetwork)
        if (active()) handler.postDelayed(recoverNetwork, 1500)
    }
    private var networkRegistered = false
    private var retryScheduled = false
    private val retryUpload = Runnable { retryScheduled = false; sendPending(); releaseIfIdle() }
    private val networkCallback = object : ConnectivityManager.NetworkCallback() {
        override fun onAvailable(network: Network) {
            handler.post {
                if (networkRecovery.available(network)) scheduleNetworkRecovery()
            }
        }
        override fun onCapabilitiesChanged(network: Network, capabilities: NetworkCapabilities) {
            val ready = capabilities.hasCapability(NetworkCapabilities.NET_CAPABILITY_INTERNET) &&
                capabilities.hasCapability(NetworkCapabilities.NET_CAPABILITY_VALIDATED)
            handler.post {
                if (networkRecovery.capabilities(network, ready)) scheduleNetworkRecovery()
            }
        }
        override fun onBlockedStatusChanged(network: Network, blocked: Boolean) {
            handler.post {
                if (networkRecovery.blocked(network, blocked)) scheduleNetworkRecovery()
                if (blocked && networkRecovery.isCurrent(network)) handler.removeCallbacks(recoverNetwork)
            }
        }
        override fun onLost(network: Network) {
            handler.post {
                if (networkRecovery.lost(network)) handler.removeCallbacks(recoverNetwork)
            }
        }
    }
    private val handler = Handler(Looper.getMainLooper())
    private val prefs by lazy { getSharedPreferences("guard", MODE_PRIVATE) }
    @Volatile private var destroyed = false
    private var foregroundReady = false
    private val workWake by lazy {
        getSystemService(PowerManager::class.java).newWakeLock(PowerManager.PARTIAL_WAKE_LOCK, "familyguard:location-work")
            .apply { setReferenceCounted(false) }
    }
    private fun keepWorking() { if (active()) workWake.acquire(150000L) }
    private fun releaseIfIdle() {
        if (!syncing && (!locating || (automaticSampling && !requestSampling)) && !uploading && !retryScheduled && workWake.isHeld) workWake.release()
    }
    private var locating = false
    private var automaticSampling = false
    private var requestSampling = false
    private var uploading = false
    private var bestLocation: Location? = null
    private var gpsListening = false
    private var fixStartedElapsed = 0L
    private var nextFix = 0L
    private var request: JSONObject? = null
    private var completedRequest = ""
    private var attemptRequestID = ""
    private var requestAttempts = 0
    private var settings = JSONObject()
    private val quickRequestedFix = Runnable {
        // Bounded GPS grace; indoors a fresh network estimate remains an honest fallback.
        if (active() && locating && !uploading) bestLocation?.let {
            if (readyToUpload(it)) uploadLocation(it)
        }
    }
    private val fixTimeout: Runnable = object : Runnable {
      override fun run() {
        val best = bestLocation
        if (best != null && active()) uploadLocation(best)
        else {
            android.util.Log.w("FamilyGuard", "fresh fix timed out without sample")
            if (hasPendingRequest() && LocationPolicy.retryFix(requestAttempts, request!!.optDouble("expires"), System.currentTimeMillis()/1000.0)) {
                stopFix()
                startFix() // One bounded fresh attempt within this request, never idle polling.
                update("本次未取得新位置，正在为家属请求重试定位…")
            } else {
                if (!automaticSampling) stopFix()
                else handler.postDelayed(this, 90000)
                update("本次未取得新位置，请检查定位权限和系统定位；家属可在超时后重试")
            }
        }
      }
    }
    companion object {
        @Volatile private var running: TrackingService? = null
        fun isRunning(): Boolean = running?.let { it.foregroundReady && it.active() } == true
        fun signal(): Boolean {
            val service = running ?: return false
            android.util.Log.i("FamilyGuard", "command signal received; service running")
            service.keepWorking()
            service.handler.post { service.syncNow() }
            return true
        }
    }
    private var syncing = false
    private var syncAgain = false
    private var retryCount = 0
    private var cidChecks = 0
    private val recoverCID = object : Runnable {
        override fun run() {
            if (!active()) return
            if (ElderPushRuntime.cacheCID(this@TrackingService)) { syncNow(); return }
            if (++cidChecks < 5) handler.postDelayed(this, 10000)
            else {
                if (prefs.getString("push_registration", "") != "initialization_failed") {
                    prefs.edit().putString("push_registration", "waiting_cid")
                        .putString("push_status", "推送未取得标识，请检查网络并点击“重试推送登记”").apply()
                }
                syncNow() // Report the failed startup once; no permanent registration polling.
            }
        }
    }
    private val automaticTick = Runnable { syncNow() }
    private fun syncNow() {
        if (!active()) return
        if (syncing) { syncAgain = true; return }
        syncing = true
        keepWorking()
        handler.removeCallbacks(automaticTick)
        worker.execute {
            var error: String? = null
            var config: JSONObject? = null
            try {
                val api = Api(this)
                config = api.request("/device/commands")
                if (active()) prefs.edit().putString("settings", config.getJSONObject("settings").toString())
                    .putInt("settings_version", config.getInt("version")).commit()
            } catch (e: Exception) { error = e.message ?: "连接失败" }
            val result = config
            val failure = error
            handler.post {
                syncing = false
                if (!active()) return@post
                if (result != null) {
                    retryCount = 0
                    val previousInterval = interval()
                    settings = result.getJSONObject("settings")
                    DeviceSettings.receive(this, result.optJSONObject("setup_request"))
                    val previousRequestID = request?.optString("id") ?: ""
                    request = result.optJSONObject("location_request")
                    val pending = hasPendingRequest()
                    val restart = LocationPolicy.restartFix(locating, automaticSampling, automatic(), requestSampling,
                        pending, previousRequestID, request?.optString("id") ?: "") || (locating && automaticSampling && previousInterval != interval())
                    if (restart) stopFix()
                    if (!automatic() && !pending) {
                        if (locating) stopFix()
                        if (!uploading) update("按需定位待命中 · 不定时定位，不轮询家属请求")
                    }
                    if (!locating && !uploading && (pending || (automatic() && (restart || SystemClock.elapsedRealtime() >= nextFix)))) startFix()
                } else {
                    update("同步失败：$failure")
                    if (automatic() && !locating && !uploading && SystemClock.elapsedRealtime() >= nextFix) startFix()
                }
                GuardWakeReceiver.schedule(this, automatic())
                if (syncAgain) {
                    syncAgain = false
                    handler.post(automaticTick)
                } else if (automatic()) {
                    handler.postDelayed(automaticTick, interval())
                } else if (failure != null && retryCount++ < 2) {
                    // Only bounded recovery for this trigger; no idle polling.
                    handler.postDelayed(automaticTick, 20000)
                }
                reportPushStateAsync()
                releaseIfIdle()
            }
        }
    }
    private fun reportPushStateAsync() {
        val signature = listOf(prefs.getString("push_cid", ""), prefs.getString("push_registration", ""),
            prefs.getBoolean("push_online", false), DeviceSettings.collect(this).toString(),
            prefs.getString("setup_id", ""), prefs.getString("setup_state", "")).joinToString(":")
        val now = SystemClock.elapsedRealtime()
        if (!active() || reporting || (signature == lastReportSignature && now - lastReport < 300000)) return
        reporting = true
        lastReport = now
        lastReportSignature = signature
        metadata.execute {
            try { if (active()) reportPushState() }
            finally { handler.post { reporting = false; if (active()) reportPushStateAsync() } }
        }
    }
    private fun reportPushState() {
        DeviceSettings.report(this)
        try {
            val api = Api(this)
            ElderPushRuntime.cacheCID(this)
            val cid = prefs.getString("push_cid", "") ?: ""
            if (cid.isNotEmpty()) {
                try {
                    api.request("/device/push", JSONObject().put("cid", cid).put("app_id", BuildConfig.GETUI_APP_ID))
                    prefs.edit().putString("push_status", "推送设备已登记，等待消息").putString("push_registration", "registered").apply()
                } catch (e: Exception) {
                    prefs.edit().putString("push_status", "推送登记失败：${e.message ?: "请检查网络"}")
                        .putString("push_registration", "registration_failed").apply()
                }
            }
            if (!active()) return
            val diagnostics = JSONObject().put("app_version", BuildConfig.VERSION_NAME)
                .put("push_consent", prefs.getBoolean("push_consent", false)).put("cid_available", cid.isNotEmpty())
                .put("registration_state", prefs.getString("push_registration", "waiting_cid"))
            if (prefs.contains("push_online")) diagnostics.put("sdk_online", prefs.getBoolean("push_online", false))
            api.request("/device/diagnostics", diagnostics)
        } catch (_: Exception) { /* Diagnostics must never block location uploads. */ }
    }
    private fun active() = !destroyed && prefs.getBoolean("tracking_enabled", false)
    private fun hasPermission() = checkSelfPermission(Manifest.permission.ACCESS_FINE_LOCATION) == PackageManager.PERMISSION_GRANTED
    override fun onBind(intent: Intent?) = null
    override fun onCreate() {
        super.onCreate()
        manager = getSystemService(LocationManager::class.java)
        getSystemService(NotificationManager::class.java).createNotificationChannel(NotificationChannel("tracking", "位置守护", NotificationManager.IMPORTANCE_LOW))
        if (!active() || !hasPermission() || !prefs.getBoolean("push_consent", false)) { stopSelf(); return }
        try {
            startForeground(1, notification("省电守护正在启动"))
            foregroundReady = true
            GuardWakeReceiver.cancelRecovery(this)
            running = this
            settings = JSONObject(prefs.getString("settings", "{}") ?: "{}")
            pendingUpload = try { prefs.getString("pending_location", null)?.let { JSONObject(it) } } catch (_: Exception) { null }
            try {
                getSystemService(ConnectivityManager::class.java).registerDefaultNetworkCallback(networkCallback)
                networkRegistered = true
            } catch (_: Exception) { }
            ElderPushRuntime.start(this)
            handler.postDelayed(recoverCID, 5000)
            commandStream = CommandStream(this, {
                if (active()) { keepWorking(); handler.post { syncNow() } }
            }, { handler.post { if (active()) reportPushStateAsync() } }).also { it.start() }
        } catch (_: Exception) {
            prefs.edit().putString("status", "系统未允许恢复定位，请打开应用重新开始守护").apply()
            stopSelf()
        }
    }
    private fun notification(message: String): Notification {
        val open = PendingIntent.getActivity(this, 0, Intent(this, MainActivity::class.java), PendingIntent.FLAG_IMMUTABLE or PendingIntent.FLAG_UPDATE_CURRENT)
        return Notification.Builder(this, "tracking").setSmallIcon(android.R.drawable.ic_menu_mylocation).setContentTitle("家人守护正在运行").setContentText(message).setContentIntent(open).setOngoing(true).build()
    }
    private fun update(message: String) {
        if (!active()) return
        prefs.edit().putString("status", message).apply()
        getSystemService(NotificationManager::class.java).notify(1, notification(message))
    }
    override fun onStartCommand(intent: Intent?, flags: Int, startId: Int): Int {
        if (!foregroundReady || !active() || prefs.getString("token", "").isNullOrEmpty() || !hasPermission()) {
            stopSelf(); return START_NOT_STICKY
        }
        sendPending()
        syncNow()
        return START_STICKY
    }
    private fun automatic(): Boolean = settings.optJSONObject("fence") != null ||
        settings.optJSONObject("trip")?.optString("status") == "active"
    // Only called for automatic guard scheduling; on-demand requests bypass the timer.
    private fun interval(): Long = settings.optInt("automatic_interval", 60).coerceIn(30, 120) * 1000L
    private fun hasPendingRequest(): Boolean = request?.let {
        LocationPolicy.pendingRequest(it.optString("id"), completedRequest, it.optDouble("expires", 0.0), System.currentTimeMillis()/1000.0)
    } ?: false
    private fun startFix() {
        if (!active() || locating || uploading || !hasPermission()) return
        nextFix = SystemClock.elapsedRealtime() + interval()
        bestLocation = null
        fixStartedElapsed = SystemClock.elapsedRealtime()
        android.util.Log.i("FamilyGuard", "fresh fix started; automatic=${automatic()}; remote=${request != null}")
        locating = true
        automaticSampling = automatic()
        requestSampling = hasPendingRequest()
        if (requestSampling) {
            val id = request!!.getString("id")
            if (id != attemptRequestID) { attemptRequestID = id; requestAttempts = 0 }
            requestAttempts++
        }
        keepWorking()
        var listening = false
        gpsListening = false
        for (provider in listOf(LocationManager.NETWORK_PROVIDER, LocationManager.GPS_PROVIDER)) {
            try {
                if (manager.allProviders.contains(provider) && manager.isProviderEnabled(provider)) {
                    manager.requestLocationUpdates(provider, if (automaticSampling && !requestSampling) interval() else 1000L, 0f, this, Looper.getMainLooper())
                    listening = true
                    if (provider == LocationManager.GPS_PROVIDER) gpsListening = true
                }
            } catch (_: Exception) { }
        }
        if (!listening) {
            stopFix(); update("系统定位未开启或权限不足，请打开定位设置"); return
        }
        update(if (request != null) "已收到家属请求，正在获取新位置…" else "正在进行定时定位…")
        val window = if (requestSampling) LocationPolicy.fixWindow(request!!.optDouble("expires"), System.currentTimeMillis()/1000.0) else 90000L
        handler.postDelayed(fixTimeout, window)
        handler.postDelayed(quickRequestedFix, LocationPolicy.GPS_GRACE_MS)
    }
    private fun stopFix() {
        locating = false
        automaticSampling = false
        requestSampling = false
        manager.removeUpdates(this)
        gpsListening = false
        handler.removeCallbacks(fixTimeout)
        handler.removeCallbacks(quickRequestedFix)
        releaseIfIdle()
    }
    override fun onLocationChanged(location: Location) {
        if (!active() || !locating || uploading) return
        val elapsed = location.elapsedRealtimeNanos / 1000000
        if (!location.hasAccuracy() || location.accuracy > 10000 || !LocationPolicy.fresh(elapsed, SystemClock.elapsedRealtime(), fixStartedElapsed,
                location.time, System.currentTimeMillis(), prefs.getLong("last_uploaded_capture", 0), location.accuracy)) return
        val best = bestLocation
        val moving = location.hasSpeed() && location.speed > 0.7f
        if (best == null || LocationPolicy.prefer(location.accuracy, elapsed, best.accuracy, best.elapsedRealtimeNanos / 1000000, moving)) bestLocation = Location(location)
        // A usable GPS fix wins immediately; otherwise upload the best candidate, not
        // whichever (possibly worse) provider callback happened to cross the deadline.
        val candidate = if (location.provider == LocationManager.GPS_PROVIDER && location.accuracy <= 100) location else bestLocation
        if (candidate != null && readyToUpload(candidate)) uploadLocation(candidate)
    }
    private fun readyToUpload(location: Location): Boolean = LocationPolicy.readyToUpload(
        location.accuracy, hasPendingRequest(), SystemClock.elapsedRealtime() - fixStartedElapsed,
        location.provider == LocationManager.GPS_PROVIDER, gpsListening)
    private fun uploadLocation(location: Location) {
        if (!active()) return
        handler.removeCallbacks(quickRequestedFix)
        if (automaticSampling) {
            // Keep OS location subscriptions while rules need monitoring. Handler timers alone
            // cannot reliably wake a sleeping CPU; provider callbacks drive subsequent samples.
            bestLocation = null
            fixStartedElapsed = SystemClock.elapsedRealtime()
            handler.postDelayed(quickRequestedFix, LocationPolicy.GPS_GRACE_MS)
            handler.removeCallbacks(fixTimeout)
            handler.postDelayed(fixTimeout, 90000)
        } else stopFix()
        val remote = request?.takeIf { it.optString("id") != completedRequest &&
            it.optDouble("expires") > System.currentTimeMillis()/1000.0 && location.time/1000.0 >= it.optDouble("requested_at") }
        val battery = getSystemService(BatteryManager::class.java).getIntProperty(BatteryManager.BATTERY_PROPERTY_CAPACITY).coerceIn(0, 100)
        val payload = JSONObject().put("lat", location.latitude).put("lon", location.longitude)
            .put("accuracy", location.accuracy.toDouble()).put("recorded_at", location.time / 1000.0)
            .put("battery", battery).put("applied_version", prefs.getInt("settings_version", 0))
            .put("provider", if (location.provider == LocationManager.GPS_PROVIDER) "gps" else "network")
        if (remote != null) payload.put("request_id", remote.getString("id")).put("request_expires", remote.getDouble("expires"))
        val previous = pendingUpload
        if (previous == null || payload.getDouble("recorded_at") > previous.getDouble("recorded_at")) {
            pendingUpload = payload
            uploadFailures = 0
            prefs.edit().putString("pending_location", payload.toString()).commit()
        }
        sendPending()
    }
    private fun sendPending() {
        if (!active() || uploading) return
        val stored = pendingUpload ?: return
        val captured = (stored.getDouble("recorded_at") * 1000).toLong()
        if (!LocationPolicy.uploadable(captured, System.currentTimeMillis())) {
            pendingUpload = null
            prefs.edit().remove("pending_location").apply()
            update("待传位置已过期，等待下一次新定位；不会把旧位置当作实时位置")
            return
        }
        handler.removeCallbacks(retryUpload)
        retryScheduled = false
        val payload = JSONObject(stored.toString())
        val requestID = payload.optString("request_id")
        if (payload.optDouble("request_expires", 0.0) <= System.currentTimeMillis()/1000.0) payload.remove("request_id")
        payload.remove("request_expires")
        uploading = true
        keepWorking()
        uploader.execute {
            var failure: String? = null
            try {
                if (!active()) return@execute
                val api = Api(this)
                try { api.request("/device/location", payload) }
                catch (e: ApiFailure) {
                    if (e.status != 409) throw e
                    // An acknowledgement can be lost during Wi-Fi/mobile handover.
                    val status = api.request("/device/settings")
                    if (status.optDouble("last_recorded_at", -1.0) < payload.getDouble("recorded_at")) {
                        payload.remove("request_id")
                        api.request("/device/location", payload)
                    }
                }
                prefs.edit().putLong("last_uploaded_capture", maxOf(captured, prefs.getLong("last_uploaded_capture", 0)))
                    .putLong("last_upload", System.currentTimeMillis()).apply()
            } catch (e: Exception) { failure = e.message ?: "请检查网络" }
            val error = failure
            handler.post {
                uploading = false
                if (!active()) return@post
                val same = pendingUpload?.optDouble("recorded_at") == stored.getDouble("recorded_at")
                if (error == null) {
                    android.util.Log.i("FamilyGuard", "location upload acknowledged")
                    if (same) { pendingUpload = null; prefs.edit().remove("pending_location").apply() }
                    if (requestID.isNotEmpty()) completedRequest = requestID
                    val time = SimpleDateFormat("HH:mm:ss", Locale.CHINA).format(Date(captured))
                    update("省电守护中 · $time 已同步 · 等待下次采集")
                    if (pendingUpload != null) sendPending()
                    syncNow()
                } else {
                    android.util.Log.w("FamilyGuard", "location upload failed; bounded retry")
                    update("已取得位置，网络上传失败：$error；正在等待重试")
                    if (!same) { sendPending(); return@post }
                    val delay = LocationPolicy.retryDelay(++uploadFailures)
                    if (delay >= 0) {
                        retryScheduled = true
                        keepWorking()
                        handler.postDelayed(retryUpload, delay)
                    }
                    // Network recovery can also retry this original capture before it expires.
                }
                releaseIfIdle()
            }
        }
    }
    override fun onProviderEnabled(provider: String) { nextFix = 0 }
    override fun onProviderDisabled(provider: String) { update("定位源已关闭，请检查系统定位开关") }
    @Deprecated("Legacy callback")
    override fun onStatusChanged(provider: String?, status: Int, extras: Bundle?) {}
    private fun activeForRecovery() = prefs.getBoolean("tracking_enabled", false) && prefs.getBoolean("push_consent", false)
    override fun onTaskRemoved(rootIntent: Intent?) {
        GuardWakeReceiver.recoverAfterLoss(this)
        super.onTaskRemoved(rootIntent)
    }
    override fun onDestroy() {
        destroyed = true
        commandStream?.close()
        if (running === this) running = null
        stopFix()
        handler.removeCallbacksAndMessages(null)
        if (networkRegistered) {
            try { getSystemService(ConnectivityManager::class.java).unregisterNetworkCallback(networkCallback) } catch (_: Exception) { }
        }
        GuardWakeReceiver.schedule(this, activeForRecovery() && automatic())
        GuardWakeReceiver.recoverAfterLoss(this)
        if (workWake.isHeld) workWake.release()
        worker.shutdownNow()
        uploader.shutdownNow()
        metadata.shutdownNow()
        super.onDestroy()
    }
}
