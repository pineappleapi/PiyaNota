package com.piyanota.piyanota_application.scan

import android.app.ForegroundServiceStartNotAllowedException
import android.app.Service
import android.content.Context
import android.content.Intent
import android.os.Build
import android.os.IBinder
import android.util.Log

/**
 * Keeps the app's process in the foreground while a conversion is being
 * followed (PIYA-218, user decision 2026-10-22), so the Dart tracker's
 * 2 s poll keeps running when the user leaves the app: without it Android
 * freezes a cached app (14+) or kills it under memory pressure, and the
 * poll stops until the next launch.
 *
 * It does no work itself: the polling stays in Dart
 * (ProcessingJobsController), and MainActivity keeps the Flutter engine
 * alive past the Activity while this is [wanted]. Chosen over WorkManager,
 * whose 15 min minimum period is far longer than a 2 min scan (NFR-1) and
 * which would need the poll and the session token rebuilt natively. Push
 * (FCM, PIYA-218 AC7's backend dependency) is the long-term answer: it
 * reaches a killed app and needs no foreground service.
 *
 * Type: dataSync, see [ScanNotices.serviceType].
 */
class ScanTrackingService : Service() {
    override fun onBind(intent: Intent?): IBinder? = null

    override fun onStartCommand(intent: Intent?, flags: Int, startId: Int): Int {
        val text = text
        // Must enter the foreground once whatever happens, or Android
        // stops the app.
        val entered = enterForeground(text ?: FALLBACK_TEXT)
        if (text == null || !entered) {
            // Dart stopped following before the service got going, or
            // Android refused the foreground: don't linger as a plain
            // started service.
            stopNow()
            // Only a refusal is news to Dart; a null text was its own stop.
            if (text != null) onStoppedByItself?.invoke()
            return START_NOT_STICKY
        }
        instance = this
        // Not restarted by Android: with the process gone there is no Dart
        // to poll; the next launch re-polls the stored jobs (AC8).
        return START_NOT_STICKY
    }

    /** False when Android refused the foreground start. */
    private fun enterForeground(text: String): Boolean {
        val notification = ScanNotifications.ongoing(this, text)
        try {
            val type = ScanNotices.serviceType(Build.VERSION.SDK_INT)
            if (type != null && Build.VERSION.SDK_INT >= Build.VERSION_CODES.Q) {
                startForeground(ScanNotifications.ONGOING_ID, notification, type)
            } else {
                startForeground(ScanNotifications.ONGOING_ID, notification)
            }
            return true
        } catch (e: RuntimeException) {
            if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.S && e is ForegroundServiceStartNotAllowedException) {
                // Started from the open app, so this should not happen; the
                // poll still runs as long as the process lives.
                Log.w(TAG, "scan service not allowed in the foreground", e)
                return false
            }
            throw e
        }
    }

    override fun onTimeout(startId: Int, fgsType: Int) {
        // Android 15+'s 6 h daily dataSync limit: leave the foreground.
        // Dart keeps polling while the process lives, but MainActivity no
        // longer keeps the engine for it (stopNow clears [wanted]).
        stopNow()
    }

    override fun onDestroy() {
        if (instance === this) instance = null
        super.onDestroy()
    }

    /**
     * Also clears [text], so [wanted] goes false and MainActivity stops
     * keeping the engine for a service that is no longer there. Dart's
     * next change of words (or a new scan) starts it again.
     */
    private fun stopNow() {
        text = null
        if (instance === this) instance = null
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.N) {
            stopForeground(STOP_FOREGROUND_REMOVE)
        } else {
            @Suppress("DEPRECATION")
            stopForeground(true)
        }
        stopSelf()
    }

    companion object {
        private const val TAG = "PiyaNotaScan"

        /** Only seen for a moment, when following ended before the start. */
        private const val FALLBACK_TEXT = "Scanning…"

        /** The ongoing notification's words; null when nothing is followed. */
        @Volatile
        private var text: String? = null

        @Volatile
        private var instance: ScanTrackingService? = null

        /**
         * Dart is following a conversion. MainActivity reads it to keep the
         * Flutter engine (and so the poll) alive when the Activity goes.
         */
        val wanted: Boolean get() = text != null

        /**
         * Tells Dart the service went without being asked (Android 15+
         * timeout, or a refused start), so its cache of the words it last
         * sent no longer matches and the next sync starts it again.
         * Main thread only; set by ScanChannel.
         */
        @Volatile
        var onStoppedByItself: (() -> Unit)? = null

        /** Starts the service, or updates its notification if it runs. */
        fun show(context: Context, words: String) {
            val app = context.applicationContext
            text = words
            if (instance != null) {
                ScanNotifications.updateOngoing(app, words)
                return
            }
            // Also when a start is still on its way: onStartCommand runs
            // again and shows the latest words.
            val intent = Intent(app, ScanTrackingService::class.java)
            try {
                if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.O) {
                    app.startForegroundService(intent)
                } else {
                    app.startService(intent)
                }
            } catch (e: RuntimeException) {
                // Refused from the background (IllegalStateException or,
                // 12+, ForegroundServiceStartNotAllowedException): the
                // poll runs while the process lives, without the guard.
                Log.w(TAG, "scan service not started", e)
                text = null
                onStoppedByItself?.invoke()
            }
        }

        /** Nothing left to follow: leave the foreground. */
        fun stop(context: Context) {
            text = null
            val running = instance
            if (running != null) {
                running.stopNow()
            } else {
                ScanNotifications.cancelOngoing(context.applicationContext)
            }
        }
    }
}
