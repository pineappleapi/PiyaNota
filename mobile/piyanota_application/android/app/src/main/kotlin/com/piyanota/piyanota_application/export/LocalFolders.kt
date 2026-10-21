package com.piyanota.piyanota_application.export

/**
 * Which folder providers count as "on this phone" (PIYA-211, user decision
 * 2026-10-21: exports are saved only to the phone's own storage, never to
 * Drive, another app or the cloud).
 *
 * The picker is asked for local folders only (EXTRA_LOCAL_ONLY), but
 * pickers may ignore that, so the answer is checked against this list.
 * Kept free of Android types so the JVM tests can check it.
 */
internal object LocalFolders {
    /** Internal storage and SD cards (the "primary:" and "1A2B-3C4D:" ids). */
    const val EXTERNAL_STORAGE = "com.android.externalstorage.documents"

    /**
     * The Downloads provider. It only lists files in the phone's own
     * Download folder (and DownloadManager records of files on the
     * phone); it has no cloud backing. Android 11+ hides its root from
     * the folder picker, so in practice it is only picked on Android 10
     * and older.
     */
    const val DOWNLOADS = "com.android.providers.downloads.documents"

    private val accepted = setOf(EXTERNAL_STORAGE, DOWNLOADS)

    fun isLocal(authority: String?): Boolean = authority in accepted
}
