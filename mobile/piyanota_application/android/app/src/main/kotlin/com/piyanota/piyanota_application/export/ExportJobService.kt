package com.piyanota.piyanota_application.export

import android.app.ForegroundServiceStartNotAllowedException
import android.app.Service
import android.content.Context
import android.content.Intent
import android.os.Build
import android.os.IBinder
import android.util.Log

/**
 * Keeps the app's process in the foreground while an export runs, so it
 * keeps going when the user leaves the app (user decision 2026-10-22).
 * It does no work itself: [ExportWorker] owns the export, and this service
 * only holds the foreground state, shows the worker's notification and
 * passes on the notification's Cancel.
 *
 * Type: mediaProcessing on Android 15+, dataSync on 10..14 (see
 * [ExportNotices.serviceType]). Both have a 6 h daily limit on 15+;
 * [onTimeout] ends the export as interrupted if it is ever reached.
 */
class ExportJobService : Service() {
    override fun onBind(intent: Intent?): IBinder? = null

    override fun onStartCommand(intent: Intent?, flags: Int, startId: Int): Int {
        if (intent?.action == ACTION_CANCEL) {
            ExportWorker.cancelFromNotification(applicationContext)
            if (!ExportWorker.isActive) stopNow()
            return START_NOT_STICKY
        }
        val notice = ExportWorker.currentNotice()
        if (notice == null) {
            // The export ended before the service got going; still has to
            // enter the foreground once, or Android stops the app.
            enterForeground(fallback = true)
            stopNow()
            return START_NOT_STICKY
        }
        ExportWorker.service = this
        enterForeground(fallback = false)
        // Not restarted by Android: an export cut short by a killed process
        // cannot be resumed, and Dart reports it as interrupted.
        return START_NOT_STICKY
    }

    private fun enterForeground(fallback: Boolean) {
        val notice = ExportWorker.currentNotice()
        val notification = if (notice != null && !fallback) {
            ExportNotifications.progress(this, notice, ExportWorker.currentPercent())
        } else {
            ExportNotifications.progress(this, FALLBACK_NOTICE, 0)
        }
        try {
            val type = ExportNotices.serviceType(Build.VERSION.SDK_INT)
            if (type != null && Build.VERSION.SDK_INT >= Build.VERSION_CODES.Q) {
                startForeground(ExportNotifications.PROGRESS_ID, notification, type)
            } else {
                startForeground(ExportNotifications.PROGRESS_ID, notification)
            }
        } catch (e: RuntimeException) {
            // Android 12+ refuses a foreground start from the background
            // (ForegroundServiceStartNotAllowedException). The export was
            // started from the open app, so this should not happen; if it
            // does, the export carries on as long as the process lives.
            if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.S && e is ForegroundServiceStartNotAllowedException) {
                Log.w(TAG, "export service not allowed in the foreground", e)
            } else {
                throw e
            }
        }
    }

    override fun onTimeout(startId: Int, fgsType: Int) {
        // Android 15+'s limit for the type ran out.
        ExportWorker.timedOut(applicationContext)
        stopNow()
    }

    override fun onDestroy() {
        if (ExportWorker.service === this) ExportWorker.service = null
        super.onDestroy()
    }

    /** Leaves the foreground, removing the progress notification. */
    fun stopNow() {
        if (ExportWorker.service === this) ExportWorker.service = null
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.N) {
            stopForeground(STOP_FOREGROUND_REMOVE)
        } else {
            @Suppress("DEPRECATION")
            stopForeground(true)
        }
        stopSelf()
    }

    companion object {
        const val ACTION_CANCEL = "com.piyanota.piyanota_application.export.CANCEL"
        private const val TAG = "PiyaNotaExport"

        /** Only seen for a moment, when an export ended before its service started. */
        private val FALLBACK_NOTICE = ExportNotice(
            exporting = "Exporting…",
            cancel = "Cancel",
            savedTemplate = "",
            failedTitle = "",
            failures = emptyMap(),
            fallbackFailure = "",
        )

        fun start(context: Context) {
            val intent = Intent(context, ExportJobService::class.java)
            try {
                if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.O) {
                    context.startForegroundService(intent)
                } else {
                    context.startService(intent)
                }
            } catch (e: RuntimeException) {
                // Background start refused (IllegalStateException or, 12+,
                // ForegroundServiceStartNotAllowedException): the export
                // still runs while the app is open.
                Log.w(TAG, "export service not started", e)
            }
        }
    }
}
