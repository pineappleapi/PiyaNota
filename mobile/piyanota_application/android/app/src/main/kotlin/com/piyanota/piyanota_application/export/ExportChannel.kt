package com.piyanota.piyanota_application.export

import android.app.Activity
import android.content.ActivityNotFoundException
import android.content.Intent
import android.net.Uri
import android.os.Handler
import android.os.Looper
import android.provider.DocumentsContract
import android.system.ErrnoException
import android.system.OsConstants
import android.util.Log
import io.flutter.plugin.common.BinaryMessenger
import io.flutter.plugin.common.MethodCall
import io.flutter.plugin.common.MethodChannel
import java.io.BufferedOutputStream
import java.io.File
import java.io.FileInputStream
import java.io.FileNotFoundException
import java.io.FileOutputStream
import java.io.IOException
import java.util.concurrent.ExecutorService
import java.util.concurrent.Executors
import java.util.concurrent.RejectedExecutionException
import java.util.concurrent.atomic.AtomicBoolean

/**
 * The "piyanota/export" channel behind the Export Audio modal (PIYA-211).
 *
 * Methods:
 *  - pickFolder() -> tree Uri string, or null when cancelled (AC10, AC11).
 *    The permission is persisted so Open folder works afterwards.
 *  - listNames({treeUri}) -> display names already in that folder (AC15).
 *  - render({inputs: [{path, gain}], speed, outPath}) -> null. Decodes
 *    each input to a temp PCM file, time-stretches each one separately
 *    (pitch kept, as Playback does per player) in memory, mixes with the
 *    gains and encodes one MP3 (AC13, AC23). Temp space is the decoded
 *    files plus the MP3, whatever the speed: no stretched copy is kept.
 *    Dart sends only the ticked tracks (user decision 2026-10-21), so
 *    nothing unticked is decoded or stretched. While it runs, this side
 *    calls Dart's "progress" with the render's 0..1 ([RenderProgress]).
 *  - cancel() -> null. Stops the running render or save; its reply
 *    becomes `cancelled` and the partial MP3 (or saved file) is deleted.
 *  - save({treeUri, fileName, srcPath}) -> {fileName, location} (AC16).
 *  - openFolder({treeUri}) -> whether a file manager could be opened.
 *
 * Error codes match the Dart ExportFailure types (AC18): storage_full,
 * permission_denied, generation_failed, interrupted, cancelled,
 * no_folder_picker, plus bad_args.
 */
internal class ExportChannel(private val activity: Activity, messenger: BinaryMessenger) {
    private val channel = MethodChannel(messenger, CHANNEL)
    private val executor: ExecutorService = Executors.newSingleThreadExecutor()
    private val mainHandler = Handler(Looper.getMainLooper())

    /**
     * The user's Cancel. Reset when a render starts, on the main thread
     * before the work is queued: channel calls arrive in order, so a
     * cancel sent after that render is never wiped, and one left over
     * from an earlier export never stops this one.
     */
    private val cancelled = AtomicBoolean(false)

    /** The activity is going away; never reset. */
    private val disposed = AtomicBoolean(false)
    private val stopRequested: () -> Boolean = { cancelled.get() || disposed.get() }
    private var pendingPick: MethodChannel.Result? = null

    init {
        channel.setMethodCallHandler { call, result -> handle(call, result) }
    }

    private fun handle(call: MethodCall, result: MethodChannel.Result) {
        when (call.method) {
            "pickFolder" -> pickFolder(result)
            "openFolder" -> {
                val tree = call.argument<String>("treeUri")
                if (tree == null) badArgs(result, "treeUri") else result.success(openFolder(Uri.parse(tree)))
            }
            "listNames" -> {
                val tree = call.argument<String>("treeUri")
                    ?: return badArgs(result, "treeUri")
                runOffMain(result) { listNames(Uri.parse(tree)) }
            }
            "render" -> {
                val inputs = call.argument<List<Map<String, Any?>>>("inputs")
                val speed = call.argument<Double>("speed")
                val outPath = call.argument<String>("outPath")
                // Dart never sends an empty job; refusing one here keeps an
                // empty MP3 from ever being saved as a success.
                if (inputs.isNullOrEmpty() || speed == null || speed <= 0 || outPath == null) {
                    return badArgs(result, "non-empty inputs, speed > 0 and outPath")
                }
                cancelled.set(false)
                runOffMain(result) {
                    render(inputs, speed, File(outPath))
                    null
                }
            }
            "cancel" -> {
                cancelled.set(true)
                result.success(null)
            }
            "save" -> {
                val tree = call.argument<String>("treeUri")
                val name = call.argument<String>("fileName")
                val src = call.argument<String>("srcPath")
                if (tree == null || name == null || src == null) {
                    return badArgs(result, "treeUri, fileName and srcPath")
                }
                runOffMain(result) { save(Uri.parse(tree), name, File(src)) }
            }
            else -> result.notImplemented()
        }
    }

    // ---- Folder picking -------------------------------------------------

    private fun pickFolder(result: MethodChannel.Result) {
        if (pendingPick != null) {
            // The sheet is busy while picking, so a second call is a bug;
            // fail it rather than orphaning the first reply.
            result.error("bad_args", "a folder pick is already open", null)
            return
        }
        val intent = Intent(Intent.ACTION_OPEN_DOCUMENT_TREE).addFlags(
            Intent.FLAG_GRANT_READ_URI_PERMISSION or
                Intent.FLAG_GRANT_WRITE_URI_PERMISSION or
                Intent.FLAG_GRANT_PERSISTABLE_URI_PERMISSION,
        )
        try {
            pendingPick = result
            activity.startActivityForResult(intent, PICK_FOLDER_REQUEST)
        } catch (e: ActivityNotFoundException) {
            // Some stripped-down ROMs ship without a documents UI. Its own
            // code: "choose another folder" cannot help here.
            pendingPick = null
            result.error(NO_FOLDER_PICKER, "no folder picker on this device", null)
        }
    }

    /** Called from MainActivity.onActivityResult; true when consumed. */
    fun onActivityResult(requestCode: Int, resultCode: Int, data: Intent?): Boolean {
        if (requestCode != PICK_FOLDER_REQUEST) return false
        val result = pendingPick ?: return true
        pendingPick = null
        val tree = data?.data
        if (resultCode != Activity.RESULT_OK || tree == null) {
            result.success(null)
            return true
        }
        try {
            activity.contentResolver.takePersistableUriPermission(
                tree,
                Intent.FLAG_GRANT_READ_URI_PERMISSION or Intent.FLAG_GRANT_WRITE_URI_PERMISSION,
            )
        } catch (e: SecurityException) {
            // The provider handed back a folder it will not let us keep.
            // Saving may still work this once, so carry on and let save()
            // report permission_denied if it does not.
            Log.w(TAG, "could not persist folder permission", e)
        }
        result.success(tree.toString())
        return true
    }

    private fun openFolder(tree: Uri): Boolean {
        val doc = DocumentsContract.buildDocumentUriUsingTree(tree, DocumentsContract.getTreeDocumentId(tree))
        val intent = Intent(Intent.ACTION_VIEW)
            .setDataAndType(doc, DocumentsContract.Document.MIME_TYPE_DIR)
            .addFlags(Intent.FLAG_GRANT_READ_URI_PERMISSION or Intent.FLAG_ACTIVITY_NEW_TASK)
        return try {
            activity.startActivity(intent)
            true
        } catch (e: ActivityNotFoundException) {
            // No file manager handles folders here; Dart hides the button.
            Log.i(TAG, "no activity opens a folder", e)
            false
        } catch (e: SecurityException) {
            Log.w(TAG, "folder permission lost", e)
            false
        }
    }

    // ---- Work off the main thread --------------------------------------

    private fun listNames(tree: Uri): List<String> {
        val children = DocumentsContract.buildChildDocumentsUriUsingTree(
            tree,
            DocumentsContract.getTreeDocumentId(tree),
        )
        val names = mutableListOf<String>()
        activity.contentResolver.query(
            children,
            arrayOf(DocumentsContract.Document.COLUMN_DISPLAY_NAME),
            null,
            null,
            null,
        )?.use { c ->
            while (c.moveToNext()) c.getString(0)?.let(names::add)
        }
        return names
    }

    private fun render(inputs: List<Map<String, Any?>>, speed: Double, out: File) {
        // Before any decoding: a build without LAME would otherwise spend
        // the whole decode before failing.
        Mp3Encoder.ensureLoaded()
        val decoded = mutableListOf<File>()
        var complete = false
        val progress = RenderProgress(::sendProgress)
        try {
            val specs = inputs.map { spec ->
                val path = spec["path"] as? String ?: throw IllegalArgumentException("input path")
                val gain = (spec["gain"] as? Number)?.toFloat() ?: throw IllegalArgumentException("input gain")
                File(path) to gain
            }
            progress.begin(RenderProgress.DECODE, specs.sumOf { (src, _) -> PcmDecoder.estimateFrames(src) })
            val mixInputs = specs.map { (src, gain) ->
                val pcm = File.createTempFile("export_pcm", ".raw", out.parentFile)
                decoded += pcm
                PcmDecoder.decode(src, pcm, progress::advance, stopRequested)
                MixInput(pcm, gain)
            }
            BufferedOutputStream(FileOutputStream(out)).use { stream ->
                Mp3Encoder(PcmDecoder.OUT_RATE, PcmDecoder.OUT_CHANNELS, stream).use { encoder ->
                    Mixer.mix(mixInputs, speed, encoder::encode, progress, stopRequested)
                    encoder.finish()
                }
            }
            progress.finish()
            complete = true
        } finally {
            decoded.forEach { it.delete() }
            // A half-written MP3 must never be mistaken for a result.
            if (!complete) out.delete()
        }
    }

    /** Called on the export thread; the channel must be used on main. */
    private fun sendProgress(fraction: Double) {
        mainHandler.post {
            if (!disposed.get()) channel.invokeMethod(PROGRESS, fraction)
        }
    }

    private fun save(tree: Uri, fileName: String, src: File): Map<String, String> {
        val resolver = activity.contentResolver
        val parent = DocumentsContract.buildDocumentUriUsingTree(tree, DocumentsContract.getTreeDocumentId(tree))
        val doc = folderStep { DocumentsContract.createDocument(resolver, parent, MP3_MIME, fileName) }
            ?: throw SecurityException("the folder refused a new file")
        var complete = false
        try {
            val stream = folderStep { resolver.openOutputStream(doc, "w") }
                ?: throw SecurityException("the folder refused writing")
            stream.use { o ->
                FileInputStream(src).use { i ->
                    val buf = ByteArray(COPY_BUFFER_BYTES)
                    while (true) {
                        if (stopRequested()) throw ExportCancelled()
                        val n = i.read(buf)
                        if (n < 0) break
                        o.write(buf, 0, n)
                    }
                }
            }
            complete = true
        } finally {
            if (!complete) {
                // Leave no partial file in the user's folder (AC18).
                runCatching { DocumentsContract.deleteDocument(resolver, doc) }
                    .onFailure { Log.w(TAG, "could not remove partial export", it) }
            }
        }
        // A provider may rename on its own; report the name it really used.
        // The file is already saved, so a failing lookup must not turn
        // that into an error: fall back to the name asked for.
        val savedName = runCatching {
            resolver.query(doc, arrayOf(DocumentsContract.Document.COLUMN_DISPLAY_NAME), null, null, null)
                ?.use { c -> if (c.moveToFirst()) c.getString(0) else null }
        }.onFailure { Log.w(TAG, "saved file name not readable", it) }.getOrNull() ?: fileName
        return mapOf("fileName" to savedName, "location" to describeLocation(tree))
    }

    /**
     * A folder that was deleted or unmounted (SD card out) since it was
     * picked makes SAF throw FileNotFoundException. That is the folder's
     * fault, not the audio's, so it becomes [FolderGone] and is reported
     * as permission_denied, which makes Retry ask for a folder again. The
     * cause is kept so a full disk still reads as storage_full.
     */
    private fun <T> folderStep(step: () -> T): T = try {
        step()
    } catch (e: FileNotFoundException) {
        throw FolderGone(e)
    }

    /**
     * A readable folder path for the success dialog. External storage tree
     * ids look like "primary:Music/PiyaNota" or "1A2B-3C4D:Songs"; other
     * providers (Drive, Downloads) have opaque ids, so those fall back to
     * the folder's display name.
     */
    private fun describeLocation(tree: Uri): String {
        val id = DocumentsContract.getTreeDocumentId(tree)
        if (tree.authority == EXTERNAL_STORAGE_AUTHORITY) {
            val volume = id.substringBefore(':')
            val path = id.substringAfter(':', "")
            val root = if (volume == PRIMARY_VOLUME) INTERNAL_STORAGE_LABEL else SD_CARD_LABEL
            return if (path.isEmpty()) root else "$root/$path"
        }
        val doc = DocumentsContract.buildDocumentUriUsingTree(tree, id)
        return runCatching {
            activity.contentResolver.query(
                doc,
                arrayOf(DocumentsContract.Document.COLUMN_DISPLAY_NAME),
                null,
                null,
                null,
            )?.use { c -> if (c.moveToFirst()) c.getString(0) else null }
        }.getOrNull() ?: id
    }

    /**
     * Runs [work] on the export thread. Any throwable escaping a plain
     * executor thread kills the process, so each becomes an error code, and
     * the reply goes to Flutter exactly once, on the main thread.
     */
    private fun runOffMain(result: MethodChannel.Result, work: () -> Any?) {
        val replied = AtomicBoolean(false)
        fun reply(send: () -> Unit) {
            if (replied.compareAndSet(false, true)) mainHandler.post(send)
        }
        try {
            executor.execute {
                try {
                    val value = work()
                    reply { result.success(value) }
                } catch (e: Throwable) {
                    val code = errorCode(e)
                    Log.w(TAG, "export step failed: $code", e)
                    reply { result.error(code, e.message, null) }
                }
            }
        } catch (e: RejectedExecutionException) {
            // The activity is being destroyed.
            result.error(INTERRUPTED, e.message, null)
        }
    }

    private fun errorCode(e: Throwable): String = when {
        // Read when the error is reported: a dispose during a user's
        // cancel is still an interruption, not something they chose.
        e is ExportCancelled && !disposed.get() && cancelled.get() -> CANCELLED
        e is ExportCancelled || e is InterruptedException -> INTERRUPTED
        isOutOfSpace(e) -> STORAGE_FULL
        e is SecurityException || e is FolderGone -> PERMISSION_DENIED
        // An unreadable or missing folder surfaces as this from SAF.
        e is IllegalArgumentException && e.message?.contains("tree", ignoreCase = true) == true -> PERMISSION_DENIED
        else -> GENERATION_FAILED
    }

    private fun isOutOfSpace(e: Throwable): Boolean {
        var t: Throwable? = e
        while (t != null) {
            if (t is ErrnoException && t.errno == OsConstants.ENOSPC) return true
            // SAF providers rethrow ENOSPC as a plain IOException with the
            // errno text only.
            if (t is IOException && t.message?.let { "ENOSPC" in it || "No space left" in it } == true) return true
            t = t.cause
        }
        return false
    }

    private fun badArgs(result: MethodChannel.Result, what: String) =
        result.error("bad_args", "$what required", null)

    /** Stops any running export; its reply becomes `interrupted` (AC18). */
    fun dispose() {
        disposed.set(true)
        channel.setMethodCallHandler(null)
        executor.shutdown()
        pendingPick?.success(null)
        pendingPick = null
    }

    companion object {
        const val CHANNEL = "piyanota/export"
        private const val TAG = "PiyaNotaExport"
        private const val PICK_FOLDER_REQUEST = 0x5049 // "PI"
        private const val MP3_MIME = "audio/mpeg"
        private const val COPY_BUFFER_BYTES = 64 * 1024
        private const val EXTERNAL_STORAGE_AUTHORITY = "com.android.externalstorage.documents"
        private const val PRIMARY_VOLUME = "primary"
        private const val INTERNAL_STORAGE_LABEL = "Internal storage"
        private const val SD_CARD_LABEL = "SD card"

        const val STORAGE_FULL = "storage_full"
        const val PERMISSION_DENIED = "permission_denied"
        const val GENERATION_FAILED = "generation_failed"
        const val INTERRUPTED = "interrupted"
        const val CANCELLED = "cancelled"
        private const val PROGRESS = "progress"
        const val NO_FOLDER_PICKER = "no_folder_picker"
    }

    /** See [folderStep]. */
    private class FolderGone(cause: FileNotFoundException) : IOException(cause.message, cause)
}
