package com.piyanota.piyanota_application.export

import org.junit.Assert.assertEquals
import org.junit.Test

/** The save copy's share of the progress bar (PIYA-211). */
class CopyProgressTest {
    private val reports = mutableListOf<Double>()

    @Test
    fun countsBytesInWholePercentStepsUpToOne() {
        val progress = CopyProgress(1000) { reports += it }
        progress.advance(5) // under one percent: nothing new
        progress.advance(495)
        progress.advance(500)
        progress.finish()
        assertEquals(listOf(0.0, 0.5, 1.0), reports)
    }

    @Test
    fun anEmptySourceStillEndsAtOne() {
        val progress = CopyProgress(0) { reports += it }
        progress.finish()
        assertEquals(listOf(0.0, 1.0), reports)
    }

    @Test
    fun moreBytesThanExpectedNeverPassOne() {
        val progress = CopyProgress(100) { reports += it }
        progress.advance(500)
        progress.finish()
        assertEquals(listOf(0.0, 1.0), reports)
    }
}
