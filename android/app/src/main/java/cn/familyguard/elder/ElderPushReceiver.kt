package cn.familyguard.elder

import android.app.Notification
import android.app.NotificationChannel
import android.app.NotificationManager
import android.app.PendingIntent
import android.content.Context
import android.content.Intent
import com.igexin.sdk.GTIntentService
import com.igexin.sdk.PushService
import com.igexin.sdk.message.GTTransmitMessage
import org.json.JSONObject

class ElderPushService : PushService()

class ElderPushReceiver : GTIntentService() {
    private fun allowed(context: Context): Boolean {
        val prefs = context.getSharedPreferences("guard", Context.MODE_PRIVATE)
        return prefs.getBoolean("push_consent", false) && prefs.getBoolean("tracking_enabled", false) &&
            !prefs.getString("token", "").isNullOrEmpty()
    }
    override fun onReceiveClientId(context: Context, clientid: String) {
        if (!allowed(context)) return
        context.getSharedPreferences("guard", Context.MODE_PRIVATE).edit()
            .putString("push_cid", clientid).putString("push_status", "已取得推送标识，正在登记").apply()
        TrackingService.signal()
    }
    override fun onReceiveOnlineState(context: Context, online: Boolean) {
        if (!allowed(context)) return
        context.getSharedPreferences("guard", Context.MODE_PRIVATE).edit()
            .putString("push_status", if (online) "推送通道已连接" else "推送通道断开，等待SDK重连").apply()
        if (online) TrackingService.signal()
    }
    override fun onReceiveMessageData(context: Context, message: GTTransmitMessage) {
        if (!allowed(context)) return
        val payload = message.payload ?: return
        if (payload.size > 4096) return
        val type = try { JSONObject(String(payload, Charsets.UTF_8)).optString("type") } catch (_: Exception) { return }
        if (type != "sync_commands") return
        // Only a hint: authenticate and fetch current server state, never trust payload coordinates or rules.
        if (!TrackingService.signal()) {
            val manager = context.getSystemService(NotificationManager::class.java)
            manager.createNotificationChannel(NotificationChannel("guard_resume", "守护恢复提醒", NotificationManager.IMPORTANCE_DEFAULT))
            val open = PendingIntent.getActivity(context, 2, Intent(context, MainActivity::class.java), PendingIntent.FLAG_IMMUTABLE or PendingIntent.FLAG_UPDATE_CURRENT)
            val notification = Notification.Builder(context, "guard_resume").setSmallIcon(android.R.drawable.ic_menu_mylocation)
                .setContentTitle("家属请求同步守护信息").setContentText("请点击打开家人守护，恢复位置共享")
                .setContentIntent(open).setAutoCancel(true).build()
            try { manager.notify(2, notification) } catch (_: SecurityException) { }
            context.getSharedPreferences("guard", Context.MODE_PRIVATE).edit()
                .putString("status", "已收到家属请求，但守护服务未运行，请打开应用恢复").apply()
        }
    }
}
