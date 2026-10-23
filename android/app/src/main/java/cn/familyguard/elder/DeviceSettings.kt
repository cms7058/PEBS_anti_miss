package cn.familyguard.elder

import android.Manifest
import android.app.*
import android.content.Context
import android.content.Intent
import android.content.pm.PackageManager
import android.location.LocationManager
import android.net.Uri
import android.os.Build
import android.provider.Settings
import org.json.JSONObject

/** Reports observations; never changes OS permissions or the elder's sharing consent. */
object DeviceSettings {
    val titles = mapOf("location" to "定位权限", "background" to "后台定位", "battery" to "电池限制", "notifications" to "通知提醒", "startup" to "自启动和后台活动")
    fun collect(context: Context): JSONObject {
        val prefs = context.getSharedPreferences("guard", Context.MODE_PRIVATE)
        val locations = context.getSystemService(LocationManager::class.java)
        val notifications = context.getSystemService(NotificationManager::class.java)
        val settings = try { JSONObject(prefs.getString("settings", "{}") ?: "{}") } catch (_: Exception) { JSONObject() }
        return JSONObject().put("precise_location", context.checkSelfPermission(Manifest.permission.ACCESS_FINE_LOCATION) == PackageManager.PERMISSION_GRANTED)
            .put("background_location", context.checkSelfPermission(Manifest.permission.ACCESS_FINE_LOCATION) == PackageManager.PERMISSION_GRANTED && GuardWakeReceiver.backgroundGranted(context))
            .put("battery_unrestricted", GuardWakeReceiver.unrestricted(context))
            .put("notifications", notifications.areNotificationsEnabled() && notifications.getNotificationChannel("tracking")?.importance != NotificationManager.IMPORTANCE_NONE)
            .put("location_enabled", if (Build.VERSION.SDK_INT >= 28) locations.isLocationEnabled else locations.isProviderEnabled(LocationManager.GPS_PROVIDER) || locations.isProviderEnabled(LocationManager.NETWORK_PROVIDER))
            .put("network_location", locations.allProviders.contains(LocationManager.NETWORK_PROVIDER) && locations.isProviderEnabled(LocationManager.NETWORK_PROVIDER))
            .put("guard_enabled", prefs.getBoolean("tracking_enabled", false)).put("service_running", TrackingService.isRunning())
            .put("command_stream_connected", prefs.getBoolean("command_stream_connected", false))
            .put("settings_version", prefs.getInt("settings_version", 0)).put("automatic_interval", settings.optInt("automatic_interval", 60).coerceIn(30, 120))
    }
    fun report(context: Context) {
        val prefs = context.getSharedPreferences("guard", Context.MODE_PRIVATE)
        if (prefs.getString("token", "").isNullOrEmpty()) return
        try {
            val payload = collect(context)
            Api(context).request("/device/state", payload)
            val id = prefs.getString("setup_id", "") ?: ""
            val state = prefs.getString("setup_state", "received") ?: "received"
            val signature = "$id:$state"
            if (id.isNotEmpty() && prefs.getString("setup_ack_sent", "") != signature) {
                try { Api(context).request("/device/state", payload.put("setup_request_id", id).put("setup_state", state)) }
                catch (error: ApiFailure) { if (error.status != 409) throw error }
                prefs.edit().putString("setup_ack_sent", signature).apply()
            }
        } catch (_: Exception) { /* Last observed state remains explicitly timestamped on manager. */ }
    }
    fun receive(context: Context, request: JSONObject?) {
        if (request == null) return
        val id = request.optString("id"); val action = request.optString("action")
        if (id.isEmpty() || action !in titles || request.optDouble("expires") <= System.currentTimeMillis()/1000.0) return
        val prefs = context.getSharedPreferences("guard", Context.MODE_PRIVATE)
        if (prefs.getString("setup_id", "") == id) return
        prefs.edit().putString("setup_id", id).putString("setup_action", action).putString("setup_state", "received")
            .putLong("setup_expires", (request.optDouble("expires")*1000).toLong()).apply()
        val manager = context.getSystemService(NotificationManager::class.java)
        manager.createNotificationChannel(NotificationChannel("device_setup", "家属设置提醒", NotificationManager.IMPORTANCE_DEFAULT))
        if (!manager.areNotificationsEnabled() || manager.getNotificationChannel("device_setup")?.importance == NotificationManager.IMPORTANCE_NONE) return
        val open = PendingIntent.getActivity(context, 6, Intent(context, MainActivity::class.java), PendingIntent.FLAG_IMMUTABLE or PendingIntent.FLAG_UPDATE_CURRENT)
        try {
            manager.notify(6, Notification.Builder(context, "device_setup").setSmallIcon(android.R.drawable.ic_dialog_info)
                .setContentTitle("家属请你检查${titles[action]}").setContentText("点击打开家人守护，由你确认是否前往设置")
                .setContentIntent(open).setAutoCancel(true).build())
            prefs.edit().putString("setup_state", "notified").apply()
        } catch (_: SecurityException) { }
    }
    fun open(context: Context, action: String) {
        val intent = when (action) {
            "battery" -> if (GuardWakeReceiver.unrestricted(context)) Intent(Settings.ACTION_IGNORE_BATTERY_OPTIMIZATION_SETTINGS)
                else Intent(Settings.ACTION_REQUEST_IGNORE_BATTERY_OPTIMIZATIONS, Uri.parse("package:${context.packageName}"))
            "notifications" -> Intent(Settings.ACTION_APP_NOTIFICATION_SETTINGS).putExtra(Settings.EXTRA_APP_PACKAGE, context.packageName)
            else -> Intent(Settings.ACTION_APPLICATION_DETAILS_SETTINGS, Uri.parse("package:${context.packageName}"))
        }
        try { context.startActivity(intent) }
        catch (_: Exception) { context.startActivity(Intent(Settings.ACTION_APPLICATION_DETAILS_SETTINGS, Uri.parse("package:${context.packageName}"))) }
    }
}
