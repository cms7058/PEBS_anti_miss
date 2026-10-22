package cn.familyguard.elder

import android.Manifest
import android.app.*
import android.content.Intent
import android.content.pm.PackageManager
import android.location.Location
import android.location.LocationListener
import android.location.LocationManager
import android.os.*
import org.json.JSONObject
import com.igexin.sdk.PushManager
import java.text.SimpleDateFormat
import java.util.Date
import java.util.Locale
import java.util.concurrent.Executors

/** Keep the service available, but activate location providers only for bounded fixes. */
class TrackingService : Service(), LocationListener {
    private lateinit var manager: LocationManager
    private val worker = Executors.newSingleThreadExecutor()
    private val handler = Handler(Looper.getMainLooper())
    private val prefs by lazy { getSharedPreferences("guard", MODE_PRIVATE) }
    @Volatile private var destroyed = false
    private var foregroundReady = false
    private var locating = false
    private var uploading = false
    private var bestLocation: Location? = null
    private var fixStarted = 0L
    private var nextFix = 0L
    private var request: JSONObject? = null
    private var completedRequest = ""
    private var settings = JSONObject()
    private val fixTimeout = Runnable {
        val best = bestLocation
        if (best != null && active()) uploadLocation(best)
        else {
            stopFix()
            update("本次未取得新位置，请检查定位权限和系统定位；家属可在超时后重试")
        }
    }
    companion object {
        private var running: TrackingService? = null
        fun signal(): Boolean {
            val service = running ?: return false
            service.handler.post { service.syncNow() }
            return true
        }
    }
    private var syncing = false
    private var syncAgain = false
    private var retryCount = 0
    private val automaticTick = Runnable { syncNow() }
    private fun syncNow() {
        if (!active()) return
        if (syncing) { syncAgain = true; return }
        syncing = true
        handler.removeCallbacks(automaticTick)
        worker.execute {
            var error: String? = null
            var config: JSONObject? = null
            try {
                val api = Api(this)
                val cid = prefs.getString("push_cid", "") ?: ""
                if (cid.isNotEmpty()) {
                    try {
                        api.request("/device/push", JSONObject().put("cid", cid).put("app_id", BuildConfig.GETUI_APP_ID))
                        prefs.edit().putString("push_status", "推送设备已登记，等待消息").apply()
                    } catch (_: Exception) {
                        prefs.edit().putString("push_status", "推送登记失败，请检查后台版本和个推AppID配置").apply()
                    }
                }
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
                    settings = result.getJSONObject("settings")
                    request = result.optJSONObject("location_request")
                    val pending = request?.optString("id")?.let { it != completedRequest } == true
                    if (!automatic() && !pending) {
                        if (locating) stopFix()
                        if (!uploading) update("按需定位待命中 · 不定时定位，不轮询家属请求")
                    }
                    if (!locating && !uploading && (pending || (automatic() && SystemClock.elapsedRealtime() >= nextFix))) startFix()
                } else {
                    update("同步失败：$failure")
                    if (automatic() && !locating && !uploading && SystemClock.elapsedRealtime() >= nextFix) startFix()
                }
                if (syncAgain) {
                    syncAgain = false
                    handler.post(automaticTick)
                } else if (automatic()) {
                    handler.postDelayed(automaticTick, 60000)
                } else if (failure != null && retryCount++ < 2) {
                    // Only bounded recovery for this trigger; no idle polling.
                    handler.postDelayed(automaticTick, 20000)
                }
            }
        }
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
            running = this
            settings = JSONObject(prefs.getString("settings", "{}") ?: "{}")
            PushManager.getInstance().initialize(applicationContext)
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
        syncNow()
        return START_STICKY
    }
    private fun automatic(): Boolean = settings.optJSONObject("fence") != null ||
        settings.optJSONObject("trip")?.optString("status") == "active"
    // Only called for automatic guard scheduling; on-demand requests bypass the timer.
    private fun interval(): Long = 60000L
    private fun startFix() {
        if (!active() || locating || uploading || !hasPermission()) return
        nextFix = SystemClock.elapsedRealtime() + interval()
        bestLocation = null
        fixStarted = System.currentTimeMillis()
        locating = true
        var listening = false
        for (provider in listOf(LocationManager.NETWORK_PROVIDER, LocationManager.GPS_PROVIDER)) {
            try {
                if (manager.allProviders.contains(provider) && manager.isProviderEnabled(provider)) {
                    manager.requestLocationUpdates(provider, 1000, 0f, this, Looper.getMainLooper())
                    listening = true
                }
            } catch (_: Exception) { }
        }
        if (!listening) {
            stopFix(); update("系统定位未开启或权限不足，请打开定位设置"); return
        }
        update(if (request != null) "已收到家属请求，正在获取新位置…" else "正在进行定时定位…")
        handler.postDelayed(fixTimeout, 45000)
    }
    private fun stopFix() {
        locating = false
        manager.removeUpdates(this)
        handler.removeCallbacks(fixTimeout)
    }
    override fun onLocationChanged(location: Location) {
        if (!active() || !locating || uploading) return
        // A provider cache must not complete a new remote request.
        if (location.time < fixStarted || location.time <= prefs.getLong("last_uploaded_capture", 0)) return
        if (!location.hasAccuracy() || location.accuracy <= 0 || System.currentTimeMillis() - location.time !in 0..120000) return
        if (bestLocation == null || location.accuracy < bestLocation!!.accuracy) bestLocation = Location(location)
        // Give GPS time to improve a coarse network fix before accepting it.
        if (location.accuracy <= 100) uploadLocation(location)
    }
    private fun uploadLocation(location: Location) {
        if (!active() || uploading) return
        val remote = request?.takeIf { it.optString("id") != completedRequest && it.optDouble("expires") > System.currentTimeMillis()/1000.0 }
        if (remote != null && location.time / 1000.0 < remote.getDouble("requested_at")) {
            stopFix()
            nextFix = 0
            update("已收到新请求，等待重新采集位置")
            return
        }
        stopFix()
        uploading = true
        worker.execute {
            try {
                if (!active()) return@execute
                val battery = getSystemService(BatteryManager::class.java).getIntProperty(BatteryManager.BATTERY_PROPERTY_CAPACITY).coerceIn(0, 100)
                val payload = JSONObject().put("lat", location.latitude).put("lon", location.longitude)
                    .put("accuracy", location.accuracy.toDouble()).put("recorded_at", location.time / 1000.0)
                    .put("battery", battery).put("applied_version", prefs.getInt("settings_version", 0))
                if (remote != null) payload.put("request_id", remote.getString("id"))
                Api(this).request("/device/location", payload)
                prefs.edit().putLong("last_uploaded_capture", location.time).putLong("last_upload", System.currentTimeMillis()).apply()
                val time = SimpleDateFormat("HH:mm:ss", Locale.CHINA).format(Date(location.time))
                handler.post {
                    if (remote != null) completedRequest = remote.getString("id")
                    update("省电守护中 · $time 已同步 · 定位已暂停，等待下次采集")
                }
            } catch (e: Exception) {
                handler.post { update("位置同步失败：${e.message ?: "请检查网络"}") }
            } finally { handler.post { uploading = false; if (active()) syncNow() } }
        }
    }
    override fun onProviderEnabled(provider: String) { nextFix = 0 }
    override fun onProviderDisabled(provider: String) { update("定位源已关闭，请检查系统定位开关") }
    @Deprecated("Legacy callback")
    override fun onStatusChanged(provider: String?, status: Int, extras: Bundle?) {}
    override fun onDestroy() {
        destroyed = true
        if (running === this) running = null
        stopFix()
        handler.removeCallbacksAndMessages(null)
        worker.shutdownNow()
        super.onDestroy()
    }
}
