package cn.familyguard.elder

import android.content.Context
import com.igexin.sdk.PushManager

/** Register our callback explicitly and recover an already generated local CID. */
object ElderPushRuntime {
    @Suppress("DEPRECATION")
    fun start(context: Context) {
        val prefs = context.getSharedPreferences("guard", Context.MODE_PRIVATE)
        if (!prefs.getBoolean("push_consent", false) || !prefs.getBoolean("tracking_enabled", false)) return
        try {
        val manager = PushManager.getInstance()
        manager.preInit(context.applicationContext)
        manager.registerPushIntentService(context.applicationContext, ElderPushReceiver::class.java)
        manager.initialize(context.applicationContext, ElderPushService::class.java)
        manager.turnOnPush(context.applicationContext)
        if (!cacheCID(context)) prefs.edit().putString("push_status", "推送初始化中，等待SDK取得标识；请保持联网")
            .putString("push_registration", "waiting_cid").apply()
        } catch (_: Exception) {
            prefs.edit().putString("push_registration", "initialization_failed")
                .putString("push_status", "推送SDK初始化失败，请检查手机网络和应用设置后重试").apply()
        }
    }
    fun cacheCID(context: Context): Boolean {
        val prefs = context.getSharedPreferences("guard", Context.MODE_PRIVATE)
        val cid = try { PushManager.getInstance().getClientid(context.applicationContext) } catch (_: Exception) { null }
        if (cid.isNullOrBlank()) return false
        if (prefs.getString("push_cid", "") != cid) {
            prefs.edit().putString("push_cid", cid).putString("push_registration", "waiting_registration")
                .putString("push_status", "已取得推送标识，等待向服务器登记").apply()
        }
        return true
    }
}
