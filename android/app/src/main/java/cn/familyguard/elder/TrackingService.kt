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
    private val uploading = AtomicBoolean(false)
    private val handler = Handler(Looper.getMainLooper())
    private val prefs by lazy { getSharedPreferences("guard", MODE_PRIVATE) }
    private val watchdog = object : Runnable {
        override fun run() {
            val last = prefs.getLong("last_capture", 0)
            if (System.currentTimeMillis() - last > 180000) update("尚未取得新位置，请检查定位开关并到开阔处")
            handler.postDelayed(this, 60000)
        }
    }
    override fun onBind(intent: Intent?) = null
    override fun onCreate() {
        super.onCreate()
        manager = getSystemService(LocationManager::class.java)
        getSystemService(NotificationManager::class.java).createNotificationChannel(NotificationChannel("tracking", "位置守护", NotificationManager.IMPORTANCE_LOW))
        startForeground(1, notification("正在启动位置守护"))
        handler.post(watchdog)
    }
    private fun notification(message: String): Notification {
        val open = PendingIntent.getActivity(this, 0, Intent(this, MainActivity::class.java), PendingIntent.FLAG_IMMUTABLE or PendingIntent.FLAG_UPDATE_CURRENT)
        return Notification.Builder(this, "tracking").setSmallIcon(android.R.drawable.ic_menu_mylocation).setContentTitle("家人守护正在运行").setContentText(message).setContentIntent(open).setOngoing(true).build()
    }
    private fun update(message: String) {
        prefs.edit().putString("status", message).apply()
        getSystemService(NotificationManager::class.java).notify(1, notification(message))
    }
    override fun onStartCommand(intent: Intent?, flags: Int, startId: Int): Int {
        if (prefs.getString("token", "").isNullOrEmpty() || checkSelfPermission(Manifest.permission.ACCESS_FINE_LOCATION) != PackageManager.PERMISSION_GRANTED) {
            update("请打开应用完成绑定及定位授权"); stopSelf(); return START_NOT_STICKY
        }
        manager.removeUpdates(this)
        var listening = false
        for (provider in listOf(LocationManager.GPS_PROVIDER, LocationManager.NETWORK_PROVIDER)) {
            if (manager.allProviders.contains(provider)) {
                try { manager.requestLocationUpdates(provider, 30000, 0f, this, Looper.getMainLooper()); listening = true }
                catch (_: Exception) { /* The other provider may still be available. */ }
            }
        }
        update(if (listening) "守护已开启，等待定位…" else "定位服务不可用，请检查系统设置")
        return START_NOT_STICKY
    }
    override fun onLocationChanged(location: Location) {
        // Never replay a cached fix as a current position.
        if (!location.hasAccuracy() || location.accuracy <= 0 || System.currentTimeMillis() - location.time !in 0..120000) return
        if (!uploading.compareAndSet(false, true)) return
        prefs.edit().putLong("last_capture", location.time).apply()
        worker.execute {
            try {
                val api = Api(this)
                val config = api.request("/device/settings")
                val version = config.getInt("version")
                // Persist the configuration before acknowledging it to the server.
                prefs.edit().putString("settings", config.getJSONObject("settings").toString()).putInt("settings_version", version).commit()
                val battery = getSystemService(BatteryManager::class.java).getIntProperty(BatteryManager.BATTERY_PROPERTY_CAPACITY).coerceIn(0, 100)
                api.request("/device/location", JSONObject().put("lat", location.latitude).put("lon", location.longitude).put("accuracy", location.accuracy.toDouble()).put("recorded_at", location.time / 1000.0).put("battery", battery).put("applied_version", version))
                val time = SimpleDateFormat("HH:mm:ss", Locale.CHINA).format(Date())
                update("守护中 · $time 位置已同步 · 电量 $battery%")
            } catch (e: Exception) { update("位置同步失败：${e.message ?: "请检查网络"}") }
            finally { uploading.set(false) }
        }
    }
    override fun onProviderEnabled(provider: String) { update("定位已开启，等待新位置…") }
    override fun onProviderDisabled(provider: String) { update("定位源已关闭，请检查系统定位开关") }
    @Deprecated("Legacy callback")
    override fun onStatusChanged(provider: String?, status: Int, extras: Bundle?) {}
    override fun onDestroy() {
        manager.removeUpdates(this)
        handler.removeCallbacksAndMessages(null)
        worker.shutdownNow()
        super.onDestroy()
    }
}
