package com.piyanota.piyanota_application.export

import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test

/** Exports are saved only on this phone (user decision 2026-10-21). */
class LocalFoldersTest {
    @Test
    fun acceptsThePhonesOwnStorageAndDownloads() {
        assertTrue(LocalFolders.isLocal("com.android.externalstorage.documents"))
        assertTrue(LocalFolders.isLocal("com.android.providers.downloads.documents"))
    }

    @Test
    fun refusesCloudAndAppProviders() {
        assertFalse(LocalFolders.isLocal("com.google.android.apps.docs.storage"))
        assertFalse(LocalFolders.isLocal("com.android.providers.media.documents"))
        assertFalse(LocalFolders.isLocal("com.dropbox.product.android.dbapp.document_provider.documents"))
        assertFalse(LocalFolders.isLocal(""))
        assertFalse(LocalFolders.isLocal(null))
    }
}
