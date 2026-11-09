package com.piyanota.piyanota_application.export

import android.content.Context
import android.net.Uri
import android.os.Handler
import android.os.Looper
import android.provider.DocumentsContract
import android.system.ErrnoException
import android.system.OsConstants
import android.util.Log
import com.piyanota.piyanota_application.AppVisibility
import java.io.BufferedOutputStream
import java.io.File
import java.io.FileInputStream
import java.io.FileNotFoundException
import java.io.FileOutputStream
import java.io.IOException
import java.util.concurrent.ExecutorService
import java.util.concurrent.Executors
import java.util.concurrent.atomic.AtomicBoolean

/**
 * Owns the one export that may run (user decision 2026-10-22: an export
 * keeps going when the user leaves the app). Process-wide and tied only to
 * the application context, so the Activity and its Flutter engine can go
 * away mid-render and the file is still made and saved; [ExportJobService]
 * keeps the process in the foreground meanwhile, and the notifications say
 * how it went. [ExportChannel] only forwards Dart's calls here and, while
 * it is alive, passes progress back.
 *
 * An export has two halves:
 *  1. Dart's: `begin` (service and notification up), track downloads and
 *     the click, reported with [dartProgress];
 *  2. the device's: [run] renders and saves on the export thread. From
 *     here Dart is no longer needed.
 * A Dart half that never reaches [run] ends with [end], or with
 * [engineGone] when the engine died during it.
 *
 * Every method here is called on the main thread; only the render and
 * save run on [executor].
 */
internal object ExportWorker {
    /** Talks back to Dart while an engine is attached. */
    interface Listener {
        fun onRenderProgress(fraction: Double)
        fun onSaveProgress(fraction: Double)

        /** The notification's Cancel was pressed. */
        fun onCancelRequested()
    }

    private class Job(val notice: ExportNotice) {
        /** The user's Cancel, from the app or the notification. */
        val cancelled = AtomicBoolean(false)

        /** Android's foreground-service time limit ran out (API 35+). */
        val timedOut = AtomicBoolean(false)

        /** Logout: end without a word ([stopAll]). */
        var forgotten = false
        var handedOff = false
        var finished = false
        val throttle = PercentThrottle()
        val stopRequested: () -> Boolean = { cancelled.get() || timedOut.get() }
    }

    private const val TAG = "PiyaNotaExport"
    private const val MP3_MIME = "audio/mpeg"
    private const val COPY_BUFFER_BYTES = 64 * 1024
    private const val PRIMARY_VOLUME = "primary"
    private const val INTERNAL_STORAGE_LABEL = "Internal storage"
    private const val SD_CARD_LABEL = "SD card"

    private val main = Handler(Looper.getMainLooper())

    /** Never shut down: it lives as long as the process. */
    private val executor: ExecutorService = Executors.newSingleThreadExecutor()

    private var job: Job? = null
    var listener: Listener? = null

    /**
     * Called on the main thread once no export runs any more, so
     * MainActivity can let go of an engine it kept only for this one.
     */
    var onIdle: (() -> Unit)? = null

    /** The running service, so a finished export can stop it. */
    var service: ExportJobService? = null

    /** An export is running (either half). */
    val isActive: Boolean get() = job?.let { !it.finished } ?: false

    /** The running export's words, for the service's notification. */
    fun currentNotice(): ExportNotice? = job?.takeIf { !it.finished }?.notice

    fun currentPercent(): Int = job?.throttle?.last?.coerceAtLeast(0) ?: 0

    /**
     * Starts an export's notification and foreground service. Fails with
     * [ExportChannel.BUSY] while an earlier export is still being made on
     * the device: one whose app was closed, so this app's Dart side no
     * longer knows of it.
     */
    fun begin(context: Context, notice: ExportNotice): String? {
        val current = job
        if (current != null && !current.finished) {
            if (current.handedOff) return ExportChannel.BUSY
            // A Dart half this engine never ended: replaced quietly.
            current.forgotten = true
            current.cancelled.set(true)
            current.finished = true
        }
        val next = Job(notice)
        job = next
        ExportNotifications.updateProgress(context, notice, next.throttle.next(0.0) ?: 0)
        ExportJobService.start(context)
        return null
    }

    /** The overall bar while Dart downloads and writes the click. */
    fun dartProgress(context: Context, fraction: Double) {
        val current = job ?: return
        if (current.finished || current.handedOff) return
        current.throttle.next(fraction)?.let {
            ExportNotifications.updateProgress(context, current.notice, it)
        }
    }

    fun cancel() {
        job?.cancelled?.set(true)
    }

    /** The notification's Cancel. */
    fun cancelFromNotification(context: Context) {
        val current = job ?: return
        if (current.finished) return
        current.cancelled.set(true)
        val dart = listener
        if (dart != null) {
            dart.onCancelRequested()
        } else if (!current.handedOff) {
            // No Dart left to end its half.
            finish(context, current, ExportOutcome.CANCELLED)
        }
    }

    /** Android's time limit for the service ran out (API 35+). */
    fun timedOut(context: Context) {
        val current = job ?: return
        if (current.finished) return
        current.timedOut.set(true)
        if (!current.handedOff) finish(context, current, ExportOutcome.FAILED, ExportChannel.INTERRUPTED)
    }

    /** Dart's half ended without [run]: a failure or a cancel. */
    fun end(context: Context, outcome: ExportOutcome, code: String?) {
        val current = job ?: return
        if (current.finished || current.handedOff) return
        finish(context, current, outcome, code)
    }

    /**
     * The engine died. A Dart half can no longer finish, so it ends as
     * interrupted; a handed-off export carries on regardless.
     */
    fun engineGone(context: Context) {
        listener = null
        val current = job ?: return
        if (!current.finished && !current.handedOff) {
            finish(context, current, ExportOutcome.FAILED, ExportChannel.INTERRUPTED)
        }
    }

    /** Logout (H1): stop whatever runs, show nothing, leave no notification. */
    fun stopAll(context: Context) {
        job?.let {
            it.forgotten = true
            it.cancelled.set(true)
            it.finished = true
        }
        ExportNotifications.cancelAll(context)
        stopService()
        onIdle?.invoke()
    }

    /** The device's half: render, then save. [reply] gets the outcome once. */
    fun run(context: Context, args: RunArgs, reply: (Result<Map<String, String>>) -> Unit) {
        val current = job
        if (current == null || current.finished) {
            // A Dart side calling run without begin, or after a logout.
            reply(Result.failure(ExportCancelled()))
            return
        }
        current.handedOff = true
        val app = context.applicationContext
        val report = { saving: Boolean, fraction: Double ->
            val overall = ExportNotices.overall(args.from, args.renderShare, args.saveShare, saving, fraction)
            main.post {
                if (current.finished) return@post
                current.throttle.next(overall)?.let { ExportNotifications.updateProgress(app, current.notice, it) }
                val dart = listener
                if (saving) dart?.onSaveProgress(fraction) else dart?.onRenderProgress(fraction)
            }
        }
        executor.execute {
            val outcome = runCatching {
                render(args.inputs, args.speed, File(args.outPath), current.stopRequested) { report(false, it) }
                save(app, args.tree, args.fileName, File(args.outPath), current.stopRequested) { report(true, it) }
            }
            // The device's own copy of the work folder clean-up, for when
            // Dart is gone; Dart's is then a no-op.
            if (isInside(args.workDir, app.cacheDir.absolutePath)) {
                runCatching { File(args.workDir).deleteRecursively() }
            }
            main.post {
                val code = outcome.exceptionOrNull()?.let { errorCode(it, current) }
                if (!current.finished) {
                    when {
                        outcome.isSuccess -> {
                            val saved = outcome.getOrThrow()
                            finish(
                                app,
                                current,
                                ExportOutcome.SAVED,
                                fileName = saved["fileName"],
                                folder = saved["location"],
                                tree = args.tree,
                            )
                        }
                        code == ExportChannel.CANCELLED || code == ExportChannel.CANCELLED_PARTIAL ->
                            finish(app, current, ExportOutcome.CANCELLED)
                        else -> finish(app, current, ExportOutcome.FAILED, code)
                    }
                }
                reply(
                    outcome.fold(
                        { Result.success(it) },
                        { Result.failure(CodedFailure(code ?: ExportChannel.GENERATION_FAILED, it)) },
                    ),
                )
            }
        }
    }

    private fun finish(
        context: Context,
        current: Job,
        outcome: ExportOutcome,
        code: String? = null,
        fileName: String? = null,
        folder: String? = null,
        tree: Uri? = null,
    ) {
        current.finished = true
        if (job === current) job = null
        // The progress notification goes whatever happens.
        ExportNotifications.cancelProgress(context)
        if (ExportNotices.postsResult(current.forgotten, listener != null, AppVisibility.visible)) {
            ExportNotices.result(current.notice, outcome, code, fileName, folder)?.let {
                ExportNotifications.postResult(context, it, tree)
            }
        }
        stopService()
        onIdle?.invoke()
    }

    private fun stopService() {
        service?.stopNow()
    }

    /** Folder contents, for the clash check (AC15). Runs on the caller's executor. */
    fun listNames(context: Context, tree: Uri): List<String> {
        val children = DocumentsContract.buildChildDocumentsUriUsingTree(
            tree,
            DocumentsContract.getTreeDocumentId(tree),
        )
        val names = mutableListOf<String>()
        context.contentResolver.query(
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

    /**
     * Decodes each input to a temp PCM file, time-stretches each one
     * separately (pitch kept, as Playback does per player), mixes with the
     * gains and encodes one MP3 (AC13, AC23). Temp space is the decoded
     * files plus the MP3, whatever the speed.
     */
    private fun render(
        inputs: List<Pair<File, Float>>,
        speed: Double,
        out: File,
        stopRequested: () -> Boolean,
        report: (Double) -> Unit,
    ) {
        // Before any decoding: a build without LAME would otherwise spend
        // the whole decode before failing.
        Mp3Encoder.ensureLoaded()
        val decoded = mutableListOf<File>()
        var complete = false
        val progress = RenderProgress(report)
        try {
            progress.begin(RenderProgress.DECODE, inputs.sumOf { (src, _) -> PcmDecoder.estimateFrames(src) })
            val mixInputs = inputs.map { (src, gain) ->
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

    private fun save(
        context: Context,
        tree: Uri,
        fileName: String,
        src: File,
        stopRequested: () -> Boolean,
        report: (Double) -> Unit,
    ): Map<String, String> {
        if (stopRequested()) throw ExportCancelled()
        val resolver = context.contentResolver
        val parent = DocumentsContract.buildDocumentUriUsingTree(tree, DocumentsContract.getTreeDocumentId(tree))
        val doc = folderStep { DocumentsContract.createDocument(resolver, parent, MP3_MIME, fileName) }
            ?: throw SecurityException("the folder refused a new file")
        try {
            val stream = folderStep { resolver.openOutputStream(doc, "w") }
                ?: throw SecurityException("the folder refused writing")
            val progress = CopyProgress(src.length(), report)
            stream.use { o ->
                FileInputStream(src).use { i ->
                    val buf = ByteArray(COPY_BUFFER_BYTES)
                    while (true) {
                        if (stopRequested()) throw ExportCancelled()
                        val n = i.read(buf)
                        if (n < 0) break
                        o.write(buf, 0, n)
                        progress.advance(n.toLong())
                    }
                }
            }
            progress.finish()
        } catch (e: Throwable) {
            // Leave no partial file in the user's folder (AC18).
            val removed = runCatching { DocumentsContract.deleteDocument(resolver, doc) }
                .onFailure { Log.w(TAG, "could not remove partial export", it) }
                .getOrDefault(false)
            // A cancel normally reads "Nothing was saved"; that must not be
            // said while part of the file is still in the folder.
            if (!removed && e is ExportCancelled) throw PartialFileLeft(e)
            throw e
        }
        // A provider may rename on its own; report the name it really used.
        // The file is already saved, so a failing lookup must not turn
        // that into an error: fall back to the name asked for.
        val savedName = runCatching {
            resolver.query(doc, arrayOf(DocumentsContract.Document.COLUMN_DISPLAY_NAME), null, null, null)
                ?.use { c -> if (c.moveToFirst()) c.getString(0) else null }
        }.onFailure { Log.w(TAG, "saved file name not readable", it) }.getOrNull() ?: fileName
        return mapOf("fileName" to savedName, "location" to describeLocation(context, tree))
    }

    /**
     * A folder that was deleted or unmounted (SD card or USB drive out)
     * since it was picked makes SAF throw FileNotFoundException. That is
     * the folder's fault, not the audio's, so it becomes [FolderGone] and
     * is reported as permission_denied, which makes Retry ask for a folder
     * again. The cause is kept so a full disk still reads as storage_full.
     */
    private fun <T> folderStep(step: () -> T): T = try {
        step()
    } catch (e: FileNotFoundException) {
        throw FolderGone(e)
    }

    /**
     * A readable folder path for the success dialog. External storage tree
     * ids look like "primary:Music/PiyaNota" or "1A2B-3C4D:Songs" (an SD
     * card or a USB drive, which the id does not tell apart). The Downloads
     * provider has opaque ids, so it falls back to the folder's name.
     */
    private fun describeLocation(context: Context, tree: Uri): String {
        val id = DocumentsContract.getTreeDocumentId(tree)
        if (tree.authority == LocalFolders.EXTERNAL_STORAGE) {
            val volume = id.substringBefore(':')
            val path = id.substringAfter(':', "")
            val root = if (volume == PRIMARY_VOLUME) INTERNAL_STORAGE_LABEL else SD_CARD_LABEL
            return if (path.isEmpty()) root else "$root/$path"
        }
        val doc = DocumentsContract.buildDocumentUriUsingTree(tree, id)
        return runCatching {
            context.contentResolver.query(
                doc,
                arrayOf(DocumentsContract.Document.COLUMN_DISPLAY_NAME),
                null,
                null,
                null,
            )?.use { c -> if (c.moveToFirst()) c.getString(0) else null }
        }.getOrNull() ?: id
    }

    private fun errorCode(e: Throwable, current: Job): String = when {
        // A time-out stop is not something the user chose.
        current.timedOut.get() && (e is ExportCancelled || e is PartialFileLeft) -> ExportChannel.INTERRUPTED
        e is PartialFileLeft -> ExportChannel.CANCELLED_PARTIAL
        e is ExportCancelled -> ExportChannel.CANCELLED
        e is InterruptedException -> ExportChannel.INTERRUPTED
        isOutOfSpace(e) -> ExportChannel.STORAGE_FULL
        e is SecurityException || e is FolderGone -> ExportChannel.PERMISSION_DENIED
        // An unreadable or missing folder surfaces as this from SAF.
        e is IllegalArgumentException && e.message?.contains("tree", ignoreCase = true) == true ->
            ExportChannel.PERMISSION_DENIED
        else -> ExportChannel.GENERATION_FAILED
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

    /** Everything `run` needs, read from the channel call. */
    class RunArgs(
        val inputs: List<Pair<File, Float>>,
        val speed: Double,
        val outPath: String,
        val workDir: String,
        val tree: Uri,
        val fileName: String,
        val from: Double,
        val renderShare: Double,
        val saveShare: Double,
    )

    /** A failed run with its channel error code. */
    class CodedFailure(val code: String, cause: Throwable) : Exception(cause.message, cause)

    /** See [folderStep]. */
    private class FolderGone(cause: FileNotFoundException) : IOException(cause.message, cause)

    /** A cancelled save whose partial file could not be deleted (L8). */
    private class PartialFileLeft(cause: ExportCancelled) : IOException(cause.message, cause)
}
