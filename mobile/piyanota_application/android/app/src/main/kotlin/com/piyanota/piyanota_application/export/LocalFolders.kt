package com.piyanota.piyanota_application.export

/**
 * Which folder providers count as "on this phone" (PIYA-211, user decisions
 * 2026-10-21 and 2026-10-22: exports are saved only to storage on the phone
 * or attached to it, never straight to Drive, another app or the cloud).
 *
 * What the accepted providers cover:
 *  - internal storage, SD cards and USB-OTG drives: all served by the
 *    external storage provider, with tree ids like "primary:Music" or a
 *    volume id such as "1A2B-3C4D:Songs";
 *  - a local folder that a sync app (Drive, OneDrive, Syncthing...)
 *    happens to watch: the file is still written to the phone first, by
 *    the same provider, and the sync app copies it on its own. Allowed.
 *
 * The picker is asked for local folders only (EXTRA_LOCAL_ONLY), but
 * pickers may ignore that, so the answer is checked against this list.
 * Kept free of Android types so the JVM tests can check it. The Dart
 * `isLocalFolder` in export_service.dart applies the same exact check.
 */
internal object LocalFolders {
    /** Internal storage, SD cards and USB-OTG drives. */
    const val EXTERNAL_STORAGE = "com.android.externalstorage.documents"

    /**
     * The Downloads provider. It only lists files in the phone's own
     * Download folder (and DownloadManager records of files on the
     * phone); it has no cloud backing. Android 11+ hides its root from
     * the folder picker, so in practice it is only picked on Android 10
     * and older.
     */
    const val DOWNLOADS = "com.android.providers.downloads.documents"

    private const val CONTENT_SCHEME = "content"
    private val accepted = setOf(EXTERNAL_STORAGE, DOWNLOADS)

    /**
     * A content Uri whose authority is exactly one of the accepted ones:
     * case-sensitive, no user info or port, as Android itself matches
     * provider authorities.
     */
    fun isLocal(scheme: String?, authority: String?): Boolean =
        scheme == CONTENT_SCHEME && authority in accepted

    /**
     * The persisted folder grants to give back (user decision 2026-10-22):
     * every folder grant except [keep]. Android caps how many grants an
     * app may hold (128 before Android 11, 512 after), so grants for
     * folders nothing refers to any more are released instead of piling up.
     */
    fun grantsToRelease(persistedTrees: List<String>, keep: Set<String>): List<String> =
        persistedTrees.filter { it !in keep }
}
