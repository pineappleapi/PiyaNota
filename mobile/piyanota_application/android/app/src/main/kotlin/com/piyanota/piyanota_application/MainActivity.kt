package com.piyanota.piyanota_application

import android.graphics.pdf.PdfRenderer
import android.os.Build
import android.os.Handler
import android.os.Looper
import android.os.ParcelFileDescriptor
import io.flutter.embedding.android.FlutterActivity
import io.flutter.embedding.engine.FlutterEngine
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
 */
class MainActivity : FlutterActivity() {
    private val pdfExecutor = Executors.newSingleThreadExecutor()
    private val mainHandler = Handler(Looper.getMainLooper())

    override fun configureFlutterEngine(flutterEngine: FlutterEngine) {
        super.configureFlutterEngine(flutterEngine)
        MethodChannel(flutterEngine.dartExecutor.binaryMessenger, CHANNEL)
            .setMethodCallHandler { call, result ->
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

    override fun onDestroy() {
        pdfExecutor.shutdown()
        super.onDestroy()
    }

    private companion object {
        const val CHANNEL = "piyanota/device"
    }
}
