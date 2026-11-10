package com.piyanota.piyanota_application.scan

import android.app.job.JobInfo
import android.app.job.JobParameters
import android.app.job.JobScheduler
import android.app.job.JobService
import android.content.ComponentName
import android.content.Context
import android.os.Handler
import android.os.Looper
import android.util.Log
import com.piyanota.piyanota_application.AppVisibility
import io.flutter.FlutterInjector
import io.flutter.embedding.engine.FlutterEngine
import io.flutter.embedding.engine.dart.DartExecutor
import io.flutter.plugin.common.MethodChannel

/**
 * Finishes conversions while the app is closed (job-lifecycle Task 6): a
 * periodic job (platform minimum 15 min) starts a headless Flutter engine
 * that runs Dart's backgroundCompletionMain. Dart does the work (reads the
 * session token from secure storage, reconciles, downloads results) and
 * asks this class to post the notification and to finish.
 *
 * Best effort: the foreground reconcile stays the primary path. Plain
 * framework JobScheduler, so no new dependency; WorkManager is not in the
 * app. Skipped while the app is on screen (or its file picker is open) or the scan service is following
 * a job (the foreground poll owns the rows then, and the two must not write
 * them at once).
 */
class BackgroundCompletionJob : JobService() {
    private var engine: FlutterEngine? = null
    private var params: JobParameters? = null
    private val handler = Handler(Looper.getMainLooper())
    private val watchdog = Runnable { finish(keep = true) }

    override fun onStartJob(params: JobParameters): Boolean {
        if (AppVisibility.visible || ScanTrackingService.wanted) return false
        this.params = params
        try {
            val loader = FlutterInjector.instance().flutterLoader()
            loader.startInitialization(applicationContext)
            loader.ensureInitializationComplete(applicationContext, null)
            val flutter = FlutterEngine(applicationContext)
            engine = flutter
            MethodChannel(flutter.dartExecutor.binaryMessenger, CHANNEL).setMethodCallHandler { call, result ->
                when (call.method) {
                    "notifyResult" -> {
                        val jobId = call.argument<String>("jobId")
                        val title = call.argument<String>("title")
                        val text = call.argument<String>("text")
                        val ok = call.argument<Boolean>("ok")
                        if (jobId == null || title == null || text == null || ok == null) {
                            result.error("bad_args", "jobId, title, text and ok are required", null)
                        } else {
                            ScanNotifications.postResult(applicationContext, jobId, title, text, ok)
                            result.success(null)
                        }
                    }
                    // Dart polls this between steps and stops when the user
                    // opened the app: the foreground owns the rows then.
                    "cancelRequested" -> result.success(AppVisibility.visible)
                    "finish" -> {
                        result.success(null)
                        finish(keep = call.argument<Boolean>("keep") ?: true)
                    }
                    else -> result.notImplemented()
                }
            }
            flutter.dartExecutor.executeDartEntrypoint(
                DartExecutor.DartEntrypoint(
                    loader.findAppBundlePath(),
                    DART_LIBRARY,
                    DART_FUNCTION,
                ),
            )
            // A hung network call must not hold the job for its full limit.
            handler.postDelayed(watchdog, WATCHDOG_MS)
            return true
        } catch (e: RuntimeException) {
            Log.w(TAG, "background run not started", e)
            destroyEngine()
            return false
        }
    }

    // Android stopped the job (constraints lost, time up): try again later.
    override fun onStopJob(params: JobParameters): Boolean {
        handler.removeCallbacks(watchdog)
        this.params = null
        destroyEngine()
        return true
    }

    private fun finish(keep: Boolean) {
        val running = params ?: return
        params = null
        handler.removeCallbacks(watchdog)
        // Nothing left to follow (or the session ended): stop the period.
        if (!keep) cancel(applicationContext)
        // Destroyed after Dart's reply was sent, not inside the call.
        handler.post { destroyEngine() }
        jobFinished(running, false)
    }

    private fun destroyEngine() {
        engine?.destroy()
        engine = null
    }

    companion object {
        private const val TAG = "PiyaNotaBackground"
        const val CHANNEL = "piyanota/background"
        private const val JOB_ID = 0x5202
        private const val PERIOD_MS = 15 * 60 * 1000L
        private const val WATCHDOG_MS = 5 * 60 * 1000L
        private const val DART_LIBRARY = "package:piyanota_application/services/background_completion.dart"
        private const val DART_FUNCTION = "backgroundCompletionMain"

        /** Idempotent: leaves a pending job alone so its period is not reset. */
        fun schedule(context: Context) {
            val scheduler = context.getSystemService(JobScheduler::class.java) ?: return
            if (scheduler.getPendingJob(JOB_ID) != null) return
            val info = JobInfo.Builder(JOB_ID, ComponentName(context, BackgroundCompletionJob::class.java))
                .setRequiredNetworkType(JobInfo.NETWORK_TYPE_ANY)
                .setPeriodic(PERIOD_MS)
                // Survives a reboot (RECEIVE_BOOT_COMPLETED in the manifest).
                .setPersisted(true)
                .build()
            if (scheduler.schedule(info) != JobScheduler.RESULT_SUCCESS) {
                Log.w(TAG, "background job not scheduled")
            }
        }

        fun cancel(context: Context) {
            context.getSystemService(JobScheduler::class.java)?.cancel(JOB_ID)
        }
    }
}
