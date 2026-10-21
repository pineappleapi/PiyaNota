package com.piyanota.piyanota_application.export

import android.app.Activity
import android.content.ActivityNotFoundException
import android.content.Intent
import android.net.Uri
import android.os.Build
import android.os.Handler
import android.os.Looper
import android.provider.DocumentsContract
import android.util.Log
import io.flutter.plugin.common.BinaryMessenger
import io.flutter.plugin.common.MethodCall
import io.flutter.plugin.common.MethodChannel
import java.io.File
import java.util.concurrent.ExecutorService
import java.util.concurrent.Executors
import java.util.concurrent.RejectedExecutionException

/**
 * The "piyanota/export" channel behind the Export Audio modal (PIYA-211).
 * It only binds Dart to [ExportWorker], which owns the export so it keeps
 * going when the user leaves the app (user decision 2026-10-22).
 *
 * Methods:
 *  - pickFolder({keep}) -> tree Uri string, or null when cancelled (AC10,
 *    AC11). The permission is persisted so Open folder works afterwards,
 *    and every other persisted folder grant not in `keep` is released.
 *    Only a folder on this phone is accepted ([LocalFolders]); anything
 *    else fails with `not_local_folder` and nothing is persisted. There is
 *    no share action anywhere in the export flow.
 *  - releaseFolder({treeUri}) -> null. Gives back a folder grant Dart
 *    refused or no longer needs.
 *  - listNames({treeUri}) -> display names already in that folder (AC15).
 *  - begin({notice}) -> null. Starts the foreground service and the
 *    "Exporting <title>… 0%" notification. Fails with `busy` while an
 *    export started before the app was closed is still being made.
 *  - notifyProgress({fraction}) -> null. The overall bar while Dart
 *    downloads tracks and writes the click.
 *  - run({inputs: [{path, gain}], speed, outPath, workDir, treeUri,
 *    fileName, from, renderShare, saveShare}) -> {fileName, location}.
 *    Renders one MP3 (AC13, AC23) and saves it (AC16) on the device; from
 *    here the export no longer needs Dart. Calls Dart's "progress" with the
 *    render's 0..1 and "saveProgress" with the copy's 0..1 while it can.
 *    Ends the notification as "Saved…" or the failure.
 *  - end({outcome, code}) -> null. Dart's half failed or was cancelled
 *    before `run`.
 *  - cancel() -> null. Stops the running render or save; its reply becomes
 *    `cancelled` and the partial MP3 (or saved file) is deleted.
 *  - stopAll() -> null. Logout: stops any export and removes its
 *    notifications without a word.
 *  - openFolder({treeUri}) -> whether a file manager could be opened.
 * Native -> Dart: progress, saveProgress, cancelRequested (the
 * notification's Cancel).
 *
 * Error codes match the Dart ExportFailure types (AC18): storage_full,
 * permission_denied, generation_failed, interrupted, cancelled,
 * no_folder_picker, not_local_folder, cancelled_partial (a cancelled save
 * whose partial file could not be removed), busy, plus bad_args.
 */
internal class ExportChannel(private val activity: Activity, messenger: BinaryMessenger) :
    ExportWorker.Listener {
    private val channel = MethodChannel(messenger, CHANNEL)
    private val app = activity.applicationContext

    /** Only for listNames; the render and save run on the worker's thread. */
    private val executor: ExecutorService = Executors.newSingleThreadExecutor()
    private val mainHandler = Handler(Looper.getMainLooper())
    private var disposed = false
    private var pendingPick: PendingPick? = null

    private class PendingPick(val result: MethodChannel.Result, val keep: Set<String>)

    init {
        channel.setMethodCallHandler { call, result -> handle(call, result) }
        ExportWorker.listener = this
    }

    private fun handle(call: MethodCall, result: MethodChannel.Result) {
        when (call.method) {
            "pickFolder" -> pickFolder(call.argument<List<String>>("keep").orEmpty().toSet(), result)
            "releaseFolder" -> {
                val tree = call.argument<String>("treeUri") ?: return badArgs(result, "treeUri")
                release(listOf(tree))
                result.success(null)
            }
            "openFolder" -> {
                val tree = call.argument<String>("treeUri")
                if (tree == null) badArgs(result, "treeUri") else result.success(openFolder(Uri.parse(tree)))
            }
            "listNames" -> {
                val tree = call.argument<String>("treeUri")
                    ?: return badArgs(result, "treeUri")
                listNames(Uri.parse(tree), result)
            }
            "begin" -> {
                val notice = ExportNotice.fromMap(call.argument<Map<String, Any?>>("notice"))
                    ?: return badArgs(result, "notice")
                val refused = ExportWorker.begin(app, notice)
                if (refused != null) {
                    result.error(refused, "an earlier export is still being made", null)
                } else {
                    result.success(null)
                }
            }
            "notifyProgress" -> {
                call.argument<Double>("fraction")?.let { ExportWorker.dartProgress(app, it) }
                result.success(null)
            }
            "run" -> run(call, result)
            "end" -> {
                val outcome = when (call.argument<String>("outcome")) {
                    "cancelled" -> ExportOutcome.CANCELLED
                    else -> ExportOutcome.FAILED
                }
                ExportWorker.end(app, outcome, call.argument<String>("code"))
                result.success(null)
            }
            "cancel" -> {
                ExportWorker.cancel()
                result.success(null)
            }
            "stopAll" -> {
                ExportWorker.stopAll(app)
                result.success(null)
            }
            else -> result.notImplemented()
        }
    }

    private fun run(call: MethodCall, result: MethodChannel.Result) {
        val inputs = call.argument<List<Map<String, Any?>>>("inputs")
        val speed = call.argument<Double>("speed")
        val outPath = call.argument<String>("outPath")
        val workDir = call.argument<String>("workDir")
        val tree = call.argument<String>("treeUri")
        val fileName = call.argument<String>("fileName")
        val from = call.argument<Double>("from")
        val renderShare = call.argument<Double>("renderShare")
        val saveShare = call.argument<Double>("saveShare")
        val specs = inputs?.map { spec ->
            val path = spec["path"] as? String
            val gain = (spec["gain"] as? Number)?.toFloat()
            if (path == null || gain == null) return badArgs(result, "input path and gain")
            File(path) to gain
        }
        // Dart never sends an empty job; refusing one here keeps an empty
        // MP3 from ever being saved as a success.
        if (specs.isNullOrEmpty() || speed == null || speed <= 0 || outPath == null || workDir == null ||
            tree == null || fileName == null || from == null || renderShare == null || saveShare == null
        ) {
            return badArgs(result, "non-empty inputs, speed > 0, paths, folder, file name and shares")
        }
        val args = ExportWorker.RunArgs(
            specs,
            speed,
            outPath,
            workDir,
            Uri.parse(tree),
            fileName,
            from,
            renderShare,
            saveShare,
        )
        ExportWorker.run(app, args) { outcome ->
            // A dead engine cannot take a reply; the notification already
            // told the user.
            if (disposed) return@run
            outcome.fold(
                { result.success(it) },
                { e ->
                    val code = (e as? ExportWorker.CodedFailure)?.code ?: CANCELLED
                    result.error(code, e.message, null)
                },
            )
        }
    }

    // ---- ExportWorker.Listener (main thread) -------------------------------

    override fun onRenderProgress(fraction: Double) {
        if (!disposed) channel.invokeMethod(PROGRESS, fraction)
    }

    override fun onSaveProgress(fraction: Double) {
        if (!disposed) channel.invokeMethod(SAVE_PROGRESS, fraction)
    }

    override fun onCancelRequested() {
        if (!disposed) channel.invokeMethod(CANCEL_REQUESTED, null)
    }

    // ---- Folders -----------------------------------------------------------

    private fun pickFolder(keep: Set<String>, result: MethodChannel.Result) {
        if (pendingPick != null) {
            // The sheet is busy while picking, so a second call is a bug;
            // fail it rather than orphaning the first reply.
            result.error("bad_args", "a folder pick is already open", null)
            return
        }
        val intent = Intent(Intent.ACTION_OPEN_DOCUMENT_TREE)
            .addFlags(
                Intent.FLAG_GRANT_READ_URI_PERMISSION or
                    Intent.FLAG_GRANT_WRITE_URI_PERMISSION or
                    Intent.FLAG_GRANT_PERSISTABLE_URI_PERMISSION,
            )
            // Asks the picker to hide cloud and app providers. Pickers may
            // ignore it, so the answer is still checked in onActivityResult.
            .putExtra(Intent.EXTRA_LOCAL_ONLY, true)
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.O) {
            // Opens on the phone's own storage rather than wherever the
            // picker was last used, which may have been Drive.
            intent.putExtra(
                DocumentsContract.EXTRA_INITIAL_URI,
                DocumentsContract.buildRootUri(LocalFolders.EXTERNAL_STORAGE, PRIMARY_VOLUME),
            )
        }
        try {
            pendingPick = PendingPick(result, keep)
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
        val pick = pendingPick ?: return true
        pendingPick = null
        val tree = data?.data
        if (resultCode != Activity.RESULT_OK || tree == null) {
            pick.result.success(null)
            return true
        }
        if (!LocalFolders.isLocal(tree.scheme, tree.authority)) {
            // Before persisting, so a refused folder leaves no grant behind.
            Log.i(TAG, "refused a folder from ${tree.authority}")
            pick.result.error(NOT_LOCAL_FOLDER, "pick a folder on this phone", null)
            return true
        }
        try {
            activity.contentResolver.takePersistableUriPermission(
                tree,
                Intent.FLAG_GRANT_READ_URI_PERMISSION or Intent.FLAG_GRANT_WRITE_URI_PERMISSION,
            )
        } catch (e: SecurityException) {
            // The provider handed back a folder it will not let us keep.
            // Saving may still work this once, so carry on and let the save
            // report permission_denied if it does not.
            Log.w(TAG, "could not persist folder permission", e)
        }
        // The folder this pick replaces, and any other no export refers to.
        releaseAllBut(pick.keep + tree.toString())
        pick.result.success(tree.toString())
        return true
    }

    private fun releaseAllBut(keep: Set<String>) {
        val persisted = activity.contentResolver.persistedUriPermissions
            .map { it.uri }
            .filter { DocumentsContract.isTreeUri(it) }
            .map { it.toString() }
        release(LocalFolders.grantsToRelease(persisted, keep))
    }

    private fun release(trees: List<String>) {
        for (tree in trees) {
            try {
                activity.contentResolver.releasePersistableUriPermission(
                    Uri.parse(tree),
                    Intent.FLAG_GRANT_READ_URI_PERMISSION or Intent.FLAG_GRANT_WRITE_URI_PERMISSION,
                )
            } catch (e: SecurityException) {
                // Not held (any more): nothing to give back.
                Log.i(TAG, "no folder grant to release", e)
            }
        }
    }

    private fun openFolder(tree: Uri): Boolean = try {
        activity.startActivity(ExportNotifications.folderIntent(tree))
        true
    } catch (e: ActivityNotFoundException) {
        // No file manager handles folders here; Dart hides the button.
        Log.i(TAG, "no activity opens a folder", e)
        false
    } catch (e: SecurityException) {
        Log.w(TAG, "folder permission lost", e)
        false
    } catch (e: IllegalArgumentException) {
        Log.w(TAG, "not a folder Uri", e)
        false
    }

    private fun listNames(tree: Uri, result: MethodChannel.Result) {
        try {
            executor.execute {
                val outcome = runCatching { ExportWorker.listNames(app, tree) }
                mainHandler.post {
                    if (disposed) return@post
                    outcome.fold(
                        { result.success(it) },
                        { e ->
                            Log.w(TAG, "folder listing failed", e)
                            // Only a folder that is gone or refused fails here.
                            result.error(PERMISSION_DENIED, e.message, null)
                        },
                    )
                }
            }
        } catch (e: RejectedExecutionException) {
            result.error(INTERRUPTED, e.message, null)
        }
    }

    private fun badArgs(result: MethodChannel.Result, what: String) =
        result.error("bad_args", "$what required", null)

    /**
     * The engine is going away. An export already handed to the device
     * carries on under its service; one still in Dart's half ends as
     * interrupted (AC18).
     */
    fun dispose() {
        disposed = true
        channel.setMethodCallHandler(null)
        if (ExportWorker.listener === this) ExportWorker.engineGone(app)
        executor.shutdown()
        pendingPick?.result?.success(null)
        pendingPick = null
    }

    companion object {
        const val CHANNEL = "piyanota/export"
        private const val TAG = "PiyaNotaExport"
        private const val PICK_FOLDER_REQUEST = 0x5049 // "PI"
        private const val PRIMARY_VOLUME = "primary"

        const val STORAGE_FULL = "storage_full"
        const val PERMISSION_DENIED = "permission_denied"
        const val GENERATION_FAILED = "generation_failed"
        const val INTERRUPTED = "interrupted"
        const val CANCELLED = "cancelled"
        const val CANCELLED_PARTIAL = "cancelled_partial"
        const val BUSY = "busy"
        private const val PROGRESS = "progress"
        private const val SAVE_PROGRESS = "saveProgress"
        private const val CANCEL_REQUESTED = "cancelRequested"
        const val NO_FOLDER_PICKER = "no_folder_picker"
        const val NOT_LOCAL_FOLDER = "not_local_folder"
    }
}
