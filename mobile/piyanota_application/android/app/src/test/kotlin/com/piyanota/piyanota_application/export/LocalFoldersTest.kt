package com.piyanota.piyanota_application.export

import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test

/** Exports are saved only on this phone (user decisions 2026-10-21/22). */
class LocalFoldersTest {
    @Test
    fun acceptsThePhonesOwnStorageAndDownloads() {
        assertTrue(LocalFolders.isLocal("content", "com.android.externalstorage.documents"))
        assertTrue(LocalFolders.isLocal("content", "com.android.providers.downloads.documents"))
    }

    @Test
    fun refusesCloudAndAppProviders() {
        assertFalse(LocalFolders.isLocal("content", "com.google.android.apps.docs.storage"))
        assertFalse(LocalFolders.isLocal("content", "com.android.providers.media.documents"))
        assertFalse(LocalFolders.isLocal("content", "com.dropbox.product.android.dbapp.document_provider.documents"))
        assertFalse(LocalFolders.isLocal("content", ""))
        assertFalse(LocalFolders.isLocal("content", null))
    }

    @Test
    fun theMatchIsExact() {
        // Android matches authorities exactly; so does this check, and so
        // must the Dart one.
        assertFalse(LocalFolders.isLocal("content", "COM.ANDROID.EXTERNALSTORAGE.DOCUMENTS"))
        assertFalse(LocalFolders.isLocal("content", "com.android.externalstorage.documents:80"))
        assertFalse(LocalFolders.isLocal("content", "x@com.android.externalstorage.documents"))
        assertFalse(LocalFolders.isLocal("file", "com.android.externalstorage.documents"))
        assertFalse(LocalFolders.isLocal(null, "com.android.externalstorage.documents"))
    }

    @Test
    fun releasesEveryFolderGrantNotKept() {
        val a = "content://com.android.externalstorage.documents/tree/primary%3AA"
        val b = "content://com.android.externalstorage.documents/tree/primary%3AB"
        val c = "content://com.android.externalstorage.documents/tree/1A2B-3C4D%3AC"
        assertEquals(listOf(b), LocalFolders.grantsToRelease(listOf(a, b, c), setOf(a, c)))
        assertEquals(emptyList<String>(), LocalFolders.grantsToRelease(emptyList(), setOf(a)))
    }
}
