package com.piyanota.piyanota_application.export

import androidx.annotation.OptIn
import androidx.media3.common.audio.AudioProcessor
import androidx.media3.common.audio.SonicAudioProcessor
import androidx.media3.common.util.UnstableApi
import java.io.BufferedInputStream
import java.io.BufferedOutputStream
import java.io.File
import java.io.FileInputStream
import java.io.FileOutputStream
import java.io.InputStream
import java.io.OutputStream
import java.nio.ByteBuffer
import java.nio.ByteOrder
import kotlin.math.abs
import kotlin.math.roundToInt

/** One decoded track (stereo PCM from [PcmDecoder]) and its mixer gain. */
internal class MixInput(val pcm: File, val gain: Float)

/**
 * Time-stretches each decoded track on its own, mixes them and hands
 * 16-bit stereo frames to [sink].
 *
 * Each track gets its own Sonic instance at the same speed, the way
 * Playback runs one player (so one Sonic) per voice and one for the
 * click, and the gains are applied after the stretch, as player volume
 * is. Sonic over the summed mix is not the same signal: its WSOLA splice
 * points follow the pitch of whatever it is fed, so one Sonic over four
 * voices would not match what Playback plays. The stretched tracks go to
 * temp files beside the decoded ones, never to memory. They all start at
 * frame 0, so voices and click stay sample-aligned, and the mix runs to
 * the end of the longest stretched track.
 *
 * Two passes over the stretched files: the first finds the peak of the
 * summed signal, the second scales it down to [PEAK_CEILING] if it is
 * louder (a quieter mix is left as the Mixer set it). Four loud voices
 * plus the click can sum past full scale; one fixed gain for the whole
 * file keeps the balance the singer set in the Voice Mixer, where a
 * sample-by-sample limiter would pump.
 */
internal object Mixer {
    private const val CHUNK_FRAMES = 4096
    private const val FULL_SCALE = 32768f
    private const val UNITY_SPEED = 1.0
    private const val BYTES_PER_SAMPLE = 2

    /**
     * About -1 dBFS (10^(-1/20)). The peak is measured after the stretch,
     * but MP3 encoding adds its own small overshoots, so a mix peaking at
     * exactly full scale would still clip; the loudest sample is held just
     * below it.
     */
    private const val PEAK_CEILING = 0.891f

    /**
     * Sonic reports itself inactive (and then drops input) within this
     * distance of 1.0, so such a speed is treated as unity and Sonic is
     * skipped for every track.
     */
    private const val SONIC_CLOSENESS = 1e-4

    fun mix(
        inputs: List<MixInput>,
        speed: Double,
        sink: (ShortArray, Int) -> Unit,
        cancelled: () -> Boolean,
    ) {
        val stretched = mutableListOf<File>()
        try {
            val tracks = if (abs(speed - UNITY_SPEED) < SONIC_CLOSENESS) {
                inputs
            } else {
                inputs.map { input ->
                    val out = File.createTempFile("export_stretch", ".raw", input.pcm.parentFile)
                    stretched += out
                    stretch(input.pcm, out, speed.toFloat(), cancelled)
                    // Only the stretched copy is read from here on. Freeing
                    // the decoded file now caps temp space at the stretched
                    // set plus one decoded track (the caller's own cleanup
                    // of an already-deleted file is a no-op).
                    input.pcm.delete()
                    MixInput(out, input.gain)
                }
            }
            val peak = scan(tracks, cancelled) { _, _ -> }
            val scale = PEAK_CEILING / maxOf(PEAK_CEILING, peak)
            // The sink (Mp3Encoder.encode) consumes the frames before
            // returning, so one buffer serves every chunk.
            val out = ShortArray(CHUNK_FRAMES * PcmDecoder.OUT_CHANNELS)
            scan(tracks, cancelled) { mixed, frames ->
                for (i in 0 until frames * PcmDecoder.OUT_CHANNELS) {
                    out[i] = (mixed[i] * scale * Short.MAX_VALUE).roundToInt()
                        .coerceIn(Short.MIN_VALUE.toInt(), Short.MAX_VALUE.toInt()).toShort()
                }
                sink(out, frames)
            }
        } finally {
            stretched.forEach { it.delete() }
        }
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

    /**
     * Pitch-preserving speed change (FR-9) of one track file into [dst],
     * using the same Sonic WSOLA implementation ExoPlayer applies to each
     * player in Playback. A fresh instance per track, so no track's audio
     * shapes another's splice points. Streams in chunks; the output starts
     * at frame 0 like the input, and the end-of-stream drain writes the
     * tail Sonic still holds.
     */
    @OptIn(UnstableApi::class)
    private fun stretch(src: File, dst: File, speed: Float, cancelled: () -> Boolean) {
        val sonic = SonicAudioProcessor()
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
        try {
            BufferedInputStream(FileInputStream(src)).use { input ->
                BufferedOutputStream(FileOutputStream(dst)).use { output ->
                    val drain = SonicDrain(output)
                    val bytes = ByteArray(CHUNK_FRAMES * PcmDecoder.BYTES_PER_FRAME)
                    // Sonic reads shorts in the buffer's own byte order, so the
                    // file's little-endian order is stated, not assumed.
                    val queue = ByteBuffer.allocateDirect(bytes.size).order(ByteOrder.LITTLE_ENDIAN)
                    while (true) {
                        if (cancelled()) throw ExportCancelled()
                        val n = readFully(input, bytes)
                        val whole = n - n % PcmDecoder.BYTES_PER_FRAME
                        if (whole > 0) {
                            queue.clear()
                            queue.put(bytes, 0, whole)
                            queue.flip()
                            // queueInput takes the whole buffer, so it is free
                            // to refill on the next chunk.
                            sonic.queueInput(queue)
                            drain.from(sonic)
                        }
                        if (n < bytes.size) break
                    }
                    sonic.queueEndOfStream()
                    while (!sonic.isEnded) {
                        if (!drain.from(sonic)) break
                    }
                }
            }
        } finally {
            sonic.reset()
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

    /** Writes Sonic's output to a little-endian PCM stream, reusing its buffers. */
    @OptIn(UnstableApi::class)
    private class SonicDrain(private val output: OutputStream) {
        private var shorts = ShortArray(0)
        private var bytes = ByteArray(0)

        /** Returns whether any output was written. */
        fun from(sonic: SonicAudioProcessor): Boolean {
            val out = sonic.output.order(ByteOrder.nativeOrder())
            val n = out.remaining() / BYTES_PER_SAMPLE
            if (n == 0) return false
            if (shorts.size < n) {
                shorts = ShortArray(n)
                bytes = ByteArray(n * BYTES_PER_SAMPLE)
            }
            out.asShortBuffer().get(shorts, 0, n)
            ByteBuffer.wrap(bytes, 0, n * BYTES_PER_SAMPLE).order(ByteOrder.LITTLE_ENDIAN)
                .asShortBuffer().put(shorts, 0, n)
            output.write(bytes, 0, n * BYTES_PER_SAMPLE)
            return true
        }
    }
}
