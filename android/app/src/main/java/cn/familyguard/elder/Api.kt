package cn.familyguard.elder

import android.content.Context
import org.json.JSONObject
import java.net.HttpURLConnection
import java.net.URI

class ApiFailure(val status: Int, message: String) : IllegalStateException(message)

class Api(private val context: Context) {
    private val prefs get() = context.getSharedPreferences("guard", Context.MODE_PRIVATE)
    fun request(path: String, body: JSONObject? = null, authenticated: Boolean = true): JSONObject {
        val base = prefs.getString("server", "")!!.trimEnd('/')
        val uri = URI(base)
        require(uri.host != null && uri.userInfo == null && uri.query == null && uri.fragment == null && (uri.scheme == "https" || (BuildConfig.DEBUG && uri.scheme == "http"))) { "请填写有效 HTTPS 服务地址" }
        val connection = URI(base + path).toURL().openConnection() as HttpURLConnection
        connection.connectTimeout = 15000
        connection.readTimeout = 15000
        connection.instanceFollowRedirects = false
        connection.requestMethod = if (body == null) "GET" else "POST"
        if (authenticated) connection.setRequestProperty("Authorization", "Bearer " + prefs.getString("token", ""))
        try {
            if (body != null) {
                connection.doOutput = true
                connection.setRequestProperty("Content-Type", "application/json")
                connection.outputStream.use { it.write(body.toString().toByteArray(Charsets.UTF_8)) }
            }
            val status = connection.responseCode
            val stream = if (status in 200..299) connection.inputStream else connection.errorStream
            val result = JSONObject(stream?.bufferedReader()?.use { it.readText() } ?: "{}")
            if (status !in 200..299) throw ApiFailure(status, result.optString("error", "连接失败 ($status)"))
            return result
        } finally { connection.disconnect() }
    }
}
