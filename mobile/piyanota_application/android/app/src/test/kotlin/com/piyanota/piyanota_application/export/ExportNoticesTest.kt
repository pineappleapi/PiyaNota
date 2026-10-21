package com.piyanota.piyanota_application.export

import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Test

/** The export's notifications and service type (user decision 2026-10-22). */
class ExportNoticesTest {
    private val notice = ExportNotice(
        exporting = "Exporting Bituin…",
        cancel = "Cancel",
        savedTemplate = "Saved {file} to {folder}",
        failedTitle = "Bituin wasn’t exported",
        failures = mapOf("storage_full" to "Your phone is full."),
        fallbackFailure = "Something stopped it.",
    )

    @Test
    fun progressShowsTheWholePercent() {
        assertEquals("Exporting Bituin… 42%", notice.progressText(42))
        assertEquals(0, ExportNotices.percent(-1.0))
        assertEquals(0, ExportNotices.percent(Double.NaN))
        assertEquals(99, ExportNotices.percent(0.999))
        assertEquals(100, ExportNotices.percent(2.0))
    }

    @Test
    fun savedNamesTheFileAndFolderAndOpensIt() {
        val result = ExportNotices.result(notice, ExportOutcome.SAVED, fileName = "Bituin.mp3", folder = "Internal storage/Music")
        assertEquals("Saved Bituin.mp3 to Internal storage/Music", result?.title)
        assertNull(result?.text)
        assertTrue(result!!.opensFolder)
    }

    @Test
    fun failedSaysWhatToDo() {
        val full = ExportNotices.result(notice, ExportOutcome.FAILED, code = "storage_full")
        assertEquals("Bituin wasn’t exported", full?.title)
        assertEquals("Your phone is full.", full?.text)
        assertFalse(full!!.opensFolder)
        assertEquals("Something stopped it.", ExportNotices.result(notice, ExportOutcome.FAILED, code = "weird")?.text)
        assertEquals("Something stopped it.", ExportNotices.result(notice, ExportOutcome.FAILED)?.text)
    }

    @Test
    fun aCancelLeavesNothing() {
        assertNull(ExportNotices.result(notice, ExportOutcome.CANCELLED))
    }

    @Test
    fun serviceTypeByAndroidVersion() {
        assertEquals(ExportNotices.TYPE_MEDIA_PROCESSING, ExportNotices.serviceType(35))
        assertEquals(ExportNotices.TYPE_MEDIA_PROCESSING, ExportNotices.serviceType(36))
        assertEquals(ExportNotices.TYPE_DATA_SYNC, ExportNotices.serviceType(34))
        assertEquals(ExportNotices.TYPE_DATA_SYNC, ExportNotices.serviceType(29))
        assertNull(ExportNotices.serviceType(28))
        assertNull(ExportNotices.serviceType(24))
    }

    @Test
    fun overallProgressContinuesFromDartsHandOver() {
        // Download took 0.2; render 0.7, save 0.1.
        assertEquals(0.2, ExportNotices.overall(0.2, 0.7, 0.1, saving = false, fraction = 0.0), 1e-9)
        assertEquals(0.55, ExportNotices.overall(0.2, 0.7, 0.1, saving = false, fraction = 0.5), 1e-9)
        assertEquals(0.95, ExportNotices.overall(0.2, 0.7, 0.1, saving = true, fraction = 0.5), 1e-9)
        assertEquals(1.0, ExportNotices.overall(0.2, 0.7, 0.1, saving = true, fraction = 3.0), 1e-9)
    }

    @Test
    fun throttlePostsEachPercentOnceAndNeverGoesBack() {
        val throttle = PercentThrottle()
        assertEquals(0, throttle.next(0.0))
        assertNull(throttle.next(0.004))
        assertEquals(1, throttle.next(0.012))
        assertNull(throttle.next(0.005))
        assertEquals(1, throttle.last)
    }

    @Test
    fun noticeFromDartNeedsEveryField() {
        val map = mapOf(
            "exporting" to "Exporting A…",
            "cancel" to "Cancel",
            "saved" to "Saved {file} to {folder}",
            "failedTitle" to "A wasn’t exported",
            "failures" to mapOf("interrupted" to "Try again."),
            "fallbackFailure" to "Try again.",
        )
        assertEquals("Exporting A… 3%", ExportNotice.fromMap(map)?.progressText(3))
        assertNull(ExportNotice.fromMap(map - "cancel"))
        assertNull(ExportNotice.fromMap(map - "failures"))
        assertNull(ExportNotice.fromMap(null))
    }

    @Test
    fun onlyAWorkFolderInsideTheCacheIsDeleted() {
        val cache = "/data/user/0/app/cache"
        assertTrue(isInside("$cache/export_1", cache))
        assertTrue(isInside("$cache/export_1", "$cache/"))
        assertFalse(isInside(cache, cache))
        assertFalse(isInside("/data/user/0/app/cache2/x", cache))
        assertFalse(isInside("$cache/../files", cache))
        assertFalse(isInside("/sdcard/Music", cache))
    }
}
