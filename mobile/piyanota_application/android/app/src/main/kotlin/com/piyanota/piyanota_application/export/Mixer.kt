package com.piyanota.piyanota_application.export

import androidx.annotation.OptIn
import androidx.media3.common.audio.AudioProcessor
import androidx.media3.common.audio.SonicAudioProcessor
import androidx.media3.common.util.UnstableApi
import java.io.BufferedInputStream
import java.io.File
import java.io.FileInputStream
import java.io.InputStream
import java.nio.ByteBuffer
import java.nio.ByteOrder
import kotlin.math.abs
import kotlin.math.roundToInt

/** One decoded track (stereo PCM from [PcmDecoder]) and its mixer gain. */
internal class MixInput(val pcm: File, val gain: Float)

/**
 * Mixes the decoded tracks, time-stretches the mix and hands 16-bit
 * stereo frames to [sink].
 *
 * Two passes over the files: the first finds the peak of the summed
 * signal, the second scales it down to [PEAK_CEILING] if it is louder
 * (a quieter mix is left as the Mixer set it). Four loud voices plus
 * the click can sum past full scale; one fixed gain for the whole file
 * keeps the balance the singer set in the Voice Mixer, where a sample-
 * by-sample limiter would pump.
 */
internal object Mixer {
    private const val CHUNK_FRAMES = 4096
    private const val FULL_SCALE = 32768f
    private const val UNITY_SPEED = 1.0

    /**
     * About -1 dBFS (10^(-1/20)). A mix peaking at exactly full scale
     * clips once MP3 encoding and the time-stretch add their own small
     * overshoots, so the loudest sample is held just below it.
     */
    private const val PEAK_CEILING = 0.891f

    /**
     * Sonic reports itself inactive (and then drops input) within this
     * distance of 1.0, so such a speed is treated as unity.
     */
    private const val SONIC_CLOSENESS = 1e-4

    fun mix(
        inputs: List<MixInput>,
        speed: Double,
        sink: (ShortArray, Int) -> Unit,
        cancelled: () -> Boolean,
    ) {
        val peak = scan(inputs, cancelled) { _, _ -> }
        val scale = PEAK_CEILING / maxOf(PEAK_CEILING, peak)
        val stretcher = if (abs(speed - UNITY_SPEED) < SONIC_CLOSENESS) null else TimeStretcher(speed.toFloat(), sink)
        scan(inputs, cancelled) { mixed, frames ->
            val out = ShortArray(frames * PcmDecoder.OUT_CHANNELS)
            for (i in out.indices) {
                out[i] = (mixed[i] * scale * Short.MAX_VALUE).roundToInt()
                    .coerceIn(Short.MIN_VALUE.toInt(), Short.MAX_VALUE.toInt()).toShort()
            }
            if (stretcher != null) stretcher.queue(out, frames) else sink(out, frames)
        }
        stretcher?.finish()
    }

    /**
     * Reads every input in step, sums them with their gains (as floats in
     * -1..1, so the sum can exceed 1), and passes each chunk to [onChunk].
     * A track shorter than the longest is treated as silence after its end.
     * Returns the largest absolute summed sample.
     */
    private fun scan(
        inputs: List<MixInput>,
        cancelled: () -> Boolean,
        onChunk: (FloatArray, Int) -> Unit,
    ): Float {
        val streams: List<InputStream> = inputs.map { BufferedInputStream(FileInputStream(it.pcm)) }
        try {
            val bytes = ByteArray(CHUNK_FRAMES * PcmDecoder.BYTES_PER_FRAME)
            val mixed = FloatArray(CHUNK_FRAMES * PcmDecoder.OUT_CHANNELS)
            val open = BooleanArray(inputs.size) { true }
            var peak = 0f
            while (open.any { it }) {
                if (cancelled()) throw ExportCancelled()
                mixed.fill(0f)
                var frames = 0
                for ((k, input) in inputs.withIndex()) {
                    if (!open[k]) continue
                    val n = readFully(streams[k], bytes)
                    if (n < bytes.size) open[k] = false
                    val count = n / PcmDecoder.BYTES_PER_FRAME
                    frames = maxOf(frames, count)
                    val shorts = ByteBuffer.wrap(bytes, 0, count * PcmDecoder.BYTES_PER_FRAME)
                        .order(ByteOrder.LITTLE_ENDIAN).asShortBuffer()
                    var i = 0
                    while (shorts.hasRemaining()) {
                        mixed[i++] += shorts.get() / FULL_SCALE * input.gain
                    }
                }
                if (frames == 0) break
                for (i in 0 until frames * PcmDecoder.OUT_CHANNELS) {
                    peak = maxOf(peak, abs(mixed[i]))
                }
                onChunk(mixed, frames)
            }
            return peak
        } finally {
            streams.forEach { s -> runCatching { s.close() } }
        }
    }

    private fun readFully(stream: InputStream, into: ByteArray): Int {
        var total = 0
        while (total < into.size) {
            val n = stream.read(into, total, into.size - total)
            if (n < 0) break
            total += n
        }
        return total
    }
}

/**
 * Pitch-preserving speed change (FR-9), using the same Sonic WSOLA
 * implementation ExoPlayer applies in Playback, so the exported file
 * sounds like what the singer heard at that speed.
 */
@OptIn(UnstableApi::class)
private class TimeStretcher(speed: Float, private val sink: (ShortArray, Int) -> Unit) {
    private val sonic = SonicAudioProcessor()

    init {
        sonic.setSpeed(speed)
        sonic.setPitch(1f)
        sonic.configure(
            AudioProcessor.AudioFormat(
                PcmDecoder.OUT_RATE,
                PcmDecoder.OUT_CHANNELS,
                android.media.AudioFormat.ENCODING_PCM_16BIT,
            ),
        )
        // configure() only stages the format; flush() applies it.
        sonic.flush()
    }

    fun queue(frames: ShortArray, count: Int) {
        val input = ByteBuffer.allocateDirect(count * PcmDecoder.BYTES_PER_FRAME).order(ByteOrder.nativeOrder())
        input.asShortBuffer().put(frames, 0, count * PcmDecoder.OUT_CHANNELS)
        sonic.queueInput(input)
        drain()
    }

    fun finish() {
        sonic.queueEndOfStream()
        while (!sonic.isEnded) {
            if (!drain()) break
        }
        sonic.reset()
    }

    /** Returns whether any output was produced. */
    private fun drain(): Boolean {
        val out = sonic.output.order(ByteOrder.nativeOrder())
        val n = out.remaining() / 2
        if (n == 0) return false
        val shorts = ShortArray(n)
        out.asShortBuffer().get(shorts)
        sink(shorts, n / PcmDecoder.OUT_CHANNELS)
        return true
    }
}
