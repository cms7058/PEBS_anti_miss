package cn.familyguard.elder

import android.Manifest
import android.app.AlarmManager
import android.app.PendingIntent
import android.content.BroadcastReceiver
import android.content.Context
import android.content.Intent
import android.content.pm.PackageManager
import android.os.Build
import android.os.PowerManager
import android.os.SystemClock

/** Wake only for enabled automatic guarding. Idle on-demand mode has no alarm. */
class GuardWakeReceiver : BroadcastReceiver() {
    override fun onReceive(context: Context, intent: Intent) {
        if (intent.action == "cn.familyguard.elder.GUARD_WAKE" || intent.action == Intent.ACTION_BOOT_COMPLETED) {
            android.util.Log.i("FamilyGuard", "system guard wake: ${intent.action}")
            resume(context)
        }
    }
    companion object {
        fun backgroundGranted(context: Context) = Build.VERSION.SDK_INT < 29 ||
            context.checkSelfPermission(Manifest.permission.ACCESS_BACKGROUND_LOCATION) == PackageManager.PERMISSION_GRANTED
        fun unrestricted(context: Context) = context.getSystemService(PowerManager::class.java).isIgnoringBatteryOptimizations(context.packageName)
        private fun pending(context: Context) = PendingIntent.getBroadcast(context, 40,
            Intent(context, GuardWakeReceiver::class.java).setAction("cn.familyguard.elder.GUARD_WAKE"),
            PendingIntent.FLAG_IMMUTABLE or PendingIntent.FLAG_UPDATE_CURRENT)
        fun schedule(context: Context, automatic: Boolean) {
            val manager = context.getSystemService(AlarmManager::class.java)
            if (automatic) manager.setAndAllowWhileIdle(AlarmManager.ELAPSED_REALTIME_WAKEUP,
                SystemClock.elapsedRealtime() + 60000, pending(context))
            else manager.cancel(pending(context))
        }
        fun resume(context: Context): Boolean {
            val prefs = context.getSharedPreferences("guard", Context.MODE_PRIVATE)
            if (!prefs.getBoolean("tracking_enabled", false) || !prefs.getBoolean("push_consent", false) ||
                prefs.getString("token", "").isNullOrEmpty()) return false
            // A normal Getui callback is not an Android FCM high-priority exemption.
            if (TrackingService.signal()) return true
            if (!backgroundGranted(context) || !unrestricted(context) ||
                context.checkSelfPermission(Manifest.permission.ACCESS_FINE_LOCATION) != PackageManager.PERMISSION_GRANTED) return false
            return try {
                android.util.Log.i("FamilyGuard", "restoring consented location service")
                context.startForegroundService(Intent(context, TrackingService::class.java))
                true
            } catch (_: Exception) {
                prefs.edit().putString("status", "系统阻止后台恢复，请打开应用开始守护，并检查后台权限").apply()
                false
            }
        }
    }
}
