package com.piyanota.piyanota_application.export

import org.junit.Assert.assertEquals
import org.junit.Assert.assertThrows
import org.junit.Test

/** The progress bar's mapping of render work to 0..1 (PIYA-211). */
class RenderProgressTest {
    private val reports = mutableListOf<Double>()
    private val progress = RenderProgress { reports += it }

    @Test
    fun threeEqualStagesCountedInFrames() {
        progress.begin(RenderProgress.DECODE, 1000)
        assertEquals(0.0, progress.fraction, 1e-9)
        progress.advance(500)
        assertEquals(1.0 / 6, progress.fraction, 1e-9)
        progress.begin(RenderProgress.PEAK_PASS, 4000)
        assertEquals(1.0 / 3, progress.fraction, 1e-9)
        progress.advance(2000)
        assertEquals(0.5, progress.fraction, 1e-9)
        progress.begin(RenderProgress.ENCODE_PASS, 4000)
        progress.advance(4000)
        assertEquals(1.0, progress.fraction, 1e-9)
    }

    @Test
    fun aShortDecodeEstimateNeverRunsIntoTheNextStage() {
        progress.begin(RenderProgress.DECODE, 100)
        progress.advance(1000)
        assertEquals(1.0 / 3, progress.fraction, 1e-9)
    }

    @Test
    fun aZeroEstimateStillMovesForward() {
        progress.begin(RenderProgress.DECODE, 0)
        progress.advance(10)
        assertEquals(1.0 / 3, progress.fraction, 1e-9)
    }

    @Test
    fun reportsWholePercentStepsOnlyAndNeverGoesBack() {
        progress.begin(RenderProgress.DECODE, 30_000)
        repeat(30_000) { progress.advance(1) }
        progress.begin(RenderProgress.PEAK_PASS, 10)
        progress.begin(RenderProgress.ENCODE_PASS, 10)
        progress.finish()
        assertEquals(reports.sorted().distinct(), reports)
        assertEquals(0.0, reports.first(), 0.0)
        assertEquals(1.0, reports.last(), 0.0)
        // 0.00 to 0.33 one step at a time, then 0.66 and 1.0 straight away.
        assertEquals(34 + 2, reports.size)
    }

    @Test
    fun stagesOnlyGoForward() {
        progress.begin(RenderProgress.PEAK_PASS, 10)
        assertThrows(IllegalArgumentException::class.java) {
            progress.begin(RenderProgress.DECODE, 10)
        }
    }
}
