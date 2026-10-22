package com.piyanota.piyanota_application

import android.content.Context
import android.content.Intent
import android.graphics.pdf.PdfRenderer
import android.os.Build
import android.os.Bundle
import android.os.Handler
import android.os.Looper
import android.os.ParcelFileDescriptor
import com.piyanota.piyanota_application.export.ExportChannel
import com.piyanota.piyanota_application.export.ExportWorker
import com.piyanota.piyanota_application.scan.ScanChannel
import com.piyanota.piyanota_application.scan.ScanTrackingService
import io.flutter.embedding.android.FlutterActivity
import io.flutter.embedding.engine.FlutterEngine
import io.flutter.embedding.engine.FlutterEngineCache
import io.flutter.plugin.common.MethodChannel
import java.io.File
import java.io.IOException
import java.util.concurrent.Executors
import java.util.concurrent.RejectedExecutionException
import java.util.concurrent.atomic.AtomicBoolean

/**
 * Hosts the small "piyanota/device" channel used by Capture (PIYA-206):
 *  - sdkInt: decides whether the gallery needs a storage permission
 *    (Android 12L and older) or uses the permission-less photo picker.
 *  - pdfPageCount: counts pages with the platform PdfRenderer, so a PDF over
 *    20 pages is rejected before upload (AC6) without a Dart PDF parser.
 *
 * It also hosts "piyanota/export" (PIYA-211), see [ExportChannel], and
 * "piyanota/scans" (PIYA-218), see [ScanChannel].
 *
 * PIYA-218 / PIYA-211: while a conversion is being followed
 * ([ScanTrackingService.wanted]) or an export runs ([ExportWorker.isActive])
 * the Flutter engine outlives this Activity (Back out of the app, or swiped
 * from Recents with a service holding the process), so the Dart poll and
 * the export's Dart half keep running. The next Activity picks the same
 * engine up, and it is destroyed once nothing needs it. Otherwise the
 * engine goes with the Activity, as before.
 *
 * The engine is built here, on the application context, so a kept engine
 * never holds on to the Activity that first created it (review M4). The
 * export channel lives as long as the engine, not the Activity (review
 * H2): it is disposed, and a Dart-side export reported interrupted, only
 * when the engine is really destroyed.
 */
class MainActivity : FlutterActivity() {
    private val pdfExecutor = Executors.newSingleThreadExecutor()
    private val mainHandler = Handler(Looper.getMainLooper())
    private var scanChannel: ScanChannel? = null
    private var deviceChannel: MethodChannel? = null

    /** This Activity took over an engine whose Dart was already running. */
    private var reattached = false

    /** Decided as this Activity lets go of its engine. */
    private var keepEngine = false

    override fun provideFlutterEngine(context: Context): FlutterEngine {
        val retained = FlutterEngineCache.getInstance().get(RETAINED_ENGINE)
        reattached = retained != null
        if (retained != null) return retained
        // Plugins register themselves (the constructor's default), as
        // FlutterActivity would for an engine it built.
        val engine = FlutterEngine(applicationContext, flutterShellArgs.toArray())
        val export = ExportChannel(applicationContext, engine.dartExecutor.binaryMessenger)
        engineExport?.dispose()
        engineExport = export
        engine.addEngineLifecycleListener(
            object : FlutterEngine.EngineLifecycleListener {
                override fun onPreEngineRestart() = Unit

                override fun onEngineWillDestroy() {
                    export.dispose()
                    if (engineExport === export) engineExport = null
                }
            },
        )
        return engine
    }

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        // A fresh engine starts at Login (no auto-login yet, PIYA-214), and
        // logging in forgets every followed scan, so a tap only opens its
        // scan when Dart was already running.
        if (reattached) scanChannel?.deliver(intent)
    }

    override fun onNewIntent(intent: Intent) {
        super.onNewIntent(intent)
        setIntent(intent)
        scanChannel?.deliver(intent)
    }

    override fun configureFlutterEngine(flutterEngine: FlutterEngine) {
        super.configureFlutterEngine(flutterEngine)
        engineExport?.attach(this)
        ExportWorker.onIdle = { releaseEngineWhenIdle() }
        attached = true
        scanChannel = ScanChannel(this, flutterEngine.dartExecutor.binaryMessenger, { releaseEngineWhenIdle() })
        val device = MethodChannel(flutterEngine.dartExecutor.binaryMessenger, CHANNEL)
        deviceChannel = device
        device.setMethodCallHandler { call, result ->
                when (call.method) {
                    "sdkInt" -> result.success(Build.VERSION.SDK_INT)
                    "pdfPageCount" -> {
                        val path = call.argument<String>("path")
                        if (path == null) {
                            result.error("bad_args", "path is required", null)
                        } else {
                            // Opening a large PDF can take a moment; keep it
                            // off the main thread.
                            try {
                                pdfExecutor.execute { countPages(path, result) }
                            } catch (e: RejectedExecutionException) {
                                // The activity is being destroyed.
                                result.error("corrupt", e.message, null)
                            }
                        }
                    }
                    else -> result.notImplemented()
                }
            }
    }

    /**
     * Runs on [pdfExecutor]. Any exception escaping a plain executor thread
     * kills the process, so every throwable becomes an error code, and the
     * reply goes to Flutter exactly once, on the main thread.
     */
    private fun countPages(path: String, result: MethodChannel.Result) {
        val replied = AtomicBoolean(false)
        fun reply(send: () -> Unit) {
            if (replied.compareAndSet(false, true)) mainHandler.post(send)
        }
        var fd: ParcelFileDescriptor? = null
        var renderer: PdfRenderer? = null
        try {
            fd = ParcelFileDescriptor.open(File(path), ParcelFileDescriptor.MODE_READ_ONLY)
            renderer = PdfRenderer(fd)
            val count = renderer.pageCount
            reply { result.success(count) }
        } catch (e: SecurityException) {
            // PdfRenderer throws this for password-protected files.
            reply { result.error("encrypted", e.message, null) }
        } catch (e: IOException) {
            reply { result.error("corrupt", e.message, null) }
        } catch (e: Throwable) {
            // IllegalArgumentException, OutOfMemoryError on a hostile file,
            // or anything else PdfRenderer surprises us with.
            reply { result.error("corrupt", e.message, null) }
        } finally {
            runCatching { renderer?.close() }
            runCatching { fd?.close() }
        }
    }

    // FlutterActivity is a plain Activity, not a ComponentActivity, so the
    // Activity Result API is not available; the classic callback is.
    override fun onActivityResult(requestCode: Int, resultCode: Int, data: Intent?) {
        if (engineExport?.onActivityResult(requestCode, resultCode, data) == true) return
        super.onActivityResult(requestCode, resultCode, data)
    }

    override fun cleanUpFlutterEngine(flutterEngine: FlutterEngine) {
        // Asked just before shouldDestroyEngineWithHost, as the Activity
        // detaches. The scan and export channels stay: Dart may still use
        // them. A Dart-side export keeps running without the Activity.
        keepEngine = ScanTrackingService.wanted || ExportWorker.isActive
        engineExport?.detach(this)
        val cache = FlutterEngineCache.getInstance()
        if (keepEngine) cache.put(RETAINED_ENGINE, flutterEngine) else cache.remove(RETAINED_ENGINE)
        deviceChannel?.setMethodCallHandler(null)
        deviceChannel = null
        attached = false
        super.cleanUpFlutterEngine(flutterEngine)
    }

    // Load-bearing: the default is false for a host-provided engine, so without this every engine built in provideFlutterEngine would leak.
    override fun shouldDestroyEngineWithHost(): Boolean = !keepEngine

    override fun onResume() {
        super.onResume()
        AppVisibility.resumed = true
        engineExport?.onResumed()
    }

    override fun onPause() {
        AppVisibility.resumed = false
        super.onPause()
    }

    override fun onDestroy() {
        pdfExecutor.shutdown()
        super.onDestroy()
    }

    private companion object {
        const val CHANNEL = "piyanota/device"
        const val RETAINED_ENGINE = "piyanota_scan_tracking"

        /** Gives the last scans' state a moment to be saved before the engine goes. */
        const val RELEASE_DELAY_MS = 5_000L

        /** An Activity has the engine; only touched on the main thread. */
        var attached = false

        /** The engine's export channel; one engine exists at a time. */
        var engineExport: ExportChannel? = null

        /**
         * Nothing is followed and no export runs any more. An engine kept alive past its
         * Activity is destroyed, so the next launch starts at Login as
         * usual, once Dart has had time to save the finished jobs.
         */
        fun releaseEngineWhenIdle() {
            Handler(Looper.getMainLooper()).postDelayed({
                if (attached || ScanTrackingService.wanted || ExportWorker.isActive) return@postDelayed
                val cache = FlutterEngineCache.getInstance()
                val engine = cache.get(RETAINED_ENGINE) ?: return@postDelayed
                cache.remove(RETAINED_ENGINE)
                engine.destroy()
            }, RELEASE_DELAY_MS)
        }
    }
}
