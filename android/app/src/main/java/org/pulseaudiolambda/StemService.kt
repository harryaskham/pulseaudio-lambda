package org.pulseaudiolambda

import android.app.Notification
import android.app.NotificationChannel
import android.app.NotificationManager
import android.app.Service
import android.content.Context
import android.content.Intent
import android.media.projection.MediaProjection
import android.os.Build
import android.os.IBinder
import androidx.core.app.NotificationCompat

/**
 * Foreground service that drives StemEngine.
 * Start with action START and projection extras; send SET_VOLUME to adjust volumes.
 */
class StemService : Service() {
    companion object {
        const val ACTION_START = "org.pulseaudiolambda.action.START"
        const val ACTION_STOP = "org.pulseaudiolambda.action.STOP"
        const val ACTION_SET_VOLUME = "org.pulseaudiolambda.action.SET_VOLUME"
        const val EXTRA_RESULT_CODE = "result_code"
        const val EXTRA_RESULT_DATA = "result_data"
        const val EXTRA_STEM = "stem"
        const val EXTRA_VOLUME = "volume"

        private const val CHANNEL_ID = "stem_channel"
        private const val NOTIF_ID = 1001
    }

    private lateinit var engine: StemEngine

    override fun onCreate() {
        super.onCreate()
        engine = StemEngine(this)
        createNotificationChannel()
        startForeground(NOTIF_ID, buildNotification("Idle"))
    }

    override fun onStartCommand(intent: Intent?, flags: Int, startId: Int): Int {
        when (intent?.action) {
            ACTION_START -> {
                if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.Q) {
                    val code = intent.getIntExtra(EXTRA_RESULT_CODE, 0)
                    val data = intent.getParcelableExtra(EXTRA_RESULT_DATA, android.content.Intent::class.java)
                    val mgr = getSystemService(Context.MEDIA_PROJECTION_SERVICE) as android.media.projection.MediaProjectionManager
                    val projection: MediaProjection? = if (code == android.app.Activity.RESULT_OK && data != null) mgr.getMediaProjection(code, data) else null
                    val ok = projection?.let { engine.start(it) } ?: false
                    updateNotification(if (ok) "Running" else "Model load failed")
                } else updateNotification("Requires Android 10+")
            }
            ACTION_SET_VOLUME -> {
                val stemName = intent.getStringExtra(EXTRA_STEM)
                val vol = intent.getFloatExtra(EXTRA_VOLUME, 1f)
                stemName?.let {
                    runCatching { Stem.valueOf(it) }.getOrNull()?.let { engine.setVolume(it, vol) }
                }
            }
            ACTION_STOP -> {
                engine.stop()
                stopForeground(STOP_FOREGROUND_REMOVE)
                stopSelf()
            }
        }
        return START_STICKY
    }

    override fun onBind(intent: Intent?): IBinder? = null

    override fun onDestroy() {
        engine.stop()
        super.onDestroy()
    }

    private fun createNotificationChannel() {
        val mgr = getSystemService(Context.NOTIFICATION_SERVICE) as NotificationManager
        val channel = NotificationChannel(CHANNEL_ID, "Stem Separation", NotificationManager.IMPORTANCE_LOW)
        mgr.createNotificationChannel(channel)
    }

    private fun buildNotification(state: String): Notification {
        return NotificationCompat.Builder(this, CHANNEL_ID)
            .setContentTitle("PA Lambda")
            .setContentText("Stem service: $state")
            .setSmallIcon(android.R.drawable.ic_media_play)
            .setOngoing(true)
            .build()
    }

    private fun updateNotification(state: String) {
        val mgr = getSystemService(Context.NOTIFICATION_SERVICE) as NotificationManager
        mgr.notify(NOTIF_ID, buildNotification(state))
    }
}
