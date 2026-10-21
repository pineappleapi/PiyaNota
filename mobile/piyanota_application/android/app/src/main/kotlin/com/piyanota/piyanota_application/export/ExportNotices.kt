package com.piyanota.piyanota_application.export

/**
 * The plain logic behind the export's system notifications (user decision
 * 2026-10-22), kept free of Android types so the JVM tests can check it.
 * [ExportNotifications] turns these into real notifications.
 */

/**
 * The words the notifications use, sent by Dart in `begin` so they match
 * the in-app bell and banner (ExportMessages) and stay in one place.
 */
internal data class ExportNotice(
    /** "Exporting Bituin…"; the percent is added here. */
    val exporting: String,
    val cancel: String,
    /** "Saved {file} to {folder}". */
    val savedTemplate: String,
    /** "Bituin wasn't exported". */
    val failedTitle: String,
    /** What to do next, per error code; [fallbackFailure] for the rest. */
    val failures: Map<String, String>,
    val fallbackFailure: String,
) {
    fun progressText(percent: Int): String = "$exporting $percent%"

    fun savedText(fileName: String, folder: String): String =
        savedTemplate.replace(FILE, fileName).replace(FOLDER, folder)

    fun failureText(code: String?): String = code?.let(failures::get) ?: fallbackFailure

    companion object {
        const val FILE = "{file}"
        const val FOLDER = "{folder}"

        /** Null when anything is missing: Dart always sends all of it. */
        fun fromMap(map: Map<*, *>?): ExportNotice? {
            if (map == null) return null
            val failures = (map["failures"] as? Map<*, *>)
                ?.mapNotNull { (k, v) -> if (k is String && v is String) k to v else null }
                ?.toMap()
                ?: return null
            return ExportNotice(
                exporting = map["exporting"] as? String ?: return null,
                cancel = map["cancel"] as? String ?: return null,
                savedTemplate = map["saved"] as? String ?: return null,
                failedTitle = map["failedTitle"] as? String ?: return null,
                failures = failures,
                fallbackFailure = map["fallbackFailure"] as? String ?: return null,
            )
        }
    }
}

/** How an export ended, for its last notification. */
internal enum class ExportOutcome { SAVED, FAILED, CANCELLED }

/** The notification left once an export has finished. */
internal data class ResultNotice(
    val title: String,
    val text: String?,
    /** Tapping it opens the folder the file was saved in. */
    val opensFolder: Boolean,
)

internal object ExportNotices {
    /**
     * Saved: "Saved <file> to <folder>", opening the folder. Failed: the
     * same failure words the app shows. Cancelled: nothing, the user knows
     * (user decision 2026-10-22).
     */
    fun result(
        notice: ExportNotice,
        outcome: ExportOutcome,
        code: String? = null,
        fileName: String? = null,
        folder: String? = null,
    ): ResultNotice? = when (outcome) {
        ExportOutcome.CANCELLED -> null
        ExportOutcome.SAVED ->
            if (fileName == null || folder == null) {
                null
            } else {
                ResultNotice(notice.savedText(fileName, folder), null, opensFolder = true)
            }
        ExportOutcome.FAILED -> ResultNotice(notice.failedTitle, notice.failureText(code), opensFolder = false)
    }

    /** The whole number the bar and the in-app row show (floor, 0..100). */
    fun percent(fraction: Double): Int =
        if (fraction.isNaN()) 0 else (fraction.coerceIn(0.0, 1.0) * 100).toInt()

    /**
     * Foreground service type for the export, by Android version:
     *  - 35+: mediaProcessing, made for exactly this (decoding, stretching
     *    and encoding audio on the device), and not one of the types
     *    Google has said it will restrict further, as it has dataSync;
     *  - 29..34: dataSync, the only fitting type that exists there (the
     *    save is an export of data to a folder);
     *  - older: no types exist, so none is passed.
     * Values are android.content.pm.ServiceInfo's constants.
     */
    fun serviceType(sdkInt: Int): Int? = when {
        sdkInt >= MEDIA_PROCESSING_SDK -> TYPE_MEDIA_PROCESSING
        sdkInt >= TYPED_SERVICES_SDK -> TYPE_DATA_SYNC
        else -> null
    }

    /**
     * The whole export's progress once the device has it (`run`): Dart
     * hands over at [from] (download done), and render and save fill their
     * [renderShare] and [saveShare] of the bar after it.
     */
    fun overall(from: Double, renderShare: Double, saveShare: Double, saving: Boolean, fraction: Double): Double {
        val f = fraction.coerceIn(0.0, 1.0)
        val value = if (saving) from + renderShare + saveShare * f else from + renderShare * f
        return value.coerceIn(0.0, 1.0)
    }

    const val TYPE_DATA_SYNC = 0x00000001
    const val TYPE_MEDIA_PROCESSING = 0x00002000
    private const val TYPED_SERVICES_SDK = 29
    private const val MEDIA_PROCESSING_SDK = 35
}

/**
 * Posts a progress notification only when the whole percent changes, so a
 * render reporting every few milliseconds does not flood the system
 * (Android drops apps that update a notification too often).
 */
internal class PercentThrottle {
    /** The last percent posted; -1 before the first. */
    var last = -1
        private set

    /** The percent to post, or null when it has not changed. */
    fun next(fraction: Double): Int? {
        val now = ExportNotices.percent(fraction)
        if (now <= last) return null
        last = now
        return now
    }
}

/**
 * The work folder an export may delete when it ends: only one inside the
 * app's own cache, so a wrong path from Dart can never delete anything else.
 */
internal fun isInside(path: String, dir: String): Boolean {
    val base = dir.trimEnd('/')
    return path.startsWith("$base/") && !path.split('/').contains("..")
}
