package cn.familyguard.elder

import android.Manifest
import android.app.Activity
import android.app.AlertDialog
import android.content.Intent
import android.content.pm.PackageManager
import android.graphics.Color
import android.net.Uri
import android.os.Build
import android.os.Bundle
import android.os.Handler
import android.os.Looper
import android.provider.Settings
import android.view.View
import android.widget.*
import java.util.concurrent.Executors
import org.json.JSONObject
import com.igexin.sdk.PushManager

class MainActivity : Activity() {
    private val prefs by lazy { getSharedPreferences("guard", MODE_PRIVATE) }
    private val worker = Executors.newSingleThreadExecutor()
    private val handler = Handler(Looper.getMainLooper())
    private lateinit var status: TextView
    private lateinit var content: LinearLayout
    private val update = object : Runnable {
        override fun run() {
            if (::status.isInitialized) status.text = (prefs.getString("status", "尚未开始守护") ?: "") + "\n" + prefs.getString("push_status", "推送尚未启用")
            handler.postDelayed(this, 2000)
        }
    }
    override fun onCreate(savedInstanceState: Bundle?) { super.onCreate(savedInstanceState); render() }
    override fun onResume() {
        super.onResume(); handler.post(update)
        if (prefs.getBoolean("tracking_enabled", false) && !prefs.getString("token", "").isNullOrEmpty() &&
            checkSelfPermission(Manifest.permission.ACCESS_FINE_LOCATION) == PackageManager.PERMISSION_GRANTED) launchTracking()
    }
    override fun onPause() { super.onPause(); handler.removeCallbacks(update) }
    private fun text(value: String, size: Float = 20f): TextView = TextView(this).apply {
        text = value; textSize = size; setTextColor(Color.rgb(28, 48, 49)); setPadding(0, 16, 0, 16)
    }
    private fun button(label: String, action: () -> Unit) {
        content.addView(Button(this).apply { text = label; textSize = 21f; setOnClickListener { action() } })
    }
    private fun render() {
        content = LinearLayout(this).apply { orientation = LinearLayout.VERTICAL; setPadding(32, 48, 32, 32); setBackgroundColor(Color.rgb(245, 248, 245)) }
        setContentView(ScrollView(this).apply { addView(content) })
        content.addView(text("家人守护", 34f))
        content.addView(text("出门安心，家人放心", 21f))
        status = text(prefs.getString("status", "尚未开始守护")!!, 24f)
        content.addView(status)
        if (prefs.getString("token", "").isNullOrEmpty()) {
            content.addView(text("请家属先在 iPhone 管理端添加老人，并取得绑定码。"))
            val server = EditText(this).apply { hint = "服务地址，例如 https://guard.example.cn"; inputType = 17; setText(prefs.getString("server", "")) }
            val code = EditText(this).apply { hint = "输入家属提供的绑定码"; isSingleLine = true }
            val consent = CheckBox(this).apply { text = "我同意向已绑定的家属共享本机位置，用于安全守护。可随时停止或解除共享。"; textSize = 20f }
            content.addView(server); content.addView(code); content.addView(consent)
            button("确认绑定") {
                if (!consent.isChecked) { status.text = "请先确认位置共享"; return@button }
                val address = server.text.toString().trim().trimEnd('/')
                val pairCode = code.text.toString().trim().uppercase()
                prefs.edit().putString("server", address).apply()
                worker.execute {
                    try {
                        val result = Api(this).request("/device/pair", JSONObject().put("code", pairCode).put("consent", true), false)
                        prefs.edit().putString("token", result.getString("token")).putString("elder_id", result.getString("elder_id")).putString("name", result.getString("name")).putString("status", "已绑定，请点击开始守护").apply()
                        runOnUiThread { render() }
                    } catch (e: Exception) { runOnUiThread { status.text = e.message ?: "绑定失败" } }
                }
            }
        } else {
            content.addView(text("使用者：" + prefs.getString("name", "老人")))
            button("个推隐私说明") { startActivity(Intent(Intent.ACTION_VIEW, Uri.parse("https://docs.getui.com/privacy"))) }
            button("开始守护") { startTracking() }
            button("停止位置共享") {
                AlertDialog.Builder(this).setTitle("停止守护？").setMessage("停止后家属将无法获得新位置，并可能收到位置未更新提醒。").setPositiveButton("停止") { _, _ ->
                    prefs.edit().putBoolean("tracking_enabled", false).commit()
                    PushManager.getInstance().turnOffPush(this)
                    stopService(Intent(this, TrackingService::class.java))
                    prefs.edit().putString("status", "位置共享已停止").apply(); status.text = "位置共享已停止"
                    worker.execute { try { Api(this).request("/device/push", JSONObject().put("enabled", false)) } catch (_: Exception) { } }
                }.setNegativeButton("继续守护", null).show()
            }
            button("打开应用设置") { startActivity(Intent(Settings.ACTION_APPLICATION_DETAILS_SETTINGS, Uri.parse("package:$packageName"))) }
            button("打开系统定位设置") { startActivity(Intent(Settings.ACTION_LOCATION_SOURCE_SETTINGS)) }
            button("打开电池优化设置") { startActivity(Intent(Settings.ACTION_IGNORE_BATTERY_OPTIMIZATION_SETTINGS)) }
            content.addView(text("开启一次后可返回桌面、锁屏。无围栏和进行中的行程时不自动定位，只响应家属请求；围栏或进行中的行程约每分钟定位，取到位置后停止本次定位。通过个推接收家属请求，已取消30秒轮询。推送通道仍有少量通信耗电，锁屏或进程关闭可能无法响应。常驻通知表示守护服务运行中。请允许精确定位、通知，并在手机应用启动管理中允许自启动、关联启动和后台活动，在电池优化中允许本应用。普通系统回收会尝试恢复；手动停止后不会恢复。重启或强制停止后需重新打开应用。", 18f))
            button("解除与家属的绑定") {
                AlertDialog.Builder(this).setTitle("解除绑定？").setMessage("解除后已授权的家属无法继续取得本机新位置。").setPositiveButton("解除") { _, _ ->
                    prefs.edit().putBoolean("tracking_enabled", false).commit()
                    PushManager.getInstance().turnOffPush(this)
                    stopService(Intent(this, TrackingService::class.java))
                    worker.execute {
                        try {
                            Api(this).request("/device/unpair", JSONObject())
                            prefs.edit().clear().apply()
                            runOnUiThread { render() }
                        } catch (e: Exception) { runOnUiThread { status.text = "解除失败：${e.message}。本机定位已停止，可重试。" } }
                    }
                }.setNegativeButton("取消", null).show()
            }
        }
    }
    private fun startTracking() {
        if (checkSelfPermission(Manifest.permission.ACCESS_FINE_LOCATION) != PackageManager.PERMISSION_GRANTED) {
            requestPermissions(arrayOf(Manifest.permission.ACCESS_FINE_LOCATION, Manifest.permission.ACCESS_COARSE_LOCATION), 10)
            return
        }
        if (Build.VERSION.SDK_INT >= 33 && checkSelfPermission(Manifest.permission.POST_NOTIFICATIONS) != PackageManager.PERMISSION_GRANTED) {
            requestPermissions(arrayOf(Manifest.permission.POST_NOTIFICATIONS), 11)
            return
        }
        launchTracking()
    }
    private fun launchTracking() {
        if (!prefs.getBoolean("push_consent", false)) {
            AlertDialog.Builder(this).setTitle("启用推送接收家属请求")
                .setMessage("为减少定时联网，家人守护使用个推SDK接收家属的定位请求和规则变更。SDK会处理设备标识、应用及网络信息，推送内容不包含位置或账号凭证。可通过本页的个推隐私说明了解详情；停止共享时关闭推送。是否同意并开启？")
                .setPositiveButton("同意并开启") { _, _ -> prefs.edit().putBoolean("push_consent", true).commit(); launchTracking() }
                .setNegativeButton("暂不开启") { _, _ -> status.text = "尚未启用推送，请阅读说明后开启守护" }.show()
            return
        }
        prefs.edit().putBoolean("tracking_enabled", true).commit()
        try {
            startForegroundService(Intent(this, TrackingService::class.java))
            PushManager.getInstance().initialize(applicationContext)
            PushManager.getInstance().turnOnPush(applicationContext)
            PushManager.getInstance().getClientid(applicationContext)?.let { prefs.edit().putString("push_cid", it).apply() }
            status.text = "正在启动后台守护及推送…"
        } catch (e: Exception) {
            val message = "系统未允许启动守护：${e.message ?: "请检查应用权限和后台活动设置"}"
            prefs.edit().putString("status", message).apply(); status.text = message
        }
    }
    override fun onRequestPermissionsResult(requestCode: Int, permissions: Array<out String>, grantResults: IntArray) {
        super.onRequestPermissionsResult(requestCode, permissions, grantResults)
        if (requestCode == 10 && checkSelfPermission(Manifest.permission.ACCESS_FINE_LOCATION) == PackageManager.PERMISSION_GRANTED) startTracking()
        else if (requestCode == 11) {
            launchTracking()
        } else status.text = "需要精确定位权限才能开始守护"
    }
}
