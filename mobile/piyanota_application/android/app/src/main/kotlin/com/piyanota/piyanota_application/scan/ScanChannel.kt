package com.piyanota.piyanota_application.scan

import android.content.Context
import android.content.Intent
import io.flutter.plugin.common.BinaryMessenger
import io.flutter.plugin.common.MethodChannel

/**
 * The "piyanota/scans" channel (PIYA-218): Dart's tracker tells the device
 * what it is following, and the device tells Dart which scan a tapped
 * notification is about. Holds only the application context, so it keeps
 * working while the engine outlives the Activity.
 *
 * Methods:
 *  - show({text}) -> null. Starts [ScanTrackingService] with the ongoing
 *    "Scanning <title>…", or updates its words.
 *  - stop() -> null. Nothing left to follow.
 *  - notifyResult({jobId, title, text, ok}) -> null. A scan finished while
 *    the app was not on screen; tapping it opens that scan.
 *  - clearResult({jobId}) -> null. Seen in the app, or forgotten.
 *  - stopAll() -> null. Logout: the service and every conversion
 *    notification go.
 * Native -> Dart: open({jobId}), a result notification was tapped;
 * stopped(), the service went by itself (Android 15+ timeout, or a refused
 * start), so Dart must send its words again to bring it back.
 */
internal class ScanChannel(
    context: Context,
    /** The engine this channel talks to, so its destruction can find it. */
    val messenger: BinaryMessenger,
    /** Called once nothing is followed (stop, stopAll). */
    private val onIdle: () -> Unit,
) {
    private val app = context.applicationContext
    private val channel = MethodChannel(messenger, CHANNEL)

    private val stoppedCallback: () -> Unit = { channel.invokeMethod("stopped", null) }

    init {
        // The newest channel (this Activity's) answers; the engine is the same.
        ScanTrackingService.onStoppedByItself = stoppedCallback
        channel.setMethodCallHandler { call, result ->
            when (call.method) {
                "show" -> {
                    val text = call.argument<String>("text")
                    if (text == null) {
                        result.error("bad_args", "text is required", null)
                    } else {
                        ScanTrackingService.show(app, text)
                        result.success(null)
                    }
                }
                "stop" -> {
                    ScanTrackingService.stop(app)
                    onIdle()
                    result.success(null)
                }
                "notifyResult" -> {
                    val jobId = call.argument<String>("jobId")
                    val title = call.argument<String>("title")
                    val text = call.argument<String>("text")
                    val ok = call.argument<Boolean>("ok")
                    if (jobId == null || title == null || text == null || ok == null) {
                        result.error("bad_args", "jobId, title, text and ok are required", null)
                    } else {
                        ScanNotifications.postResult(app, jobId, title, text, ok)
                        result.success(null)
                    }
                }
                "clearResult" -> {
                    val jobId = call.argument<String>("jobId")
                    if (jobId == null) {
                        result.error("bad_args", "jobId is required", null)
                    } else {
                        ScanNotifications.cancelResult(app, jobId)
                        result.success(null)
                    }
                }
                "stopAll" -> {
                    ScanTrackingService.stop(app)
                    ScanNotifications.cancelAll(app)
                    onIdle()
                    result.success(null)
                }
                else -> result.notImplemented()
            }
        }
    }

    /**
     * The engine is being destroyed: a later service stop must not call
     * into its dead channel (review L3). A newer channel's callback stays.
     */
    fun dispose() {
        if (ScanTrackingService.onStoppedByItself === stoppedCallback) {
            ScanTrackingService.onStoppedByItself = null
        }
    }

    /**
     * Passes a tapped result notification's job to Dart. Only called when
     * Dart is already running (MainActivity decides); the extra is removed
     * so the same Intent never opens it twice.
     */
    fun deliver(intent: Intent?) {
        val jobId = intent?.getStringExtra(ScanNotices.EXTRA_JOB_ID) ?: return
        intent.removeExtra(ScanNotices.EXTRA_JOB_ID)
        channel.invokeMethod("open", mapOf("jobId" to jobId))
    }

    private companion object {
        const val CHANNEL = "piyanota/scans"
    }
}
