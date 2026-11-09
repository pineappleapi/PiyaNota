package com.piyanota.piyanota_application.scan

import org.junit.Assert.assertEquals
import org.junit.Assert.assertNotEquals
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Test

/** PIYA-218's background service type and per-job notification ids. */
class ScanNoticesTest {
    @Test
    fun serviceTypeIsDataSyncFromAndroid10() {
        assertEquals(ScanNotices.TYPE_DATA_SYNC, ScanNotices.serviceType(29))
        assertEquals(ScanNotices.TYPE_DATA_SYNC, ScanNotices.serviceType(34))
        assertEquals(ScanNotices.TYPE_DATA_SYNC, ScanNotices.serviceType(36))
        assertNull(ScanNotices.serviceType(28))
        assertNull(ScanNotices.serviceType(24))
    }

    @Test
    fun resultIdsAreStablePerJobAndNeverNegative() {
        assertEquals(ScanNotices.resultId("job-1"), ScanNotices.resultId("job-1"))
        assertNotEquals(ScanNotices.resultId("job-1"), ScanNotices.resultId("job-2"))
        // A hash whose top bit is set must still give a valid id.
        val negative = generateSequence(0) { it + 1 }.map { "j$it" }.first { it.hashCode() < 0 }
        assertTrue(ScanNotices.resultId(negative) >= 0)
    }
}
