package com.piyanota.piyanota_application.export

import android.app.Notification
import android.app.NotificationChannel
import android.app.NotificationManager
import android.app.PendingIntent
import android.content.Context
import android.content.Intent
import android.net.Uri
import android.os.Build
import android.provider.DocumentsContract
import android.util.Log

/**
 * The export's system notifications (user decision 2026-10-22): an ongoing
 * "Exporting <title>… n%" with a Cancel action while it runs (it is also
 * the foreground service's notification), then "Saved <file> to <folder>"
 * or the failure. A cancel leaves nothing.
 *
 * Plain platform Notification.Builder: the app has no androidx.core, and
 * minSdk 24 has everything used here. When POST_NOTIFICATIONS is refused
 * (Android 13+) notify() is silently dropped by the system, and the export
 * runs all the same.
 */
internal object ExportNotifications {
    const val PROGRESS_ID = 0x5101
    private const val RESULT_ID = 0x5102
    private const val PROGRESS_CHANNEL = "export_progress"
    private const val RESULT_CHANNEL = "export_results"
    private const val TAG = "PiyaNotaExport"

    // Shown in the phone's notification settings for the app.
    private const val PROGRESS_CHANNEL_NAME = "Export progress"
    private const val RESULT_CHANNEL_NAME = "Finished exports"

    private const val REQUEST_CANCEL = 1
    private const val REQUEST_OPEN_APP = 2
    private const val REQUEST_OPEN_FOLDER = 3

    fun ensureChannels(context: Context) {
        if (Build.VERSION.SDK_INT < Build.VERSION_CODES.O) return
        val manager = context.getSystemService(NotificationManager::class.java) ?: return
        manager.createNotificationChannel(
            // Low: no sound or pop-up for a bar that updates every percent.
            NotificationChannel(PROGRESS_CHANNEL, PROGRESS_CHANNEL_NAME, NotificationManager.IMPORTANCE_LOW),
        )
        manager.createNotificationChannel(
            NotificationChannel(RESULT_CHANNEL, RESULT_CHANNEL_NAME, NotificationManager.IMPORTANCE_DEFAULT),
        )
    }

    fun progress(context: Context, notice: ExportNotice, percent: Int): Notification {
        ensureChannels(context)
        val cancel = PendingIntent.getService(
            context,
            REQUEST_CANCEL,
            Intent(context, ExportJobService::class.java).setAction(ExportJobService.ACTION_CANCEL),
            PendingIntent.FLAG_IMMUTABLE or PendingIntent.FLAG_UPDATE_CURRENT,
        )
        val builder = builder(context, PROGRESS_CHANNEL)
            .setSmallIcon(android.R.drawable.stat_sys_download)
            .setContentTitle(notice.progressText(percent))
            .setProgress(MAX_PERCENT, percent, false)
            .setOngoing(true)
            .setOnlyAlertOnce(true)
            .setShowWhen(false)
            .setContentIntent(openApp(context))
            .addAction(
                Notification.Action.Builder(null, notice.cancel, cancel).build(),
            )
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.S) {
            // Shown at once rather than after Android 12's 10 s grace,
            // since most exports finish within a minute.
            builder.setForegroundServiceBehavior(Notification.FOREGROUND_SERVICE_IMMEDIATE)
        }
        return builder.build()
    }

    fun updateProgress(context: Context, notice: ExportNotice, percent: Int) {
        notify(context, PROGRESS_ID, progress(context, notice, percent))
    }

    fun postResult(context: Context, result: ResultNotice, tree: Uri?) {
        ensureChannels(context)
        val tap = if (result.opensFolder && tree != null) openFolder(context, tree) else null
        val builder = builder(context, RESULT_CHANNEL)
            .setSmallIcon(
                if (result.opensFolder) android.R.drawable.stat_sys_download_done else android.R.drawable.stat_notify_error,
            )
            .setContentTitle(result.title)
            .setAutoCancel(true)
            .setContentIntent(tap ?: openApp(context))
        result.text?.let {
            builder.setContentText(it).setStyle(Notification.BigTextStyle().bigText(it))
        }
        notify(context, RESULT_ID, builder.build())
    }

    /** Logout (H1): every export notification goes. */
    fun cancelAll(context: Context) {
        val manager = context.getSystemService(NotificationManager::class.java) ?: return
        manager.cancel(PROGRESS_ID)
        manager.cancel(RESULT_ID)
    }

    fun cancelProgress(context: Context) {
        context.getSystemService(NotificationManager::class.java)?.cancel(PROGRESS_ID)
    }

    @Suppress("DEPRECATION")
    private fun builder(context: Context, channel: String): Notification.Builder =
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.O) {
            Notification.Builder(context, channel)
        } else {
            Notification.Builder(context)
        }

    private fun notify(context: Context, id: Int, notification: Notification) {
        try {
            context.getSystemService(NotificationManager::class.java)?.notify(id, notification)
        } catch (e: SecurityException) {
            // Notifications refused; the export itself is unaffected.
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

    /**
     * Opens the folder in a file manager, like the in-app "Open folder".
     * Null when none on the phone opens folders (the <queries> entry in
     * the manifest lets this be checked); the tap then opens the app.
     * Direct to the file manager, not through a service: Android 12+ does
     * not let a notification start an activity from a service or receiver.
     */
    private fun openFolder(context: Context, tree: Uri): PendingIntent? {
        val intent = runCatching { folderIntent(tree) }.getOrNull() ?: return null
        if (intent.resolveActivity(context.packageManager) == null) return null
        return PendingIntent.getActivity(
            context,
            REQUEST_OPEN_FOLDER,
            intent,
            PendingIntent.FLAG_IMMUTABLE or PendingIntent.FLAG_UPDATE_CURRENT,
        )
    }

    fun folderIntent(tree: Uri): Intent {
        val doc = DocumentsContract.buildDocumentUriUsingTree(tree, DocumentsContract.getTreeDocumentId(tree))
        return Intent(Intent.ACTION_VIEW)
            .setDataAndType(doc, DocumentsContract.Document.MIME_TYPE_DIR)
            .addFlags(Intent.FLAG_GRANT_READ_URI_PERMISSION or Intent.FLAG_ACTIVITY_NEW_TASK)
    }

    private const val MAX_PERCENT = 100
}
