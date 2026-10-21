package com.piyanota.piyanota_application.export

import kotlin.math.floor

/**
 * Turns render work into the 0..1 the Export sheet's bar shows (PIYA-211).
 *
 * A render is three stages of the same size, each counted in decoded
 * frames: decoding every track, the mixer's peak pass and its encode pass
 * (see [Mixer]). Both mixer passes read every decoded frame once, so they
 * really are the same work; decoding is counted against an estimate from
 * each file's header, since the exact count is only known afterwards, and
 * is capped at its share so a short estimate never runs ahead.
 *
 * Only whole-percent steps are reported, and never a smaller one than
 * before, so the channel carries at most about a hundred messages and the
 * bar never moves back.
 */
internal class RenderProgress(private val report: (Double) -> Unit) {
    private var stage = NOT_STARTED
    private var total = 1L
    private var done = 0L
    private var lastStep = NOT_STARTED

    /** Starts [next] (one of the stage constants) with its frame count. */
    fun begin(next: Int, totalFrames: Long) {
        require(next in DECODE until STAGES && next > stage) { "stage $next after $stage" }
        stage = next
        // A zero estimate (an unreadable header) still makes progress
        // instead of dividing by zero; the stage then reads as done.
        total = maxOf(1L, totalFrames)
        done = 0
        emit()
    }

    fun advance(frames: Long) {
        done += frames
        emit()
    }

    /** The whole render is done. */
    fun finish() {
        stage = STAGES
        emit()
    }

    val fraction: Double
        get() = when {
            stage >= STAGES -> 1.0
            stage < DECODE -> 0.0
            else -> (stage + minOf(1.0, done.toDouble() / total)) / STAGES
        }

    private fun emit() {
        val step = floor(fraction * STEPS).toInt()
        if (step <= lastStep) return
        lastStep = step
        report(step.toDouble() / STEPS)
    }

    companion object {
        const val DECODE = 0
        const val PEAK_PASS = 1
        const val ENCODE_PASS = 2
        const val STAGES = 3
        const val STEPS = 100
        private const val NOT_STARTED = -1
    }
}
