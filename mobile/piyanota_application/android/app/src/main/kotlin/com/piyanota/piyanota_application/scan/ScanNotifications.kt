package com.piyanota.piyanota_application.scan

import android.app.Notification
import android.app.NotificationChannel
import android.app.NotificationManager
import android.app.PendingIntent
import android.content.Context
import android.content.Intent
import android.os.Build
import android.util.Log
import com.piyanota.piyanota_application.MainActivity

/**
 * The conversion notifications (PIYA-218): an ongoing "Scanning <title>…"
 * while a scan runs and the app is followed by [ScanTrackingService], then
 * one per scan that finished while the app was not on screen, which opens
 * that score (or its Processing screen) when tapped.
 *
 * Plain platform Notification.Builder, as for the export. With
 * POST_NOTIFICATIONS refused (Android 13+) the system drops them and the
 * scan is still followed.
 */
internal object ScanNotifications {
    const val ONGOING_ID = 0x5201
    private const val RESULT_TAG = "scan_result"
    private const val ONGOING_CHANNEL = "scan_progress"
    private const val RESULT_CHANNEL = "scan_results"
    private const val TAG = "PiyaNotaScan"

    // Shown in the phone's notification settings for the app.
    private const val ONGOING_CHANNEL_NAME = "Conversions in progress"
    private const val RESULT_CHANNEL_NAME = "Finished conversions"

    private const val REQUEST_OPEN_APP = 1

    private fun ensureChannels(context: Context) {
        if (Build.VERSION.SDK_INT < Build.VERSION_CODES.O) return
        val manager = context.getSystemService(NotificationManager::class.java) ?: return
        manager.createNotificationChannel(
            NotificationChannel(ONGOING_CHANNEL, ONGOING_CHANNEL_NAME, NotificationManager.IMPORTANCE_LOW),
        )
        manager.createNotificationChannel(
            NotificationChannel(RESULT_CHANNEL, RESULT_CHANNEL_NAME, NotificationManager.IMPORTANCE_DEFAULT),
        )
    }

    fun ongoing(context: Context, text: String): Notification {
        ensureChannels(context)
        val builder = builder(context, ONGOING_CHANNEL)
            .setSmallIcon(android.R.drawable.stat_notify_sync)
            .setContentTitle(text)
            // No percent: the app's bar is the place for that, and posting
            // every 2 s poll would be noise.
            .setProgress(0, 0, true)
            .setOngoing(true)
            .setOnlyAlertOnce(true)
            .setShowWhen(false)
            .setContentIntent(openApp(context))
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.S) {
            builder.setForegroundServiceBehavior(Notification.FOREGROUND_SERVICE_IMMEDIATE)
        }
        return builder.build()
    }

    fun updateOngoing(context: Context, text: String) {
        notify(context, null, ONGOING_ID, ongoing(context, text))
    }

    fun cancelOngoing(context: Context) {
        context.getSystemService(NotificationManager::class.java)?.cancel(ONGOING_ID)
    }

    fun postResult(context: Context, jobId: String, title: String, text: String, ok: Boolean) {
        ensureChannels(context)
        val id = ScanNotices.resultId(jobId)
        // MainActivity is singleTop: a running app gets onNewIntent, a
        // closed one starts with the extra.
        val open = Intent(context, MainActivity::class.java)
            .putExtra(ScanNotices.EXTRA_JOB_ID, jobId)
            .addFlags(Intent.FLAG_ACTIVITY_NEW_TASK or Intent.FLAG_ACTIVITY_SINGLE_TOP)
        val tap = PendingIntent.getActivity(
            context,
            id,
            open,
            PendingIntent.FLAG_IMMUTABLE or PendingIntent.FLAG_UPDATE_CURRENT,
        )
        val notification = builder(context, RESULT_CHANNEL)
            .setSmallIcon(if (ok) android.R.drawable.stat_sys_download_done else android.R.drawable.stat_notify_error)
            .setContentTitle(title)
            .setContentText(text)
            .setAutoCancel(true)
            .setContentIntent(tap)
            .build()
        notify(context, RESULT_TAG, id, notification)
    }

    /** Seen in the app (bell, card, Processing): the shade needn't say it again. */
    fun cancelResult(context: Context, jobId: String) {
        context.getSystemService(NotificationManager::class.java)
            ?.cancel(RESULT_TAG, ScanNotices.resultId(jobId))
    }

    /** Logout: every conversion notification goes, the ongoing one too. */
    fun cancelAll(context: Context) {
        val manager = context.getSystemService(NotificationManager::class.java) ?: return
        manager.cancel(ONGOING_ID)
        // activeNotifications is API 23; minSdk is 24. It also finds
        // results posted before the process last died.
        runCatching { manager.activeNotifications }
            .getOrNull()
            ?.filter { it.tag == RESULT_TAG }
            ?.forEach { manager.cancel(RESULT_TAG, it.id) }
    }

    @Suppress("DEPRECATION")
    private fun builder(context: Context, channel: String): Notification.Builder =
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.O) {
            Notification.Builder(context, channel)
        } else {
            Notification.Builder(context)
        }

    private fun notify(context: Context, tag: String?, id: Int, notification: Notification) {
        try {
            context.getSystemService(NotificationManager::class.java)?.notify(tag, id, notification)
        } catch (e: SecurityException) {
            Log.i(TAG, "notification not shown", e)
        }
    }

    private fun openApp(context: Context): PendingIntent? {
        val launch = context.packageManager.getLaunchIntentForPackage(context.packageName) ?: return null
        launch.addFlags(Intent.FLAG_ACTIVITY_NEW_TASK or Intent.FLAG_ACTIVITY_SINGLE_TOP)
        return PendingIntent.getActivity(
            context,
            REQUEST_OPEN_APP,
            launch,
            PendingIntent.FLAG_IMMUTABLE or PendingIntent.FLAG_UPDATE_CURRENT,
        )
    }
}
