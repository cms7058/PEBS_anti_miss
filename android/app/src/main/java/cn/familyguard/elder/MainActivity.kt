package cn.familyguard.elder

import android.Manifest
import android.app.Activity
import android.app.AlertDialog
import android.content.Intent
import android.content.pm.PackageManager
import android.content.res.ColorStateList
import android.graphics.Color
import android.graphics.Typeface
import android.graphics.drawable.GradientDrawable
import android.graphics.drawable.RippleDrawable
import android.location.LocationManager
import android.net.Uri
import android.os.Build
import android.os.Bundle
import android.os.Handler
import android.os.Looper
import android.provider.Settings
import android.view.Gravity
import android.view.View
import android.view.WindowInsets
import android.widget.*
import java.util.concurrent.Executors
import org.json.JSONObject
import com.igexin.sdk.PushManager

class MainActivity : Activity() {
    private val prefs by lazy { getSharedPreferences("guard", MODE_PRIVATE) }
    private val worker = Executors.newSingleThreadExecutor()
    private val handler = Handler(Looper.getMainLooper())
    private val ink = Color.rgb(25, 48, 47)
    private val green = Color.rgb(18, 105, 82)
    private val amber = Color.rgb(139, 78, 14)
    private val muted = Color.rgb(83, 101, 99)
    private val pale = Color.rgb(233, 244, 238)
    private val paper = Color.rgb(244, 247, 244)
    private lateinit var status: TextView
    private lateinit var content: LinearLayout
    private lateinit var guardSwitch: Switch
    private lateinit var guardTitle: TextView
    private lateinit var guardSubtitle: TextView
    private lateinit var guardBadge: TextView
    private lateinit var recoverGuard: Button
    private lateinit var pushBadge: TextView
    private lateinit var pushDetail: TextView
    private lateinit var modeBadge: TextView
    private lateinit var modeDetail: TextView
    private lateinit var retryPush: Button
    private val permissionTiles = mutableListOf<PermissionTile>()
    private var updatingSwitch = false
    private var boundScreen = false
    private data class PermissionTile(val badge: TextView, val detail: TextView, val test: () -> Boolean, val good: String, val missing: String)
    private val update = object : Runnable {
        override fun run() { refreshState(); handler.postDelayed(this, 2000) }
    }
    override fun onCreate(savedInstanceState: Bundle?) { super.onCreate(savedInstanceState); render() }
    override fun onResume() {
        super.onResume()
        handler.removeCallbacks(update)
        handler.post(update)
        if (prefs.getBoolean("tracking_enabled", false) && !prefs.getString("token", "").isNullOrEmpty() &&
            checkSelfPermission(Manifest.permission.ACCESS_FINE_LOCATION) == PackageManager.PERMISSION_GRANTED) launchTracking()
    }
    override fun onPause() { super.onPause(); handler.removeCallbacks(update) }
    private fun dp(value: Int) = (value * resources.displayMetrics.density).toInt()
    private fun shape(color: Int, radius: Int = 22) = GradientDrawable().apply { setColor(color); cornerRadius = dp(radius).toFloat() }
    private fun touchBackground(color: Int, radius: Int = 15) = RippleDrawable(
        ColorStateList.valueOf(Color.argb(35, 18, 105, 82)), shape(color, radius), shape(Color.WHITE, radius))
    private fun column() = LinearLayout(this).apply { orientation = LinearLayout.VERTICAL }
    private fun row() = LinearLayout(this).apply { orientation = LinearLayout.HORIZONTAL; gravity = Gravity.CENTER_VERTICAL }
    private fun tileRow() = row().apply {
        if (resources.configuration.fontScale >= 1.3f || resources.configuration.screenWidthDp < 360) orientation = LinearLayout.VERTICAL
        gravity = Gravity.TOP
    }
    private fun tileParams(parent: LinearLayout) = if (parent.orientation == LinearLayout.HORIZONTAL)
        LinearLayout.LayoutParams(0, -2, 1f).apply { rightMargin = dp(6) }
    else LinearLayout.LayoutParams(-1, -2)
    private fun text(value: String, size: Float = 18f, color: Int = ink, bold: Boolean = false) = TextView(this).apply {
        text = value; textSize = size; setTextColor(color)
        if (bold) setTypeface(typeface, Typeface.BOLD)
        setLineSpacing(dp(3).toFloat(), 1f)
    }
    private fun space(parent: LinearLayout, height: Int = 12) { parent.addView(View(this), LinearLayout.LayoutParams(1, dp(height))) }
    private fun card(parent: LinearLayout, color: Int = Color.WHITE): LinearLayout = column().also {
        it.background = shape(color); it.setPadding(dp(20), dp(20), dp(20), dp(20))
        parent.addView(it, LinearLayout.LayoutParams(-1, -2).apply { bottomMargin = dp(16) })
    }
    private fun icon(resource: Int, color: Int = green) = ImageView(this).apply {
        setImageResource(resource); setColorFilter(color); importantForAccessibility = View.IMPORTANT_FOR_ACCESSIBILITY_NO
        background = shape(pale, 16); setPadding(dp(10), dp(10), dp(10), dp(10))
    }
    private fun badge(value: String) = text(value, 16f, green, true).apply {
        background = shape(pale, 10); setPadding(dp(10), dp(6), dp(10), dp(6))
    }
    private fun paintBadge(view: TextView, label: String, good: Boolean) {
        view.text = label; view.setTextColor(if (good) green else amber)
        view.background = shape(if (good) pale else Color.rgb(255, 240, 217), 10)
    }
    private fun button(parent: LinearLayout, label: String, primary: Boolean = false, action: () -> Unit): Button = Button(this).apply {
        text = label; textSize = 20f; isAllCaps = false; minHeight = dp(58)
        setTextColor(if (primary) Color.WHITE else green)
        background = touchBackground(if (primary) green else pale)
        setPadding(dp(16), dp(12), dp(16), dp(12))
        parent.addView(this, LinearLayout.LayoutParams(-1, -2).apply { topMargin = dp(12) })
        setOnClickListener { action(); refreshState() }
    }
    private fun appSettings() { startActivity(Intent(Settings.ACTION_APPLICATION_DETAILS_SETTINGS, Uri.parse("package:$packageName"))) }
    private fun showNotice(message: String) { prefs.edit().putString("status", message).apply(); status.text = message }
    private fun render() {
        boundScreen = !prefs.getString("token", "").isNullOrEmpty()
        permissionTiles.clear()
        content = column().apply { setPadding(dp(20), dp(20), dp(20), dp(24)) }
        val scroll = ScrollView(this).apply { setBackgroundColor(paper); isFillViewport = true; addView(content) }
        scroll.setOnApplyWindowInsetsListener { view, insets ->
            if (Build.VERSION.SDK_INT >= 30) {
                val bars = insets.getInsets(WindowInsets.Type.systemBars() or WindowInsets.Type.displayCutout())
                view.setPadding(bars.left, bars.top, bars.right, bars.bottom)
            } else {
                @Suppress("DEPRECATION")
                view.setPadding(insets.systemWindowInsetLeft, insets.systemWindowInsetTop, insets.systemWindowInsetRight, insets.systemWindowInsetBottom)
            }
            insets
        }
        setContentView(scroll)
        content.addView(text("家人守护", 30f, ink, true))
        content.addView(text(if (boundScreen) "${prefs.getString("name", "家人")}，出门安心，家人放心" else "和家人连接，让出门更安心", 18f, muted))
        space(content, 22)
        if (!boundScreen) renderPairing() else renderDashboard()
        content.addView(text("家人守护 · 老人端 ${BuildConfig.VERSION_NAME}", 14f, muted).apply { gravity = Gravity.CENTER })
        refreshState()
    }
    private fun renderPairing() {
        val box = card(content)
        box.addView(icon(android.R.drawable.ic_menu_myplaces), LinearLayout.LayoutParams(dp(56), dp(56)))
        space(box)
        box.addView(text("连接家人", 26f, ink, true))
        box.addView(text("请家属在管理端添加老人，再填写服务地址和绑定码。", 18f, muted))
        space(box)
        box.addView(text("服务地址", 18f, ink, true))
        val server = EditText(this).apply { hint = "https://guard.example.cn"; inputType = 17; textSize = 18f; setText(prefs.getString("server", "")); minHeight = dp(56) }
        box.addView(server)
        space(box)
        box.addView(text("家属提供的绑定码", 18f, ink, true))
        val code = EditText(this).apply { hint = "输入绑定码"; isSingleLine = true; textSize = 22f; minHeight = dp(56) }
        box.addView(code)
        val consent = CheckBox(this).apply { text = "同意向绑定的家属共享位置，可随时停止或解除绑定"; textSize = 18f; buttonTintList = ColorStateList.valueOf(green); setPadding(0, dp(12), 0, dp(8)) }
        box.addView(consent)
        status = text("尚未绑定家人", 18f, muted)
        box.addView(status)
        val pair = button(box, "连接家人", true) { }
        pair.setOnClickListener {
            if (!consent.isChecked) { showNotice("请先勾选同意位置共享"); return@setOnClickListener }
            val address = server.text.toString().trim().trimEnd('/')
            val pairCode = code.text.toString().trim().uppercase()
            if (address.isEmpty() || pairCode.isEmpty()) { showNotice("请填写服务地址和绑定码"); return@setOnClickListener }
            prefs.edit().putString("server", address).apply()
            pair.isEnabled = false; pair.text = "正在连接…"
            worker.execute {
                try {
                    val result = Api(this).request("/device/pair", JSONObject().put("code", pairCode).put("consent", true), false)
                    prefs.edit().putString("token", result.getString("token")).putString("elder_id", result.getString("elder_id"))
                        .putString("name", result.getString("name")).putString("status", "已连接家人，请开启守护").apply()
                    runOnUiThread { if (!isFinishing && !isDestroyed) render() }
                } catch (e: Exception) { runOnUiThread { pair.isEnabled = true; pair.text = "连接家人"; showNotice(e.message ?: "连接失败，请重试") } }
            }
        }
    }
    private fun renderDashboard() {
        val hero = card(content, pale)
        val heroTop = row()
        heroTop.addView(icon(android.R.drawable.ic_lock_idle_lock), LinearLayout.LayoutParams(dp(56), dp(56)))
        guardBadge = badge("")
        heroTop.addView(guardBadge, LinearLayout.LayoutParams(-2, -2).apply { leftMargin = dp(12) })
        hero.addView(heroTop)
        space(hero)
        guardTitle = text("", 30f, ink, true); hero.addView(guardTitle)
        guardSubtitle = text("", 18f, muted); hero.addView(guardSubtitle)
        space(hero, 16)
        guardSwitch = Switch(this).apply {
            text = "位置守护"; textSize = 23f; setTextColor(ink); setTypeface(typeface, Typeface.BOLD)
            minHeight = dp(64); switchPadding = dp(16)
            thumbTintList = ColorStateList(arrayOf(intArrayOf(android.R.attr.state_checked), intArrayOf()), intArrayOf(green, Color.rgb(100, 110, 108)))
            trackTintList = ColorStateList(arrayOf(intArrayOf(android.R.attr.state_checked), intArrayOf()), intArrayOf(Color.rgb(153, 205, 184), Color.rgb(200, 208, 204)))
            setOnCheckedChangeListener { _, checked ->
                if (!updatingSwitch) {
                    if (checked) startTracking() else confirmStop()
                    refreshState()
                }
            }
        }
        hero.addView(guardSwitch, LinearLayout.LayoutParams(-1, -2))
        recoverGuard = button(hero, "恢复守护", true) { startTracking() }

        val tiles = tileRow()
        val push = card(tiles)
        push.layoutParams = tileParams(tiles).apply { bottomMargin = dp(16) }
        push.addView(icon(android.R.drawable.ic_dialog_email), LinearLayout.LayoutParams(dp(44), dp(44)))
        space(push); push.addView(text("家属请求", 19f, ink, true)); space(push, 8)
        pushBadge = badge(""); push.addView(pushBadge)
        space(push, 8); pushDetail = text("", 16f, muted); push.addView(pushDetail)
        val mode = card(tiles)
        mode.layoutParams = tileParams(tiles).apply { bottomMargin = dp(16) }
        mode.addView(icon(android.R.drawable.ic_menu_mylocation), LinearLayout.LayoutParams(dp(44), dp(44)))
        space(mode); mode.addView(text("定位方式", 19f, ink, true)); space(mode, 8)
        modeBadge = badge(""); mode.addView(modeBadge)
        space(mode, 8); modeDetail = text("", 16f, muted); mode.addView(modeDetail)
        tiles.gravity = Gravity.TOP
        content.addView(tiles, LinearLayout.LayoutParams(-1, -2))

        val permissionCard = card(content)
        permissionCard.addView(text("后台守护检查", 23f, ink, true))
        permissionCard.addView(text("绿色表示已开启，橙色表示需要设置", 16f, muted))
        val first = tileRow()
        permissionCard.addView(first)
        permissionTile(first, "精确定位", android.R.drawable.ic_menu_mylocation, "已允许", "未允许", {
            checkSelfPermission(Manifest.permission.ACCESS_FINE_LOCATION) == PackageManager.PERMISSION_GRANTED
        }) {
            if (checkSelfPermission(Manifest.permission.ACCESS_FINE_LOCATION) == PackageManager.PERMISSION_GRANTED) appSettings()
            else startTracking()
        }
        permissionTile(first, "系统定位", android.R.drawable.ic_menu_compass, "已开启", "未开启", {
            val manager = getSystemService(LocationManager::class.java)
            if (Build.VERSION.SDK_INT >= 28) manager.isLocationEnabled else manager.isProviderEnabled(LocationManager.GPS_PROVIDER) || manager.isProviderEnabled(LocationManager.NETWORK_PROVIDER)
        }) { startActivity(Intent(Settings.ACTION_LOCATION_SOURCE_SETTINGS)) }
        val second = tileRow()
        permissionCard.addView(second)
        permissionTile(second, "后台定位", android.R.drawable.ic_lock_idle_lock, "已允许", "需设置", {
            checkSelfPermission(Manifest.permission.ACCESS_FINE_LOCATION) == PackageManager.PERMISSION_GRANTED && GuardWakeReceiver.backgroundGranted(this)
        }) { requestBackgroundLocation() }
        permissionTile(second, "电池限制", android.R.drawable.ic_lock_idle_charging, "已解除", "需解除", { GuardWakeReceiver.unrestricted(this) }) {
            if (!GuardWakeReceiver.unrestricted(this)) {
                try { startActivity(Intent(Settings.ACTION_REQUEST_IGNORE_BATTERY_OPTIMIZATIONS, Uri.parse("package:$packageName"))) }
                catch (_: Exception) { startActivity(Intent(Settings.ACTION_IGNORE_BATTERY_OPTIMIZATION_SETTINGS)) }
            } else startActivity(Intent(Settings.ACTION_IGNORE_BATTERY_OPTIMIZATION_SETTINGS))
        }
        val third = tileRow()
        permissionCard.addView(third)
        permissionTile(third, "通知提醒", android.R.drawable.ic_dialog_info, "已允许", "未允许", {
            val notifications = getSystemService(android.app.NotificationManager::class.java)
            notifications.areNotificationsEnabled() && notifications.getNotificationChannel("tracking")?.importance != android.app.NotificationManager.IMPORTANCE_NONE
        }) { startActivity(Intent(Settings.ACTION_APP_NOTIFICATION_SETTINGS).putExtra(Settings.EXTRA_APP_PACKAGE, packageName)) }
        permissionTile(third, "网络辅助", android.R.drawable.ic_menu_compass, "可使用", "不可用", {
            val manager = getSystemService(LocationManager::class.java)
            manager.allProviders.contains(LocationManager.NETWORK_PROVIDER) && manager.isProviderEnabled(LocationManager.NETWORK_PROVIDER)
        }) { startActivity(Intent(Settings.ACTION_LOCATION_SOURCE_SETTINGS)) }
        permissionCard.addView(text("点击卡片可设置。手机的启动管理还需允许自启动、关联启动和后台活动。", 16f, muted).apply { setPadding(0, dp(12), 0, 0) })

        val details = card(content)
        val detailBody = column().apply { visibility = View.GONE }
        val detailsButton = button(details, "查看运行详情  ⌄") {
            detailBody.visibility = if (detailBody.visibility == View.VISIBLE) View.GONE else View.VISIBLE
        }
        detailsButton.setOnClickListener {
            val open = detailBody.visibility != View.VISIBLE
            detailBody.visibility = if (open) View.VISIBLE else View.GONE
            detailsButton.text = if (open) "收起运行详情  ⌃" else "查看运行详情  ⌄"
        }
        details.addView(detailBody)
        status = text("", 17f, muted); space(detailBody); detailBody.addView(status)
        retryPush = button(detailBody, "重新连接推送") { startTracking() }
        button(detailBody, "应用与启动设置") { appSettings() }
        button(detailBody, "个推隐私说明") { startActivity(Intent(Intent.ACTION_VIEW, Uri.parse("https://docs.getui.com/privacy"))) }
        detailBody.addView(text("定位同时使用GPS与系统网络辅助；基站/Wi-Fi定位依赖系统支持，误差可能较大。无围栏和进行中的行程时，只响应家属请求；开启围栏或行程后自动定位。锁屏后仍会尝试守护，但系统限制、网络中断或强制停止可能影响响应。关闭守护后不再共享新位置。", 16f, muted).apply { setPadding(0, dp(16), 0, 0) })
        button(content, "解除家人绑定") { confirmUnpair() }.apply { setTextColor(amber); background = shape(Color.rgb(255, 240, 217), 15) }
        space(content, 20)
    }
    private fun permissionTile(parent: LinearLayout, title: String, resource: Int, good: String, missing: String, test: () -> Boolean, action: () -> Unit) {
        val tile = column().apply { background = touchBackground(paper); setPadding(dp(12), dp(14), dp(12), dp(14)); isClickable = true; isFocusable = true }
        parent.addView(tile, tileParams(parent).apply { topMargin = dp(12) })
        tile.addView(icon(resource), LinearLayout.LayoutParams(dp(40), dp(40)))
        space(tile, 8); tile.addView(text(title, 18f, ink, true)); space(tile, 8)
        val state = badge(""); tile.addView(state)
        val hint = text("", 14f, muted); space(tile, 6); tile.addView(hint)
        tile.setOnClickListener { action(); refreshState() }
        permissionTiles.add(PermissionTile(state, hint, test, good, missing))
    }
    private fun refreshState() {
        if (!boundScreen || !::guardSwitch.isInitialized) return
        val enabled = prefs.getBoolean("tracking_enabled", false)
        val running = enabled && TrackingService.isRunning()
        updatingSwitch = true; guardSwitch.isChecked = enabled; updatingSwitch = false
        guardSwitch.text = if (enabled) "守护开关 · 开" else "守护开关 · 关"
        paintBadge(guardBadge, if (running) "● 守护服务运行中" else if (enabled) "! 等待服务恢复" else "○ 已关闭", running)
        guardTitle.text = if (running) "守护已开启" else if (enabled) "守护需要恢复" else "守护已暂停"
        guardSubtitle.text = if (running) "可返回桌面或锁屏，保留守护通知" else if (enabled) "请检查下方权限，或重新连接守护" else "开启后，家属才可请求新位置"
        recoverGuard.visibility = if (enabled && !running) View.VISIBLE else View.GONE
        val online = running && prefs.getBoolean("push_online", false)
        paintBadge(pushBadge, if (!enabled) "已关闭" else if (online) "最近在线" else "待连接", online)
        pushDetail.text = if (online) "最近回报已连接；以实际请求结果为准" else if (enabled) "暂不能确认请求可送达，请检查网络" else "开启守护后连接"
        val settings = try { JSONObject(prefs.getString("settings", "{}") ?: "{}") } catch (_: Exception) { JSONObject() }
        val automatic = settings.optJSONObject("fence") != null || settings.optJSONObject("trip")?.optString("status") == "active"
        paintBadge(modeBadge, if (!enabled) "已暂停" else if (automatic) "自动守护" else "按需定位", enabled)
        modeDetail.text = if (!enabled) "开启后恢复定位服务" else if (automatic) "围栏或行程已开启，自动采集位置" else "家属请求时定位，平时不定时采集"
        permissionTiles.forEach {
            val allowed = it.test()
            paintBadge(it.badge, (if (allowed) "✓ " else "! ") + if (allowed) it.good else it.missing, allowed)
            it.detail.text = if (allowed) "点击查看设置" else "点击去开启"
        }
        status.text = prefs.getString("status", "尚未开始守护") + "\n\n" + prefs.getString("push_status", "推送尚未启用") + "\n\n" + backgroundStatus()
        retryPush.text = if (enabled) "重新连接推送" else "开启守护并连接"
    }
    private fun stopSharing() {
        prefs.edit().putBoolean("tracking_enabled", false).remove("pending_location").commit()
        GuardWakeReceiver.schedule(this, false)
        PushManager.getInstance().turnOffPush(this)
        stopService(Intent(this, TrackingService::class.java))
        showNotice("位置共享已停止")
        refreshState()
    }
    private fun confirmStop() {
        AlertDialog.Builder(this).setTitle("暂停位置守护？").setMessage("关闭后家属将无法取得新位置，围栏和行程守护也会停止。")
            .setPositiveButton("暂停守护") { _, _ ->
                stopSharing()
                worker.execute { try { Api(this).request("/device/push", JSONObject().put("enabled", false)) } catch (_: Exception) { } }
            }.setNegativeButton("继续守护") { _, _ -> refreshState() }.setOnCancelListener { refreshState() }.show()
    }
    private fun confirmUnpair() {
        AlertDialog.Builder(this).setTitle("解除家人绑定？").setMessage("解除后家属无法取得本机新位置，再次连接需要绑定码。")
            .setPositiveButton("解除绑定") { _, _ ->
                stopSharing()
                worker.execute {
                    try {
                        Api(this).request("/device/unpair", JSONObject())
                        prefs.edit().clear().apply()
                        runOnUiThread { if (!isFinishing && !isDestroyed) render() }
                    } catch (e: Exception) { runOnUiThread { showNotice("解除失败：${e.message}。本机定位已停止，可重试。") } }
                }
            }.setNegativeButton("保留绑定", null).show()
    }
    private fun backgroundStatus(): String =
        "后台定位：" + (if (GuardWakeReceiver.backgroundGranted(this)) "已允许" else "未允许，服务回收后不能自动恢复") +
        "\n电池限制：" + (if (GuardWakeReceiver.unrestricted(this)) "已解除" else "未解除，息屏可能暂停联网及定位")
    private fun requestBackgroundLocation() {
        if (checkSelfPermission(Manifest.permission.ACCESS_FINE_LOCATION) != PackageManager.PERMISSION_GRANTED) {
            showNotice("请先开启守护，允许精确定位"); return
        }
        if (GuardWakeReceiver.backgroundGranted(this)) { showNotice("后台定位已允许"); return }
        AlertDialog.Builder(this).setTitle("允许息屏后的后台守护")
            .setMessage("用于服务被系统回收后的恢复、家属主动查询及围栏监测。请将位置权限设为“始终允许”，并保留精确定位。未开启围栏或行程时仍只按需定位。")
            .setPositiveButton("去设置") { _, _ ->
                if (Build.VERSION.SDK_INT == 29) requestPermissions(arrayOf(Manifest.permission.ACCESS_BACKGROUND_LOCATION), 12)
                else startActivity(Intent(Settings.ACTION_APPLICATION_DETAILS_SETTINGS, Uri.parse("package:$packageName")))
            }.setNegativeButton("暂不", null).show()
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
                .setNegativeButton("暂不开启") { _, _ -> showNotice("尚未启用推送，请阅读说明后开启守护") }.show()
            return
        }
        prefs.edit().putBoolean("tracking_enabled", true).commit()
        try {
            startForegroundService(Intent(this, TrackingService::class.java))
            ElderPushRuntime.start(this)
            showNotice("正在启动后台守护及推送…")
            refreshState()
        } catch (e: Exception) {
            val message = "系统未允许启动守护：${e.message ?: "请检查应用权限和后台活动设置"}"
            showNotice(message); refreshState()
        }
    }
    override fun onRequestPermissionsResult(requestCode: Int, permissions: Array<out String>, grantResults: IntArray) {
        super.onRequestPermissionsResult(requestCode, permissions, grantResults)
        if (requestCode == 10 && checkSelfPermission(Manifest.permission.ACCESS_FINE_LOCATION) == PackageManager.PERMISSION_GRANTED) startTracking()
        else if (requestCode == 11) {
            launchTracking()
        } else if (requestCode == 12) { showNotice(backgroundStatus()); refreshState() }
        else showNotice("需要精确定位权限才能开始守护")
    }
}
