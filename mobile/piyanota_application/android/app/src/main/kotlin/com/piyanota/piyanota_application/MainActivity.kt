package com.piyanota.piyanota_application

import android.graphics.pdf.PdfRenderer
import android.os.Build
import android.os.ParcelFileDescriptor
import io.flutter.embedding.android.FlutterActivity
import io.flutter.embedding.engine.FlutterEngine
import io.flutter.plugin.common.MethodChannel
import java.io.File
import java.io.IOException
import java.util.concurrent.Executors

/**
 * Hosts the small "piyanota/device" channel used by Capture (PIYA-206):
 *  - sdkInt: decides whether the gallery needs a storage permission
 *    (Android 12L and older) or uses the permission-less photo picker.
 *  - pdfPageCount: counts pages with the platform PdfRenderer, so a PDF over
 *    20 pages is rejected before upload (AC6) without a Dart PDF parser.
 */
class MainActivity : FlutterActivity() {
    private val pdfExecutor = Executors.newSingleThreadExecutor()

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
                            pdfExecutor.execute { countPages(path, result) }
                        }
                    }
                    else -> result.notImplemented()
                }
            }
    }

    private fun countPages(path: String, result: MethodChannel.Result) {
        var fd: ParcelFileDescriptor? = null
        var renderer: PdfRenderer? = null
        try {
            fd = ParcelFileDescriptor.open(File(path), ParcelFileDescriptor.MODE_READ_ONLY)
            renderer = PdfRenderer(fd)
            val count = renderer.pageCount
            runOnUiThread { result.success(count) }
        } catch (e: SecurityException) {
            // PdfRenderer throws this for password-protected files.
            runOnUiThread { result.error("encrypted", e.message, null) }
        } catch (e: IOException) {
            runOnUiThread { result.error("corrupt", e.message, null) }
        } catch (e: IllegalArgumentException) {
            runOnUiThread { result.error("corrupt", e.message, null) }
        } finally {
            renderer?.close()
            fd?.close()
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
