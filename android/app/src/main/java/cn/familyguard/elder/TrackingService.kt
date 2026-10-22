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
import java.text.SimpleDateFormat
import java.util.Date
import java.util.Locale
import java.util.concurrent.Executors
import java.util.concurrent.atomic.AtomicBoolean

class TrackingService : Service(), LocationListener {
    private lateinit var manager: LocationManager
    private val worker = Executors.newSingleThreadExecutor()
    private var destroyed = false
    private var currentFix: CancellationSignal? = null
    private var foregroundReady = false
    private var requestingFix = false
    private val uploading = AtomicBoolean(false)
    private val handler = Handler(Looper.getMainLooper())
    private val prefs by lazy { getSharedPreferences("guard", MODE_PRIVATE) }
    private val watchdog = object : Runnable {
        override fun run() {
            val last = prefs.getLong("last_capture", 0)
            if (!prefs.getBoolean("tracking_enabled", false)) return
            if (System.currentTimeMillis() - last > 60000) requestFreshLocation()
            if (System.currentTimeMillis() - last > 180000) update("尚未取得新位置，请检查系统定位、精确定位权限并到开阔处")
            handler.postDelayed(this, 60000)
        }
    }
    override fun onBind(intent: Intent?) = null
    override fun onCreate() {
        super.onCreate()
        manager = getSystemService(LocationManager::class.java)
        getSystemService(NotificationManager::class.java).createNotificationChannel(NotificationChannel("tracking", "位置守护", NotificationManager.IMPORTANCE_LOW))
        if (!prefs.getBoolean("tracking_enabled", false) || !hasPermission()) { stopSelf(); return }
        try {
            startForeground(1, notification("正在启动位置守护"))
            foregroundReady = true
            handler.post(watchdog)
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
        if (destroyed) return
        prefs.edit().putString("status", message).apply()
        getSystemService(NotificationManager::class.java).notify(1, notification(message))
    }
    private fun hasPermission() = checkSelfPermission(Manifest.permission.ACCESS_FINE_LOCATION) == PackageManager.PERMISSION_GRANTED
    override fun onStartCommand(intent: Intent?, flags: Int, startId: Int): Int {
        if (!foregroundReady || !prefs.getBoolean("tracking_enabled", false) || prefs.getString("token", "").isNullOrEmpty() || !hasPermission()) {
            update("请打开应用完成绑定及定位授权"); stopSelf(); return START_NOT_STICKY
        }
        manager.removeUpdates(this)
        var listening = false
        for (provider in listOf(LocationManager.GPS_PROVIDER, LocationManager.NETWORK_PROVIDER)) {
            if (manager.allProviders.contains(provider) && manager.isProviderEnabled(provider)) {
                try { manager.requestLocationUpdates(provider, 30000, 0f, this, Looper.getMainLooper()); listening = true }
                catch (_: Exception) { /* The other provider may still be available. */ }
            }
        }
        update(if (listening) "后台守护已开启，等待定位…" else "系统定位未开启，请打开手机定位开关")
        requestFreshLocation()
        // Ask Android to recreate the active service after ordinary process reclamation.
        // A user stop/force-stop or vendor battery policy can still prevent restart.
        return START_STICKY
    }
    private fun requestFreshLocation() {
        if (destroyed || requestingFix || !foregroundReady || !hasPermission()) return
        val provider = listOf(LocationManager.NETWORK_PROVIDER, LocationManager.GPS_PROVIDER)
            .firstOrNull { manager.allProviders.contains(it) && manager.isProviderEnabled(it) } ?: return
        if (Build.VERSION.SDK_INT >= 30) {
            requestingFix = true
            currentFix = CancellationSignal()
            try {
                manager.getCurrentLocation(provider, currentFix, mainExecutor) { location ->
                    requestingFix = false
                    currentFix = null
                    if (!destroyed && prefs.getBoolean("tracking_enabled", false) && location != null) onLocationChanged(location)
                }
            } catch (_: Exception) { requestingFix = false }
        }
        // Older devices continue receiving the two normal provider subscriptions.
    }
    override fun onLocationChanged(location: Location) {
        // Never replay a cached fix as a current position.
        if (destroyed || !prefs.getBoolean("tracking_enabled", false)) return
        if (location.time <= prefs.getLong("last_uploaded_capture", 0)) return
        if (!location.hasAccuracy() || location.accuracy <= 0 || System.currentTimeMillis() - location.time !in 0..120000) return
        if (!uploading.compareAndSet(false, true)) return
        prefs.edit().putLong("last_capture", location.time).apply()
        worker.execute {
            try {
                if (!prefs.getBoolean("tracking_enabled", false)) return@execute
                val api = Api(this)
                val config = api.request("/device/settings")
                val version = config.getInt("version")
                // Persist the configuration before acknowledging it to the server.
                prefs.edit().putString("settings", config.getJSONObject("settings").toString()).putInt("settings_version", version).commit()
                val battery = getSystemService(BatteryManager::class.java).getIntProperty(BatteryManager.BATTERY_PROPERTY_CAPACITY).coerceIn(0, 100)
                api.request("/device/location", JSONObject().put("lat", location.latitude).put("lon", location.longitude).put("accuracy", location.accuracy.toDouble()).put("recorded_at", location.time / 1000.0).put("battery", battery).put("applied_version", version))
                val time = SimpleDateFormat("HH:mm:ss", Locale.CHINA).format(Date())
                prefs.edit().putLong("last_uploaded_capture", location.time).putLong("last_upload", System.currentTimeMillis()).apply()
                if (prefs.getBoolean("tracking_enabled", false)) update("后台守护中 · $time 位置已同步 · 电量 $battery%")
            } catch (e: Exception) {
                if (prefs.getBoolean("tracking_enabled", false)) update("位置同步失败：${e.message ?: "请检查网络"}")
            }
            finally { uploading.set(false) }
        }
    }
    override fun onProviderEnabled(provider: String) { update("定位已开启，等待新位置…") }
    override fun onProviderDisabled(provider: String) { update("定位源已关闭，请检查系统定位开关") }
    @Deprecated("Legacy callback")
    override fun onStatusChanged(provider: String?, status: Int, extras: Bundle?) {}
    override fun onDestroy() {
        destroyed = true
        currentFix?.cancel()
        manager.removeUpdates(this)
        handler.removeCallbacksAndMessages(null)
        worker.shutdownNow()
        super.onDestroy()
    }
}
